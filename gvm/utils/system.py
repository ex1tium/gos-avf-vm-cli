"""System detection and status utilities for GVM tool.

This module provides functions for:
- Detecting Debian codename from /etc/os-release
- Checking service status via systemctl
- Checking if ports are listening
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional


def detect_debian_codename() -> Optional[str]:
    """Detect the Debian version codename from /etc/os-release.

    Parses the VERSION_CODENAME field from the os-release file.

    Returns:
        The Debian codename (e.g., "trixie", "bookworm") or None if not found.

    Example:
        >>> codename = detect_debian_codename()
        >>> print(codename)
        trixie
    """
    os_release_path = Path("/etc/os-release")

    if not os_release_path.exists():
        return None

    try:
        content = os_release_path.read_text()
    except (IOError, PermissionError):
        return None

    # Look for VERSION_CODENAME=<codename>
    match = re.search(r"VERSION_CODENAME=(\w+)", content)
    if match:
        return match.group(1)

    return None


def is_service_running(service_name: str) -> bool:
    """Check if a systemd service is running.

    Uses systemctl is-active to check service status.

    Args:
        service_name: Name of the systemd service (e.g., "ssh", "sshd").

    Returns:
        True if the service is active/running, False otherwise.

    Example:
        >>> if is_service_running("ssh"):
        ...     print("SSH service is running")
    """
    result = subprocess.run(
        ["systemctl", "is-active", service_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_port_listening(port: int) -> bool:
    """Check if a TCP port is listening.

    Uses ss command to check for listening sockets on the specified port.

    Args:
        port: TCP port number to check.

    Returns:
        True if the port is listening, False otherwise.

    Example:
        >>> if is_port_listening(22):
        ...     print("SSH port is open")
    """
    try:
        # Use ss to list listening TCP sockets
        ss_result = subprocess.run(
            ["ss", "-ltn"],
            capture_output=True,
            text=True,
        )

        if ss_result.returncode != 0:
            return False

        # Check if the port appears in the output
        # ss output format includes ":port" in the local address column
        port_pattern = f":{port}\\s"
        return bool(re.search(port_pattern, ss_result.stdout))

    except (FileNotFoundError, PermissionError):
        return False


def get_user_home(username: str) -> Optional[Path]:
    """Get the home directory for a user.

    Args:
        username: The username to look up.

    Returns:
        Path to the user's home directory, or None if not found.

    Example:
        >>> home = get_user_home("droid")
        >>> print(home)
        /home/droid
    """
    try:
        result = subprocess.run(
            ["getent", "passwd", username],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return None

        # getent passwd format: username:x:uid:gid:gecos:home:shell
        parts = result.stdout.strip().split(":")
        if len(parts) >= 6:
            return Path(parts[5])

        return None

    except (FileNotFoundError, PermissionError):
        return None


def user_exists(username: str) -> bool:
    """Check if a user exists on the system.

    Args:
        username: The username to check.

    Returns:
        True if the user exists, False otherwise.

    Example:
        >>> if user_exists("droid"):
        ...     print("User droid exists")
    """
    result = subprocess.run(
        ["id", username],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def get_display_server() -> Optional[str]:
    """Detect the current display server type.

    Checks environment variables to determine if running under
    Wayland or X11.

    Returns:
        "wayland", "x11", or None if not in a graphical session.

    Example:
        >>> server = get_display_server()
        >>> if server == "wayland":
        ...     print("Running on Wayland")
    """
    import os

    # Check for Wayland
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"

    # Check for X11
    if os.environ.get("DISPLAY"):
        return "x11"

    return None
