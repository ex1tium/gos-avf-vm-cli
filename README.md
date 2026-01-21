# GrapheneOS AVF Debian VM Setup Tool (GVM)

Automated setup tool for configuring Debian Trixie on GrapheneOS Android Virtualization Framework (AVF) VMs.

## Prerequisites (Before Cloning)

These steps must be completed **on your Android device** before starting the VM:

### 1. Enable Linux Terminal (Required)

1. Go to **Settings > System > Developer Options**
   - If Developer Options is not visible, go to Settings > About Phone and tap "Build Number" 7 times
2. Enable **"Linux development environment"**
3. Optionally enable **"Disable Child Process Restrictions"** for better compatibility

### 2. Enable GPU Acceleration (Recommended)

VirGL GPU acceleration must be enabled **before** starting the VM. This cannot be done from inside the VM.

1. Open the **Files** app on your Android device
2. Navigate to **Internal Storage**
3. Create a folder named `linux` (if it doesn't exist)
4. Inside the `linux` folder, create an empty file named `virglrenderer`
   - The file contents don't matter, only the filename
5. When you open the Terminal app, you should see a toast message: **"VirGL enabled"**
   - This toast is displayed automatically by the GrapheneOS Terminal app

### 3. Start the VM

1. Open the **Terminal** app
2. Wait for the Debian image to download (first launch only, ~500MB)
3. Once at the shell prompt, proceed with cloning this repository

### 4. Enable Graphical Display (For Desktop Use)

When you're ready to use a desktop environment:

1. Look for the **display icon** in the top-right corner of the Terminal app
2. Tap it to enable the graphical display
3. Then run `gvm start` to launch your desktop

> **Note**: GPU acceleration is provided via ANGLE-based VirGL. Some applications
> requiring newer OpenGL versions may not work until full GPU virtualization
> is available in future AVF releases.

## Features

- **Modular Architecture**: Five independent modules (apt, ssh, shell, gui, desktop) with dependency resolution
- **Interactive TUI**: Curses-based terminal interface with component selection and progress display
- **Dry-Run Mode**: Simulate execution without making actual system changes
- **Error Recovery**: Interactive error handling with retry, skip, and abort options
- **Configuration System**: TOML-based with layered priority (defaults → repo → user → CLI)
- **Desktop Environments**: Extensible desktop configuration via TOML files

## Target Environment

- **Platform**: Debian Trixie running on GrapheneOS AVF
- **Python**: 3.11+ (uses `tomllib` from standard library)
- **Terminal**: Any terminal supporting curses (for TUI mode)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/ex1tium/gos-avf-vm-cli.git
cd gos-avf-vm-cli

# Run setup (auto-detects and installs missing dependencies)
./gvm setup

# Or run non-interactive full setup
./gvm setup --all
```

The `setup` command automatically:
- Checks Python version (requires 3.11+)
- Verifies required modules (tomllib, curses)
- Offers to install missing system packages
- Proceeds to TUI or non-interactive setup

### Requirements

- **Python 3.11+** (uses `tomllib` from standard library)
- **curses support** (for TUI mode - auto-installed if missing)

> **Note:** If git doesn't preserve executable permissions, run: `chmod +x gvm`

## Installation Methods

### Direct Execution (Recommended)

```bash
# From repository root
./gvm <command>
```

### Python Module Execution

```bash
# Alternative entrypoint (equivalent to ./gvm)
python3 -m gvm <command>
```

No installation required - the tool is self-contained and runs from the repository.

## Command Reference

### Main Command

| Command | Description |
|---------|-------------|
| `./gvm setup` | Interactive TUI with component selection |
| `./gvm setup --all` | Non-interactive full setup (all modules) |

### Setup Commands

| Command | Description |
|---------|-------------|
| `./gvm apt` | Configure APT package manager |
| `./gvm ssh` | Configure SSH server (ports 2222/22) |
| `./gvm desktop <name>` | Install desktop environment |
| `./gvm desktop list` | List available desktops |
| `./gvm shell` | Configure shell (Starship, banner) |
| `./gvm gui` | Install GUI helper scripts |

### Runtime Commands

| Command | Description |
|---------|-------------|
| `./gvm start [desktop]` | Launch desktop environment |
| `./gvm start --list` | List installed desktops |
| `./gvm gpu status` | Check VirGL GPU status |
| `./gvm gpu help` | Show VirGL setup instructions |

### Management Commands

| Command | Description |
|---------|-------------|
| `./gvm config init` | Create user config at `~/.config/gvm/config.toml` |
| `./gvm config show` | Display effective configuration |
| `./gvm info` | Show system information |
| `./gvm fix <target>` | Run recovery commands |

### Global Flags

| Flag | Description |
|------|-------------|
| `-v, --verbose` | Detailed output with operation logs |
| `--config PATH` | Use custom config file |
| `--dry-run` | Simulate without making changes |
| `-i, --interactive` | Force interactive mode |

## Configuration Guide

### Priority Chain

Configuration values are loaded in this order (later overrides earlier):

1. **Embedded defaults** - Built into `gvm/config.py`
2. **Repository config** - `config/default.toml`
3. **User config** - `~/.config/gvm/config.toml`
4. **CLI-specified config** - `--config /path/to/file.toml`
5. **CLI flag overrides** - Direct command-line options

### Configuration Sections

```toml
[meta]
tool_version = "1.0.0"
default_distro = "debian-trixie"

[environment]
vm_user = "droid"
host_name = "GrapheneOS Terminal"

[ports]
ssh_forward = 2222    # Port exposed via GrapheneOS Terminal Port Control
ssh_internal = 22     # Internal SSH port (not exposed)

[apt]
retries = 10
http_timeout = 60
https_timeout = 60
pipeline_depth = 0

[ssh]
permit_root_login = "no"
password_auth = true
pubkey_auth = true
listen_address = "0.0.0.0"

[features]
install_desktop = true
install_shell_mods = true
auto_display = true
show_banner = true

[banner]
title = "GrapheneOS Linux VM Status"
show_ssh_note = true
```

### Creating User Configuration

```bash
# Create default user config
./gvm config init

# View effective configuration
./gvm config show
```

## Desktop Customization

### Adding Custom Desktops

Create a TOML file in `~/.config/gvm/packages/<name>.toml`:

```toml
[meta]
name = "my-desktop"
type = "desktop"
description = "My custom desktop environment"

[packages]
core = ["package1", "package2", "package3"]
optional = ["extra-package"]
wayland_helpers = ["wl-clipboard", "xdg-desktop-portal"]

[environment]
vars = [
    "QT_QPA_PLATFORM=wayland",
    "XDG_SESSION_TYPE=wayland"
]

[session]
start_command = "my-session-start"
fallback_command = "startx"
requires_dbus_session = true
helper_script_name = "start-my-desktop"

[files]
"~/.config/my-desktop/settings.conf" = """
# Custom settings content here
setting1=value1
"""
```

### Available Desktops

| Desktop | Config File |
|---------|-------------|
| Plasma Mobile | `config/packages/plasma-mobile.toml` |
| XFCE4 | `config/packages/xfce4.toml` |

User configs in `~/.config/gvm/packages/` override repository configs with the same name.

## Troubleshooting

### Common Errors

| Error | Solution |
|-------|----------|
| "Interactive mode requires curses support" | Use `./gvm setup --all` for non-interactive mode |
| APT errors (lock, network) | Run `./gvm fix apt` |
| SSH not starting | Run `./gvm fix ssh` |
| Module dependency failures | Check `./gvm info` for status |

### Recovery Commands

```bash
# Fix APT issues (clean cache, repair dpkg, update)
./gvm fix apt

# Fix SSH issues (restart service)
./gvm fix ssh

# Re-run a specific module
./gvm <module-name>
```

## Architecture Overview

### Module System

The tool uses a modular architecture with:

- **Base class**: `gvm/modules/base.py` - Abstract module interface
- **Five modules**: apt, ssh, shell, gui, desktop
- **Dependency resolution**: Topological sort with cycle detection
- **Progress callbacks**: Real-time progress reporting with throttling
- **Error recovery**: Callback-based pattern allowing RETRY, SKIP, or ABORT

### Key Components

```text
src/gvm/
├── __init__.py          # Package initialization
├── __main__.py          # Entry point for python -m gvm
├── cli.py               # CLI argument parsing and command routing
├── config.py            # Configuration system with TOML support
├── orchestrator.py      # Module dependency resolution and execution
├── tui.py               # Curses-based interactive TUI
└── modules/
    ├── __init__.py      # Module registry
    ├── base.py          # Abstract base class
    ├── apt.py           # APT configuration module
    ├── ssh.py           # SSH configuration module
    ├── shell.py         # Shell customization module
    ├── gui.py           # GUI helpers module
    └── desktop.py       # Desktop environment module
```

### Configuration System

- **TOML-based**: Uses Python 3.11+'s built-in `tomllib`
- **Replace-based merging**: Later values completely override earlier ones
- **Desktop discovery**: Scans `config/packages/` and `~/.config/gvm/packages/`

## Manual Testing

For AVF VM testing procedures, see [DEPLOYMENT.md](DEPLOYMENT.md).

**Important Notes:**

- TUI requires an actual terminal (cannot test in CI)
- Dry-run mode available for safe testing: `./gvm setup --all --dry-run`
- Port 2222 must be forwarded via GrapheneOS Terminal Port Control

## Development

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run integration tests only
python -m pytest tests/test_integration.py -v

# Run with coverage
python -m pytest tests/ --cov=gvm --cov-report=html
```

### Project Structure

```text
gos-avf-vm-cli/
├── gvm                  # Root-level executable wrapper
├── src/
│   └── gvm/             # Python package
├── config/              # Repository configuration files
│   ├── default.toml     # Default configuration
│   └── packages/        # Desktop environment configs
├── tests/               # Test suite
├── README.md            # This file
└── DEPLOYMENT.md        # Deployment and testing guide
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
