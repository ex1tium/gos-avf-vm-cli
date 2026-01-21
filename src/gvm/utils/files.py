"""File manipulation utilities for GVM tool.

This module provides functions for:
- Managing marker-based snippets in configuration files
- Safe file writing with backup support
- Handling system files that require elevated permissions
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def ensure_snippet(
    file_path: Path,
    label: str,
    snippet: str,
) -> None:
    """Ensure a labeled snippet exists in a file.

    Uses marker comments to identify and manage the snippet:
    - Marker begin: # >>> {label} >>>
    - Marker end: # <<< {label} <<<

    If markers already exist in the file, the function returns without
    modification. Otherwise, the snippet is appended to the file.

    Args:
        file_path: Path to the file to modify.
        label: Unique label for the snippet markers.
        snippet: Content to add between markers.

    Example:
        >>> ensure_snippet(
        ...     Path("/home/user/.bashrc"),
        ...     "gvm-env",
        ...     "export PATH=$PATH:/opt/gvm/bin"
        ... )
    """
    # Create parent directories if they don't exist
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content
    if file_path.exists():
        content = file_path.read_text()
    else:
        content = ""

    # Define markers
    marker_begin = f"# >>> {label} >>>"
    marker_end = f"# <<< {label} <<<"

    # Check if markers already present
    if marker_begin in content and marker_end in content:
        print(f"Snippet '{label}' already exists in {file_path}")
        return

    # Append the snippet block
    block = f"\n{marker_begin}\n{snippet.strip()}\n{marker_end}\n"

    with open(file_path, "a") as f:
        f.write(block)

    print(f"Added snippet '{label}' to {file_path}")


def safe_write(
    path: Path,
    content: str,
    backup: bool = True,
    mode: int = 0o644,
) -> None:
    """Safely write content to a file with optional backup.

    For system files (outside user's home), uses sudo to copy the file.
    Creates a backup with .bak suffix if requested.

    Args:
        path: Target file path.
        content: Content to write.
        backup: If True, create backup of existing file.
        mode: File permission mode (default 0o644).

    Raises:
        SystemExit: If file operations fail.

    Example:
        >>> safe_write(
        ...     Path("/etc/ssh/sshd_config.d/custom.conf"),
        ...     "PermitRootLogin no",
        ...     backup=True
        ... )
    """
    # Determine if we need sudo (system files outside home)
    home = Path.home()
    needs_sudo = not str(path).startswith(str(home))

    # Create backup if requested and file exists
    if backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        if needs_sudo:
            _sudo_copy(path, backup_path)
        else:
            shutil.copy2(path, backup_path)
        print(f"Created backup: {backup_path}")

    # Write to temporary file first
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tmp") as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        if needs_sudo:
            # Ensure parent directory exists
            parent = path.parent
            if not parent.exists():
                _sudo_mkdir(parent)

            # Copy temp file to target with sudo
            _sudo_copy(tmp_path, path)
            _sudo_chmod(path, mode)
        else:
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)

            # Move temp file to target
            shutil.move(tmp_path, path)
            path.chmod(mode)

        print(f"Written: {path}")

    except Exception as e:
        raise SystemExit(f"Failed to write {path}: {e}") from e

    finally:
        # Clean up temp file if it still exists
        if tmp_path.exists():
            tmp_path.unlink()


def _sudo_copy(src: Path, dst: Path) -> None:
    """Copy a file using sudo.

    Args:
        src: Source file path.
        dst: Destination file path.

    Raises:
        SystemExit: If copy fails.
    """
    result = subprocess.run(
        ["sudo", "cp", str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"sudo cp failed: {result.stderr}")


def _sudo_mkdir(path: Path) -> None:
    """Create a directory using sudo.

    Args:
        path: Directory path to create.

    Raises:
        SystemExit: If mkdir fails.
    """
    result = subprocess.run(
        ["sudo", "mkdir", "-p", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"sudo mkdir failed: {result.stderr}")


def _sudo_chmod(path: Path, mode: int) -> None:
    """Change file permissions using sudo.

    Args:
        path: File path.
        mode: Permission mode (e.g., 0o644).

    Raises:
        SystemExit: If chmod fails.
    """
    mode_str = oct(mode)[2:]  # Convert 0o644 to "644"
    result = subprocess.run(
        ["sudo", "chmod", mode_str, str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"sudo chmod failed: {result.stderr}")
