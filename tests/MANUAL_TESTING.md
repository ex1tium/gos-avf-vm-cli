# Manual Testing Checklist for AVF VM Deployment

This document provides manual testing procedures for validating the GVM modules
on an actual AVF (Android Virtualization Framework) virtual machine.

## Prerequisites

- AVF VM running Debian trixie
- SSH access to the VM (or direct terminal access)
- sudo privileges for the test user (typically `droid`)

## SSH Module Manual Tests

### Verification Steps

1. **Verify sshd config file created**
   ```bash
   ls -la /etc/ssh/sshd_config.d/99-linuxvm-ssh.conf
   cat /etc/ssh/sshd_config.d/99-linuxvm-ssh.conf
   ```
   Expected: File exists with Port, ListenAddress, and authentication settings.

2. **Check SSH service is enabled and running**
   ```bash
   systemctl status ssh
   systemctl is-enabled ssh
   ```
   Expected: Service is active (running) and enabled.

3. **Verify SSH listening ports**
   ```bash
   ss -ltn | grep -E ':(22|2222)\s'
   ```
   Expected: Ports 22 and 2222 are in LISTEN state.

4. **Test SSH connection on port 2222**
   ```bash
   ssh -p 2222 droid@localhost
   ```
   Expected: Successful connection (or password prompt).

5. **Verify security settings applied**
   ```bash
   sudo sshd -T | grep -iE '(permitrootlogin|passwordauthentication|pubkeyauthentication)'
   ```
   Expected:
   - `permitrootlogin no`
   - `passwordauthentication yes`
   - `pubkeyauthentication yes`

6. **Verify backup created (if config existed)**
   ```bash
   ls -la /etc/ssh/sshd_config.d/*.bak 2>/dev/null
   ```

### Recovery Test

1. **Simulate failure and test recovery**
   ```bash
   sudo systemctl stop ssh
   gvm fix ssh
   systemctl status ssh
   ```
   Expected: SSH service restored to running state.

---

## Shell Module Manual Tests

### Verification Steps

1. **Verify Starship installed**
   ```bash
   which starship
   starship --version
   ```
   Expected: Starship binary found and version displayed.

2. **Check bashrc snippet present**
   ```bash
   grep -A2 ">>> gvm-starship >>>" ~/.bashrc
   ```
   Expected: Shows Starship eval command between markers.

3. **Test banner display**
   ```bash
   # Logout and login again, or source the banner script
   source /etc/profile.d/00-linuxvm-banner.sh
   ```
   Expected: Banner displays with hostname, kernel, uptime, memory info.

4. **Verify banner script content**
   ```bash
   cat /etc/profile.d/00-linuxvm-banner.sh
   file /etc/profile.d/00-linuxvm-banner.sh
   ```
   Expected: Script contains display_banner function and is executable.

5. **Verify auto-display marker**
   ```bash
   ls -la ~/.config/linuxvm/auto_display
   ```
   Expected: Empty marker file exists.

6. **Test Starship prompt**
   ```bash
   # Open new terminal or source bashrc
   source ~/.bashrc
   ```
   Expected: Starship prompt appears (custom prompt style).

### Recovery Test

1. **Test recovery command**
   ```bash
   gvm fix shell
   ```
   Expected: Shell configuration restored/verified.

---

## GUI Module Manual Tests

### Verification Steps

1. **Check helper scripts exist**
   ```bash
   ls -la ~/.local/bin/start-*
   ```
   Expected: `start-gui` and any desktop-specific scripts.

2. **Verify scripts are executable**
   ```bash
   test -x ~/.local/bin/start-gui && echo "start-gui is executable"
   for script in ~/.local/bin/start-*; do
       test -x "$script" && echo "$(basename $script) is executable"
   done
   ```
   Expected: All scripts are executable.

3. **Test PATH includes local bin**
   ```bash
   echo $PATH | grep ".local/bin"
   ```
   Expected: PATH contains `~/.local/bin` or `/home/droid/.local/bin`.

4. **Check bashrc PATH snippet**
   ```bash
   grep -A2 ">>> gvm-local-bin >>>" ~/.bashrc
   ```
   Expected: Shows PATH export between markers.

5. **Run start-gui helper**
   ```bash
   start-gui
   ```
   Expected: Shows available desktop launchers (or usage message).

6. **Verify script content includes display enabler source**
   ```bash
   grep "enable_display" ~/.local/bin/start-gui
   ```
   Expected: Script sources `~/.config/linuxvm/enable_display` if available.

### Recovery Test

1. **Test recovery command**
   ```bash
   gvm fix gui
   ```
   Expected: GUI helper scripts restored/verified.

---

## Desktop Module Manual Tests

### Prerequisites

- APT module must be run first (`gvm apt`)
- Sufficient disk space for desktop packages

### Verification Steps

1. **Test desktop discovery**
   ```bash
   python -c "from gvm.config import Config; print(Config.load().discover_desktops())"
   ```
   Expected: Dictionary with available desktops (e.g., plasma-mobile, xfce4, plasma).

2. **Test dry-run mode**
   ```bash
   python -m gvm desktop plasma-mobile --dry-run
   ```
   Expected: Shows what would be done without making changes:
   - Package list to install
   - Files to create
   - Helper script content

3. **Test actual installation (Plasma Mobile)**
   ```bash
   python -m gvm desktop plasma-mobile
   ```
   Expected: Packages downloaded and installed, files created, helper script generated.

4. **Verify packages installed**
   ```bash
   dpkg -l | grep plasma-mobile
   dpkg -l plasma-mobile-core
   ```
   Expected: Core packages show status "ii" (installed).

5. **Verify configuration files created**
   ```bash
   ls -la ~/.config/plasma-workspace/env/
   cat ~/.config/plasma-workspace/env/linuxvm-wayland.sh
   ```
   Expected: Environment setup script exists with Wayland variables.

6. **Verify helper script created**
   ```bash
   ls -la ~/.local/bin/start-plasma-mobile
   cat ~/.local/bin/start-plasma-mobile
   ```
   Expected: Executable script with:
   - Shebang line
   - Display enabler source
   - Environment exports
   - dbus-run-session wrapped launch command
   - Fallback command with `||`

7. **Verify helper script is executable**
   ```bash
   test -x ~/.local/bin/start-plasma-mobile && echo "Script is executable"
   ```
   Expected: "Script is executable" output.

8. **Verify marker file created**
   ```bash
   cat /etc/gvm/desktop-installed
   ```
   Expected: Contains "plasma-mobile" or list of installed desktops.

9. **Test XFCE4 installation (alternative)**
   ```bash
   python -m gvm desktop xfce4 --dry-run
   python -m gvm desktop xfce4
   ```
   Expected: XFCE4 packages installed, start-xfce4 script created.

### Recovery Test

1. **Test recovery command**
   ```bash
   gvm fix desktop
   gvm fix desktop plasma-mobile
   ```
   Expected: Desktop configuration restored/verified.

### Rollback Procedure

1. **Remove installed packages**
   ```bash
   # For Plasma Mobile
   sudo apt-get remove --purge plasma-mobile-core plasma-settings plasma-mobile-tweaks maliit-keyboard

   # For XFCE4
   sudo apt-get remove --purge xfce4 xfce4-goodies
   ```

2. **Remove configuration files**
   ```bash
   rm -rf ~/.config/plasma-workspace/env/linuxvm-wayland.sh
   rm -f ~/.local/bin/start-plasma-mobile
   rm -f ~/.local/bin/start-xfce4
   ```

3. **Remove marker file**
   ```bash
   sudo rm -f /etc/gvm/desktop-installed
   ```

---

## Integration Tests

### Full Setup Test

1. **Run full setup**
   ```bash
   ./gvm setup --all
   ```
   Expected: All modules execute successfully with progress indication.

2. **Run setup with dry-run**
   ```bash
   ./gvm setup --all --dry-run
   ```
   Expected: Shows what would be done without making changes.

### Individual Module Execution

1. **Test individual module execution**
   ```bash
   ./gvm ssh
   ./gvm shell
   ./gvm gui
   ```
   Expected: Each module executes independently.

### Module Dependency Resolution

1. **Test dependency resolution**
   ```bash
   # SSH depends on APT
   ./gvm ssh --verbose
   ```
   Expected: APT module runs first (if not already configured), then SSH.

### Verbose Mode

1. **Test verbose output**
   ```bash
   ./gvm setup --all --verbose
   ```
   Expected: Detailed operation information displayed.

---

## Error Recovery Tests

### Simulated Failure Scenarios

1. **Missing package test**
   ```bash
   # Test module behavior when a package cannot be found
   # Use a non-existent package name to simulate missing package

   # Create a temporary desktop config with a fake package
   mkdir -p ~/.config/gvm/packages
   cat > ~/.config/gvm/packages/test-missing-pkg.toml << 'EOF'
   [meta]
   name = "TestMissingPkg"
   description = "Test desktop with missing package"
   type = "desktop"

   [packages]
   core = ["this-package-does-not-exist-12345"]

   [session]
   start_command = "echo test"
   EOF

   # Run the module (should fail gracefully with error message)
   ./gvm desktop "TestMissingPkg"

   # Expected: Module reports failure with package name and recovery command

   # Cleanup
   rm ~/.config/gvm/packages/test-missing-pkg.toml
   ```

2. **Permission denied test**
   ```bash
   # Run as non-sudo user
   ./gvm ssh
   ```
   Expected: Clear error message with recovery command suggestion.

3. **Service failure test**
   ```bash
   sudo systemctl mask ssh
   ./gvm ssh
   sudo systemctl unmask ssh
   ```
   Expected: Module reports failure with recovery command.

---

## Configuration Validation

### Custom Configuration Test

1. **Test with custom config**
   ```bash
   mkdir -p ~/.config/gvm
   cat > ~/.config/gvm/config.toml << 'EOF'
   [banner]
   title = "Custom VM Title"
   show_ssh_note = false
   EOF
   ./gvm shell
   source /etc/profile.d/00-linuxvm-banner.sh
   ```
   Expected: Banner shows custom title, no SSH note.

### Port Configuration Test

1. **Test custom ports**
   ```bash
   cat > ~/.config/gvm/config.toml << 'EOF'
   [ports]
   ssh_forward = 2223
   EOF
   ./gvm ssh
   ss -ltn | grep 2223
   ```
   Expected: SSH listening on custom port.

---

## Test Results Summary

| Module | Test | Result | Notes |
|--------|------|--------|-------|
| SSH | Config file created | [ ] | |
| SSH | Service running | [ ] | |
| SSH | Ports listening | [ ] | |
| SSH | Security settings | [ ] | |
| Shell | Starship installed | [ ] | |
| Shell | Bashrc snippet | [ ] | |
| Shell | Banner displays | [ ] | |
| Shell | Auto-display marker | [ ] | |
| GUI | Scripts created | [ ] | |
| GUI | Scripts executable | [ ] | |
| GUI | PATH configured | [ ] | |
| Desktop | Packages installed | [ ] | |
| Desktop | Config files created | [ ] | |
| Desktop | Helper script created | [ ] | |
| Desktop | Helper script executable | [ ] | |
| Desktop | Marker file created | [ ] | |
| Integration | Full setup | [ ] | |
| Integration | Dry-run mode | [ ] | |
| Integration | Dependencies | [ ] | |

---

## Troubleshooting

### Common Issues

1. **SSH won't start**
   - Check sshd config syntax: `sudo sshd -t`
   - Check logs: `journalctl -u ssh -n 50`

2. **Starship not working**
   - Verify installed: `dpkg -l starship`
   - Check bashrc sourced: `echo $STARSHIP_SHELL`

3. **GUI scripts not found**
   - Verify PATH: `echo $PATH`
   - Source bashrc: `source ~/.bashrc`

4. **Permission errors**
   - Check sudo access: `sudo -l`
   - Verify user groups: `groups`
