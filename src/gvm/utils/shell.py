"""Shell command execution utilities for GVM tool.

This module provides functions for executing shell commands with:
- Optional output capture
- Verbose mode for debugging
- Progress callback support for streaming output
- Proper error handling with clear messages
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional


def run(
    cmd: list[str],
    check: bool = True,
    capture: bool = False,
    verbose: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
    env: Optional[dict] = None,
    input_data: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Execute a shell command with optional output capture and progress streaming.

    Args:
        cmd: Command and arguments as a list of strings.
        check: If True, raise SystemExit on non-zero exit code.
        capture: If True, capture stdout/stderr and return in result.
        verbose: If True, print command before execution.
        progress_callback: Optional callback to receive output lines in real-time.
            Only used when capture is True.
        env: Optional environment variables to pass to subprocess.
        input_data: Optional string to pass to stdin of the command.

    Returns:
        subprocess.CompletedProcess with execution results.

    Raises:
        SystemExit: If check is True and command returns non-zero exit code.

    Example:
        >>> result = run(["ls", "-la"], capture=True)
        >>> print(result.stdout)

        >>> run(["apt", "update"], verbose=True, progress_callback=print)

        >>> run(["chpasswd"], input_data="user:password\\n")
    """
    if verbose:
        print(f"Running: {' '.join(cmd)}")

    # Use Popen for streaming with progress callback
    if capture and progress_callback:
        return _run_with_streaming(cmd, check, verbose, progress_callback, env)

    # Standard subprocess.run for simpler cases
    kwargs: dict = {}

    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
        kwargs["text"] = True

    if input_data is not None:
        kwargs["input"] = input_data
        kwargs["text"] = True

    if env:
        # Merge provided env with current environment (preserving PATH, etc.)
        merged_env = os.environ.copy()
        merged_env.update(env)
        kwargs["env"] = merged_env

    try:
        result = subprocess.run(cmd, **kwargs)
    except FileNotFoundError:
        raise SystemExit(f"Command not found: {cmd[0]}") from None
    except PermissionError:
        raise SystemExit(f"Permission denied: {cmd[0]}") from None

    if check and result.returncode != 0:
        error_msg = f"Command failed with exit code {result.returncode}: {' '.join(cmd)}"
        if capture and result.stdout:
            error_msg += f"\nOutput: {result.stdout}"
        raise SystemExit(error_msg)

    return result


def _run_with_streaming(
    cmd: list[str],
    check: bool,
    _verbose: bool,
    progress_callback: Callable[[str], None],
    env: Optional[dict],
) -> subprocess.CompletedProcess:
    """Execute command with real-time output streaming to callback.

    Args:
        cmd: Command and arguments as a list of strings.
        check: If True, raise SystemExit on non-zero exit code.
        _verbose: Unused here (already printed in caller), kept for API consistency.
        progress_callback: Callback to receive output lines.
        env: Optional environment variables.

    Returns:
        subprocess.CompletedProcess with captured output.

    Raises:
        SystemExit: If check is True and command returns non-zero exit code.
    """
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,  # Line buffered
    }

    if env:
        # Merge provided env with current environment (preserving PATH, etc.)
        merged_env = os.environ.copy()
        merged_env.update(env)
        kwargs["env"] = merged_env

    output_lines: list[str] = []

    try:
        with subprocess.Popen(cmd, **kwargs) as proc:
            if proc.stdout:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    output_lines.append(line)
                    progress_callback(line)

            proc.wait()
            returncode = proc.returncode

    except FileNotFoundError:
        raise SystemExit(f"Command not found: {cmd[0]}") from None
    except PermissionError:
        raise SystemExit(f"Permission denied: {cmd[0]}") from None

    stdout = "\n".join(output_lines)

    if check and returncode != 0:
        error_msg = f"Command failed with exit code {returncode}: {' '.join(cmd)}"
        if stdout:
            error_msg += f"\nOutput: {stdout}"
        raise SystemExit(error_msg)

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout=stdout,
        stderr=None,
    )
