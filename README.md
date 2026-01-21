# GrapheneOS AVF Debian VM Setup Tool (GVM)

Automated setup tool for configuring Debian Trixie on GrapheneOS Android Virtualization Framework (AVF) VMs.

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
git clone https://github.com/ex1tium/grapheneos-avf-debian-setup-scripts.git
cd grapheneos-avf-debian-setup-scripts

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

```
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

```
grapheneos-avf-debian-setup-scripts/
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

[Add your license information here]

## Contributing

[Add contributing guidelines here]
