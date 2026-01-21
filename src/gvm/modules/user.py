"""User module for GVM tool.

This module configures user accounts on the VM, including setting
passwords and optionally creating additional users. It depends on
the APT module for package installation.
"""

from __future__ import annotations

import secrets
import string
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from gvm.modules.base import Dependency, Module, ModuleResult, ModuleStatus
from gvm.utils.shell import run

if TYPE_CHECKING:
    from gvm.config import Config


class UserModule(Module):
    """Configure user accounts with passwords.

    This module depends on the APT module for package installation.
    It performs the following operations:
    1. Set password for the droid user (required for sudo and login screens)
    2. Optionally create additional users
    3. Configure passwordless sudo for droid user (convenience)
    """

    name = "user"
    description = "Configure user accounts and passwords"
    dependencies = (Dependency("apt", required=True),)

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize User module.

        Args:
            config: Configuration object with user settings.
            verbose: Enable verbose output.
            dry_run: Simulate execution without making changes.
        """
        super().__init__(config, verbose, dry_run)
        self.marker_path = Path.home() / ".config" / "gvm" / "user-configured"
        self.sudoers_path = Path("/etc/sudoers.d/droid-nopasswd")

    def is_installed(self) -> tuple[bool, str]:
        """Check if user configuration is already present.

        Returns:
            Tuple of (is_installed, message) indicating detection result.
        """
        if self.marker_path.exists():
            return (True, "User configuration already present")

        return (False, "User not configured")

    def run(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> ModuleResult:
        """Execute user configuration.

        Args:
            progress_callback: Callback to report progress.

        Returns:
            ModuleResult indicating success or failure.
        """
        try:
            self._report_progress(
                progress_callback, 0.0, "Starting user configuration"
            )

            # Step 1: Generate and set password for droid user
            password = self._set_droid_password(progress_callback)

            # Step 2: Configure passwordless sudo for droid
            self._configure_passwordless_sudo(progress_callback)

            # Step 3: Create marker file with password hint
            self._create_marker_file(password, progress_callback)

            self._report_progress(
                progress_callback, 1.0, "User configuration complete"
            )

            if self.dry_run:
                return ModuleResult(
                    status=ModuleStatus.SUCCESS,
                    message="[DRY RUN] User configuration complete",
                )

            return ModuleResult(
                status=ModuleStatus.SUCCESS,
                message=f"User configuration complete. Password for 'droid': {password}",
            )

        except (SystemExit, Exception) as e:
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )

    def get_recovery_command(self) -> str:
        """Return the CLI command to recover from User module failure.

        Returns:
            Recovery command string.
        """
        return "gvm fix user"

    def _generate_password(self, length: int = 12) -> str:
        """Generate a secure random password.

        Args:
            length: Password length (default 12 characters).

        Returns:
            Random password string.
        """
        # Use alphanumeric characters for easy typing on mobile
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def _set_droid_password(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> str:
        """Set password for the droid user.

        Args:
            progress_callback: Callback to report progress.

        Returns:
            The generated password.
        """
        self._report_progress(
            progress_callback,
            0.1,
            "Setting password for droid user",
            "Generating secure password",
        )

        # Check if user wants a custom password from config
        user_settings = self.config.user if hasattr(self.config, 'user') else {}
        custom_password = user_settings.get("password") if isinstance(user_settings, dict) else None

        if custom_password:
            password = custom_password
        else:
            password = self._generate_password()

        if self.dry_run:
            print(f"[DRY RUN] Would set password for droid user: {password}")
            self._report_progress(
                progress_callback, 0.4, "Password set (dry run)"
            )
            return password

        # Use chpasswd to set the password
        # This is safer than echo password | passwd as it handles special chars
        result = run(
            ["sudo", "chpasswd"],
            input_data=f"droid:{password}\n",
            check=True,
            verbose=self.verbose,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to set password: {result.stderr}")

        print(f"Password set for droid user: {password}")

        self._report_progress(
            progress_callback, 0.4, "Password set for droid user"
        )

        return password

    def _configure_passwordless_sudo(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Configure passwordless sudo for the droid user.

        This allows droid to run sudo commands without entering password,
        which is convenient for VM usage while still having a password
        for login screens.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.5,
            "Configuring passwordless sudo",
            f"Writing {self.sudoers_path}",
        )

        content = "# GVM: Allow droid user to run sudo without password\ndroid ALL=(ALL) NOPASSWD: ALL\n"

        if self.dry_run:
            print(f"[DRY RUN] Would write to {self.sudoers_path}:")
            print(content)
            self._report_progress(
                progress_callback, 0.7, "Passwordless sudo configured (dry run)"
            )
            return

        # Write sudoers file with correct permissions
        # Use a temporary file and visudo to validate
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sudo', delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            # Validate the sudoers syntax
            result = run(
                ["sudo", "visudo", "-c", "-f", temp_path],
                check=False,
                capture=True,
                verbose=self.verbose,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Invalid sudoers syntax: {result.stderr}")

            # Move to final location with correct ownership and permissions
            run(
                ["sudo", "cp", temp_path, str(self.sudoers_path)],
                check=True,
                verbose=self.verbose,
            )
            run(
                ["sudo", "chmod", "440", str(self.sudoers_path)],
                check=True,
                verbose=self.verbose,
            )
            run(
                ["sudo", "chown", "root:root", str(self.sudoers_path)],
                check=True,
                verbose=self.verbose,
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)

        self._report_progress(
            progress_callback, 0.7, "Passwordless sudo configured"
        )

    def _create_marker_file(
        self,
        password: str,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create marker file indicating user configuration is complete.

        The marker file also stores the password for reference.

        Args:
            password: The generated password.
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.8,
            "Creating configuration marker",
            f"Writing {self.marker_path}",
        )

        content = f"""# GVM User Configuration
# Generated by gvm setup
#
# Password for 'droid' user: {password}
#
# You can change the password with: passwd
# Or regenerate with: gvm fix user
"""

        if self.dry_run:
            print(f"[DRY RUN] Would create marker file: {self.marker_path}")
            self._report_progress(
                progress_callback, 0.9, "Marker file created (dry run)"
            )
            return

        # Ensure parent directory exists
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.write_text(content)
        # Secure the file so only the user can read it
        self.marker_path.chmod(0o600)

        self._report_progress(
            progress_callback, 0.9, "Marker file created"
        )
