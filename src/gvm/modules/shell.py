"""Shell module for GVM tool.

This module configures the shell environment with Starship prompt
and a login banner displaying system status. It depends on the APT
module for package installation.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from gvm.modules.base import Dependency, Module, ModuleResult, ModuleStatus
from gvm.utils.files import ensure_snippet, safe_write
from gvm.utils.shell import run

if TYPE_CHECKING:
    from gvm.config import Config


class ShellModule(Module):
    """Configure shell environment with Starship prompt and banner.

    This module depends on the APT module for package installation.
    It performs the following operations:
    1. Install Starship prompt package
    2. Add Starship init to bashrc
    3. Create login banner script
    4. Configure auto-display toggle
    """

    name = "shell"
    description = "Configure shell environment with Starship prompt and banner"
    dependencies = (Dependency("apt", required=True),)

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize Shell module.

        Args:
            config: Configuration object with user settings.
            verbose: Enable verbose output.
            dry_run: Simulate execution without making changes.
        """
        super().__init__(config, verbose, dry_run)
        self.bashrc_path = Path.home() / ".bashrc"
        self.banner_script_path = Path("/etc/profile.d/00-linuxvm-banner.sh")
        self.auto_display_path = Path.home() / ".config" / "linuxvm" / "auto_display"
        self.starship_marker = "gvm-starship"

    def is_installed(self) -> tuple[bool, str]:
        """Check if shell configuration is already present.

        Returns:
            Tuple of (is_installed, message) indicating detection result.
        """
        # Check if Starship is installed
        result = run(["which", "starship"], capture=True, check=False)
        starship_installed = result.returncode == 0

        # Check if bashrc snippet exists
        bashrc_snippet_present = False
        if self.bashrc_path.exists():
            try:
                content = self.bashrc_path.read_text()
                marker = f"# >>> {self.starship_marker} >>>"
                bashrc_snippet_present = marker in content
            except (IOError, PermissionError):
                pass

        if starship_installed and bashrc_snippet_present:
            return (True, "Shell configuration already present")

        return (False, "Shell not configured")

    def run(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> ModuleResult:
        """Execute shell configuration.

        Args:
            progress_callback: Callback to report progress.

        Returns:
            ModuleResult indicating success or failure.
        """
        try:
            self._report_progress(
                progress_callback, 0.0, "Starting shell configuration"
            )

            # Step 1: Install Starship package
            self._install_starship(progress_callback)

            # Step 2: Add Starship init to bashrc
            self._configure_starship_bashrc(progress_callback)

            # Step 3: Create login banner script
            self._create_banner_script(progress_callback)

            # Step 4: Configure auto-display toggle
            self._configure_auto_display(progress_callback)

            if self.dry_run:
                return ModuleResult(
                    status=ModuleStatus.SUCCESS,
                    message="[DRY RUN] Shell configuration complete",
                )

            return ModuleResult(
                status=ModuleStatus.SUCCESS,
                message="Shell configuration complete",
            )

        except (SystemExit, Exception) as e:
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )

    def get_recovery_command(self) -> str:
        """Return the CLI command to recover from Shell module failure.

        Returns:
            Recovery command string.
        """
        return "gvm fix shell"

    def _install_starship(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Install Starship prompt package.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.05,
            "Installing Starship prompt",
            "Running apt-get install starship",
        )

        if self.dry_run:
            print("[DRY RUN] Would run: sudo apt-get -y install starship")
            self._report_progress(
                progress_callback, 0.3, "Starship installed (dry run)"
            )
            return

        run(
            ["sudo", "apt-get", "-y", "install", "starship"],
            check=True,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback, 0.3, "Starship installed"
        )

    def _configure_starship_bashrc(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Add Starship init to bashrc.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.35,
            "Configuring Starship in bashrc",
            f"Adding snippet to {self.bashrc_path}",
        )

        snippet = 'eval "$(starship init bash)"'

        if self.dry_run:
            print(f"[DRY RUN] Would add snippet to {self.bashrc_path}:")
            print(f"  # >>> {self.starship_marker} >>>")
            print(f"  {snippet}")
            print(f"  # <<< {self.starship_marker} <<<")
            self._report_progress(
                progress_callback, 0.5, "Starship bashrc configured (dry run)"
            )
            return

        ensure_snippet(self.bashrc_path, self.starship_marker, snippet)

        self._report_progress(
            progress_callback, 0.5, "Starship bashrc configured"
        )

    def _create_banner_script(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create login banner script.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.55,
            "Creating login banner",
            f"Writing banner script to {self.banner_script_path}",
        )

        # Build banner content from config
        banner_settings = self.config.banner
        title = banner_settings.get("title", "GrapheneOS Linux VM Status")
        show_ssh_note = banner_settings.get("show_ssh_note", True)
        ssh_note = banner_settings.get("ssh_note", "Note: GrapheneOS Terminal Port Control will NOT expose port 22.")

        # Build SSH note section if enabled
        ssh_note_section = ""
        if show_ssh_note:
            ssh_note_section = f'''
    echo ""
    echo "{ssh_note}"'''

        content = f'''#!/bin/bash
# GVM Login Banner Script
# Displays system status on interactive login

# Only run in interactive shells
case $- in
    *i*) ;;
    *) return;;
esac

# Display banner
display_banner() {{
    echo ""
    echo "====================================="
    echo "  {title}"
    echo "====================================="
    echo ""
    echo "  Hostname:  $(hostname)"
    echo "  Kernel:    $(uname -r)"
    echo "  Uptime:    $(uptime -p 2>/dev/null || echo 'N/A')"
    echo "  Memory:    $(free -h 2>/dev/null | awk '/^Mem:/ {{print $3 "/" $2}}' || echo 'N/A')"
    echo ""{ssh_note_section}
    echo "====================================="
    echo ""
}}

# Check if banner should be displayed
if [ -f ~/.config/linuxvm/auto_display ] || [ "${{GVM_SHOW_BANNER:-1}}" = "1" ]; then
    display_banner
fi
'''

        if self.dry_run:
            print(f"[DRY RUN] Would write banner script to {self.banner_script_path}:")
            print(content[:500] + "..." if len(content) > 500 else content)
            self._report_progress(
                progress_callback, 0.7, "Banner script created (dry run)"
            )
            return

        safe_write(self.banner_script_path, content, backup=True, mode=0o755)

        self._report_progress(
            progress_callback, 0.7, "Banner script created"
        )

    def _configure_auto_display(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Configure auto-display toggle marker file.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.8,
            "Configuring auto-display",
            f"Setting up {self.auto_display_path}",
        )

        auto_display_enabled = self.config.features.get("auto_display", True)

        if self.dry_run:
            if auto_display_enabled:
                print(f"[DRY RUN] Would create marker file: {self.auto_display_path}")
            else:
                if self.auto_display_path.exists():
                    print(f"[DRY RUN] Would remove marker file: {self.auto_display_path}")
                else:
                    print("[DRY RUN] Would skip (auto_display disabled, marker does not exist)")
            self._report_progress(
                progress_callback, 1.0, "Auto-display configured (dry run)"
            )
            return

        if auto_display_enabled:
            # Create directory if needed
            self.auto_display_path.parent.mkdir(parents=True, exist_ok=True)
            # Create empty marker file
            self.auto_display_path.touch()
            print(f"Created auto-display marker: {self.auto_display_path}")
            self._report_progress(
                progress_callback, 1.0, "Auto-display configured (enabled)"
            )
        else:
            # Remove marker file if it exists
            if self.auto_display_path.exists():
                self.auto_display_path.unlink()
                print(f"Removed auto-display marker: {self.auto_display_path}")
                self._report_progress(
                    progress_callback, 1.0, "Auto-display configured (disabled, marker removed)"
                )
            else:
                self._report_progress(
                    progress_callback, 1.0, "Auto-display configured (disabled)"
                )
