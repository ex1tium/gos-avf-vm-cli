"""Tests for Shell module.

This module validates:
- ShellModule instantiation and attributes
- is_installed() detection logic
- Starship snippet creation
- Banner script generation
- Auto-display toggle configuration
- Dry-run mode behavior
- Recovery command output

Run with: python -m pytest tests/test_shell_module.py -v
Or standalone: python tests/test_shell_module.py
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from gvm.config import Config
from gvm.modules import Dependency, ModuleStatus
from gvm.modules.shell import ShellModule


class TestShellModuleInstantiation(unittest.TestCase):
    """Test cases for ShellModule instantiation."""

    def test_shell_module_instantiation(self) -> None:
        """ShellModule can be instantiated with config."""
        config = Config.load()
        module = ShellModule(config)

        self.assertEqual(module.name, "shell")
        self.assertFalse(module.verbose)
        self.assertFalse(module.dry_run)
        self.assertIs(module.config, config)

    def test_shell_module_with_flags(self) -> None:
        """ShellModule respects verbose and dry_run flags."""
        config = Config.load()
        module = ShellModule(config, verbose=True, dry_run=True)

        self.assertTrue(module.verbose)
        self.assertTrue(module.dry_run)


class TestShellModuleAttributes(unittest.TestCase):
    """Test cases for ShellModule class attributes."""

    def test_module_name(self) -> None:
        """ShellModule has correct name attribute."""
        self.assertEqual(ShellModule.name, "shell")

    def test_module_description(self) -> None:
        """ShellModule has a description."""
        self.assertTrue(len(ShellModule.description) > 0)
        self.assertIn("shell", ShellModule.description.lower())

    def test_module_dependencies(self) -> None:
        """ShellModule declares APT as required dependency."""
        self.assertIsInstance(ShellModule.dependencies, tuple)
        self.assertEqual(len(ShellModule.dependencies), 1)

        apt_dep = ShellModule.dependencies[0]
        self.assertIsInstance(apt_dep, Dependency)
        self.assertEqual(apt_dep.module_name, "apt")
        self.assertTrue(apt_dep.required)


class TestShellModuleIsInstalled(unittest.TestCase):
    """Test cases for is_installed() detection."""

    @patch("gvm.modules.shell.run")
    @patch.object(Path, "exists")
    @patch.object(Path, "read_text")
    def test_is_installed_when_starship_and_snippet_present(
        self,
        mock_read_text: MagicMock,
        mock_exists: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """is_installed returns True when Starship installed and bashrc snippet present."""
        # Mock starship being installed
        mock_run.return_value = MagicMock(returncode=0)
        # Mock bashrc existing
        mock_exists.return_value = True
        # Mock bashrc containing the marker
        mock_read_text.return_value = "# >>> gvm-starship >>>\neval\n# <<< gvm-starship <<<"

        config = Config.load()
        module = ShellModule(config)

        installed, message = module.is_installed()

        self.assertTrue(installed)
        self.assertIn("already present", message)

    @patch("gvm.modules.shell.run")
    def test_is_installed_when_starship_missing(self, mock_run: MagicMock) -> None:
        """is_installed returns False when Starship not installed."""
        mock_run.return_value = MagicMock(returncode=1)

        config = Config.load()
        module = ShellModule(config)

        installed, message = module.is_installed()

        self.assertFalse(installed)
        self.assertIn("not configured", message)


class TestStarshipSnippetCreation(unittest.TestCase):
    """Test cases for Starship snippet creation."""

    def test_starship_marker_label(self) -> None:
        """Verify Starship marker label is correct."""
        config = Config.load()
        module = ShellModule(config)

        self.assertEqual(module.starship_marker, "gvm-starship")

    def test_bashrc_path(self) -> None:
        """Verify bashrc path is set to user home."""
        config = Config.load()
        module = ShellModule(config)

        expected_path = Path.home() / ".bashrc"
        self.assertEqual(module.bashrc_path, expected_path)


class TestBannerScriptGeneration(unittest.TestCase):
    """Test cases for banner script generation."""

    def test_banner_script_path(self) -> None:
        """Verify banner script path is correct."""
        config = Config.load()
        module = ShellModule(config)

        expected_path = Path("/etc/profile.d/00-linuxvm-banner.sh")
        self.assertEqual(module.banner_script_path, expected_path)

    def test_banner_config_values(self) -> None:
        """Verify banner config values are accessible."""
        config = Config.load()

        banner_settings = config.banner
        self.assertIn("title", banner_settings)
        self.assertIn("show_ssh_note", banner_settings)
        self.assertIn("ssh_note", banner_settings)


class TestAutoDisplayToggle(unittest.TestCase):
    """Test cases for auto-display toggle configuration."""

    def test_auto_display_path(self) -> None:
        """Verify auto-display marker path is correct."""
        config = Config.load()
        module = ShellModule(config)

        expected_path = Path.home() / ".config" / "linuxvm" / "auto_display"
        self.assertEqual(module.auto_display_path, expected_path)

    def test_auto_display_config_default(self) -> None:
        """Verify auto_display feature is enabled by default."""
        config = Config.load()

        auto_display = config.features.get("auto_display", True)
        self.assertTrue(auto_display)


class TestShellModuleDryRun(unittest.TestCase):
    """Test cases for dry-run mode behavior."""

    @patch("gvm.modules.shell.run")
    @patch("gvm.modules.shell.ensure_snippet")
    @patch("gvm.modules.shell.safe_write")
    def test_dry_run_no_commands_executed(
        self,
        mock_safe_write: MagicMock,
        mock_ensure_snippet: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """Dry-run mode doesn't execute actual commands."""
        config = Config.load()
        module = ShellModule(config, dry_run=True)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        # Verify no actual system calls were made
        mock_run.assert_not_called()
        mock_safe_write.assert_not_called()
        mock_ensure_snippet.assert_not_called()

        # Verify result indicates dry run
        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("DRY RUN", result.message)


class TestShellModuleRecovery(unittest.TestCase):
    """Test cases for recovery command."""

    def test_recovery_command(self) -> None:
        """get_recovery_command returns correct string."""
        config = Config.load()
        module = ShellModule(config)

        self.assertEqual(module.get_recovery_command(), "gvm fix shell")


class TestShellModuleRun(unittest.TestCase):
    """Test cases for the run() method."""

    @patch("gvm.modules.shell.run")
    @patch("gvm.modules.shell.ensure_snippet")
    @patch("gvm.modules.shell.safe_write")
    @patch.object(Path, "mkdir")
    @patch.object(Path, "touch")
    def test_run_success(
        self,
        mock_touch: MagicMock,
        mock_mkdir: MagicMock,
        mock_safe_write: MagicMock,
        mock_ensure_snippet: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """run() returns success when all operations complete."""
        config = Config.load()
        module = ShellModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("complete", result.message.lower())

    @patch("gvm.modules.shell.run")
    def test_run_failure_on_command_error(self, mock_run: MagicMock) -> None:
        """run() returns failure when command raises SystemExit."""
        mock_run.side_effect = SystemExit("apt-get failed")

        config = Config.load()
        module = ShellModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIn("apt-get failed", result.message)
        self.assertIsNotNone(result.details)

    def test_progress_callback_called(self) -> None:
        """run() calls progress callback during execution."""
        config = Config.load()
        module = ShellModule(config, dry_run=True)

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Verify progress callback was called multiple times
        self.assertTrue(progress_callback.call_count > 0)


class TestShellModuleExceptionHandling(unittest.TestCase):
    """Test cases for exception handling."""

    @patch("gvm.modules.shell.run")
    def test_handles_system_exit(self, mock_run: MagicMock) -> None:
        """Module handles SystemExit and returns proper result."""
        mock_run.side_effect = SystemExit("Command failed")

        config = Config.load()
        module = ShellModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertEqual(result.recovery_command, "gvm fix shell")

    @patch("gvm.modules.shell.run")
    def test_handles_general_exception(self, mock_run: MagicMock) -> None:
        """Module handles general Exception and returns proper result."""
        mock_run.side_effect = RuntimeError("Unexpected error")

        config = Config.load()
        module = ShellModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIn("Unexpected error", result.message)
        self.assertIsNotNone(result.details)


if __name__ == "__main__":
    unittest.main()
