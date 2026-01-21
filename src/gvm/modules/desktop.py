"""Desktop module for GVM tool.

This module installs and configures desktop environments on the VM.
It dynamically loads desktop configurations from TOML files, installs
packages using APT with a download-first strategy, creates configuration
files with path expansion, and generates helper launch scripts.
"""

from __future__ import annotations

import os
import shlex
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from gvm.config import DesktopConfig
from gvm.modules.base import Dependency, Module, ModuleResult, ModuleStatus
from gvm.utils.files import safe_write
from gvm.utils.shell import run

if TYPE_CHECKING:
    from gvm.config import Config


class DesktopModule(Module):
    """Install and configure desktop environments.

    This module depends on the APT module for package installation.
    It performs the following operations:
    1. Discover available desktop configurations
    2. Install desktop packages using download-first strategy
    3. Create configuration files from templates
    4. Generate helper launch scripts
    """

    name = "desktop"
    description = "Install and configure desktop environments"
    dependencies = (Dependency("apt", required=True),)

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
        desktop_name: Optional[str] = None,
    ) -> None:
        """Initialize Desktop module.

        Args:
            config: Configuration object with user settings.
            verbose: Enable verbose output.
            dry_run: Simulate execution without making changes.
            desktop_name: Optional specific desktop to install. If not provided,
                         falls back to config.selected_desktop.
        """
        super().__init__(config, verbose, dry_run)
        self.marker_path = Path("/etc/gvm/desktop-installed")
        # Use explicit desktop_name, or fall back to config.selected_desktop
        self.desktop_name = desktop_name or config.selected_desktop

    def is_installed(self) -> tuple[bool, str]:
        """Check if desktop environment is already installed.

        Returns:
            Tuple of (is_installed, message) indicating detection result.
        """
        # If specific desktop requested, check if its core packages are installed
        if self.desktop_name:
            desktops = self.config.discover_desktops()
            if self.desktop_name in desktops:
                desktop = desktops[self.desktop_name]
                if desktop.packages_core and self._check_packages_installed(desktop.packages_core):
                    return (True, f"Desktop '{self.desktop_name}' is already installed")
            return (False, f"Desktop '{self.desktop_name}' not installed")

        # Otherwise check marker file
        if self.marker_path.exists():
            try:
                installed_desktops = self.marker_path.read_text().strip()
                return (True, f"Desktop(s) already installed: {installed_desktops}")
            except Exception:
                return (True, "Desktop installation marker present")

        return (False, "No desktop environment installed")

    def run(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> ModuleResult:
        """Execute desktop installation and configuration.

        Args:
            progress_callback: Callback to report progress.

        Returns:
            ModuleResult indicating success or failure.
        """
        try:
            self._report_progress(
                progress_callback, 0.0, "Starting desktop installation"
            )

            # Discover available desktops
            desktops = self.config.discover_desktops()

            if not desktops:
                return ModuleResult(
                    status=ModuleStatus.FAILED,
                    message="No desktop configurations found",
                    details="No TOML files with 'meta.type = desktop' found in config/packages or ~/.config/gvm/packages",
                    recovery_command=self.get_recovery_command(),
                )

            # Validate requested desktop exists
            if self.desktop_name:
                if self.desktop_name not in desktops:
                    available = ", ".join(desktops.keys())
                    return ModuleResult(
                        status=ModuleStatus.FAILED,
                        message=f"Desktop '{self.desktop_name}' not found",
                        details=f"Available desktops: {available}",
                        recovery_command=self.get_recovery_command(),
                    )
                desktops_to_install = {self.desktop_name: desktops[self.desktop_name]}
            else:
                desktops_to_install = desktops

            installed_names: list[str] = []
            total_desktops = len(desktops_to_install)

            for idx, (name, desktop) in enumerate(desktops_to_install.items()):
                base_progress = idx / total_desktops
                progress_scale = 1.0 / total_desktops

                # Install packages
                self._report_progress(
                    progress_callback,
                    base_progress + 0.1 * progress_scale,
                    f"Installing packages for {name}",
                    f"Processing {desktop.description or name}",
                )
                self._install_desktop_packages(desktop, progress_callback, base_progress, progress_scale)

                # Create configuration files
                self._report_progress(
                    progress_callback,
                    base_progress + 0.5 * progress_scale,
                    f"Creating configuration files for {name}",
                )
                self._create_desktop_files(desktop, progress_callback)

                # Create helper launch script
                self._report_progress(
                    progress_callback,
                    base_progress + 0.8 * progress_scale,
                    f"Creating helper launch script for {name}",
                )
                self._create_helper_script(desktop, progress_callback)

                installed_names.append(name)

            # Create marker file
            self._report_progress(
                progress_callback, 0.95, "Finalizing installation"
            )
            self._create_marker_file(installed_names)

            self._report_progress(
                progress_callback, 1.0, "Desktop installation complete"
            )

            if self.dry_run:
                return ModuleResult(
                    status=ModuleStatus.SUCCESS,
                    message=f"[DRY RUN] Desktop installation complete: {', '.join(installed_names)}",
                )

            return ModuleResult(
                status=ModuleStatus.SUCCESS,
                message=f"Desktop installation complete: {', '.join(installed_names)}",
            )

        except (SystemExit, Exception) as e:
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )

    def get_recovery_command(self) -> str:
        """Return the CLI command to recover from Desktop module failure.

        Returns:
            Recovery command string.
        """
        if self.desktop_name:
            return f"gvm fix desktop {shlex.quote(self.desktop_name)}"
        return "gvm fix desktop"

    def _install_desktop_packages(
        self,
        desktop: DesktopConfig,
        progress_callback: Callable[[float, str, Optional[str]], None],
        base_progress: float = 0.0,
        progress_scale: float = 1.0,
    ) -> None:
        """Install packages for a desktop environment using download-first strategy.

        Args:
            desktop: Desktop configuration with package lists.
            progress_callback: Callback to report progress.
            base_progress: Base progress value for this operation.
            progress_scale: Scale factor for progress increments.
        """
        packages = desktop.get_all_packages()

        if not packages:
            self._report_progress(
                progress_callback,
                base_progress + 0.4 * progress_scale,
                f"No packages to install for {desktop.name}",
            )
            return

        self._report_progress(
            progress_callback,
            base_progress + 0.15 * progress_scale,
            f"Downloading {len(packages)} packages for {desktop.name}",
            "Prefetching packages to cache",
        )

        if self.dry_run:
            print(f"[DRY RUN] Would download packages: {', '.join(packages)}")
            print("[DRY RUN] Would install packages from cache")
            self._report_progress(
                progress_callback,
                base_progress + 0.4 * progress_scale,
                f"Package installation complete for {desktop.name} (dry run)",
            )
            return

        # Download packages first
        run(
            ["sudo", "apt-get", "-y", "--download-only", "install"] + packages,
            check=True,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback,
            base_progress + 0.3 * progress_scale,
            f"Installing {len(packages)} packages from cache",
            f"Installing packages for {desktop.name}",
        )

        # Install from cache
        run(
            ["sudo", "apt-get", "-y", "--no-download", "install"] + packages,
            check=True,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback,
            base_progress + 0.4 * progress_scale,
            f"Package installation complete for {desktop.name}",
        )

    def _create_desktop_files(
        self,
        desktop: DesktopConfig,
        _progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create configuration files from desktop templates.

        Args:
            desktop: Desktop configuration with file templates.
            _progress_callback: Callback to report progress (unused, kept for API consistency).
        """
        if not desktop.files:
            return

        for file_path, content in desktop.files.items():
            # Expand path: handle ~ and environment variables
            expanded_path = Path(file_path).expanduser()
            expanded_path = Path(os.path.expandvars(str(expanded_path)))

            # Determine file mode: executable if starts with shebang
            mode = 0o755 if content.strip().startswith("#!") else 0o644

            if self.dry_run:
                print(f"[DRY RUN] Would write file: {expanded_path}")
                print(f"[DRY RUN] Mode: {oct(mode)}")
                preview = content[:200] + "..." if len(content) > 200 else content
                print(f"[DRY RUN] Content preview:\n{preview}")
                continue

            safe_write(expanded_path, content.rstrip("\n") + "\n", backup=True, mode=mode)

    def _create_helper_script(
        self,
        desktop: DesktopConfig,
        _progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create helper launch script for desktop environment.

        Args:
            desktop: Desktop configuration with session settings.
            _progress_callback: Callback to report progress (unused, kept for API consistency).
        """
        # Derive script name
        if desktop.session_helper_script_name:
            script_name = desktop.session_helper_script_name
        else:
            script_name = desktop.name.lower().replace(" ", "-")

        # Ensure script name has 'start-' prefix
        if not script_name.startswith("start-"):
            script_name = f"start-{script_name}"

        # Script path
        script_path = Path.home() / ".local" / "bin" / script_name

        # Build script content
        lines: list[str] = [
            "#!/bin/bash",
            f"# Helper launch script for {desktop.name}",
            f"# {desktop.description}" if desktop.description else "",
            "# Generated by GVM Desktop Module",
            "",
            "# Source display enabler if available",
            'if [ -f ~/.config/linuxvm/enable_display ]; then',
            '    source ~/.config/linuxvm/enable_display',
            'fi',
            "",
        ]

        # Export environment variables
        if desktop.environment_vars:
            lines.append("# Environment variables")
            for var in desktop.environment_vars:
                # Validate and quote environment variable assignments
                if "=" in var:
                    key, value = var.split("=", 1)
                    # Use shlex.quote for shell-safe quoting (handles single quotes, etc.)
                    lines.append(f"export {key}={shlex.quote(value)}")
                else:
                    # Variable reference without value (export existing var)
                    lines.append(f"export {var}")
            lines.append("")

        # Build launch command
        if desktop.session_start_command:
            lines.append("# Launch desktop session")

            launch_cmd = desktop.session_start_command

            # Wrap with dbus-run-session if required
            if desktop.session_requires_dbus:
                launch_cmd = f"dbus-run-session {launch_cmd}"

            # Add fallback command if specified
            if desktop.session_fallback_command:
                fallback_cmd = desktop.session_fallback_command
                if desktop.session_requires_dbus:
                    fallback_cmd = f"dbus-run-session {fallback_cmd}"
                # Use conditional block so fallback can execute if primary fails
                # (exec replaces the shell, so || would never run after exec)
                lines.append(f"if ! {launch_cmd}; then")
                lines.append(f"    exec {fallback_cmd}")
                lines.append("fi")
            else:
                lines.append(f"exec {launch_cmd}")
        else:
            lines.append("# No session start command configured")
            lines.append(f'echo "No session start command configured for {desktop.name}"')
            lines.append("exit 1")

        content = "\n".join(lines) + "\n"

        if self.dry_run:
            print(f"[DRY RUN] Would create helper script: {script_path}")
            print(f"[DRY RUN] Content:\n{content}")
            return

        # Ensure .local/bin directory exists
        script_path.parent.mkdir(parents=True, exist_ok=True)

        safe_write(script_path, content, backup=True, mode=0o755)

    def _check_packages_installed(self, packages: list[str]) -> bool:
        """Check if packages are installed using dpkg-query.

        Args:
            packages: List of package names to check.

        Returns:
            True if all packages are installed, False otherwise.
        """
        for package in packages:
            try:
                result = run(
                    ["dpkg-query", "-W", "-f=${Status}\\n", package],
                    check=False,
                    capture=True,
                    verbose=self.verbose,
                )
                # Check for exact "install ok installed" status
                if result.returncode != 0:
                    return False
                if not result.stdout or "install ok installed" not in result.stdout:
                    return False
            except Exception:
                return False
        return True

    def _create_marker_file(self, installed_names: list[str]) -> None:
        """Create marker file recording installed desktops.

        Args:
            installed_names: List of installed desktop names.
        """
        content = "\n".join(installed_names) + "\n"

        if self.dry_run:
            print(f"[DRY RUN] Would create marker file: {self.marker_path}")
            print(f"[DRY RUN] Content: {content}")
            return

        safe_write(self.marker_path, content, backup=False, mode=0o644)
