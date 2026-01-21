"""SSH module for GVM tool.

This module configures the SSH server with security hardening settings,
sets up listening ports, and manages the sshd service. It depends on
the APT module for package installation.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from gvm.modules.base import Dependency, Module, ModuleResult, ModuleStatus
from gvm.utils.files import safe_write
from gvm.utils.shell import run
from gvm.utils.system import is_port_listening, is_service_running

if TYPE_CHECKING:
    from gvm.config import Config


class SSHModule(Module):
    """Configure SSH server with security hardening.

    This module depends on the APT module for package installation.
    It performs the following operations:
    1. Install openssh-server package
    2. Create SSH configuration file with security settings
    3. Enable SSH service
    4. Start/restart SSH service and verify it's running
    """

    name = "ssh"
    description = "Configure SSH server with security hardening"
    dependencies = (Dependency("apt", required=True),)

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize SSH module.

        Args:
            config: Configuration object with user settings.
            verbose: Enable verbose output.
            dry_run: Simulate execution without making changes.
        """
        super().__init__(config, verbose, dry_run)
        self.sshd_config_path = Path("/etc/ssh/sshd_config.d/99-linuxvm-ssh.conf")

    def is_installed(self) -> tuple[bool, str]:
        """Check if SSH is already configured and running.

        Returns:
            Tuple of (is_installed, message) indicating detection result.
        """
        forward_port = self.config.ssh_forward_port
        internal_port = self.config.ssh_internal_port

        # Check if sshd is listening on configured ports
        forward_listening = is_port_listening(forward_port)
        # Only check internal port if enabled (non-zero)
        internal_listening = is_port_listening(internal_port) if internal_port else False

        if forward_listening or internal_listening:
            ports_listening = []
            if forward_listening:
                ports_listening.append(str(forward_port))
            if internal_listening:
                ports_listening.append(str(internal_port))
            return (True, f"SSH already configured and running on port(s): {', '.join(ports_listening)}")

        return (False, "SSH not configured")

    def run(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> ModuleResult:
        """Execute SSH configuration and service setup.

        Args:
            progress_callback: Callback to report progress.

        Returns:
            ModuleResult indicating success or failure.
        """
        try:
            self._report_progress(
                progress_callback, 0.0, "Starting SSH configuration"
            )

            # Step 1: Install openssh-server
            self._install_ssh_package(progress_callback)

            # Step 2: Create SSH configuration file
            self._create_sshd_config(progress_callback)

            # Step 3: Enable SSH service
            self._enable_ssh_service(progress_callback)

            # Step 4: Start/restart SSH service
            self._restart_ssh_service(progress_callback)

            if self.dry_run:
                return ModuleResult(
                    status=ModuleStatus.SUCCESS,
                    message="[DRY RUN] SSH configuration complete",
                )

            return ModuleResult(
                status=ModuleStatus.SUCCESS,
                message="SSH configuration complete",
            )

        except (SystemExit, Exception) as e:
            return ModuleResult(
                status=ModuleStatus.FAILED,
                message=str(e),
                details=traceback.format_exc(),
                recovery_command=self.get_recovery_command(),
            )

    def get_recovery_command(self) -> str:
        """Return the CLI command to recover from SSH module failure.

        Returns:
            Recovery command string.
        """
        return "gvm fix ssh"

    def _install_ssh_package(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Install openssh-server package.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.05,
            "Installing SSH server",
            "Running apt-get install openssh-server",
        )

        if self.dry_run:
            print("[DRY RUN] Would run: sudo apt-get -y install openssh-server")
            self._report_progress(
                progress_callback, 0.2, "SSH package installed (dry run)"
            )
            return

        run(
            ["sudo", "apt-get", "-y", "install", "openssh-server"],
            check=True,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback, 0.2, "SSH package installed"
        )

    def _create_sshd_config(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Create SSH configuration file with security settings.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.25,
            "Creating SSH configuration",
            f"Writing config to {self.sshd_config_path}",
        )

        # Build config content from settings
        ssh_settings = self.config.ssh
        forward_port = self.config.ssh_forward_port
        internal_port = self.config.ssh_internal_port

        listen_address = ssh_settings.get("listen_address", "0.0.0.0")

        # Normalize permit_root_login: convert boolean to sshd-accepted string
        permit_root_login_raw = ssh_settings.get("permit_root_login", "no")
        if permit_root_login_raw is True:
            permit_root_login = "yes"
        elif permit_root_login_raw is False:
            permit_root_login = "no"
        else:
            permit_root_login = str(permit_root_login_raw)

        password_auth = "yes" if ssh_settings.get("password_auth", True) else "no"
        pubkey_auth = "yes" if ssh_settings.get("pubkey_auth", True) else "no"

        # Build port configuration - only include internal port if enabled (non-zero)
        port_lines = f"Port {forward_port}"
        if internal_port:
            port_lines += f"\nPort {internal_port}"

        content = f"""# GVM SSH configuration
# Security hardening settings for GrapheneOS Linux VM

# Listen ports
{port_lines}

# Network settings
ListenAddress {listen_address}

# Authentication settings
PermitRootLogin {permit_root_login}
PasswordAuthentication {password_auth}
PubkeyAuthentication {pubkey_auth}

# Additional security settings
X11Forwarding no
MaxAuthTries 3
"""

        if self.dry_run:
            print(f"[DRY RUN] Would write SSH config to {self.sshd_config_path}:")
            print(content)
            self._report_progress(
                progress_callback, 0.5, "SSH configuration created (dry run)"
            )
            return

        safe_write(self.sshd_config_path, content, backup=True, mode=0o644)

        self._report_progress(
            progress_callback, 0.5, "SSH configuration created"
        )

    def _enable_ssh_service(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Enable SSH service to start on boot.

        Args:
            progress_callback: Callback to report progress.
        """
        self._report_progress(
            progress_callback,
            0.55,
            "Enabling SSH service",
            "Running systemctl enable ssh",
        )

        if self.dry_run:
            print("[DRY RUN] Would run: sudo systemctl enable ssh")
            self._report_progress(
                progress_callback, 0.7, "SSH service enabled (dry run)"
            )
            return

        run(
            ["sudo", "systemctl", "enable", "ssh"],
            check=True,
            verbose=self.verbose,
        )

        self._report_progress(
            progress_callback, 0.7, "SSH service enabled"
        )

    def _restart_ssh_service(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> None:
        """Restart SSH service and verify it's running.

        Args:
            progress_callback: Callback to report progress.
        """
        import time

        self._report_progress(
            progress_callback,
            0.75,
            "Restarting SSH service",
            "Running systemctl restart ssh",
        )

        if self.dry_run:
            print("[DRY RUN] Would run: sudo systemctl restart ssh")
            self._report_progress(
                progress_callback, 1.0, "SSH service restarted (dry run)"
            )
            return

        run(
            ["sudo", "systemctl", "restart", "ssh"],
            check=True,
            verbose=self.verbose,
        )

        # Verify service is running
        self._report_progress(
            progress_callback,
            0.85,
            "Verifying SSH service",
            "Checking service status",
        )

        if not is_service_running("ssh"):
            raise SystemExit("SSH service failed to start after restart")

        # Wait for SSH port to be listening inside the VM
        forward_port = self.config.ssh_forward_port
        internal_port = self.config.ssh_internal_port

        self._report_progress(
            progress_callback,
            0.9,
            "Waiting for SSH port",
            f"Checking port {forward_port}",
        )

        max_wait = 10  # seconds
        port_listening = False
        for _ in range(max_wait * 2):  # Check every 0.5 seconds
            if is_port_listening(forward_port):
                port_listening = True
                break
            time.sleep(0.5)

        if port_listening:
            print(f"SSH listening on port {forward_port}")
            if internal_port and is_port_listening(internal_port):
                print(f"SSH also listening on port {internal_port}")
            print("")
            print("To connect from your computer:")
            print(f"  1. In GrapheneOS Terminal, tap the menu (⋮) and select 'Port forwarding'")
            print(f"  2. Add a rule to forward port {forward_port}")
            print(f"  3. Connect with: ssh -p {forward_port} <user>@<device-ip>")
        else:
            # Port not listening after timeout
            raise SystemExit(
                f"SSH service started but port {forward_port} is not listening. "
                f"Check 'sudo systemctl status ssh' for errors."
            )

        self._report_progress(
            progress_callback, 1.0, "SSH service running"
        )
