"""GPU status and diagnostics for GVM tool.

This module provides GPU-related utilities for checking VirGL status
and displaying setup instructions for GrapheneOS AVF VMs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def check_virgl_status() -> tuple[bool, str]:
    """Check if VirGL appears to be active.

    Returns:
        Tuple of (is_active, message) with status details.
        is_active is computed from GPU-specific signals only (DRI devices
        and VirGL/Zink renderer detection), not from Wayland status.
    """
    indicators = []
    gpu_signals = []  # Track GPU-specific positive signals
    software_rendering = False  # Track if software rendering is detected

    # Check for DRI devices
    dri_path = Path("/dev/dri")
    if dri_path.exists() and list(dri_path.glob("*")):
        indicators.append("✓ DRI devices present")
        gpu_signals.append(True)
    else:
        indicators.append("✗ No DRI devices found")

    # Check glxinfo if available
    try:
        result = subprocess.run(
            ["glxinfo", "-B"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            output = result.stdout.lower()
            if "virgl" in output or "zink" in output:
                indicators.append("✓ VirGL/Zink renderer detected")
                gpu_signals.append(True)
            else:
                indicators.append("✗ Software rendering detected")
                software_rendering = True
        else:
            indicators.append("⚠ glxinfo failed to run")
    except FileNotFoundError:
        indicators.append("⚠ glxinfo not installed (run: sudo apt install mesa-utils)")
    except subprocess.TimeoutExpired:
        indicators.append("⚠ glxinfo timed out")

    # Check Wayland display (informational only, not used for is_active)
    wayland_display = Path(f"/run/user/{os.getuid()}/wayland-0")
    if wayland_display.exists():
        indicators.append("✓ Wayland display active")
    else:
        indicators.append("✗ Wayland display not active")

    # is_active based only on GPU-specific signals, but software rendering overrides
    is_active = len(gpu_signals) > 0 and not software_rendering
    message = "\n".join(indicators)

    return is_active, message


def show_virgl_help() -> None:
    """Display VirGL setup instructions."""
    help_text = """
GPU Acceleration Setup (VirGL)

VirGL must be enabled BEFORE starting the VM. This cannot be
done from inside the VM due to AVF security isolation.

To enable VirGL GPU acceleration:

  1. Close the Terminal app completely (swipe away from recents)
  2. Open the Files app on your Android device
  3. Navigate to: Internal Storage > linux
     (create the 'linux' folder if it doesn't exist)
  4. Create an empty file named: virglrenderer
     (the content doesn't matter, just the filename)
  5. Reopen the Terminal app - you should see a toast
     message saying "VirGL enabled"

Note: VirGL provides OpenGL acceleration via ANGLE. Some
applications requiring newer OpenGL versions may not work
until full GPU virtualization is available (Pixel 10+).

To verify VirGL is working:
  - Run: gvm gpu status
  - Run: glxinfo -B | grep -i renderer
"""
    print(help_text)


def cmd_gpu_status(verbose: bool = False) -> int:
    """Handle 'gvm gpu status' command.

    Args:
        verbose: Show detailed output including raw diagnostics.

    Returns:
        Exit code (0 for success).
    """
    print("GPU Status Check\n")
    print("=" * 50)

    is_active, message = check_virgl_status()
    print(message)
    print("=" * 50)

    if verbose:
        print("\nDiagnostics:")
        print(f"  is_active: {is_active}")
        print("  Raw message:\n    " + message.replace("\n", "\n    "))

    if is_active:
        print("\n✓ GPU acceleration appears to be active")
    else:
        print("\n✗ GPU acceleration may not be active")
        print("\nRun 'gvm gpu help' for setup instructions")

    return 0


def cmd_gpu_help() -> int:
    """Handle 'gvm gpu help' command.

    Returns:
        Exit code (0 for success).
    """
    show_virgl_help()
    return 0
