#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# =============================================================================
# GrapheneOS Linux VM bootstrap:
# - APT hardening + mirror reliability
# - SSH on forwardable port (2222) + helpful banner
# - Plasma Mobile minimal "tablet-like" install (download first, then install)
# - Starship prompt for bash
# - Helpers for display/GUI launching and Plasma Mobile session attempt
# =============================================================================

SSH_FORWARD_PORT = 2222        # Forwardable via GrapheneOS Terminal Port Control
SSH_INTERNAL_PORT = 22         # Optional internal-only port (not forwardable)
INSTALL_PLASMA = True
INSTALL_STARSHIP = True

PLASMA_MIN_TABLET_PACKAGES = [
    # Minimal Plasma Mobile environment for trixie without modem/telephony focus
    "plasma-mobile-core",
    "plasma-settings",
    "plasma-mobile-tweaks",
    "maliit-keyboard",
]

PLASMA_NICE_TO_HAVE = [
    "angelfish",       # KDE mobile browser
    "okular-mobile",   # KDE document viewer (mobile)
    "kscreen",         # KDE screen config
]

BASE_TOOLS = [
    "ca-certificates",
    "curl",
    "nano",
    "less",
    "iproute2",
    "net-tools",
    "procps",
    "dbus-user-session",
    "openssh-server",
]

# KDE/Wayland environment helpers (lightweight)
WAYLAND_HELPERS = [
    "weston",          # often already present, but harmless
    "xwayland",        # allows X11 apps if needed
]

STARSHIP_PACKAGE = "starship"


def run(cmd, check=True, capture=False, env=None):
    """Run a command and print it."""
    print(f"\n>>> {' '.join(cmd)}")
    kwargs = {}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
        kwargs["text"] = True
    if env:
        kwargs["env"] = env
    p = subprocess.run(cmd, **kwargs)
    if check and p.returncode != 0:
        if capture and p.stdout:
            print(p.stdout)
        raise SystemExit(f"Command failed with exit code {p.returncode}: {' '.join(cmd)}")
    return p


def must_be_in_vm_userland():
    # Not bulletproof, but avoids running on "random Debian host"
    # GrapheneOS Terminal VM usually includes "droid" user.
    if os.geteuid() == 0:
        return  # allowed
    user = os.environ.get("USER", "")
    if user != "droid":
        print("WARNING: USER != 'droid'. This script is intended for the GrapheneOS Terminal VM.")
    # ok anyway


def print_manual_steps():
    msg = r"""
================================================================================
MANUAL STEPS (do these on the phone side before/during big installs)
================================================================================

1) GrapheneOS settings:
   - Enable Developer options
   - Enable Linux development environment / Terminal
   - (Recommended) Enable "Stay awake" while charging (Developer options)
   - Disable Battery Optimization for the Terminal app (so it doesn't pause mid-install)

2) Networking:
   - Prefer Ethernet via your USB-C hub for stability if possible
   - Keep screen on + terminal in foreground during the big download/install

3) Port Control popup:
   - GrapheneOS Terminal port forwarding DOES NOT expose privileged ports (<1024).
   - SSH port 22 will NOT appear.
   - This script configures SSH on port 2222 (forwardable).
   - When SSH starts, you should get a popup: "Allow port 2222?"
     -> Choose ALLOW.

4) External monitor:
   - Plug in your USB-C hub + HDMI monitor
   - Use keyboard/mouse from the hub (Android forwards input)

================================================================================
"""
    print(msg)


def detect_debian_codename():
    osr = Path("/etc/os-release")
    if not osr.exists():
        return None
    text = osr.read_text(errors="ignore")
    m = re.search(r"VERSION_CODENAME=(\w+)", text)
    if m:
        return m.group(1)
    return None


def harden_apt():
    """
    Make APT more robust in flaky environments:
    - retries
    - longer timeouts
    - disable HTTP pipelining (less likely to glitch)
    """
    conf = Path("/etc/apt/apt.conf.d/99-linuxvm-robust")
    content = """\
Acquire::Retries "10";
Acquire::http::Timeout "60";
Acquire::https::Timeout "60";
Acquire::http::Pipeline-Depth "0";
Dpkg::Use-Pty "0";
"""
    print("\n[+] Hardening APT config...")
    run(["sudo", "mkdir", "-p", "/etc/apt/apt.conf.d"], check=True)
    # Write to secure temp file and copy with sudo (avoids TOCTOU race condition)
    fd, tmp_path = tempfile.mkstemp(prefix="gvm-apt-", suffix=".conf")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        run(["sudo", "cp", tmp_path, str(conf)], check=True)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def stabilize_debian_mirror():
    """
    Your error showed usage of /etc/apt/mirrors/debian.list (mirror method).
    It's fine, but for reliability we can force a single stable mirror.
    We'll keep it conservative:
      - Only rewrite /etc/apt/mirrors/debian.list if it exists.
    """
    mirrors = Path("/etc/apt/mirrors/debian.list")
    if not mirrors.exists():
        print("\n[~] /etc/apt/mirrors/debian.list not present; leaving APT sources unchanged.")
        return

    codename = detect_debian_codename() or "trixie"
    backup = mirrors.with_suffix(".list.bak")
    print(f"\n[+] Stabilizing mirror list at {mirrors} (backup -> {backup}) ...")
    run(["sudo", "cp", str(mirrors), str(backup)], check=True)

    # Use deb.debian.org + security
    # (non-free + non-free-firmware included for broader hardware/app support)
    stable_list = "\n".join([
        f"https://deb.debian.org/debian {codename} main contrib non-free non-free-firmware",
        f"https://deb.debian.org/debian {codename}-updates main contrib non-free non-free-firmware",
        f"https://security.debian.org/debian-security {codename}-security main contrib non-free non-free-firmware",
        ""
    ])
    # Write to secure temp file and copy with sudo (avoids TOCTOU race condition)
    fd, tmp_path = tempfile.mkstemp(prefix="gvm-mirror-", suffix=".list")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, stable_list.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        run(["sudo", "cp", tmp_path, str(mirrors)], check=True)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def apt_clean_sledgehammer():
    """
    Clean lists + partial downloads to avoid poisoning dpkg with corrupted archives.
    Safe to run repeatedly.
    """
    print("\n[+] Cleaning APT lists + cached debs (safe reset)...")
    run(["sudo", "apt", "clean"], check=False)
    run(["sudo", "rm", "-rf", "/var/lib/apt/lists/*"], check=False)
    run(["sudo", "mkdir", "-p", "/var/lib/apt/lists/partial"], check=False)
    run(["sudo", "rm", "-rf", "/var/cache/apt/archives/partial/*"], check=False)
    run(["sudo", "rm", "-f", "/var/cache/apt/archives/*.deb"], check=False)


def apt_update_upgrade():
    print("\n[+] Updating package index + upgrading base system...")
    run(["sudo", "apt", "update"], check=True)
    run(["sudo", "apt", "-y", "full-upgrade"], check=True)


def apt_download_then_install(packages):
    """
    Download packages first, then install without downloading.
    This reduces the chance of half-downloaded/corrupted packages breaking dpkg.
    """
    if not packages:
        return

    pkg_list = list(packages)

    print("\n[+] Download-only phase (prefetch .deb files)...")
    run(["sudo", "apt-get", "-y", "--download-only", "install"] + pkg_list, check=True)

    print("\n[+] Install phase (no-download, use cached .debs)...")
    run(["sudo", "apt-get", "-y", "--no-download", "install"] + pkg_list, check=True)


def dpkg_repair_if_needed():
    """
    If dpkg got stuck, this usually fixes it.
    """
    print("\n[+] Attempting dpkg repair pass (safe)...")
    run(["sudo", "dpkg", "--configure", "-a"], check=False)
    run(["sudo", "apt", "-f", "install", "-y"], check=False)


def configure_sshd_forwardable():
    """
    Configure sshd to listen on SSH_FORWARD_PORT (2222) for GrapheneOS port forwarding popups.
    Optionally keep SSH_INTERNAL_PORT=22 for inside-VM use only.
    """
    print("\n[+] Configuring OpenSSH server for GrapheneOS port forwarding...")

    cfg = Path("/etc/ssh/sshd_config")
    if not cfg.exists():
        raise SystemExit("sshd_config not found. Is openssh-server installed?")

    # Backup
    backup = cfg.with_suffix(".bak")
    if not backup.exists():
        run(["sudo", "cp", str(cfg), str(backup)], check=True)

    # Read and rewrite minimal directives (append if missing)
    text = cfg.read_text(errors="ignore").splitlines()

    def set_or_add(key, value):
        nonlocal text
        pattern = re.compile(rf"^\s*{re.escape(key)}\b", re.IGNORECASE)
        replaced = False
        out = []
        for line in text:
            if pattern.match(line):
                out.append(f"{key} {value}")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            out.append(f"{key} {value}")
        text = out

    # We want sshd to listen on a forwardable high port
    # (Port 22 cannot be exposed by GrapheneOS Terminal Port Control)
    # You can keep port 22 internal too, but it won't be reachable from LAN.
    # We'll use two Port lines by ensuring we add both.
    # Easiest: remove existing Port lines and add our own at bottom.
    filtered = []
    for line in text:
        if re.match(r"^\s*Port\s+\d+", line, re.IGNORECASE):
            continue
        filtered.append(line)
    text = filtered
    text.append(f"Port {SSH_FORWARD_PORT}")
    if SSH_INTERNAL_PORT != SSH_FORWARD_PORT:
        text.append(f"Port {SSH_INTERNAL_PORT}")

    # Ensure it listens broadly inside the VM
    set_or_add("ListenAddress", "0.0.0.0")
    # Security-ish defaults: allow password for now (user can harden later)
    set_or_add("PermitRootLogin", "no")
    set_or_add("PasswordAuthentication", "yes")
    set_or_add("KbdInteractiveAuthentication", "yes")
    set_or_add("PubkeyAuthentication", "yes")
    set_or_add("UsePAM", "yes")

    # Security hardening warning
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠️  SSH SECURITY NOTICE                                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  The current SSH configuration is permissive for initial setup convenience.  ║
║  For production use, consider hardening the following settings in            ║
║  /etc/ssh/sshd_config:                                                       ║
║                                                                              ║
║    • ListenAddress           - Restrict to specific interface (not 0.0.0.0) ║
║    • PasswordAuthentication  - Set to 'no' after configuring SSH keys       ║
║    • KbdInteractiveAuthentication - Set to 'no' to disable keyboard auth    ║
║    • PubkeyAuthentication    - Keep 'yes' (required for key-based auth)     ║
║    • UsePAM                  - Set to 'no' if PAM is not required           ║
║                                                                              ║
║  To reconfigure: sudo nano /etc/ssh/sshd_config && sudo systemctl restart ssh║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

    new_cfg = "\n".join(text) + "\n"
    # Write to secure temp file and copy with sudo (avoids TOCTOU race condition)
    fd, tmp_path = tempfile.mkstemp(prefix="gvm-sshd-", suffix=".conf")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, new_cfg.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        run(["sudo", "cp", tmp_path, str(cfg)], check=True)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    run(["sudo", "systemctl", "enable", "--now", "ssh"], check=True)
    run(["sudo", "systemctl", "restart", "ssh"], check=True)

    # Show listening ports
    run(["bash", "-lc", f"ss -ltnp | grep -E ':({SSH_FORWARD_PORT}|{SSH_INTERNAL_PORT})\\b' || true"], check=False)

    print(f"""
[OK] SSH server configured.

IMPORTANT:
- GrapheneOS Terminal Port Control will NOT expose port 22.
- You MUST allow port {SSH_FORWARD_PORT} when the popup appears.
- Connect from LAN using:  ssh -p {SSH_FORWARD_PORT} droid@<PHONE_WIFI_IP>

If you DIDN'T get a popup:
- Keep Terminal in the foreground and run:
    sudo systemctl restart ssh
or open a temporary listener:
    nc -lvnp {SSH_FORWARD_PORT}
""")


def install_starship_for_bash():
    """
    Install starship and enable it in ~/.bashrc
    """
    print("\n[+] Installing Starship prompt for bash...")
    dpkg_repair_if_needed()
    apt_download_then_install([STARSHIP_PACKAGE])

    bashrc = Path.home() / ".bashrc"
    snippet = r"""
# --- Starship prompt (bash) ---
if command -v starship >/dev/null 2>&1; then
  eval "$(starship init bash)"
fi
"""
    ensure_snippet(bashrc, "Starship prompt", snippet)


def ensure_snippet(file_path: Path, label: str, snippet: str):
    """Ensure a labeled snippet exists in a file using marker comments.

    Uses marker comments to identify and manage the snippet:
    - Marker begin: # >>> {label} >>>
    - Marker end: # <<< {label} <<<

    If markers already exist, the function returns without modification.
    Otherwise, the snippet is appended to the file.

    Args:
        file_path: Path to the file to modify.
        label: Unique label for the snippet markers.
        snippet: Content to add between markers.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    marker_begin = f"# >>> {label} >>>"
    marker_end = f"# <<< {label} <<<"
    block = f"\n{marker_begin}\n{snippet.strip()}\n{marker_end}\n"

    if marker_begin in existing and marker_end in existing:
        print(f"Snippet '{label}' already exists in {file_path}")
        return

    with file_path.open("a", encoding="utf-8") as f:
        f.write(block)
    print(f"Added snippet '{label}' to {file_path}")


def install_plasma_mobile_minimal():
    """
    Plasma Mobile minimal install (tablet-ish) for trixie.
    Uses download-first then install.
    """
    print("\n[+] Installing Plasma Mobile minimal (tablet-ish) stack...")
    print("    Packages:", " ".join(PLASMA_MIN_TABLET_PACKAGES))

    dpkg_repair_if_needed()

    # Download first (big!)
    apt_download_then_install(PLASMA_MIN_TABLET_PACKAGES)

    # Optionally add nice-to-haves
    print("\n[+] Installing optional Plasma Mobile apps (browser/docs/screen config)...")
    apt_download_then_install(PLASMA_NICE_TO_HAVE)

    # Helpful Wayland components
    print("\n[+] Installing lightweight Wayland helpers (weston/xwayland)...")
    apt_download_then_install(WAYLAND_HELPERS)


def configure_plasma_wayland_env():
    """
    Best-effort environment tuning for VM display stack:
    - Prefer Wayland
    - Make Qt/GTK/Firefox behave nicer under Wayland
    KDE reads env scripts from:
      ~/.config/plasma-workspace/env/*.sh
    """
    env_dir = Path.home() / ".config/plasma-workspace/env"
    env_dir.mkdir(parents=True, exist_ok=True)

    env_script = env_dir / "linuxvm-wayland.sh"
    content = """\
#!/bin/sh
# Linux VM (GrapheneOS Terminal) Wayland preferences

export XDG_SESSION_TYPE=wayland
export QT_QPA_PLATFORM=wayland
export MOZ_ENABLE_WAYLAND=1
export GDK_BACKEND=wayland
export SDL_VIDEODRIVER=wayland

# If you see cursor glitches under virt/ANGLE paths, this sometimes helps:
export WLR_NO_HARDWARE_CURSORS=1
"""
    env_script.write_text(content)
    env_script.chmod(0o755)
    print(f"[OK] Wrote KDE env script: {env_script}")


def create_gui_helpers():
    """
    Create helper commands in ~/.local/bin:
    - start-gui: sources enable_display (if present) and launches weston if needed
    - start-plasma-mobile: attempts a Plasma Mobile-style session
    """
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    start_gui = bin_dir / "start-gui"
    start_gui.write_text("""#!/usr/bin/env bash
set -euo pipefail

# GrapheneOS Linux VM helper:
# Starts display integration so GUI apps can run.

echo "[linuxvm] Starting GUI integration..."
if command -v enable_display >/dev/null 2>&1; then
  source enable_display
else
  echo "[linuxvm] enable_display not found in PATH. This VM build may not support GUI yet."
  exit 1
fi

echo "[linuxvm] GUI environment ready."
echo "[linuxvm] Try: chromium --ozone-platform=wayland"
""")
    start_gui.chmod(0o755)

    start_plasma = bin_dir / "start-plasma-mobile"
    start_plasma.write_text("""#!/usr/bin/env bash
set -euo pipefail

echo "[linuxvm] Starting display integration..."
if command -v enable_display >/dev/null 2>&1; then
  source enable_display
else
  echo "[linuxvm] enable_display not found."
  exit 1
fi

# Plasma Mobile in this VM is experimental:
# - GrapheneOS Terminal VM uses its own GUI plumbing
# - This tries the "native-ish" startplasma-wayland first.
# - If it fails, we fall back to KWin nested + phone shell.

echo "[linuxvm] Attempt 1: startplasma-wayland"
if command -v startplasma-wayland >/dev/null 2>&1; then
  exec dbus-run-session startplasma-wayland
fi

echo "[linuxvm] Attempt 2: nested kwin_wayland + phone plasmashell"
if command -v kwin_wayland >/dev/null 2>&1 && command -v plasmashell >/dev/null 2>&1; then
  exec dbus-run-session -- \
    kwin_wayland --xwayland --exit-with-session \
    plasmashell -p org.kde.plasma.phone
fi

echo "[linuxvm] Could not find startplasma-wayland nor kwin_wayland/plasmashell."
echo "[linuxvm] Installed packages may be incomplete."
exit 2
""")
    start_plasma.chmod(0o755)

    print(f"[OK] Created helper: {start_gui}")
    print(f"[OK] Created helper: {start_plasma}")


def set_default_bash_banner():
    """
    Add a login banner with useful info:
    - Debian version, kernel
    - VM IPs
    - SSH port to use (2222)
    This runs for interactive shells (bash).
    """
    banner_path = Path("/etc/profile.d/00-linuxvm-banner.sh")
    content = f"""\
#!/bin/sh
# Linux VM banner for GrapheneOS Terminal
# Printed on interactive shells.

case "$-" in
  *i*) ;;
  *) return ;;
esac

echo ""
echo "=== GrapheneOS Linux VM Status ==="
echo "User: $(whoami)    Host: $(hostname)"
echo "Debian: $(. /etc/os-release 2>/dev/null; echo ${{PRETTY_NAME:-unknown}})"
echo "Kernel: $(uname -r)"
echo "Disk:   $(df -h / | awk 'NR==2{{print $4 \" free of \" $2}}')"
echo "RAM:    $(free -h | awk '/Mem:/{{print $7 \" available\"}}')"
echo "IPs:    $(hostname -I 2>/dev/null | tr -s ' ' | sed 's/ $//')"
echo ""
echo "SSH:    ssh -p {SSH_FORWARD_PORT} droid@<PHONE_WIFI_IP>"
echo "Note:   GrapheneOS Terminal Port Control will NOT expose port 22."
echo "        Allow port {SSH_FORWARD_PORT} if prompted."
echo ""
"""
    # Write to secure temp file and copy with sudo (avoids TOCTOU race condition)
    fd, tmp_path = tempfile.mkstemp(prefix="gvm-banner-", suffix=".sh")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        run(["sudo", "cp", tmp_path, str(banner_path)], check=True)
        run(["sudo", "chmod", "755", str(banner_path)], check=True)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    print(f"[OK] Installed banner: {banner_path}")


def enable_auto_display_on_terminal_launch():
    """
    Best-effort auto-display enablement for *local* Terminal sessions:
    - Do NOT do this on SSH sessions (it can break or slow remote work)
    - Adds a toggle file ~/.config/linuxvm/auto_display
    """
    cfgdir = Path.home() / ".config/linuxvm"
    cfgdir.mkdir(parents=True, exist_ok=True)
    toggle = cfgdir / "auto_display"
    if not toggle.exists():
        toggle.write_text("1\n")

    bashrc = Path.home() / ".bashrc"
    snippet = r"""
# Auto-enable GUI display integration when opening local Terminal (NOT via SSH)
# Toggle file: ~/.config/linuxvm/auto_display
if [ -z "${SSH_CONNECTION:-}" ] && [ -f "$HOME/.config/linuxvm/auto_display" ]; then
  if command -v enable_display >/dev/null 2>&1; then
    # Avoid repeating if already configured
    if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
      # Best-effort; ignore errors so shell still opens
      source enable_display >/dev/null 2>&1 || true
    fi
  fi
fi
"""
    ensure_snippet(bashrc, "Linux VM auto display", snippet)
    print(f"[OK] Auto-display toggle enabled via {toggle}")


def main():
    must_be_in_vm_userland()
    print_manual_steps()

    # Sanity: show Debian codename
    codename = detect_debian_codename()
    print(f"[i] Detected Debian codename: {codename or 'unknown'}")
    if codename and codename.lower() not in ("trixie", "sid", "bookworm"):
        print("[!] Unexpected Debian codename; continuing anyway.")

    # APT reliability improvements
    harden_apt()
    stabilize_debian_mirror()
    apt_clean_sledgehammer()
    apt_update_upgrade()

    # Base tools + SSH server
    print("\n[+] Installing base tools (download first)...")
    apt_download_then_install(BASE_TOOLS)

    # SSH config: forwardable port 2222 + optional port 22 internal
    configure_sshd_forwardable()

    # Plasma mobile minimal install
    if INSTALL_PLASMA:
        try:
            install_plasma_mobile_minimal()
            configure_plasma_wayland_env()
            create_gui_helpers()
        except SystemExit:
            print("\n[!] Plasma install failed.")
            print("    This usually happens due to partial/corrupt downloads or the Terminal being paused.")
            print("    Recovery steps:")
            print("      sudo apt clean")
            print("      sudo rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/partial/* /var/cache/apt/archives/*.deb")
            print("      sudo apt update")
            print("      sudo dpkg --configure -a || true")
            print("      sudo apt -f install")
            print("\n    Then rerun this script.")
            raise

    # Starship prompt
    if INSTALL_STARSHIP:
        install_starship_for_bash()

    # Banner + optional display autostart
    set_default_bash_banner()
    enable_auto_display_on_terminal_launch()

    print("""
================================================================================
DONE ✅
================================================================================

What to do next:

1) GrapheneOS popup:
   - You should see "Allow port 2222?" -> ALLOW it.

2) SSH from your laptop (same Wi-Fi):
   ssh -p 2222 droid@<PHONE_WIFI_IP>

3) Start GUI on external monitor:
   start-gui

4) Try Plasma Mobile:
   start-plasma-mobile

Notes:
- Port 22 cannot be exposed by GrapheneOS Terminal Port Control; use 2222.
- Plasma Mobile inside this VM is experimental; Plasma Desktop may be more stable on big screens.
================================================================================
""")


if __name__ == "__main__":
    main()
