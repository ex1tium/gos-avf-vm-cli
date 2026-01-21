"""Desktop launcher for GVM tool.

This module provides the 'gvm start' command for launching desktop
environments with proper AVF environment setup and Wayland display checks.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gvm.config import Config


def resolve_desktop_name(config: Config, user_input: str) -> Optional[str]:
    """Resolve user input to actual desktop name with fuzzy matching.

    Supports:
    - Exact match (case-insensitive)
    - Partial match (e.g., "plasma" matches "Plasma Mobile")
    - Common aliases

    Args:
        config: Configuration object.
        user_input: User-provided desktop name.

    Returns:
        Actual desktop name from config, or None if not found.
    """
    desktops = config.discover_desktops()
    user_lower = user_input.lower()

    # Try exact match (case-insensitive)
    for name in desktops.keys():
        if name.lower() == user_lower:
            return name

    # Try partial match - user input is prefix or substring
    matches = []
    for name in desktops.keys():
        name_lower = name.lower()
        # Check if user input is a prefix or the name starts with it
        if name_lower.startswith(user_lower):
            matches.append(name)
        # Check if any word in the name starts with user input
        elif any(word.startswith(user_lower) for word in name_lower.split()):
            matches.append(name)

    # If exactly one match, return it
    if len(matches) == 1:
        return matches[0]

    # If multiple matches, try to find the best one
    if len(matches) > 1:
        # Prefer exact word match
        for name in matches:
            if user_lower in name.lower().split():
                return name
        # Return first match if no exact word match
        return matches[0]

    return None


def check_wayland_ready(timeout: int = 10) -> bool:
    """Check if Wayland compositor is ready.

    Checks for:
    1. XDG_RUNTIME_DIR exists
    2. WAYLAND_DISPLAY socket exists in runtime dir

    Args:
        timeout: Maximum seconds to wait for display.

    Returns:
        True if Wayland display is ready, False otherwise.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    socket_path = Path(runtime_dir) / wayland_display

    # Poll for socket with timeout
    start = time.time()
    while time.time() - start < timeout:
        if socket_path.exists():
            return True
        time.sleep(0.5)

    return False


def show_display_not_ready_message() -> None:
    """Display guidance when Wayland display is not ready."""
    message = """
Display not ready

To enable the graphical display:
  1. Look for the display icon in the top-right corner
     of the GrapheneOS Terminal app
  2. Tap the icon to enable the display
  3. Run 'gvm start' again
"""
    print(message)


def get_installed_desktops(config: Config) -> list[str]:
    """Get list of installed desktop environments.

    Args:
        config: Configuration object.

    Returns:
        List of installed desktop names.
    """
    installed = []
    desktops = config.discover_desktops()

    for name, desktop in desktops.items():
        if desktop.packages_core:
            # Check if core packages are installed
            all_installed = True
            for package in desktop.packages_core:
                try:
                    result = subprocess.run(
                        ["dpkg-query", "-W", "-f=${Status}\\n", package],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode != 0 or "install ok installed" not in result.stdout:
                        all_installed = False
                        break
                except Exception:
                    all_installed = False
                    break

            if all_installed:
                installed.append(name)

    return installed


def get_default_desktop(config: Config) -> Optional[str]:
    """Get default desktop to start.

    Priority:
    1. Last used desktop (from ~/.config/gvm/last-desktop)
    2. Only installed desktop (if exactly one)
    3. None (user must specify)

    Args:
        config: Configuration object.

    Returns:
        Desktop name or None.
    """
    last_desktop_file = Path.home() / ".config" / "gvm" / "last-desktop"

    # Check last used
    if last_desktop_file.exists():
        try:
            last = last_desktop_file.read_text().strip()
            if last:
                # Verify it's still installed
                installed = get_installed_desktops(config)
                if last in installed:
                    return last
        except Exception:
            pass

    # Check for single installed desktop
    installed = get_installed_desktops(config)
    if len(installed) == 1:
        return installed[0]

    return None


def save_last_desktop(desktop_name: str) -> None:
    """Save last used desktop for future default.

    Args:
        desktop_name: Name of desktop to save.

    Note:
        Failures are logged as warnings but do not raise exceptions,
        as this is just a convenience feature.
    """
    try:
        last_desktop_file = Path.home() / ".config" / "gvm" / "last-desktop"
        last_desktop_file.parent.mkdir(parents=True, exist_ok=True)
        last_desktop_file.write_text(desktop_name + "\n")
    except OSError as e:
        # Log warning but don't fail - this is just a convenience feature
        print(f"Warning: Could not save last desktop preference: {e}")


def launch_desktop(config: Config, desktop_name: str, verbose: bool = False) -> int:
    """Launch a desktop environment.

    Args:
        config: Configuration object.
        desktop_name: Name of desktop to launch.
        verbose: Show verbose output.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    desktops = config.discover_desktops()

    if desktop_name not in desktops:
        print(f"Error: Desktop '{desktop_name}' not found")
        available = ", ".join(sorted(desktops.keys()))
        print(f"Available desktops: {available}")
        return 1

    desktop = desktops[desktop_name]

    # Check if desktop is installed
    installed = get_installed_desktops(config)
    if desktop_name not in installed:
        print(f"Error: Desktop '{desktop_name}' is not installed")
        print(f"Install with: gvm desktop {desktop_name}")
        return 1

    # Source enable_display script BEFORE checking Wayland readiness
    # This ensures environment variables like XDG_RUNTIME_DIR and WAYLAND_DISPLAY are set
    enable_display_path = Path.home() / ".config" / "linuxvm" / "enable_display"
    if enable_display_path.exists():
        if verbose:
            print(f"Sourcing {enable_display_path}")
        # Environment variables will be inherited by subprocess
        try:
            quoted_path = shlex.quote(str(enable_display_path))
            result = subprocess.run(
                ["bash", "-c", f"source {quoted_path} && env"],
                capture_output=True,
                text=True,
                check=True,
            )
            # Parse and set environment variables
            for line in result.stdout.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
        except subprocess.CalledProcessError:
            print(f"Warning: Failed to source {enable_display_path}")

    # Check Wayland display readiness (use default timeout of 10 seconds)
    if verbose:
        print("Checking Wayland display...")

    if not check_wayland_ready():
        show_display_not_ready_message()
        return 1

    # Apply desktop-specific environment variables (mirroring helper script behavior)
    if desktop.environment_vars:
        if verbose:
            print(f"Applying {len(desktop.environment_vars)} desktop environment variables")
        for var in desktop.environment_vars:
            if "=" in var:
                key, value = var.split("=", 1)
                os.environ[key] = value

    # Build launch command
    if not desktop.session_start_command:
        print(f"Error: No start command configured for {desktop_name}")
        return 1

    launch_cmd = desktop.session_start_command

    # Wrap with dbus-run-session if required
    if desktop.session_requires_dbus:
        launch_cmd = f"dbus-run-session {launch_cmd}"

    if verbose:
        print(f"Launching: {launch_cmd}")

    # Save as last used desktop
    save_last_desktop(desktop_name)

    # Launch desktop (replace current process)
    os.execvp("bash", ["bash", "-c", launch_cmd])

    # This line is never reached if exec succeeds
    return 0


def cmd_start(
    config: Config,
    desktop_name: Optional[str] = None,
    list_desktops: bool = False,
    verbose: bool = False,
) -> int:
    """Handle 'gvm start' command.

    Args:
        config: Configuration object.
        desktop_name: Optional desktop name to start.
        list_desktops: Show list of available desktops.
        verbose: Show verbose output.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if list_desktops:
        installed = get_installed_desktops(config)
        desktops = config.discover_desktops()

        if not installed:
            print("No desktop environments installed.")
            print("\nAvailable desktops:")
            for name in sorted(desktops.keys()):
                print(f"  {name} - {desktops[name].description}")
            print("\nInstall with: gvm desktop <name>")
            return 0

        print("Installed Desktop Environments:\n")
        for name in sorted(installed):
            desktop = desktops[name]
            print(f"  {name:<20} {desktop.description}")

        print("\nStart with: gvm start <name>")
        return 0

    # Determine which desktop to start
    if desktop_name is None:
        desktop_name = get_default_desktop(config)

        if desktop_name is None:
            installed = get_installed_desktops(config)
            if not installed:
                print("No desktop environments installed.")
                print("Install with: gvm desktop <name>")
                return 1

            print("Multiple desktops installed. Please specify which to start:")
            for name in sorted(installed):
                print(f"  gvm start {name.lower().replace(' ', '-')}")
            return 1

        if verbose:
            print(f"Starting default desktop: {desktop_name}")
    else:
        # Resolve user input to actual desktop name
        resolved = resolve_desktop_name(config, desktop_name)
        if resolved is None:
            desktops = config.discover_desktops()
            print(f"Error: Desktop '{desktop_name}' not found")
            print("Available desktops:")
            for name in sorted(desktops.keys()):
                print(f"  {name.lower().replace(' ', '-')} ({name})")
            return 1
        desktop_name = resolved

    return launch_desktop(config, desktop_name, verbose)
