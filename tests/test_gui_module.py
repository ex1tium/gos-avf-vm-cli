"""Tests for GUI module.

This module validates:
- GUIModule instantiation and attributes
- is_installed() detection logic
- Generic helper script creation
- Desktop-specific script generation
- PATH snippet addition
- Script permissions
- Dry-run mode behavior
- Recovery command output

Run with: python -m pytest tests/test_gui_module.py -v
Or standalone: python tests/test_gui_module.py
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gvm.config import Config, DesktopConfig
from gvm.modules import Dependency, ModuleStatus
from gvm.modules.gui import GUIModule


class TestGUIModuleInstantiation(unittest.TestCase):
    """Test cases for GUIModule instantiation."""

    def test_gui_module_instantiation(self) -> None:
        """GUIModule can be instantiated with config."""
        config = Config.load()
        module = GUIModule(config)

        self.assertEqual(module.name, "gui")
        self.assertFalse(module.verbose)
        self.assertFalse(module.dry_run)
        self.assertIs(module.config, config)

    def test_gui_module_with_flags(self) -> None:
        """GUIModule respects verbose and dry_run flags."""
        config = Config.load()
        module = GUIModule(config, verbose=True, dry_run=True)

        self.assertTrue(module.verbose)
        self.assertTrue(module.dry_run)


class TestGUIModuleAttributes(unittest.TestCase):
    """Test cases for GUIModule class attributes."""

    def test_module_name(self) -> None:
        """GUIModule has correct name attribute."""
        self.assertEqual(GUIModule.name, "gui")

    def test_module_description(self) -> None:
        """GUIModule has a description."""
        self.assertTrue(len(GUIModule.description) > 0)
        self.assertIn("GUI", GUIModule.description)

    def test_module_dependencies_optional(self) -> None:
        """GUIModule declares desktop as optional dependency."""
        self.assertIsInstance(GUIModule.dependencies, tuple)
        self.assertEqual(len(GUIModule.dependencies), 1)

        desktop_dep = GUIModule.dependencies[0]
        self.assertIsInstance(desktop_dep, Dependency)
        self.assertEqual(desktop_dep.module_name, "desktop")
        self.assertFalse(desktop_dep.required)  # Optional dependency


class TestGUIModuleIsInstalled(unittest.TestCase):
    """Test cases for is_installed() detection."""

    @patch.object(Path, "exists")
    def test_is_installed_when_script_exists(self, mock_exists: MagicMock) -> None:
        """is_installed returns True when start-gui script exists."""
        mock_exists.return_value = True

        config = Config.load()
        module = GUIModule(config)

        installed, message = module.is_installed()

        self.assertTrue(installed)
        self.assertIn("already present", message)

    @patch.object(Path, "exists")
    def test_is_installed_when_script_missing(self, mock_exists: MagicMock) -> None:
        """is_installed returns False when start-gui script doesn't exist."""
        mock_exists.return_value = False

        config = Config.load()
        module = GUIModule(config)

        installed, message = module.is_installed()

        self.assertFalse(installed)
        self.assertIn("not configured", message)


class TestGenericHelperScript(unittest.TestCase):
    """Test cases for generic start-gui script."""

    def test_start_gui_path(self) -> None:
        """Verify start-gui path is correct."""
        config = Config.load()
        module = GUIModule(config)

        expected_path = Path.home() / ".local" / "bin" / "start-gui"
        self.assertEqual(module.start_gui_path, expected_path)

    def test_local_bin_path(self) -> None:
        """Verify local bin path is correct."""
        config = Config.load()
        module = GUIModule(config)

        expected_path = Path.home() / ".local" / "bin"
        self.assertEqual(module.local_bin_path, expected_path)


class TestDesktopSpecificScripts(unittest.TestCase):
    """Test cases for desktop-specific script generation."""

    @patch.object(Config, "discover_desktops")
    @patch.object(Path, "write_text")
    @patch.object(Path, "chmod")
    @patch.object(Path, "mkdir")
    def test_desktop_scripts_created_for_each_desktop(
        self,
        mock_mkdir: MagicMock,
        mock_chmod: MagicMock,
        mock_write_text: MagicMock,
        mock_discover: MagicMock,
    ) -> None:
        """Desktop-specific scripts are created for each discovered desktop."""
        # Mock desktop discovery
        mock_desktops = {
            "labwc": DesktopConfig(
                name="labwc",
                description="Labwc window manager",
                session_start_command="labwc",
                session_requires_dbus=True,
            ),
            "sway": DesktopConfig(
                name="sway",
                description="Sway compositor",
                session_start_command="sway",
                session_requires_dbus=True,
            ),
        }
        mock_discover.return_value = mock_desktops

        config = Config.load()
        module = GUIModule(config)

        progress_callback = MagicMock()

        # Call the internal method directly
        module._create_desktop_scripts(progress_callback)

        # Verify write_text was called for each desktop
        self.assertEqual(mock_write_text.call_count, 2)
        self.assertEqual(mock_chmod.call_count, 2)

    @patch.object(Config, "discover_desktops")
    def test_no_scripts_when_no_desktops(self, mock_discover: MagicMock) -> None:
        """No scripts created when no desktops discovered."""
        mock_discover.return_value = {}

        config = Config.load()
        module = GUIModule(config)

        progress_callback = MagicMock()
        module._create_desktop_scripts(progress_callback)

        # Should complete without error


class TestPATHSnippetAddition(unittest.TestCase):
    """Test cases for PATH snippet addition."""

    def test_local_bin_marker(self) -> None:
        """Verify local bin marker label is correct."""
        config = Config.load()
        module = GUIModule(config)

        self.assertEqual(module.local_bin_marker, "gvm-local-bin")

    def test_bashrc_path(self) -> None:
        """Verify bashrc path is set to user home."""
        config = Config.load()
        module = GUIModule(config)

        expected_path = Path.home() / ".bashrc"
        self.assertEqual(module.bashrc_path, expected_path)


class TestScriptPermissions(unittest.TestCase):
    """Test cases for script permissions."""

    @patch.object(Path, "write_text")
    @patch.object(Path, "chmod")
    @patch.object(Path, "mkdir")
    def test_scripts_created_with_executable_permissions(
        self,
        mock_mkdir: MagicMock,
        mock_chmod: MagicMock,
        mock_write_text: MagicMock,
    ) -> None:
        """Scripts are created with 0o755 permissions."""
        config = Config.load()
        module = GUIModule(config)

        progress_callback = MagicMock()
        module._create_start_gui_script(progress_callback)

        # Verify chmod was called with 0o755
        mock_chmod.assert_called_with(0o755)


class TestGUIModuleDryRun(unittest.TestCase):
    """Test cases for dry-run mode behavior."""

    @patch("gvm.modules.gui.ensure_snippet")
    @patch("gvm.modules.gui.safe_write")
    @patch.object(Path, "mkdir")
    @patch.object(Path, "write_text")
    @patch.object(Path, "chmod")
    def test_dry_run_no_files_created(
        self,
        mock_chmod: MagicMock,
        mock_write_text: MagicMock,
        mock_mkdir: MagicMock,
        mock_safe_write: MagicMock,
        mock_ensure_snippet: MagicMock,
    ) -> None:
        """Dry-run mode doesn't create files."""
        config = Config.load()
        module = GUIModule(config, dry_run=True)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        # Verify no actual file operations
        mock_safe_write.assert_not_called()
        mock_ensure_snippet.assert_not_called()
        mock_write_text.assert_not_called()

        # Verify result indicates dry run
        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("DRY RUN", result.message)


class TestGUIModuleRecovery(unittest.TestCase):
    """Test cases for recovery command."""

    def test_recovery_command(self) -> None:
        """get_recovery_command returns correct string."""
        config = Config.load()
        module = GUIModule(config)

        self.assertEqual(module.get_recovery_command(), "gvm fix gui")


class TestGUIModuleRun(unittest.TestCase):
    """Test cases for the run() method."""

    @patch.object(Config, "discover_desktops")
    @patch("gvm.modules.gui.ensure_snippet")
    @patch.object(Path, "mkdir")
    @patch.object(Path, "write_text")
    @patch.object(Path, "chmod")
    def test_run_success(
        self,
        mock_chmod: MagicMock,
        mock_write_text: MagicMock,
        mock_mkdir: MagicMock,
        mock_ensure_snippet: MagicMock,
        mock_discover: MagicMock,
    ) -> None:
        """run() returns success when all operations complete."""
        mock_discover.return_value = {}

        config = Config.load()
        module = GUIModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("complete", result.message.lower())

    @patch.object(Path, "mkdir")
    def test_run_failure_on_exception(self, mock_mkdir: MagicMock) -> None:
        """run() returns failure when exception occurs."""
        mock_mkdir.side_effect = PermissionError("Access denied")

        config = Config.load()
        module = GUIModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIsNotNone(result.recovery_command)

    def test_progress_callback_called(self) -> None:
        """run() calls progress callback during execution."""
        config = Config.load()
        module = GUIModule(config, dry_run=True)

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Verify progress callback was called multiple times
        self.assertTrue(progress_callback.call_count > 0)


class TestGUIModuleExceptionHandling(unittest.TestCase):
    """Test cases for exception handling."""

    @patch.object(Path, "mkdir")
    def test_handles_system_exit(self, mock_mkdir: MagicMock) -> None:
        """Module handles SystemExit and returns proper result."""
        mock_mkdir.side_effect = SystemExit("Operation failed")

        config = Config.load()
        module = GUIModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertEqual(result.recovery_command, "gvm fix gui")

    @patch.object(Path, "mkdir")
    def test_handles_general_exception(self, mock_mkdir: MagicMock) -> None:
        """Module handles general Exception and returns proper result."""
        mock_mkdir.side_effect = RuntimeError("Unexpected error")

        config = Config.load()
        module = GUIModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIn("Unexpected error", result.message)
        self.assertIsNotNone(result.details)


if __name__ == "__main__":
    unittest.main()
