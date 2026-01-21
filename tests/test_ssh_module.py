"""Tests for SSH module.

This module validates:
- SSHModule instantiation and attributes
- is_installed() detection logic
- SSH config file generation
- Dry-run mode behavior
- Recovery command output
- Dependencies declaration

Run with: python -m pytest tests/test_ssh_module.py -v
Or standalone: python tests/test_ssh_module.py
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gvm.config import Config
from gvm.modules import Dependency, ModuleStatus
from gvm.modules.ssh import SSHModule


class TestSSHModuleInstantiation(unittest.TestCase):
    """Test cases for SSHModule instantiation."""

    def test_ssh_module_instantiation(self) -> None:
        """SSHModule can be instantiated with config."""
        config = Config.load()
        module = SSHModule(config)

        self.assertEqual(module.name, "ssh")
        self.assertFalse(module.verbose)
        self.assertFalse(module.dry_run)
        self.assertIs(module.config, config)

    def test_ssh_module_with_flags(self) -> None:
        """SSHModule respects verbose and dry_run flags."""
        config = Config.load()
        module = SSHModule(config, verbose=True, dry_run=True)

        self.assertTrue(module.verbose)
        self.assertTrue(module.dry_run)


class TestSSHModuleAttributes(unittest.TestCase):
    """Test cases for SSHModule class attributes."""

    def test_module_name(self) -> None:
        """SSHModule has correct name attribute."""
        self.assertEqual(SSHModule.name, "ssh")

    def test_module_description(self) -> None:
        """SSHModule has a description."""
        self.assertTrue(len(SSHModule.description) > 0)
        self.assertIn("SSH", SSHModule.description)

    def test_module_dependencies(self) -> None:
        """SSHModule declares APT as required dependency."""
        self.assertIsInstance(SSHModule.dependencies, tuple)
        self.assertEqual(len(SSHModule.dependencies), 1)

        apt_dep = SSHModule.dependencies[0]
        self.assertIsInstance(apt_dep, Dependency)
        self.assertEqual(apt_dep.module_name, "apt")
        self.assertTrue(apt_dep.required)


class TestSSHModuleIsInstalled(unittest.TestCase):
    """Test cases for is_installed() detection."""

    @patch("gvm.modules.ssh.is_port_listening")
    def test_is_installed_when_ports_listening(self, mock_port_listening: MagicMock) -> None:
        """is_installed returns True when SSH ports are listening."""
        mock_port_listening.side_effect = lambda port: port in [2222, 22]

        config = Config.load()
        module = SSHModule(config)

        installed, message = module.is_installed()

        self.assertTrue(installed)
        self.assertIn("SSH already configured", message)
        self.assertIn("2222", message)

    @patch("gvm.modules.ssh.is_port_listening")
    def test_is_installed_when_no_ports_listening(self, mock_port_listening: MagicMock) -> None:
        """is_installed returns False when no SSH ports are listening."""
        mock_port_listening.return_value = False

        config = Config.load()
        module = SSHModule(config)

        installed, message = module.is_installed()

        self.assertFalse(installed)
        self.assertIn("not configured", message)

    @patch("gvm.modules.ssh.is_port_listening")
    def test_is_installed_forward_port_only(self, mock_port_listening: MagicMock) -> None:
        """is_installed returns True when only forward port is listening."""
        mock_port_listening.side_effect = lambda port: port == 2222

        config = Config.load()
        module = SSHModule(config)

        installed, message = module.is_installed()

        self.assertTrue(installed)
        self.assertIn("2222", message)


class TestSSHConfigGeneration(unittest.TestCase):
    """Test cases for SSH config file generation."""

    def test_config_values_accessible(self) -> None:
        """Verify SSH config values are accessible from Config.load()."""
        config = Config.load()

        # Access the SSH configuration values
        ssh_settings = config.ssh
        forward_port = config.ssh_forward_port
        internal_port = config.ssh_internal_port

        # Verify default config values are accessible and have expected defaults
        self.assertEqual(forward_port, 2222)
        self.assertEqual(internal_port, 22)
        self.assertEqual(ssh_settings.get("permit_root_login", "no"), "no")
        self.assertTrue(ssh_settings.get("password_auth", True))
        self.assertTrue(ssh_settings.get("pubkey_auth", True))

    def test_config_path_location(self) -> None:
        """Verify SSH config path is correct."""
        config = Config.load()
        module = SSHModule(config)

        expected_path = Path("/etc/ssh/sshd_config.d/99-linuxvm-ssh.conf")
        self.assertEqual(module.sshd_config_path, expected_path)


class TestSSHModuleDryRun(unittest.TestCase):
    """Test cases for dry-run mode behavior."""

    @patch("gvm.modules.ssh.run")
    @patch("gvm.modules.ssh.safe_write")
    @patch("gvm.modules.ssh.is_service_running")
    def test_dry_run_no_commands_executed(
        self,
        mock_service_running: MagicMock,
        mock_safe_write: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """Dry-run mode doesn't execute actual commands."""
        config = Config.load()
        module = SSHModule(config, dry_run=True)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        # Verify no actual system calls were made
        mock_run.assert_not_called()
        mock_safe_write.assert_not_called()

        # Verify result indicates dry run
        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("DRY RUN", result.message)


class TestSSHModuleRecovery(unittest.TestCase):
    """Test cases for recovery command."""

    def test_recovery_command(self) -> None:
        """get_recovery_command returns correct string."""
        config = Config.load()
        module = SSHModule(config)

        self.assertEqual(module.get_recovery_command(), "gvm fix ssh")


class TestSSHModuleRun(unittest.TestCase):
    """Test cases for the run() method."""

    @patch("gvm.modules.ssh.run")
    @patch("gvm.modules.ssh.safe_write")
    @patch("gvm.modules.ssh.is_service_running")
    def test_run_success(
        self,
        mock_service_running: MagicMock,
        mock_safe_write: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """run() returns success when all operations complete."""
        mock_service_running.return_value = True

        config = Config.load()
        module = SSHModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("complete", result.message.lower())

    @patch("gvm.modules.ssh.run")
    @patch("gvm.modules.ssh.safe_write")
    @patch("gvm.modules.ssh.is_service_running")
    def test_run_failure_on_service_not_starting(
        self,
        mock_service_running: MagicMock,
        mock_safe_write: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """run() returns failure when SSH service doesn't start."""
        mock_service_running.return_value = False

        config = Config.load()
        module = SSHModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIsNotNone(result.recovery_command)

    @patch("gvm.modules.ssh.run")
    def test_run_failure_on_command_error(self, mock_run: MagicMock) -> None:
        """run() returns failure when command raises SystemExit."""
        mock_run.side_effect = SystemExit("apt-get failed")

        config = Config.load()
        module = SSHModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIn("apt-get failed", result.message)
        self.assertIsNotNone(result.details)

    def test_progress_callback_called(self) -> None:
        """run() calls progress callback during execution."""
        config = Config.load()
        module = SSHModule(config, dry_run=True)

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Verify progress callback was called multiple times
        self.assertTrue(progress_callback.call_count > 0)


if __name__ == "__main__":
    unittest.main()
