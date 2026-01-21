"""APT module for GVM tool.

This module configures the APT package manager with hardening settings,
stabilizes Debian mirrors, cleans APT caches, repairs dpkg, and performs
system updates. It serves as the foundation module with no dependencies.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from gvm.modules.base import Dependency, Module, ModuleResult, ModuleStatus
from gvm.utils.files import safe_write
from gvm.utils.shell import run
from gvm.utils.system import detect_debian_codename

if TYPE_CHECKING:
    from gvm.config import Config


class APTModule(Module):
    """Configure APT package manager with hardening and install base packages.

    This is the foundation module for the GVM system with no dependencies.
    It performs the following operations:
    1. Harden APT configuration with robust settings
    2. Stabilize Debian mirror configuration
    3. Clean APT caches
    4. Repair dpkg state
    5. Update and upgrade system packages
    6. Install base packages (if configured)
    """

    name = "apt"
    description = "Configure APT package manager with hardening and install base packages"
    dependencies = ()

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize APT module.

        Args:
            config: Configuration object with user settings.
            verbose: Enable verbose output.
            dry_run: Simulate execution without making changes.
        """
        super().__init__(config, verbose, dry_run)
        self.apt_conf_path = Path("/etc/apt/apt.conf.d/99-linuxvm-robust")
        self.mirrors_path = Path("/etc/apt/mirrors/debian.list")

    def is_installed(self) -> tuple[bool, str]:
        """Check if APT hardening configuration is already present.

        Returns:
            Tuple of (is_installed, message) indicating detection result.
        """
        if self.apt_conf_path.exists():
            return (True, "APT hardening configuration already present")
        return (False, "APT hardening not configured")

    def run(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> ModuleResult:
        """Execute APT configuration and system update.

        Args:
            progress_callback: Callback to report progress.

        Returns:
            ModuleResult indicating success or failure.
        """
        try:
            self._report_progress(
                progress_callback, 0.0, "Starting APT configuration"
            )

            # Execute operations in sequence
            self._harden_apt(progress_callback)
            self._stabilize_mirrors(progress_callback)
            self._clean_apt(progress_callback)
            self._repair_dpkg(progress_callback)
            self._update_upgrade(progress_callback)

            # Install base packages if configured
            base_packages = self.config.apt.get("base_packages", [])
            if base_packages:
                self._install_packages(base_packages, progress_callback)
            else:
                self._report_progress(
                    progress_callback, 1.0, "APT configuration complete"
                )

            if self.dry_run:
                return ModuleResult(
                    status=ModuleStatus.SUCCESS,
                    message="[DRY RUN] APT configuration and system update complete",
                )

            return ModuleResult(
                status=ModuleStatus.SUCCESS,
                message="APT configuration and system update complete",
            )

        except SystemExit as e:
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )
        except Exception as e:
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )

    def get_recovery_command(self) -> str:
        """Return the CLI command to recover from APT module failure.

        Returns:
            Recovery command string.
        """
        return "gvm fix apt"

    def _harden_apt(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create robust APT configuration file.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.1,
            "Hardening APT configuration",
            "Creating robust APT config",
        )

        # Build config content from settings
        content = f'''// GVM robust APT configuration
// Prevents failures on slow/unreliable connections

Acquire::Retries "{self.config.apt_retries}";
Acquire::http::Timeout "{self.config.apt_http_timeout}";
Acquire::https::Timeout "{self.config.apt_https_timeout}";
Acquire::http::Pipeline-Depth "0";
Dpkg::Use-Pty "0";
'''

        if self.dry_run:
            print(f"[DRY RUN] Would write APT config to {self.apt_conf_path}:")
            print(content)
            self._report_progress(
                progress_callback, 0.2, "APT hardening complete (dry run)"
            )
            return

        safe_write(self.apt_conf_path, content, backup=True, mode=0o644)

        self._report_progress(
            progress_callback, 0.2, "APT hardening complete"
        )

    def _stabilize_mirrors(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Stabilize Debian mirror configuration.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.25,
            "Stabilizing Debian mirrors",
            "Checking mirror configuration",
        )

        # Check if mirrors file exists
        if not self.mirrors_path.exists():
            self._report_progress(
                progress_callback,
                0.3,
                "Mirror stabilization skipped",
                "No mirrors file present",
            )
            return

        # Build mirror list from config
        mirrors = self.config.apt.get("mirrors", [])
        components = self.config.apt.get("components", [])

        # Guard against empty mirrors or components
        if not mirrors or not components:
            self._report_progress(
                progress_callback,
                0.3,
                "Mirror stabilization skipped",
                "No mirrors or components configured, leaving file unchanged",
            )
            return

        # Detect codename
        codename = detect_debian_codename() or "trixie"

        components_joined = " ".join(components)

        lines: list[str] = []

        for mirror in mirrors:
            if "security" in mirror:
                # Security mirror uses different format
                lines.append(f"{mirror} {codename}-security {components_joined}")
            else:
                # Regular mirror
                lines.append(f"{mirror} {codename} {components_joined}")
                lines.append(f"{mirror} {codename}-updates {components_joined}")

        content = "\n".join(lines) + "\n"

        if self.dry_run:
            print(f"[DRY RUN] Would write mirrors to {self.mirrors_path}:")
            print(content)
            self._report_progress(
                progress_callback, 0.3, "Mirror stabilization complete (dry run)"
            )
            return

        safe_write(self.mirrors_path, content, backup=True)

        self._report_progress(
            progress_callback, 0.3, "Mirror stabilization complete"
        )

    def _clean_apt(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Clean APT caches and lists.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.35,
            "Cleaning APT caches",
            "Removing cached packages and lists",
        )

        if self.dry_run:
            print("[DRY RUN] Would run:")
            print("  sudo apt clean")
            print("  sudo bash -c 'rm -rf /var/lib/apt/lists/*'")
            print("  sudo mkdir -p /var/lib/apt/lists/partial")
            print("  sudo bash -c 'rm -rf /var/cache/apt/archives/partial/*'")
            print("  sudo bash -c 'rm -f /var/cache/apt/archives/*.deb'")
            self._report_progress(
                progress_callback, 0.4, "APT cache cleaned (dry run)"
            )
            return

        # Clean APT cache
        run(["sudo", "apt", "clean"], check=False, verbose=self.verbose)

        # Remove apt lists (use bash -c for glob expansion)
        run(
            ["sudo", "bash", "-c", "rm -rf /var/lib/apt/lists/*"],
            check=False,
            verbose=self.verbose,
        )

        # Recreate partial directory
        run(
            ["sudo", "mkdir", "-p", "/var/lib/apt/lists/partial"],
            check=False,
            verbose=self.verbose,
        )

        # Clean partial archives (use bash -c for glob expansion)
        run(
            ["sudo", "bash", "-c", "rm -rf /var/cache/apt/archives/partial/*"],
            check=False,
            verbose=self.verbose,
        )

        # Remove cached deb files (use bash -c for glob expansion)
        run(
            ["sudo", "bash", "-c", "rm -f /var/cache/apt/archives/*.deb"],
            check=False,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback, 0.4, "APT cache cleaned"
        )

    def _repair_dpkg(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Repair dpkg and APT state.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.45,
            "Repairing dpkg",
            "Running dpkg configure and apt fix",
        )

        if self.dry_run:
            print("[DRY RUN] Would run:")
            print("  sudo dpkg --configure -a")
            print("  sudo apt -f install -y")
            self._report_progress(
                progress_callback, 0.5, "DPKG repair complete (dry run)"
            )
            return

        # Configure any unconfigured packages
        run(
            ["sudo", "dpkg", "--configure", "-a"],
            check=False,
            verbose=self.verbose,
        )

        # Fix broken dependencies
        run(
            ["sudo", "apt", "-f", "install", "-y"],
            check=False,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback, 0.5, "DPKG repair complete"
        )

    def _update_upgrade(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Update package index and upgrade system.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.55,
            "Updating package index",
            "Running apt update",
        )

        if self.dry_run:
            print("[DRY RUN] Would run:")
            print("  sudo apt update")
            print("  sudo apt -y full-upgrade")
            self._report_progress(
                progress_callback, 0.85, "System update complete (dry run)"
            )
            return

        # Update package index
        run(["sudo", "apt", "update"], check=True, verbose=self.verbose)

        self._report_progress(
            progress_callback,
            0.7,
            "Upgrading system packages",
            "Running apt full-upgrade",
        )

        # Perform full upgrade
        run(
            ["sudo", "apt", "-y", "full-upgrade"],
            check=True,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback, 0.85, "System update complete"
        )

    def _install_packages(
        self,
        packages: list[str],
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Install packages using download-first strategy.

        This downloads all packages first, then installs from cache
        to minimize network issues during installation.

        Args:
            packages: List of package names to install.
            progress_callback: Callback to report progress.
        """
        if not packages:
            return

        self._report_progress(
            progress_callback,
            0.9,
            "Downloading packages",
            f"Prefetching {len(packages)} packages",
        )

        if self.dry_run:
            print(f"[DRY RUN] Would install packages: {', '.join(packages)}")
            self._report_progress(
                progress_callback, 1.0, "Package installation complete (dry run)"
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
            0.95,
            "Installing packages",
            f"Installing {len(packages)} packages from cache",
        )

        # Install from cache
        run(
            ["sudo", "apt-get", "-y", "--no-download", "install"] + packages,
            check=True,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback, 1.0, "Package installation complete"
        )
