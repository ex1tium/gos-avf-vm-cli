"""CLI interface for GVM tool.

This module implements the main command-line interface with argparse-based
command routing for the GrapheneOS Debian VM Setup Tool.

Command Structure:
    - Root parser with global flags: -v/--verbose, --config, --dry-run, -i/--interactive
    - Setup domain: setup, apt, ssh, desktop, shell, gui
    - Management domain: config, info, fix
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional

from gvm.config import Config
from gvm.modules import ModuleResult, ModuleStatus, get_module_class, list_modules
from gvm.orchestrator import ModuleOrchestrator
from gvm.utils.system import detect_debian_codename, is_port_listening, is_service_running


def check_curses_available() -> bool:
    """Check if curses is available and the terminal supports it.

    Returns:
        True if curses is available and terminal supports it, False otherwise.
    """
    try:
        import curses
    except ImportError:
        return False

    try:
        # Test if terminal supports curses
        curses.setupterm()
        return True
    except curses.error:
        return False


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser with all subcommands.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="gvm",
        description="GrapheneOS Debian VM Setup Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    # Global flags
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="Use custom config file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate without making changes",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Force interactive mode (default for setup)",
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show this help message",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-run even if already installed",
    )

    # Subparsers for commands
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    # Setup command
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive setup with component selection (TUI)",
        add_help=False,
    )
    setup_parser.add_argument(
        "--all",
        action="store_true",
        help="Non-interactive full setup",
    )
    setup_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for setup command",
    )
    setup_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-run even if already installed",
    )

    # APT command
    apt_parser = subparsers.add_parser(
        "apt",
        help="Configure APT package manager",
        add_help=False,
    )
    apt_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for apt command",
    )
    apt_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-run even if already installed",
    )

    # SSH command
    ssh_parser = subparsers.add_parser(
        "ssh",
        help="Configure SSH server",
        add_help=False,
    )
    ssh_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for ssh command",
    )
    ssh_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-run even if already installed",
    )

    # Desktop command
    desktop_parser = subparsers.add_parser(
        "desktop",
        help="Install desktop environment",
        add_help=False,
    )
    desktop_parser.add_argument(
        "desktop_target",
        nargs="?",
        metavar="name|list",
        help="Desktop name to install or 'list' to show available",
    )
    desktop_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for desktop command",
    )
    desktop_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-run even if already installed",
    )

    # Shell command
    shell_parser = subparsers.add_parser(
        "shell",
        help="Configure shell customizations",
        add_help=False,
    )
    shell_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for shell command",
    )
    shell_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-run even if already installed",
    )

    # GUI command
    gui_parser = subparsers.add_parser(
        "gui",
        help="Install GUI helper scripts",
        add_help=False,
    )
    gui_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for gui command",
    )
    gui_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-run even if already installed",
    )

    # Start command
    start_parser = subparsers.add_parser(
        "start",
        help="Launch desktop environment",
        add_help=False,
    )
    start_parser.add_argument(
        "desktop_name",
        nargs="?",
        metavar="name",
        help="Desktop name to start (optional if only one installed)",
    )
    start_parser.add_argument(
        "--list",
        action="store_true",
        help="List installed desktops",
    )
    start_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for start command",
    )

    # GPU command
    gpu_parser = subparsers.add_parser(
        "gpu",
        help="GPU status and diagnostics",
        add_help=False,
    )
    gpu_parser.add_argument(
        "gpu_action",
        nargs="?",
        choices=["status", "help"],
        help="GPU action: status or help",
    )
    gpu_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for gpu command",
    )

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Config management",
        add_help=False,
    )
    config_parser.add_argument(
        "config_action",
        nargs="?",
        choices=["init", "show"],
        help="Config action: init or show",
    )
    config_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for config command",
    )

    # Info command
    subparsers.add_parser(
        "info",
        help="Display system information",
        add_help=False,
    )

    # Fix command
    fix_parser = subparsers.add_parser(
        "fix",
        help="Run recovery commands",
        add_help=False,
    )
    fix_parser.add_argument(
        "fix_target",
        nargs="?",
        metavar="target",
        help="Target to fix (apt, ssh, etc.)",
    )
    fix_parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show help for fix command",
    )

    return parser


def show_help() -> None:
    """Display formatted help screen with command grouping and examples."""
    help_text = """GrapheneOS Debian VM Setup Tool (gvm)

USAGE:
  gvm [command] [options]

MAIN COMMAND:
  setup                 Interactive setup with component selection (TUI)

SETUP COMMANDS:
  apt                   Configure APT package manager
  ssh                   Configure SSH server
  desktop <name>        Install desktop environment
  desktop list          List available desktops
  shell                 Configure shell customizations
  gui                   Install GUI helper scripts

RUNTIME COMMANDS:
  start [desktop]       Launch desktop environment
  start --list          List installed desktops
  gpu status            Check VirGL GPU status
  gpu help              Show VirGL setup instructions

MANAGEMENT COMMANDS:
  config init           Create user config file
  config show           Show effective configuration
  info                  Display system information
  fix <target>          Run recovery commands

GLOBAL FLAGS:
  -v, --verbose         Show detailed output
  --config PATH         Use custom config file
  --dry-run             Simulate without making changes
  -i, --interactive     Force interactive mode (default for setup)
  -f, --force           Force re-run even if already installed

EXAMPLES:
  gvm setup                    # Interactive setup with TUI
  gvm setup --all              # Non-interactive full setup
  gvm desktop plasma-mobile    # Install specific desktop
  gvm apt -v                   # Configure APT with verbose output
"""
    print(help_text)


def show_command_help(command: str) -> None:
    """Display help for a specific command.

    Args:
        command: The command to show help for.
    """
    help_texts = {
        "setup": """gvm setup - Interactive Setup

USAGE:
  gvm setup [options]

OPTIONS:
  --all                 Run non-interactive full setup (all modules)

DESCRIPTION:
  Launches the interactive TUI for component selection and setup.
  Use --all to run all modules without interaction.
""",
        "apt": """gvm apt - Configure APT

USAGE:
  gvm apt [options]

DESCRIPTION:
  Configures APT package manager with hardening settings, stabilizes
  Debian mirrors, cleans caches, repairs dpkg, and updates the system.
""",
        "ssh": """gvm ssh - Configure SSH

USAGE:
  gvm ssh [options]

DESCRIPTION:
  Configures SSH server with secure settings for remote access.
""",
        "desktop": """gvm desktop - Install Desktop Environment

USAGE:
  gvm desktop <name>
  gvm desktop list

ARGUMENTS:
  name                  Name of desktop to install (e.g., plasma-mobile)
  list                  Show available desktop environments

DESCRIPTION:
  Installs and configures a desktop environment. Use 'list' to see
  available options.
""",
        "shell": """gvm shell - Configure Shell

USAGE:
  gvm shell [options]

DESCRIPTION:
  Applies shell customizations and configurations.
""",
        "gui": """gvm gui - Install GUI Helpers

USAGE:
  gvm gui [options]

DESCRIPTION:
  Installs GUI helper scripts for easier desktop management.
""",
        "config": """gvm config - Configuration Management

USAGE:
  gvm config init
  gvm config show

ACTIONS:
  init                  Create user config file at ~/.config/gvm/config.toml
  show                  Display effective (merged) configuration
""",
        "info": """gvm info - System Information

USAGE:
  gvm info

DESCRIPTION:
  Displays system information including Debian version, installed
  modules, SSH status, and available desktops.
""",
        "fix": """gvm fix - Recovery Commands

USAGE:
  gvm fix <target>

TARGETS:
  apt                   Clean APT caches, repair dpkg, update
  ssh                   Restart SSH service

DESCRIPTION:
  Runs recovery procedures for the specified target.
""",
        "start": """gvm start - Launch Desktop Environment

USAGE:
  gvm start [desktop]
  gvm start --list

ARGUMENTS:
  desktop               Name of desktop to start (optional if only one installed)

OPTIONS:
  --list                List installed desktop environments

DESCRIPTION:
  Launches a desktop environment with proper AVF environment setup.
  Checks Wayland display readiness and provides guidance if not ready.

  If no desktop name is provided, starts:
  - Last used desktop (if known)
  - Only installed desktop (if exactly one)
  - Shows list if multiple desktops installed
""",
        "gpu": """gvm gpu - GPU Status and Diagnostics

USAGE:
  gvm gpu status
  gvm gpu help

ACTIONS:
  status                Check if VirGL GPU acceleration is active
  help                  Show VirGL setup instructions

DESCRIPTION:
  Provides GPU-related diagnostics and setup guidance for VirGL
  acceleration on GrapheneOS AVF VMs.
""",
    }

    if command in help_texts:
        print(help_texts[command])
    else:
        show_help()


def cmd_setup(args: argparse.Namespace, config: Config) -> int:
    """Handle the setup command.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if getattr(args, "help", False):
        show_command_help("setup")
        return 0

    if args.all:
        # Non-interactive full setup
        print("Running non-interactive full setup...")
        orchestrator = ModuleOrchestrator(
            config,
            verbose=args.verbose,
            dry_run=args.dry_run,
            force=args.force,
        )

        # Get all available modules
        modules = list_modules()

        if not modules:
            print("No modules available.")
            return 1

        def progress_callback(
            percent: float, message: str, operation: Optional[str]
        ) -> None:
            bar_width = 30
            filled = int(bar_width * percent)
            bar = "=" * filled + ">" + " " * (bar_width - filled - 1)
            print(f"\r[{bar}] {percent:.0%} {message}", end="", flush=True)
            if percent >= 1.0:
                print()  # Newline at completion

        def error_callback(module_name: str, result: ModuleResult) -> None:
            print(f"\nError in {module_name}: {result.message}")
            if result.recovery_command:
                print(f"Recovery: {result.recovery_command}")

        from gvm.modules import RecoveryAction

        results = orchestrator.execute(
            modules,
            progress_callback=progress_callback,
            error_callback=lambda n, r: (error_callback(n, r), RecoveryAction.SKIP)[1],
        )

        summary = orchestrator.get_execution_summary(results)
        print(f"\nSetup complete: {summary['successful']}/{summary['total']} modules")
        if summary["failed"] > 0:
            print(f"Failed: {summary['failed']}")
        if summary["skipped"] > 0:
            print(f"Skipped: {summary['skipped']}")

        return 0 if summary["failed"] == 0 else 1

    # Interactive setup - check curses availability
    if not check_curses_available():
        print("Error: Interactive mode requires curses support.")
        print("Your terminal does not support curses.")
        print("\nUse CLI commands instead:")
        print("  gvm setup --all              # Non-interactive full setup")
        print("  gvm apt                      # Configure APT")
        print("  gvm ssh                      # Configure SSH")
        print("  gvm desktop plasma-mobile    # Install desktop")
        return 1

    # Launch TUI
    from gvm.tui import CursesTUI

    tui = CursesTUI(config, verbose=args.verbose, dry_run=args.dry_run)
    return tui.run()


def cmd_module(args: argparse.Namespace, config: Config, module_name: str) -> int:
    """Execute an individual module.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.
        module_name: Name of the module to execute.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if getattr(args, "help", False):
        show_command_help(module_name)
        return 0

    # Validate module exists
    if get_module_class(module_name) is None:
        available = list_modules()
        print(f"Error: Unknown module '{module_name}'")
        print(f"Available modules: {', '.join(available)}")
        return 1

    orchestrator = ModuleOrchestrator(
        config,
        verbose=args.verbose,
        dry_run=args.dry_run,
        force=args.force,
    )

    def progress_callback(
        percent: float, message: str, operation: Optional[str]
    ) -> None:
        if args.verbose and operation:
            print(f"  {operation}")
        else:
            bar_width = 30
            filled = int(bar_width * percent)
            bar = "=" * filled + ">" + " " * (bar_width - filled - 1)
            print(f"\r[{bar}] {percent:.0%} {message}", end="", flush=True)
            if percent >= 1.0:
                print()

    from gvm.modules import RecoveryAction

    results = orchestrator.execute(
        [module_name],
        progress_callback=progress_callback,
        error_callback=lambda n, r: RecoveryAction.ABORT,
    )

    result = results.get(module_name)
    if result is None:
        print(f"Error: Module {module_name} did not execute")
        return 2

    if result.status == ModuleStatus.SUCCESS:
        print(f"Module {module_name} completed successfully.")
        return 0
    elif result.status == ModuleStatus.SKIPPED:
        print(f"Module {module_name} skipped: {result.message}")
        return 0
    else:
        print(f"Module {module_name} failed: {result.message}")
        if result.recovery_command:
            print(f"Recovery: {result.recovery_command}")
        return 1


def cmd_desktop(args: argparse.Namespace, config: Config) -> int:
    """Handle the desktop command.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if getattr(args, "help", False):
        show_command_help("desktop")
        return 0

    target = getattr(args, "desktop_target", None)

    if target is None or target == "list":
        # List available desktops
        desktops = config.discover_desktops()

        if not desktops:
            print("No desktop environments found.")
            print("Desktop configurations should be in config/packages/ or ~/.config/gvm/packages/")
            return 0

        print("Available Desktop Environments:\n")
        print(f"{'Name':<20} {'Description':<50}")
        print("-" * 70)

        for name, desktop_config in sorted(desktops.items()):
            desc = desktop_config.description or "No description"
            # Truncate description if too long
            if len(desc) > 47:
                desc = desc[:47] + "..."
            print(f"{name:<20} {desc:<50}")

        print("\nUse 'gvm desktop <name>' to install a desktop environment.")
        return 0

    # Install specific desktop
    desktops = config.discover_desktops()

    if target not in desktops:
        print(f"Error: Desktop '{target}' not found.")
        print(f"Available desktops: {', '.join(sorted(desktops.keys()))}")
        return 1

    # Check if desktop module exists
    if get_module_class("desktop") is None:
        print("Error: Desktop module not yet implemented.")
        print("Desktop environment installation will be available in a future release.")
        return 1

    # Set the selected desktop in config so the Desktop module knows which one to install
    config.selected_desktop = target

    # Execute desktop module with specific desktop config
    orchestrator = ModuleOrchestrator(
        config,
        verbose=args.verbose,
        dry_run=args.dry_run,
        force=args.force,
    )

    def progress_callback(
        percent: float, message: str, operation: Optional[str]
    ) -> None:
        bar_width = 30
        filled = int(bar_width * percent)
        bar = "=" * filled + ">" + " " * (bar_width - filled - 1)
        print(f"\r[{bar}] {percent:.0%} {message}", end="", flush=True)
        if percent >= 1.0:
            print()

    from gvm.modules import RecoveryAction

    results = orchestrator.execute(
        ["desktop"],
        progress_callback=progress_callback,
        error_callback=lambda n, r: RecoveryAction.ABORT,
    )

    result = results.get("desktop")
    if result and result.status == ModuleStatus.SUCCESS:
        desktop_config = desktops[target]
        helper_script = desktop_config.session_helper_script_name
        if helper_script:
            print(f"\nDesktop installed. Start with: {helper_script}")
        return 0

    return 1


def cmd_config(args: argparse.Namespace, config: Config) -> int:
    """Handle the config command.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if getattr(args, "help", False):
        show_command_help("config")
        return 0

    action = getattr(args, "config_action", None)

    if action is None:
        show_command_help("config")
        return 0

    if action == "init":
        # Create user config file
        user_config_dir = Path.home() / ".config" / "gvm"
        user_config_path = user_config_dir / "config.toml"

        if user_config_path.exists():
            response = input(f"Config file already exists at {user_config_path}. Overwrite? [y/N] ")
            if response.lower() != "y":
                print("Aborted.")
                return 0

        # Copy from default config (module is in src/gvm/)
        default_config_path = Path(__file__).parent.parent.parent / "config" / "default.toml"

        if not default_config_path.exists():
            print(f"Error: Default config not found at {default_config_path}")
            return 1

        user_config_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(default_config_path, user_config_path)
        print(f"Created config file at {user_config_path}")
        return 0

    elif action == "show":
        # Show effective configuration
        print("Effective Configuration:\n")

        sections = ["meta", "environment", "ports", "apt", "ssh", "features", "banner"]

        for section in sections:
            data = getattr(config, section, {})
            if data:
                print(f"[{section}]")
                for key, value in data.items():
                    print(f"  {key} = {value!r}")
                print()

        return 0

    return 0


def cmd_info(args: argparse.Namespace, config: Config) -> int:
    """Handle the info command.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    print("GrapheneOS Debian VM System Information\n")
    print("=" * 45)

    # Debian version
    codename = detect_debian_codename()
    print(f"Debian Version:    {codename or 'Unknown'}")

    # SSH status
    ssh_running = is_service_running("ssh") or is_service_running("sshd")
    ssh_port = config.ssh_forward_port
    port_listening = is_port_listening(ssh_port)

    print(f"SSH Service:       {'Running' if ssh_running else 'Not Running'}")
    print(f"SSH Port {ssh_port}:      {'Listening' if port_listening else 'Not Listening'}")

    # Installed modules
    print("\nModule Status:")
    print("-" * 45)

    orchestrator = ModuleOrchestrator(config)
    available_modules = list_modules()

    for module_name in available_modules:
        try:
            orchestrator.load_modules([module_name])
            module = orchestrator.modules.get(module_name)
            if module:
                is_installed, message = module.is_installed()
                status = "Installed" if is_installed else "Not Installed"
                print(f"  {module_name:<15} {status:<15} ({message})")
        except Exception as e:
            print(f"  {module_name:<15} Error: {e}")

    # Available desktops
    desktops = config.discover_desktops()
    if desktops:
        print("\nAvailable Desktops:")
        print("-" * 45)
        for name in sorted(desktops.keys()):
            print(f"  {name}")

    return 0


def cmd_fix(args: argparse.Namespace, config: Config) -> int:
    """Handle the fix command.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if getattr(args, "help", False):
        show_command_help("fix")
        return 0

    target = getattr(args, "fix_target", None)

    if target is None:
        show_command_help("fix")
        return 0

    import subprocess

    # Default timeout for recovery commands (in seconds)
    CMD_TIMEOUT = 120

    def run_recovery_command(
        cmd: list[str], desc: str, verbose: bool, timeout: int = CMD_TIMEOUT
    ) -> tuple[bool, str]:
        """Run a recovery command with timeout handling.

        Returns:
            Tuple of (success, message) where success is True if command completed
            successfully, and message contains any warning/error information.
        """
        try:
            result = subprocess.run(
                cmd, capture_output=not verbose, timeout=timeout
            )
            if result.returncode != 0:
                return (False, f"returned non-zero exit code ({result.returncode})")
            return (True, "")
        except subprocess.TimeoutExpired:
            return (False, f"timed out after {timeout} seconds")

    if target == "apt":
        print("Running APT recovery...")
        commands = [
            (["sudo", "apt", "clean"], "Cleaning APT cache"),
            (["sudo", "dpkg", "--configure", "-a"], "Configuring dpkg"),
            (["sudo", "apt", "-f", "install", "-y"], "Fixing broken dependencies"),
            (["sudo", "apt", "update"], "Updating package index"),
        ]

        for cmd, desc in commands:
            print(f"  {desc}...")
            if args.dry_run:
                print(f"    [DRY RUN] Would run: {' '.join(cmd)}")
            else:
                success, message = run_recovery_command(cmd, desc, args.verbose)
                if not success:
                    print(f"    Warning: {desc} {message}")

        print("APT recovery complete.")
        return 0

    elif target == "ssh":
        print("Running SSH recovery...")
        commands = [
            (["sudo", "systemctl", "restart", "ssh"], "Restarting SSH service"),
        ]

        for cmd, desc in commands:
            print(f"  {desc}...")
            if args.dry_run:
                print(f"    [DRY RUN] Would run: {' '.join(cmd)}")
            else:
                success, message = run_recovery_command(cmd, desc, args.verbose)
                if not success:
                    # Try sshd instead
                    alt_cmd = ["sudo", "systemctl", "restart", "sshd"]
                    success, message = run_recovery_command(alt_cmd, desc, args.verbose)
                    if not success:
                        print(f"    Warning: {desc} {message}")

        print("SSH recovery complete.")
        return 0

    else:
        # Generic suggestion
        print(f"Unknown fix target: {target}")
        print(f"Try re-running the module: gvm {target}")
        return 1


def route_command(args: argparse.Namespace, config: Config) -> int:
    """Route parsed arguments to appropriate handler functions.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    command = args.command

    if command is None:
        show_help()
        return 0

    if command == "setup":
        return cmd_setup(args, config)
    elif command == "apt":
        return cmd_module(args, config, "apt")
    elif command == "ssh":
        return cmd_module(args, config, "ssh")
    elif command == "desktop":
        return cmd_desktop(args, config)
    elif command == "shell":
        return cmd_module(args, config, "shell")
    elif command == "gui":
        return cmd_module(args, config, "gui")
    elif command == "config":
        return cmd_config(args, config)
    elif command == "info":
        return cmd_info(args, config)
    elif command == "fix":
        return cmd_fix(args, config)
    elif command == "start":
        return cmd_start(args, config)
    elif command == "gpu":
        return cmd_gpu(args, config)
    else:
        print(f"Unknown command: {command}")
        show_help()
        return 1


def cmd_start(args: argparse.Namespace, config: Config) -> int:
    """Handle the start command.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if getattr(args, "help", False):
        show_command_help("start")
        return 0

    from gvm.start import cmd_start as start_impl

    return start_impl(
        config,
        desktop_name=getattr(args, "desktop_name", None),
        list_desktops=getattr(args, "list", False),
        verbose=args.verbose,
    )


def cmd_gpu(args: argparse.Namespace, config: Config) -> int:
    """Handle the gpu command.

    Args:
        args: Parsed command-line arguments.
        config: Loaded configuration.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if getattr(args, "help", False):
        show_command_help("gpu")
        return 0

    from gvm.gpu import cmd_gpu_help, cmd_gpu_status

    action = getattr(args, "gpu_action", None)

    if action is None:
        show_command_help("gpu")
        return 0

    if action == "status":
        return cmd_gpu_status(verbose=args.verbose)
    elif action == "help":
        return cmd_gpu_help()

    return 0


def main() -> int:
    """Main entry point for the CLI.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    parser = create_argument_parser()
    args = parser.parse_args()

    # Handle top-level help
    if args.help and args.command is None:
        show_help()
        return 0

    # Load configuration
    try:
        config = Config.load(cli_config_path=args.config)
    except SystemExit as e:
        print(f"Error loading configuration: {e}")
        return 1

    return route_command(args, config)


if __name__ == "__main__":
    sys.exit(main())
