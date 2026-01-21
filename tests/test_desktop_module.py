"""Tests for Desktop module.

This module validates:
- DesktopModule instantiation and attributes
- Desktop configuration loading
- Package list generation
- File creation from templates
- Helper script generation
- Dry-run mode behavior
- Recovery command output
- Dependencies declaration

Run with: python -m pytest tests/test_desktop_module.py -v
Or standalone: python tests/test_desktop_module.py
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gvm.config import Config, DesktopConfig
from gvm.modules import Dependency, ModuleStatus
from gvm.modules.desktop import DesktopModule


class TestDesktopModuleInstantiation(unittest.TestCase):
    """Test cases for DesktopModule instantiation."""

    def test_desktop_module_instantiation(self) -> None:
        """DesktopModule can be instantiated with config."""
        config = Config.load()
        module = DesktopModule(config)

        self.assertEqual(module.name, "desktop")
        self.assertFalse(module.verbose)
        self.assertFalse(module.dry_run)
        self.assertIs(module.config, config)
        self.assertIsNone(module.desktop_name)

    def test_desktop_module_with_flags(self) -> None:
        """DesktopModule respects verbose and dry_run flags."""
        config = Config.load()
        module = DesktopModule(config, verbose=True, dry_run=True)

        self.assertTrue(module.verbose)
        self.assertTrue(module.dry_run)

    def test_desktop_module_with_desktop_name(self) -> None:
        """DesktopModule accepts optional desktop_name parameter."""
        config = Config.load()
        module = DesktopModule(config, desktop_name="Plasma Mobile")

        self.assertEqual(module.desktop_name, "Plasma Mobile")


class TestDesktopModuleAttributes(unittest.TestCase):
    """Test cases for DesktopModule class attributes."""

    def test_module_name(self) -> None:
        """DesktopModule has correct name attribute."""
        self.assertEqual(DesktopModule.name, "desktop")

    def test_module_description(self) -> None:
        """DesktopModule has a description containing 'desktop'."""
        self.assertTrue(len(DesktopModule.description) > 0)
        self.assertIn("desktop", DesktopModule.description.lower())

    def test_module_dependencies(self) -> None:
        """DesktopModule declares APT as required dependency."""
        self.assertIsInstance(DesktopModule.dependencies, tuple)
        self.assertEqual(len(DesktopModule.dependencies), 1)

        apt_dep = DesktopModule.dependencies[0]
        self.assertIsInstance(apt_dep, Dependency)
        self.assertEqual(apt_dep.module_name, "apt")
        self.assertTrue(apt_dep.required)


class TestDesktopConfigLoading(unittest.TestCase):
    """Test cases for desktop configuration loading."""

    def test_discover_desktops_returns_dict(self) -> None:
        """discover_desktops returns a dictionary."""
        config = Config.load()
        desktops = config.discover_desktops()

        self.assertIsInstance(desktops, dict)

    def test_discovered_desktops_are_desktop_configs(self) -> None:
        """Discovered desktops are DesktopConfig instances."""
        config = Config.load()
        desktops = config.discover_desktops()

        for name, desktop in desktops.items():
            self.assertIsInstance(name, str)
            self.assertIsInstance(desktop, DesktopConfig)

    @patch.object(Config, "discover_desktops")
    def test_specific_desktop_selection(self, mock_discover: MagicMock) -> None:
        """Module can select a specific desktop to install."""
        mock_desktop = DesktopConfig(
            name="Test Desktop",
            description="Test desktop for unit tests",
            packages_core=["test-core-pkg"],
        )
        mock_discover.return_value = {"Test Desktop": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test Desktop")

        self.assertEqual(module.desktop_name, "Test Desktop")

    @patch.object(Config, "discover_desktops")
    @patch("gvm.modules.desktop.run")
    @patch("gvm.modules.desktop.safe_write")
    def test_error_when_requested_desktop_not_found(
        self,
        mock_write: MagicMock,
        mock_run: MagicMock,
        mock_discover: MagicMock,
    ) -> None:
        """Module returns error when requested desktop not found."""
        mock_discover.return_value = {"XFCE4": DesktopConfig(name="XFCE4")}

        config = Config.load()
        module = DesktopModule(config, desktop_name="NonExistent")

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIn("NonExistent", result.message)
        self.assertIn("not found", result.message)


class TestPackageListGeneration(unittest.TestCase):
    """Test cases for package list generation."""

    def test_get_all_packages_combines_lists(self) -> None:
        """get_all_packages combines core, optional, wayland_helpers, and user packages."""
        desktop = DesktopConfig(
            name="Test",
            packages_core=["core1", "core2"],
            packages_optional=["opt1"],
            packages_wayland_helpers=["wayland1"],
            packages_user=["user1", "user2"],
        )

        packages = desktop.get_all_packages()

        self.assertEqual(len(packages), 6)
        self.assertIn("core1", packages)
        self.assertIn("core2", packages)
        self.assertIn("opt1", packages)
        self.assertIn("wayland1", packages)
        self.assertIn("user1", packages)
        self.assertIn("user2", packages)

    def test_get_all_packages_empty_lists(self) -> None:
        """get_all_packages handles empty package lists gracefully."""
        desktop = DesktopConfig(name="Empty")

        packages = desktop.get_all_packages()

        self.assertEqual(packages, [])

    def test_get_all_packages_partial_lists(self) -> None:
        """get_all_packages works with only some package lists populated."""
        desktop = DesktopConfig(
            name="Partial",
            packages_core=["core-only"],
        )

        packages = desktop.get_all_packages()

        self.assertEqual(packages, ["core-only"])


class TestFileCreation(unittest.TestCase):
    """Test cases for file creation from templates."""

    @patch("gvm.modules.desktop.safe_write")
    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_path_expansion_with_tilde(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        """File paths with ~ are expanded to home directory."""
        mock_desktop = DesktopConfig(
            name="Test",
            files={"~/.config/test/file.conf": "test content"},
            session_start_command="test-session",
        )
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Find the call that wrote the config file (not the helper script or marker)
        config_calls = [
            call for call in mock_write.call_args_list
            if "test/file.conf" in str(call[0][0])
        ]
        self.assertTrue(len(config_calls) > 0)

        # Verify path was expanded (should not contain ~)
        written_path = config_calls[0][0][0]
        self.assertNotIn("~", str(written_path))
        self.assertIn(".config/test/file.conf", str(written_path))

    @patch("gvm.modules.desktop.safe_write")
    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_executable_permission_detection(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        """Files starting with #! get executable permissions."""
        mock_desktop = DesktopConfig(
            name="Test",
            files={
                "~/.config/test/script.sh": "#!/bin/bash\necho hello",
                "~/.config/test/config.conf": "key=value",
            },
            session_start_command="test-session",
        )
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Find calls for our test files
        script_calls = [
            call for call in mock_write.call_args_list
            if "script.sh" in str(call[0][0])
        ]
        config_calls = [
            call for call in mock_write.call_args_list
            if "config.conf" in str(call[0][0])
        ]

        # Assert the expected writes occurred - fail loudly if they didn't
        self.assertGreater(
            len(script_calls), 0,
            "Expected safe_write call for script.sh but none found"
        )
        self.assertGreater(
            len(config_calls), 0,
            "Expected safe_write call for config.conf but none found"
        )

        # Script should have 0o755
        self.assertEqual(script_calls[0][1].get("mode"), 0o755)

        # Config should have 0o644
        self.assertEqual(config_calls[0][1].get("mode"), 0o644)


class TestHelperScriptGeneration(unittest.TestCase):
    """Test cases for helper script generation."""

    def test_script_name_from_session_helper_script_name(self) -> None:
        """Script name derived from session_helper_script_name."""
        desktop = DesktopConfig(
            name="Test Desktop",
            session_helper_script_name="start-test",
        )

        # The module would use this name directly
        self.assertEqual(desktop.session_helper_script_name, "start-test")

    def test_script_name_generation_from_desktop_name(self) -> None:
        """Script name generated from desktop.name when helper_script_name not set."""
        desktop = DesktopConfig(
            name="Plasma Mobile",
            session_helper_script_name="",  # Empty, should derive from name
        )

        # Module logic: desktop.name.lower().replace(" ", "-")
        expected_base = "plasma-mobile"
        self.assertEqual(desktop.name.lower().replace(" ", "-"), expected_base)

    @patch("gvm.modules.desktop.safe_write")
    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_dbus_wrapping_when_required(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        """Launch command wrapped with dbus-run-session when required."""
        mock_desktop = DesktopConfig(
            name="Test",
            session_start_command="starttest",
            session_requires_dbus=True,
            session_helper_script_name="start-test",
        )
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Find the helper script write call
        script_calls = [
            call for call in mock_write.call_args_list
            if "start-test" in str(call[0][0])
        ]

        self.assertTrue(len(script_calls) > 0)
        content = script_calls[0][0][1]
        self.assertIn("dbus-run-session", content)
        self.assertIn("starttest", content)

    @patch("gvm.modules.desktop.safe_write")
    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_fallback_command_inclusion(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        """Fallback command included with if/then conditional block."""
        mock_desktop = DesktopConfig(
            name="Test",
            session_start_command="primary-cmd",
            session_fallback_command="fallback-cmd",
            session_requires_dbus=False,
            session_helper_script_name="start-test",
        )
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Find the helper script write call
        script_calls = [
            call for call in mock_write.call_args_list
            if "start-test" in str(call[0][0])
        ]

        self.assertTrue(len(script_calls) > 0)
        content = script_calls[0][0][1]
        # The helper script uses an if/then block for fallback:
        # if ! primary-cmd; then
        #     exec fallback-cmd
        # fi
        self.assertIn("if ! primary-cmd; then", content)
        self.assertIn("exec fallback-cmd", content)
        self.assertIn("fi", content)

    @patch("gvm.modules.desktop.safe_write")
    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_environment_variable_exports(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        """Environment variables exported in helper script."""
        mock_desktop = DesktopConfig(
            name="Test",
            environment_vars=["VAR1=value1", "VAR2=value2"],
            session_start_command="test-cmd",
            session_helper_script_name="start-test",
        )
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Find the helper script write call
        script_calls = [
            call for call in mock_write.call_args_list
            if "start-test" in str(call[0][0])
        ]

        self.assertTrue(len(script_calls) > 0)
        content = script_calls[0][0][1]
        self.assertIn("export VAR1=value1", content)
        self.assertIn("export VAR2=value2", content)


class TestDesktopModuleDryRun(unittest.TestCase):
    """Test cases for dry-run mode behavior."""

    @patch("gvm.modules.desktop.run")
    @patch("gvm.modules.desktop.safe_write")
    @patch.object(Config, "discover_desktops")
    def test_dry_run_no_commands_executed(
        self,
        mock_discover: MagicMock,
        mock_safe_write: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """Dry-run mode doesn't execute actual commands."""
        mock_desktop = DesktopConfig(
            name="Test",
            packages_core=["test-pkg"],
            session_start_command="test-cmd",
        )
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, dry_run=True, desktop_name="Test")

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        # Verify no actual system calls were made
        mock_run.assert_not_called()
        mock_safe_write.assert_not_called()

        # Verify result indicates dry run
        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("DRY RUN", result.message)

    @patch("gvm.modules.desktop.run")
    @patch("gvm.modules.desktop.safe_write")
    @patch.object(Config, "discover_desktops")
    def test_dry_run_result_message(
        self,
        mock_discover: MagicMock,
        mock_safe_write: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """Dry-run result message includes [DRY RUN] prefix."""
        mock_desktop = DesktopConfig(name="Test", session_start_command="test")
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, dry_run=True, desktop_name="Test")

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertIn("[DRY RUN]", result.message)


class TestDesktopModuleRecovery(unittest.TestCase):
    """Test cases for recovery command."""

    def test_recovery_command_default(self) -> None:
        """get_recovery_command returns correct string for default case."""
        config = Config.load()
        module = DesktopModule(config)

        self.assertEqual(module.get_recovery_command(), "gvm fix desktop")

    def test_recovery_command_with_desktop_name(self) -> None:
        """get_recovery_command includes desktop name when specified."""
        config = Config.load()
        module = DesktopModule(config, desktop_name="Plasma Mobile")

        self.assertEqual(module.get_recovery_command(), "gvm fix desktop Plasma Mobile")


class TestDesktopModuleRun(unittest.TestCase):
    """Test cases for the run() method."""

    @patch("gvm.modules.desktop.run")
    @patch("gvm.modules.desktop.safe_write")
    @patch.object(Config, "discover_desktops")
    def test_run_success(
        self,
        mock_discover: MagicMock,
        mock_safe_write: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """run() returns success when all operations complete."""
        mock_desktop = DesktopConfig(
            name="Test",
            packages_core=["test-pkg"],
            session_start_command="test-cmd",
        )
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.SUCCESS)
        self.assertIn("complete", result.message.lower())

    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_run_failure_on_command_error(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """run() returns failure when command raises SystemExit."""
        mock_desktop = DesktopConfig(
            name="Test",
            packages_core=["test-pkg"],
            session_start_command="test-cmd",
        )
        mock_discover.return_value = {"Test": mock_desktop}
        mock_run.side_effect = SystemExit("apt-get failed")

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIn("apt-get failed", result.message)
        self.assertIsNotNone(result.details)

    @patch("gvm.modules.desktop.run")
    @patch("gvm.modules.desktop.safe_write")
    @patch.object(Config, "discover_desktops")
    def test_progress_callback_called(
        self,
        mock_discover: MagicMock,
        mock_safe_write: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """run() calls progress callback during execution."""
        mock_desktop = DesktopConfig(name="Test", session_start_command="test")
        mock_discover.return_value = {"Test": mock_desktop}

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        progress_callback = MagicMock()
        module.run(progress_callback)

        # Verify progress callback was called multiple times
        self.assertTrue(progress_callback.call_count > 0)

    @patch.object(Config, "discover_desktops")
    def test_run_failure_no_desktops_found(
        self,
        mock_discover: MagicMock,
    ) -> None:
        """run() returns failure when no desktop configurations found."""
        mock_discover.return_value = {}

        config = Config.load()
        module = DesktopModule(config)

        progress_callback = MagicMock()
        result = module.run(progress_callback)

        self.assertEqual(result.status, ModuleStatus.FAILED)
        self.assertIn("No desktop configurations found", result.message)


class TestDesktopModuleIsInstalled(unittest.TestCase):
    """Test cases for is_installed() detection."""

    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_is_installed_with_specific_desktop_installed(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """is_installed returns True when specific desktop packages are installed."""
        mock_desktop = DesktopConfig(
            name="Test",
            packages_core=["test-pkg"],
        )
        mock_discover.return_value = {"Test": mock_desktop}

        # Mock dpkg to return success with "ii" status
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ii  test-pkg  1.0  amd64  Test package"
        mock_run.return_value = mock_result

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        installed, message = module.is_installed()

        self.assertTrue(installed)
        self.assertIn("Test", message)

    @patch("gvm.modules.desktop.run")
    @patch.object(Config, "discover_desktops")
    def test_is_installed_with_specific_desktop_not_installed(
        self,
        mock_discover: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """is_installed returns False when specific desktop packages not installed."""
        mock_desktop = DesktopConfig(
            name="Test",
            packages_core=["test-pkg"],
        )
        mock_discover.return_value = {"Test": mock_desktop}

        # Mock dpkg to return failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        config = Config.load()
        module = DesktopModule(config, desktop_name="Test")

        installed, message = module.is_installed()

        self.assertFalse(installed)
        self.assertIn("not installed", message)

    @patch.object(Path, "exists")
    def test_is_installed_checks_marker_file(self, mock_exists: MagicMock) -> None:
        """is_installed checks marker file when no specific desktop requested."""
        mock_exists.return_value = False

        config = Config.load()
        module = DesktopModule(config)

        installed, message = module.is_installed()

        self.assertFalse(installed)
        self.assertIn("No desktop", message)


if __name__ == "__main__":
    unittest.main()
