# GVM Deployment Guide

This document provides step-by-step manual testing procedures for validating the GVM tool on an AVF Debian VM.

## Pre-Deployment Checklist

Before starting, verify your environment meets the requirements:

```bash
# Verify Python 3.13+ installed
python3 --version
# Expected: Python 3.13.x or higher

# Check Debian version
cat /etc/debian_version
# Expected: trixie/sid or 13.x

# Ensure sudo access
sudo -v
# Should prompt for password or succeed silently

# Verify network connectivity
ping -c 3 deb.debian.org
# Expected: successful ping responses

# Check available disk space (need ~2GB for full desktop)
df -h /
# Verify sufficient free space in root partition
```

## Step-by-Step Testing Procedure

### Phase 1: APT Module

The APT module configures the package manager with hardening settings and optimizations.

```bash
# Test dry-run first (no actual changes)
./gvm apt --dry-run

# Execute with verbose output
./gvm apt -v
```

**Verification:**

```bash
# Check config file exists
ls -la /etc/apt/apt.conf.d/99-linuxvm-apt.conf

# View config contents
cat /etc/apt/apt.conf.d/99-linuxvm-apt.conf
# Should contain: Acquire::Retries, timeouts, pipeline depth

# Verify APT works
sudo apt update
# Should complete without errors
```

**Expected Results:**
- Config file at `/etc/apt/apt.conf.d/99-linuxvm-apt.conf`
- APT configured with retry and timeout settings
- `apt update` runs without errors

---

### Phase 2: SSH Module

The SSH module configures the SSH server for secure remote access.

```bash
# Test dry-run first
./gvm ssh --dry-run

# Execute with verbose output
./gvm ssh -v
```

**Verification:**

```bash
# Check config file exists
ls -la /etc/ssh/sshd_config.d/99-linuxvm-ssh.conf

# View config contents
cat /etc/ssh/sshd_config.d/99-linuxvm-ssh.conf
# Should contain: Port 2222, PermitRootLogin no, auth settings

# Check SSH service status
sudo systemctl status ssh
# Should show: active (running)

# Verify port 2222 is listening
ss -tlnp | grep 2222
# Should show: sshd listening on 0.0.0.0:2222
```

**Expected Results:**
- Config file at `/etc/ssh/sshd_config.d/99-linuxvm-ssh.conf`
- SSH service is active and running
- Port 2222 is listening for connections

---

### Phase 3: Shell Module

The Shell module installs Starship prompt and configures login banner.

```bash
# Test dry-run first
./gvm shell --dry-run

# Execute with verbose output
./gvm shell -v
```

**Verification:**

```bash
# Check Starship is installed
which starship
# Should return path like /usr/bin/starship or ~/.cargo/bin/starship

# Check bashrc modifications
grep "gvm-starship" ~/.bashrc
# Should find start and end markers

# Check banner script
ls -la /etc/profile.d/00-linuxvm-banner.sh
# Should exist and be executable

# Check auto_display config
ls -la ~/.config/linuxvm/auto_display
# Should exist
```

**Expected Results:**
- Starship installed and available in PATH
- `.bashrc` contains gvm-starship markers
- Banner script at `/etc/profile.d/00-linuxvm-banner.sh`
- Auto display config at `~/.config/linuxvm/auto_display`

---

### Phase 4: GUI Module

The GUI module installs helper scripts for starting graphical sessions.

```bash
# Test dry-run first
./gvm gui --dry-run

# Execute with verbose output
./gvm gui -v
```

**Verification:**

```bash
# Check helper scripts exist
ls -la ~/.local/bin/start-*
# Should show start-gui and possibly others

# Check script permissions
stat -c %a ~/.local/bin/start-gui
# Should be 755 (executable)

# Check PATH includes ~/.local/bin
echo $PATH | grep ".local/bin"
# Should find the path (may need new shell session)
```

**Expected Results:**
- Helper scripts at `~/.local/bin/start-*`
- Scripts are executable (mode 755)
- PATH includes `~/.local/bin` after bashrc sourcing

---

### Phase 5: Desktop Module

The Desktop module installs a desktop environment (this is a long-running operation).

```bash
# List available desktops first
./gvm desktop list
# Shows available desktop environments

# Test dry-run
./gvm desktop plasma-mobile --dry-run

# Execute (this will take 5-10+ minutes depending on network)
./gvm desktop plasma-mobile -v
```

**Verification:**

```bash
# Check packages are installed
dpkg -l | grep plasma
# Should show plasma-* packages

# Check helper script exists
ls -la ~/.local/bin/start-plasma-mobile
# Should exist and be executable

# Verify the script content
cat ~/.local/bin/start-plasma-mobile
# Should contain environment setup and session start commands
```

**Expected Results:**
- Desktop packages installed (plasma-mobile, kwin-wayland, etc.)
- Helper script at `~/.local/bin/start-plasma-mobile`
- Desktop environment ready to launch

---

### Phase 6: Full Setup

Test the complete setup workflow.

```bash
# Test dry-run of full setup
./gvm setup --all --dry-run

# Execute full setup (on fresh VM)
./gvm setup --all -v
```

**Verification:**

```bash
# Check system info
./gvm info
# Should show all modules as installed

# Verify all expected files exist
ls -la /etc/apt/apt.conf.d/99-linuxvm-apt.conf
ls -la /etc/ssh/sshd_config.d/99-linuxvm-ssh.conf
ls -la /etc/profile.d/00-linuxvm-banner.sh
ls -la ~/.local/bin/start-*
```

**Expected Results:**
- All modules complete successfully
- `./gvm info` shows all modules as installed
- All configuration files and scripts in place

---

### Phase 7: Interactive TUI

Test the interactive terminal user interface.

```bash
# Launch interactive TUI
./gvm setup
```

**Manual Test Steps:**

1. **Navigation**: Use arrow keys to move cursor up/down
2. **Selection**: Press Space to toggle component selection
3. **Select All**: Press 'a' to select all components
4. **Select None**: Press 'n' to deselect all components
5. **Confirm**: Press Enter to start setup
6. **Quit**: Press 'q' to quit without changes

**Verification:**
- TUI displays without errors
- Navigation is responsive
- Selections are persisted to `~/.config/gvm/last-selection.json`
- Progress screen shows module execution status

---

## Expected Outputs and Verification

### APT Module

| Item | Location | Content |
|------|----------|---------|
| Config file | `/etc/apt/apt.conf.d/99-linuxvm-apt.conf` | Acquire::Retries, timeouts, pipeline depth |
| Command | `apt update` | Runs without errors |

### SSH Module

| Item | Location | Content |
|------|----------|---------|
| Config file | `/etc/ssh/sshd_config.d/99-linuxvm-ssh.conf` | Port 2222, PermitRootLogin no |
| Service | `systemctl status ssh` | Active (running) |
| Port | `ss -tlnp \| grep 2222` | sshd listening |

### Shell Module

| Item | Location | Content |
|------|----------|---------|
| Starship | `which starship` | Returns path |
| Bashrc | `~/.bashrc` | Contains gvm-starship markers |
| Banner | `/etc/profile.d/00-linuxvm-banner.sh` | Exists |
| Auto-display | `~/.config/linuxvm/auto_display` | Exists |

### GUI Module

| Item | Location | Content |
|------|----------|---------|
| Scripts | `~/.local/bin/start-*` | Exist |
| Permissions | `stat -c %a ~/.local/bin/start-gui` | 755 |
| PATH | `echo $PATH` | Includes ~/.local/bin |

### Desktop Module

| Item | Location | Content |
|------|----------|---------|
| Packages | `dpkg -l \| grep <desktop>` | Installed |
| Helper | `~/.local/bin/start-<desktop>` | Exists |

---

## Rollback Procedures

### If APT Module Fails

```bash
# Remove config
sudo rm /etc/apt/apt.conf.d/99-linuxvm-apt.conf

# Update package index
sudo apt update

# Retry
./gvm fix apt
```

### If SSH Module Fails

```bash
# Remove config
sudo rm /etc/ssh/sshd_config.d/99-linuxvm-ssh.conf

# Restart SSH
sudo systemctl restart ssh

# Retry
./gvm fix ssh
```

### If Shell Module Fails

```bash
# Edit bashrc to remove gvm-starship section
nano ~/.bashrc
# Delete lines between "# >>> gvm-starship >>>" and "# <<< gvm-starship <<<"

# Remove banner
sudo rm /etc/profile.d/00-linuxvm-banner.sh

# Retry
./gvm shell
```

### If GUI Module Fails

```bash
# Remove scripts
rm ~/.local/bin/start-*

# Edit bashrc to remove gvm-local-bin section
nano ~/.bashrc
# Delete lines between "# >>> gvm-local-bin >>>" and "# <<< gvm-local-bin <<<"

# Retry
./gvm gui
```

### If Desktop Module Fails

```bash
# Uninstall packages (example for plasma-mobile)
sudo apt remove --purge plasma-mobile kwin-wayland-backend-drm

# Remove helper script
rm ~/.local/bin/start-plasma-mobile

# Retry
./gvm desktop plasma-mobile
```

---

## Known Limitations

### Testing Environment

- **TUI cannot be tested in CI**: Requires actual terminal with curses support
- **Dry-run limitations**: Simulates but doesn't validate actual system changes
- **Disk space**: Desktop installation requires 1-2GB free space
- **Network dependency**: Package downloads depend on network speed and availability

### AVF VM Specific

- **Port 2222 forwarding**: Must be enabled via GrapheneOS Terminal Port Control
- **Port 22 not exposed**: GrapheneOS does not expose port 22 externally (internal only)
- **Display environment**: Requires manual setup or auto_display toggle
- **Performance**: Desktop performance depends on AVF VM resources

---

## Troubleshooting Guide

### Issue: "Module X failed"

1. Check logs: Run with `-v` flag for verbose output
2. Note recovery command in error message
3. Run fix command: `./gvm fix <module-name>`
4. Check dependencies: Verify required modules succeeded

### Issue: "Circular dependency detected"

This indicates a bug in module dependencies. Report the issue with the module list.

**Workaround**: Run modules individually in order:
```bash
./gvm apt
./gvm ssh
./gvm shell
./gvm gui
./gvm desktop <name>
```

### Issue: "Config file parsing error"

1. Check TOML syntax: Validate with a TOML linter
2. Verify file path: Ensure config file exists
3. Use default: Remove custom config and retry

### Issue: "Permission denied"

1. Check sudo access: `sudo -v`
2. Check file permissions: Verify script is executable
3. Some operations require root: Run with `sudo` if needed

---

## Success Criteria

A successful deployment shows:

- [ ] All modules show "Installed" in `./gvm info`
- [ ] SSH accessible on port 2222 from external device
- [ ] Shell shows Starship prompt on new login
- [ ] Banner displays on login
- [ ] Desktop launches with helper script (`start-<desktop>`)
- [ ] No errors in verbose output

---

## Automated Testing

For development and CI, run the integration test suite:

```bash
# Run all integration tests
python -m pytest tests/test_integration.py -v

# Run with coverage
python -m pytest tests/test_integration.py --cov=gvm --cov-report=term-missing

# Run specific test class
python -m pytest tests/test_integration.py::TestCompleteSetupFlow -v
```

Note: Integration tests use mocking and do not require an actual AVF VM.
