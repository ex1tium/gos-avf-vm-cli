"""GUI module for GVM tool.

This module creates GUI helper scripts for launching desktop environments.
It has an optional dependency on the desktop module for discovering
available desktop environments.
"""

from __future__ import annotations

import re
import shlex
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from gvm.modules.base import Dependency, Module, ModuleResult, ModuleStatus
from gvm.utils.files import ensure_snippet, safe_write

if TYPE_CHECKING:
    from gvm.config import Config


class GUIModule(Module):
    """Create GUI helper scripts for desktop environment launching.

    This module has an optional dependency on the desktop module.
    It performs the following operations:
    1. Create ~/.local/bin/ directory
    2. Create generic start-gui helper script
    3. Create desktop-specific launch scripts
    4. Add ~/.local/bin to PATH if not present
    """

    name = "gui"
    description = "Create GUI helper scripts for desktop environment launching"
    dependencies = (Dependency("desktop", required=False),)

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize GUI module.

        Args:
            config: Configuration object with user settings.
            verbose: Enable verbose output.
            dry_run: Simulate execution without making changes.
        """
        super().__init__(config, verbose, dry_run)
        self.local_bin_path = Path.home() / ".local" / "bin"
        self.start_gui_path = self.local_bin_path / "start-gui"
        self.bashrc_path = Path.home() / ".bashrc"
        self.display_enabler_path = Path.home() / ".config" / "linuxvm" / "enable_display"
        self.local_bin_marker = "gvm-local-bin"

    def is_installed(self) -> tuple[bool, str]:
        """Check if GUI helper scripts are already present.

        Returns:
            Tuple of (is_installed, message) indicating detection result.
        """
        if self.start_gui_path.exists():
            return (True, "GUI helper scripts already present")

        return (False, "GUI helpers not configured")

    def run(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> ModuleResult:
        """Execute GUI helper script creation.

        Args:
            progress_callback: Callback to report progress.

        Returns:
            ModuleResult indicating success or failure.
        """
        try:
            self._report_progress(
                progress_callback, 0.0, "Starting GUI helper configuration"
            )

            # Step 1: Create ~/.local/bin/ directory
            self._create_local_bin_directory(progress_callback)

            # Step 2: Create generic start-gui helper script
            self._create_start_gui_script(progress_callback)

            # Step 3: Create desktop-specific launch scripts
            self._create_desktop_scripts(progress_callback)

            # Step 4: Add ~/.local/bin to PATH
            self._add_local_bin_to_path(progress_callback)

            if self.dry_run:
                return ModuleResult(
                    status=ModuleStatus.SUCCESS,
                    message="[DRY RUN] GUI helper configuration complete",
                )

            return ModuleResult(
                status=ModuleStatus.SUCCESS,
                message="GUI helper configuration complete",
            )

        except SystemExit as e:
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )
        except Exception as e:  # noqa: BLE001
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )

    def get_recovery_command(self) -> str:
        """Return the CLI command to recover from GUI module failure.

        Returns:
            Recovery command string.
        """
        return "gvm fix gui"

    def _create_local_bin_directory(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create ~/.local/bin/ directory.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.05,
            "Creating local bin directory",
            f"Creating {self.local_bin_path}",
        )

        if self.dry_run:
            print(f"[DRY RUN] Would create directory: {self.local_bin_path}")
            self._report_progress(
                progress_callback, 0.3, "Local bin directory created (dry run)"
            )
            return

        self.local_bin_path.mkdir(parents=True, exist_ok=True)
        print(f"Created directory: {self.local_bin_path}")

        self._report_progress(
            progress_callback, 0.3, "Local bin directory created"
        )

    def _create_start_gui_script(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create generic start-gui helper script.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.35,
            "Creating start-gui script",
            f"Writing script to {self.start_gui_path}",
        )

        content = f'''#!/bin/bash
# GVM GUI Helper Script
# Provides a generic entry point for starting desktop environments

# Source display enabler if available
if [ -f "{self.display_enabler_path}" ]; then
    source "{self.display_enabler_path}"
fi

# Show available desktop launchers
echo ""
echo "GVM GUI Helper"
echo "=============="
echo ""
echo "Available desktop launchers:"
echo ""

# List available start-* scripts
for script in ~/.local/bin/start-*; do
    if [ -x "$script" ] && [ "$script" != "{self.start_gui_path}" ]; then
        name=$(basename "$script" | sed 's/^start-//')
        echo "  start-$name"
    fi
done

echo ""
echo "Usage: start-<desktop-name> to launch specific desktop"
echo ""
'''

        if self.dry_run:
            print(f"[DRY RUN] Would write script to {self.start_gui_path}:")
            print(content[:400] + "..." if len(content) > 400 else content)
            self._report_progress(
                progress_callback, 0.6, "start-gui script created (dry run)"
            )
            return

        # Ensure directory exists
        self.local_bin_path.mkdir(parents=True, exist_ok=True)

        # Write the script
        self.start_gui_path.write_text(content)
        self.start_gui_path.chmod(0o755)
        print(f"Created script: {self.start_gui_path}")

        self._report_progress(
            progress_callback, 0.6, "start-gui script created"
        )

    def _derive_script_filename(self, desktop) -> str:
        """Derive the script filename for a desktop environment.

        Uses session_helper_script_name if present, otherwise generates a safe
        slug from desktop.name (lowercase, spaces to hyphens), prefixed with
        'start-' only when not already present.

        Args:
            desktop: DesktopConfig instance.

        Returns:
            Script filename (without path), sanitized to prevent path traversal.
        """
        if desktop.session_helper_script_name:
            filename = desktop.session_helper_script_name
        else:
            # Generate safe slug: lowercase, spaces to hyphens
            filename = desktop.name.lower().replace(" ", "-")

        # Sanitize: extract basename to prevent path traversal
        filename = Path(filename).name

        # Remove any . or .. components that might remain
        filename = filename.lstrip(".")

        # Whitelist characters: only allow alphanumeric, hyphen, underscore
        filename = re.sub(r"[^a-zA-Z0-9_-]", "-", filename)

        # Collapse repeated hyphens and trim leading/trailing hyphens
        filename = re.sub(r"-+", "-", filename).strip("-")

        # Ensure non-empty filename
        if not filename:
            filename = "desktop"

        # Prefix with 'start-' only when not already present
        if not filename.startswith("start-"):
            filename = f"start-{filename}"

        return filename

    def _create_desktop_scripts(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create desktop-specific launch scripts.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.65,
            "Creating desktop-specific scripts",
            "Discovering available desktops",
        )

        # Discover available desktops
        desktops = self.config.discover_desktops()

        if not desktops:
            self._report_progress(
                progress_callback,
                0.9,
                "No desktops discovered",
                "Skipping desktop-specific scripts",
            )
            return

        created_count = 0

        if self.dry_run:
            for desktop_name, desktop in desktops.items():
                session_cmd = desktop.session_start_command
                if not session_cmd:
                    print(f"[DRY RUN] Skipping {desktop_name}: no session_start_command defined")
                    continue
                script_filename = self._derive_script_filename(desktop)
                script_path = self.local_bin_path / script_filename
                print(f"[DRY RUN] Would create script: {script_path}")
                print(f"  Session command: {session_cmd}")
                created_count += 1
            self._report_progress(
                progress_callback, 0.9, f"Desktop scripts created (dry run): {created_count}"
            )
            return

        # Create a launch script for each discovered desktop
        for desktop_name, desktop in desktops.items():
            script_filename = self._derive_script_filename(desktop)
            script_path = self.local_bin_path / script_filename
            session_cmd = desktop.session_start_command

            if not session_cmd:
                print(f"Skipping {desktop_name}: no session_start_command defined")
                continue

            # Build the script content
            dbus_wrapper = ""
            if desktop.session_requires_dbus:
                dbus_wrapper = "dbus-run-session "

            content = f'''#!/bin/bash
# GVM Desktop Launcher: {desktop_name}
# {desktop.description or f"Launch {desktop_name} desktop environment"}

# Source display enabler if available
if [ -f "{self.display_enabler_path}" ]; then
    source "{self.display_enabler_path}"
fi

# Check if Wayland display is ready
check_display_ready() {{
    local runtime_dir="${{XDG_RUNTIME_DIR:-/run/user/$(id -u)}}"
    local wayland_display="${{WAYLAND_DISPLAY:-wayland-0}}"
    local socket_path="$runtime_dir/$wayland_display"

    if [ -S "$socket_path" ]; then
        return 0
    fi
    return 1
}}

if ! check_display_ready; then
    echo ""
    echo "Display not ready"
    echo ""
    echo "To enable the graphical display:"
    echo "  1. Look for the display icon in the top-right corner"
    echo "     of the GrapheneOS Terminal app"
    echo "  2. Tap the icon to enable the display"
    echo "  3. Run this script again"
    echo ""
    exit 1
fi

# Set environment variables
'''
            # Add environment variables if defined
            # Regex for valid shell identifier: starts with letter or underscore,
            # followed by alphanumerics or underscores
            valid_key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
            for env_var in desktop.environment_vars:
                if "=" in env_var:
                    key, value = env_var.split("=", 1)
                    # Validate key is a safe shell identifier
                    if not valid_key_pattern.match(key):
                        print(f"Warning: Skipping invalid env var key in {desktop_name}: {key!r}")
                        continue
                    # Use shlex.quote for shell-safe quoting
                    content += f'export {key}={shlex.quote(value)}\n'
                else:
                    # Variable reference without value - validate the name
                    if not valid_key_pattern.match(env_var):
                        print(f"Warning: Skipping invalid env var name in {desktop_name}: {env_var!r}")
                        continue
                    content += f'export {env_var}\n'

            content += f'''
# Launch desktop session
echo "Starting {desktop_name}..."
exec {dbus_wrapper}{session_cmd}
'''

            # Write the script
            script_path.write_text(content)
            script_path.chmod(0o755)
            print(f"Created script: {script_path}")
            created_count += 1

        self._report_progress(
            progress_callback, 0.9, f"Created {created_count} desktop launcher(s)"
        )

    def _add_local_bin_to_path(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Add ~/.local/bin to PATH if not present.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.92,
            "Adding local bin to PATH",
            f"Updating {self.bashrc_path}",
        )

        snippet = 'export PATH="$HOME/.local/bin:$PATH"'

        if self.dry_run:
            print(f"[DRY RUN] Would add PATH snippet to {self.bashrc_path}:")
            print(f"  # >>> {self.local_bin_marker} >>>")
            print(f"  {snippet}")
            print(f"  # <<< {self.local_bin_marker} <<<")
            self._report_progress(
                progress_callback, 1.0, "PATH configured (dry run)"
            )
            return

        ensure_snippet(self.bashrc_path, self.local_bin_marker, snippet)

        self._report_progress(
            progress_callback, 1.0, "PATH configured"
        )
