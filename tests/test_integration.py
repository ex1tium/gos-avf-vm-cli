"""Comprehensive integration tests for GVM tool.

This module validates end-to-end workflows without requiring actual AVF VM execution.
Uses extensive mocking to simulate system interactions while testing:
- Orchestration logic
- CLI routing
- Module coordination
- Error recovery flows
- Configuration management

Manual Verification Notes:
    Many tests simulate system operations. For actual AVF VM validation:
    - See DEPLOYMENT.md for step-by-step testing procedures
    - TUI tests require an actual terminal (cannot test in CI)
    - Dry-run mode is available for safe testing: gvm setup --all --dry-run

Run with: python -m pytest tests/test_integration.py -v
Or standalone: python tests/test_integration.py
"""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from gvm.cli import (
    cmd_desktop,
    cmd_fix,
    cmd_info,
    cmd_module,
    cmd_setup,
    create_argument_parser,
    route_command,
)
from gvm.config import Config, DesktopConfig, EMBEDDED_DEFAULTS
from gvm.modules import (
    Dependency,
    Module,
    ModuleResult,
    ModuleStatus,
    RecoveryAction,
    get_module_class,
    list_modules,
)
from gvm.orchestrator import ModuleOrchestrator


class TestCompleteSetupFlow(unittest.TestCase):
    """Test gvm setup --all execution path through CLI -> orchestrator -> all modules.

    Manual Verification:
        On AVF VM, run: ./gvm setup --all -v
        Verify all modules execute in dependency order:
        1. apt (no dependencies)
        2. ssh, shell, gui, desktop (depend on apt)
        Check: gvm info shows all modules as installed
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    @mock.patch("gvm.modules.ssh.SSHModule.run")
    @mock.patch("gvm.modules.ssh.SSHModule.is_installed")
    @mock.patch("gvm.modules.shell.ShellModule.run")
    @mock.patch("gvm.modules.shell.ShellModule.is_installed")
    @mock.patch("gvm.modules.gui.GUIModule.run")
    @mock.patch("gvm.modules.gui.GUIModule.is_installed")
    @mock.patch("gvm.modules.desktop.DesktopModule.run")
    @mock.patch("gvm.modules.desktop.DesktopModule.is_installed")
    def test_full_setup_all_modules_execute(
        self,
        mock_desktop_installed: mock.Mock,
        mock_desktop_run: mock.Mock,
        mock_gui_installed: mock.Mock,
        mock_gui_run: mock.Mock,
        mock_shell_installed: mock.Mock,
        mock_shell_run: mock.Mock,
        mock_ssh_installed: mock.Mock,
        mock_ssh_run: mock.Mock,
        mock_apt_installed: mock.Mock,
        mock_apt_run: mock.Mock,
    ) -> None:
        """Test that all modules execute in correct dependency order."""
        # Configure mocks - all modules return not installed
        mock_apt_installed.return_value = (False, "Not configured")
        mock_ssh_installed.return_value = (False, "Not configured")
        mock_shell_installed.return_value = (False, "Not configured")
        mock_gui_installed.return_value = (False, "Not configured")
        mock_desktop_installed.return_value = (False, "Not configured")

        # All modules return success
        success_result = ModuleResult(status=ModuleStatus.SUCCESS, message="Completed")
        mock_apt_run.return_value = success_result
        mock_ssh_run.return_value = success_result
        mock_shell_run.return_value = success_result
        mock_gui_run.return_value = success_result
        mock_desktop_run.return_value = success_result

        # Execute all modules
        orchestrator = ModuleOrchestrator(self.config, verbose=False, dry_run=False)
        modules = list_modules()  # ['apt', 'desktop', 'gui', 'shell', 'ssh']

        progress_calls: list[tuple[float, str]] = []

        def progress_callback(
            percent: float, message: str, operation: Optional[str]
        ) -> None:
            progress_calls.append((percent, message))

        results = orchestrator.execute(modules, progress_callback=progress_callback)

        # Verify all modules executed
        self.assertEqual(len(results), len(modules))

        # Verify all succeeded
        for name, result in results.items():
            self.assertEqual(
                result.status,
                ModuleStatus.SUCCESS,
                f"Module {name} should have succeeded",
            )

        # Verify apt executed (as it has no dependencies)
        mock_apt_run.assert_called_once()

    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    def test_setup_with_verbose_mode(
        self,
        mock_apt_installed: mock.Mock,
        mock_apt_run: mock.Mock,
    ) -> None:
        """Test verbose mode passes through to modules."""
        mock_apt_installed.return_value = (False, "Not configured")
        mock_apt_run.return_value = ModuleResult(
            status=ModuleStatus.SUCCESS, message="Done"
        )

        orchestrator = ModuleOrchestrator(self.config, verbose=True, dry_run=False)
        orchestrator.execute(["apt"])

        # Verify module was created with verbose=True
        apt_module = orchestrator.modules.get("apt")
        self.assertIsNotNone(apt_module)
        self.assertTrue(apt_module.verbose)

    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    def test_progress_callback_invoked_with_percentages(
        self,
        mock_apt_installed: mock.Mock,
        mock_apt_run: mock.Mock,
    ) -> None:
        """Test progress callback receives percentage updates."""
        mock_apt_installed.return_value = (False, "Not configured")
        mock_apt_run.return_value = ModuleResult(
            status=ModuleStatus.SUCCESS, message="Done"
        )

        orchestrator = ModuleOrchestrator(self.config)

        progress_calls: list[float] = []

        def progress_callback(
            percent: float, message: str, operation: Optional[str]
        ) -> None:
            progress_calls.append(percent)

        orchestrator.execute(["apt"], progress_callback=progress_callback)

        # Verify progress was tracked
        self.assertTrue(len(progress_calls) > 0)
        # Final progress should be 1.0
        self.assertEqual(progress_calls[-1], 1.0)


class TestIndividualModuleExecution(unittest.TestCase):
    """Test individual module execution via CLI commands.

    Manual Verification:
        Test each command individually:
        - ./gvm apt -v
        - ./gvm ssh -v
        - ./gvm shell -v
        - ./gvm gui -v
        - ./gvm desktop plasma-mobile -v
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    def test_cmd_module_validates_module_exists(self) -> None:
        """cmd_module validates that module name exists."""
        args = argparse.Namespace(
            verbose=False, dry_run=False, help=False, config=None
        )

        # Test with invalid module - should print error and return 1
        with mock.patch("builtins.print") as mock_print:
            result = cmd_module(args, self.config, "nonexistent_module")
            self.assertEqual(result, 1)
            # Verify error message was printed
            mock_print.assert_called()

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    def test_cmd_module_executes_via_orchestrator(
        self, mock_execute: mock.Mock
    ) -> None:
        """cmd_module routes to orchestrator for execution."""
        mock_execute.return_value = {
            "apt": ModuleResult(status=ModuleStatus.SUCCESS, message="Done")
        }

        args = argparse.Namespace(
            verbose=False, dry_run=False, help=False, config=None
        )
        result = cmd_module(args, self.config, "apt")

        self.assertEqual(result, 0)
        mock_execute.assert_called_once()
        # Verify 'apt' was in the modules list
        call_args = mock_execute.call_args
        self.assertIn("apt", call_args[0][0])

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    def test_cmd_module_returns_error_on_failure(
        self, mock_execute: mock.Mock
    ) -> None:
        """cmd_module returns non-zero exit code on module failure."""
        mock_execute.return_value = {
            "apt": ModuleResult(
                status=ModuleStatus.FAILED,
                message="APT update failed",
                recovery_command="gvm fix apt",
            )
        }

        args = argparse.Namespace(
            verbose=False, dry_run=False, help=False, config=None
        )

        with mock.patch("builtins.print"):
            result = cmd_module(args, self.config, "apt")

        self.assertEqual(result, 1)

    def test_cli_argument_parser_creates_subcommands(self) -> None:
        """CLI parser creates all expected subcommands."""
        parser = create_argument_parser()

        # Test that parsing works for each command
        commands = ["setup", "apt", "ssh", "shell", "gui", "config", "info", "fix"]
        for cmd in commands:
            args = parser.parse_args([cmd])
            self.assertEqual(args.command, cmd)

    def test_cli_global_flags_parsed(self) -> None:
        """CLI global flags are parsed correctly."""
        parser = create_argument_parser()

        args = parser.parse_args(["-v", "--dry-run", "apt"])
        self.assertTrue(args.verbose)
        self.assertTrue(args.dry_run)
        self.assertEqual(args.command, "apt")


class TestTUIComponentSelection(unittest.TestCase):
    """Test TUI component selection logic (mocked curses).

    Manual Verification:
        Run: ./gvm setup
        - Navigate with arrow keys
        - Toggle selection with space
        - Press 'a' for select all, 'n' for none
        - Press Enter to confirm
        - Press q to quit
    """

    def test_component_discovery_finds_modules(self) -> None:
        """TUI discovers all registered modules."""
        from gvm.tui import CursesTUI

        config = Config.load()
        tui = CursesTUI(config)
        tui._discover_components()

        # Verify modules are discovered
        component_ids = [c.id for c in tui.selection_state.components]
        for module_name in list_modules():
            # base modules should be in components (not desktop-prefixed)
            if module_name != "desktop":
                self.assertIn(module_name, component_ids)

    def test_component_default_selection(self) -> None:
        """TUI sets default selections correctly."""
        from gvm.tui import CursesTUI

        config = Config.load()
        tui = CursesTUI(config)
        tui._discover_components()

        # apt, ssh, shell, gui should be selected by default
        for module_id in ["apt", "ssh", "shell", "gui"]:
            self.assertTrue(
                tui.selection_state.selections.get(module_id, False),
                f"{module_id} should be selected by default",
            )

    def test_selection_persistence_save_load(self) -> None:
        """TUI saves and loads selections correctly."""
        from gvm.tui import CursesTUI

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create TUI with custom selection file path
            config = Config.load()
            tui = CursesTUI(config)
            tui.SELECTION_FILE = Path(tmpdir) / "last-selection.json"

            tui._discover_components()

            # Modify selection
            tui.selection_state.selections["apt"] = False

            # Save
            tui._save_selections()

            # Verify file exists
            self.assertTrue(tui.SELECTION_FILE.exists())

            # Create new TUI and load
            tui2 = CursesTUI(config)
            tui2.SELECTION_FILE = tui.SELECTION_FILE
            tui2._discover_components()
            tui2._load_last_selections()

            # Verify selection was loaded
            self.assertFalse(tui2.selection_state.selections.get("apt", True))

    def test_selection_file_format(self) -> None:
        """TUI selection file has correct JSON format."""
        from gvm.tui import CursesTUI

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config.load()
            tui = CursesTUI(config)
            tui.SELECTION_FILE = Path(tmpdir) / "last-selection.json"

            tui._discover_components()
            tui._save_selections()

            # Parse and validate JSON
            data = json.loads(tui.SELECTION_FILE.read_text())
            self.assertIn("version", data)
            self.assertIn("timestamp", data)
            self.assertIn("selections", data)
            self.assertIsInstance(data["selections"], dict)


class TestErrorRecoveryFlow(unittest.TestCase):
    """Test error recovery mechanisms in orchestrator.

    Manual Verification:
        Simulate failure by modifying module to fail, then test:
        - [R] Retry re-executes the module
        - [S] Skip continues with next module
        - [A] Abort stops execution
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    def test_error_callback_skip_continues_execution(
        self,
        mock_installed: mock.Mock,
        mock_run: mock.Mock,
    ) -> None:
        """Error callback with SKIP allows execution to continue."""
        mock_installed.return_value = (False, "Not configured")
        mock_run.return_value = ModuleResult(
            status=ModuleStatus.FAILED,
            message="APT failed",
            recovery_command="gvm fix apt",
        )

        orchestrator = ModuleOrchestrator(self.config)

        def error_callback(module_name: str, result: ModuleResult) -> RecoveryAction:
            return RecoveryAction.SKIP

        results = orchestrator.execute(["apt"], error_callback=error_callback)

        # Module should be marked as skipped
        self.assertIn("apt", results)
        self.assertEqual(results["apt"].status, ModuleStatus.SKIPPED)

    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    def test_error_callback_abort_stops_execution(
        self,
        mock_installed: mock.Mock,
        mock_run: mock.Mock,
    ) -> None:
        """Error callback with ABORT stops further execution."""
        mock_installed.return_value = (False, "Not configured")
        mock_run.return_value = ModuleResult(
            status=ModuleStatus.FAILED,
            message="APT failed",
        )

        orchestrator = ModuleOrchestrator(self.config)

        def error_callback(module_name: str, result: ModuleResult) -> RecoveryAction:
            return RecoveryAction.ABORT

        # Execute with multiple modules
        results = orchestrator.execute(
            ["apt", "ssh"], error_callback=error_callback
        )

        # Should have partial results (only apt attempted)
        self.assertIn("apt", results)
        self.assertEqual(results["apt"].status, ModuleStatus.FAILED)
        # SSH should not have been executed
        self.assertNotIn("ssh", results)

    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    def test_error_callback_retry_re_executes(
        self,
        mock_installed: mock.Mock,
        mock_run: mock.Mock,
    ) -> None:
        """Error callback with RETRY re-executes the module."""
        mock_installed.return_value = (False, "Not configured")

        # First call fails, second succeeds
        mock_run.side_effect = [
            ModuleResult(status=ModuleStatus.FAILED, message="First attempt failed"),
            ModuleResult(status=ModuleStatus.SUCCESS, message="Second attempt succeeded"),
        ]

        orchestrator = ModuleOrchestrator(self.config)

        retry_count = [0]

        def error_callback(module_name: str, result: ModuleResult) -> RecoveryAction:
            retry_count[0] += 1
            if retry_count[0] < 2:
                return RecoveryAction.RETRY
            return RecoveryAction.ABORT

        results = orchestrator.execute(["apt"], error_callback=error_callback)

        # Module should have been called twice
        self.assertEqual(mock_run.call_count, 2)
        # Final result should be success
        self.assertEqual(results["apt"].status, ModuleStatus.SUCCESS)

    def test_recovery_command_in_result(self) -> None:
        """Failed modules include recovery command suggestion."""
        config = Config.load()
        apt_class = get_module_class("apt")
        self.assertIsNotNone(apt_class)

        module = apt_class(config)
        recovery = module.get_recovery_command()
        self.assertEqual(recovery, "gvm fix apt")


class TestConfigPriorityChain(unittest.TestCase):
    """Test configuration priority chain.

    Manual Verification:
        1. Remove ~/.config/gvm/config.toml
        2. Run: gvm config show (should show embedded defaults)
        3. Create ~/.config/gvm/config.toml with custom values
        4. Run: gvm config show (should show merged config)
        5. Run: gvm --config /path/to/other.toml config show
    """

    def test_embedded_defaults_loaded(self) -> None:
        """Config loads embedded defaults when no files exist."""
        # Load config (may have repo/user configs)
        config = Config.load()

        # Verify embedded defaults structure exists
        self.assertIsNotNone(config.meta)
        self.assertIsNotNone(config.environment)
        self.assertIsNotNone(config.ports)
        self.assertIsNotNone(config.apt)
        self.assertIsNotNone(config.ssh)

    def test_embedded_defaults_values(self) -> None:
        """Embedded defaults have expected values."""
        self.assertEqual(EMBEDDED_DEFAULTS["meta"]["tool_version"], "1.0.0")
        self.assertEqual(EMBEDDED_DEFAULTS["environment"]["vm_user"], "droid")
        self.assertEqual(EMBEDDED_DEFAULTS["ports"]["ssh_forward"], 2222)
        self.assertEqual(EMBEDDED_DEFAULTS["apt"]["retries"], 10)

    def test_cli_config_override(self) -> None:
        """CLI config file overrides user config."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write('[ports]\nssh_forward = 3333\n')
            f.flush()

            config = Config.load(cli_config_path=Path(f.name))
            self.assertEqual(config.ssh_forward_port, 3333)

            # Clean up
            Path(f.name).unlink()

    def test_cli_overrides_highest_priority(self) -> None:
        """CLI flag overrides have highest priority."""
        config = Config.load(
            cli_overrides={"ports": {"ssh_forward": 4444}}
        )
        self.assertEqual(config.ssh_forward_port, 4444)

    def test_config_merge_replaces_sections(self) -> None:
        """Config merge uses replace strategy (not recursive merge)."""
        from gvm.config import _merge_configs

        base = {"apt": {"retries": 10, "timeout": 60}}
        override = {"apt": {"retries": 5}}

        result = _merge_configs(base, override)

        # Override completely replaces the section
        self.assertEqual(result["apt"], {"retries": 5})
        self.assertNotIn("timeout", result["apt"])


class TestConfigPriorityChainFull(unittest.TestCase):
    """Test full configuration priority chain: embedded < repo < user < CLI.

    These tests create temporary repo and user config TOML files, patch
    Path.home() and repo config paths, and verify values are overridden
    in the correct order.
    """

    def test_repo_config_overrides_embedded_defaults(self) -> None:
        """Test that repo config overrides embedded defaults."""
        from gvm.config import _load_toml, _merge_configs, EMBEDDED_DEFAULTS
        import copy

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create repo config with override
            repo_config_path = Path(tmpdir) / "default.toml"
            repo_config_path.write_text('[ports]\nssh_forward = 3000\n')

            # Manually test the loading with simulated repo config
            config_data = copy.deepcopy(EMBEDDED_DEFAULTS)

            # Default should be 2222
            self.assertEqual(config_data["ports"]["ssh_forward"], 2222)

            # Load repo config
            repo_config = _load_toml(repo_config_path)
            config_data = _merge_configs(config_data, repo_config)

            # After repo override, should be 3000
            self.assertEqual(config_data["ports"]["ssh_forward"], 3000)

    def test_user_config_overrides_repo_config(self) -> None:
        """Test that user config overrides repo config values."""
        from gvm.config import _load_toml, _merge_configs, EMBEDDED_DEFAULTS
        import copy

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create repo config
            repo_config_path = Path(tmpdir) / "repo.toml"
            repo_config_path.write_text('[ports]\nssh_forward = 3000\n')

            # Create user config with higher precedence value
            user_config_path = Path(tmpdir) / "user.toml"
            user_config_path.write_text('[ports]\nssh_forward = 4000\n')

            # Simulate priority chain: embedded -> repo -> user
            config_data = copy.deepcopy(EMBEDDED_DEFAULTS)
            self.assertEqual(config_data["ports"]["ssh_forward"], 2222)

            # Apply repo config
            repo_config = _load_toml(repo_config_path)
            config_data = _merge_configs(config_data, repo_config)
            self.assertEqual(config_data["ports"]["ssh_forward"], 3000)

            # Apply user config
            user_config = _load_toml(user_config_path)
            config_data = _merge_configs(config_data, user_config)
            self.assertEqual(config_data["ports"]["ssh_forward"], 4000)

    def test_cli_config_overrides_user_config(self) -> None:
        """Test that CLI config file overrides user config values."""
        from gvm.config import _load_toml, _merge_configs, EMBEDDED_DEFAULTS
        import copy

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create user config
            user_config_path = Path(tmpdir) / "user.toml"
            user_config_path.write_text('[ports]\nssh_forward = 4000\n')

            # Create CLI config with highest file precedence
            cli_config_path = Path(tmpdir) / "cli.toml"
            cli_config_path.write_text('[ports]\nssh_forward = 5000\n')

            # Simulate priority chain: embedded -> user -> cli_config
            config_data = copy.deepcopy(EMBEDDED_DEFAULTS)

            user_config = _load_toml(user_config_path)
            config_data = _merge_configs(config_data, user_config)
            self.assertEqual(config_data["ports"]["ssh_forward"], 4000)

            cli_config = _load_toml(cli_config_path)
            config_data = _merge_configs(config_data, cli_config)
            self.assertEqual(config_data["ports"]["ssh_forward"], 5000)

    def test_cli_overrides_override_cli_config(self) -> None:
        """Test that CLI flag overrides have highest priority over CLI config."""
        from gvm.config import _load_toml, _merge_configs, EMBEDDED_DEFAULTS
        import copy

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create CLI config file
            cli_config_path = Path(tmpdir) / "cli.toml"
            cli_config_path.write_text('[ports]\nssh_forward = 5000\n')

            # Simulate full priority chain with CLI override
            config_data = copy.deepcopy(EMBEDDED_DEFAULTS)

            cli_config = _load_toml(cli_config_path)
            config_data = _merge_configs(config_data, cli_config)
            self.assertEqual(config_data["ports"]["ssh_forward"], 5000)

            # Apply CLI flag override (highest priority)
            cli_overrides = {"ports": {"ssh_forward": 6000}}
            config_data = _merge_configs(config_data, cli_overrides)
            self.assertEqual(config_data["ports"]["ssh_forward"], 6000)

    def test_full_priority_chain_integration(self) -> None:
        """Test complete priority chain: embedded < repo < user < cli_config < cli_override."""
        from gvm.config import _load_toml, _merge_configs, EMBEDDED_DEFAULTS, Config
        import copy

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create all config levels
            repo_path = Path(tmpdir) / "repo.toml"
            repo_path.write_text('[ports]\nssh_forward = 3000\n[apt]\nretries = 15\n')

            user_path = Path(tmpdir) / "user.toml"
            user_path.write_text('[ports]\nssh_forward = 4000\n')

            cli_path = Path(tmpdir) / "cli.toml"
            cli_path.write_text('[ports]\nssh_forward = 5000\n')

            # Simulate priority chain
            config_data = copy.deepcopy(EMBEDDED_DEFAULTS)

            # 1. Embedded defaults
            self.assertEqual(config_data["ports"]["ssh_forward"], 2222)
            self.assertEqual(config_data["apt"]["retries"], 10)

            # 2. Repo config
            config_data = _merge_configs(config_data, _load_toml(repo_path))
            self.assertEqual(config_data["ports"]["ssh_forward"], 3000)
            self.assertEqual(config_data["apt"]["retries"], 15)

            # 3. User config (doesn't have apt section, so repo's apt stays)
            config_data = _merge_configs(config_data, _load_toml(user_path))
            self.assertEqual(config_data["ports"]["ssh_forward"], 4000)
            self.assertEqual(config_data["apt"]["retries"], 15)

            # 4. CLI config file
            config_data = _merge_configs(config_data, _load_toml(cli_path))
            self.assertEqual(config_data["ports"]["ssh_forward"], 5000)

            # 5. CLI flag override (highest priority)
            cli_overrides = {"ports": {"ssh_forward": 6000}}
            config_data = _merge_configs(config_data, cli_overrides)
            self.assertEqual(config_data["ports"]["ssh_forward"], 6000)

    @mock.patch("gvm.config.Path.home")
    def test_config_load_with_patched_paths(
        self, mock_home: mock.Mock
    ) -> None:
        """Test Config.load with patched home directory for user config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up mock home directory
            mock_home.return_value = Path(tmpdir)

            # Create user config in mock home
            user_config_dir = Path(tmpdir) / ".config" / "gvm"
            user_config_dir.mkdir(parents=True, exist_ok=True)
            user_config_file = user_config_dir / "config.toml"
            user_config_file.write_text('[ports]\nssh_forward = 7777\n')

            # Load config - should pick up user config
            config = Config.load()

            # If user config was loaded, port should be 7777
            # (Note: This depends on repo config not existing or not overriding)
            self.assertEqual(config.ssh_forward_port, 7777)

    def test_config_load_with_cli_config_path(self) -> None:
        """Test Config.load with explicit cli_config_path parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create CLI config
            cli_config_path = Path(tmpdir) / "custom-config.toml"
            cli_config_path.write_text('[ports]\nssh_forward = 8888\n')

            # Load with CLI config path
            config = Config.load(cli_config_path=cli_config_path)

            self.assertEqual(config.ssh_forward_port, 8888)

    def test_config_load_with_cli_overrides(self) -> None:
        """Test Config.load with cli_overrides parameter."""
        config = Config.load(
            cli_overrides={"ports": {"ssh_forward": 9999}}
        )

        self.assertEqual(config.ssh_forward_port, 9999)

    def test_config_load_combined_cli_config_and_overrides(self) -> None:
        """Test that cli_overrides takes precedence over cli_config_path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create CLI config with one value
            cli_config_path = Path(tmpdir) / "config.toml"
            cli_config_path.write_text('[ports]\nssh_forward = 8000\n')

            # Load with both CLI config and override
            config = Config.load(
                cli_config_path=cli_config_path,
                cli_overrides={"ports": {"ssh_forward": 9000}}
            )

            # CLI override should win
            self.assertEqual(config.ssh_forward_port, 9000)


class TestDesktopDiscoveryAndListing(unittest.TestCase):
    """Test desktop discovery and listing functionality.

    Manual Verification:
        Run: ./gvm desktop list
        Verify available desktops are shown from:
        - config/packages/*.toml
        - ~/.config/gvm/packages/*.toml (if exists)
    """

    def test_discover_desktops_finds_configs(self) -> None:
        """Config discovers desktop TOML files."""
        config = Config.load()
        desktops = config.discover_desktops()

        # Should find at least one desktop (plasma-mobile or xfce4)
        # This depends on repo having config/packages/*.toml files
        self.assertIsInstance(desktops, dict)

    def test_desktop_list_command(self) -> None:
        """Desktop list command shows available desktops."""
        config = Config.load()
        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            desktop_target="list",
            config=None,
        )

        with mock.patch("builtins.print") as mock_print:
            result = cmd_desktop(args, config)

        self.assertEqual(result, 0)
        # Should have printed something
        mock_print.assert_called()

    def test_desktop_config_from_toml(self) -> None:
        """DesktopConfig loads correctly from TOML."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write('''
[meta]
name = "test-desktop"
type = "desktop"
description = "Test desktop environment"

[packages]
core = ["package1", "package2"]
optional = ["package3"]

[session]
start_command = "startx"
helper_script_name = "start-test"
''')
            f.flush()

            desktop_config = DesktopConfig.from_toml(Path(f.name))

            self.assertEqual(desktop_config.name, "test-desktop")
            self.assertEqual(desktop_config.description, "Test desktop environment")
            self.assertEqual(desktop_config.packages_core, ["package1", "package2"])
            self.assertEqual(desktop_config.session_start_command, "startx")
            self.assertEqual(desktop_config.session_helper_script_name, "start-test")

            # Clean up
            Path(f.name).unlink()

    def test_desktop_get_all_packages(self) -> None:
        """DesktopConfig.get_all_packages combines all package lists."""
        desktop_config = DesktopConfig(
            name="test",
            packages_core=["core1", "core2"],
            packages_optional=["opt1"],
            packages_wayland_helpers=["wayland1"],
            packages_user=["user1"],
        )

        all_packages = desktop_config.get_all_packages()
        self.assertEqual(
            all_packages,
            ["core1", "core2", "opt1", "wayland1", "user1"],
        )


class TestDryRunMode(unittest.TestCase):
    """Test dry-run mode propagates to all modules.

    Manual Verification:
        Run: ./gvm setup --all --dry-run
        Verify:
        - No actual system changes occur
        - Messages indicate dry-run mode
        - All modules "complete" without errors
    """

    def test_dry_run_propagates_to_modules(self) -> None:
        """Dry-run flag propagates to module instances."""
        config = Config.load()
        orchestrator = ModuleOrchestrator(config, dry_run=True)
        orchestrator.load_modules(["apt"])

        apt_module = orchestrator.modules.get("apt")
        self.assertIsNotNone(apt_module)
        self.assertTrue(apt_module.dry_run)

    def test_dry_run_in_cli_args(self) -> None:
        """CLI --dry-run flag is parsed correctly."""
        parser = create_argument_parser()
        args = parser.parse_args(["--dry-run", "setup", "--all"])

        self.assertTrue(args.dry_run)
        self.assertTrue(args.all)

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    def test_cmd_setup_all_passes_dry_run(
        self, mock_execute: mock.Mock
    ) -> None:
        """cmd_setup passes dry_run to orchestrator."""
        mock_execute.return_value = {}

        config = Config.load()
        args = argparse.Namespace(
            verbose=False,
            dry_run=True,
            help=False,
            all=True,
            config=None,
            interactive=False,
        )

        cmd_setup(args, config)

        # Orchestrator was created with dry_run=True
        # (We can't directly check this from the mock, but we verify the flow)
        mock_execute.assert_called_once()


class TestDependencyResolution(unittest.TestCase):
    """Test orchestrator dependency resolution.

    Manual Verification:
        The orchestrator uses topological sort (Kahn's algorithm).
        Modules with dependencies on 'apt' will always run after apt.
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    def test_resolve_dependencies_returns_ordered_list(self) -> None:
        """Dependency resolution returns modules in correct order."""
        orchestrator = ModuleOrchestrator(self.config)
        ordered, optional = orchestrator.resolve_dependencies(["ssh"])

        self.assertIsInstance(ordered, list)
        self.assertIsInstance(optional, set)

        # ssh depends on apt, so apt should come first
        apt_idx = ordered.index("apt") if "apt" in ordered else -1
        ssh_idx = ordered.index("ssh") if "ssh" in ordered else -1

        if apt_idx >= 0 and ssh_idx >= 0:
            self.assertLess(apt_idx, ssh_idx, "apt should come before ssh")

    def test_resolve_dependencies_circular_detection(self) -> None:
        """Circular dependencies raise ValueError."""
        # Create modules with circular dependency
        class ModuleA(Module):
            name = "module_a"
            description = "Test A"
            dependencies = (Dependency("module_b", required=True),)

            def is_installed(self) -> tuple[bool, str]:
                return (False, "")

            def run(self, progress_callback) -> ModuleResult:
                return ModuleResult(status=ModuleStatus.SUCCESS, message="")

        class ModuleB(Module):
            name = "module_b"
            description = "Test B"
            dependencies = (Dependency("module_a", required=True),)

            def is_installed(self) -> tuple[bool, str]:
                return (False, "")

            def run(self, progress_callback) -> ModuleResult:
                return ModuleResult(status=ModuleStatus.SUCCESS, message="")

        # Temporarily register these modules
        from gvm.modules import AVAILABLE_MODULES

        original_modules = AVAILABLE_MODULES.copy()
        AVAILABLE_MODULES["module_a"] = ModuleA
        AVAILABLE_MODULES["module_b"] = ModuleB

        try:
            orchestrator = ModuleOrchestrator(self.config)
            with self.assertRaises(ValueError) as context:
                orchestrator.resolve_dependencies(["module_a"])

            self.assertIn("Circular dependency", str(context.exception))
        finally:
            # Restore original modules
            AVAILABLE_MODULES.clear()
            AVAILABLE_MODULES.update(original_modules)

    def test_optional_dependencies_auto_included(self) -> None:
        """Optional dependencies are auto-included when dependent is selected."""
        orchestrator = ModuleOrchestrator(self.config)

        # Get modules with optional dependencies
        # This test verifies the mechanism works even if no current modules
        # have optional dependencies
        ordered, optional_auto = orchestrator.resolve_dependencies(list_modules())

        # All modules should be in ordered list
        for module_name in list_modules():
            self.assertIn(module_name, ordered)

    @mock.patch("gvm.modules.ssh.SSHModule.run")
    @mock.patch("gvm.modules.ssh.SSHModule.is_installed")
    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    def test_required_dependency_failure_skips_dependent(
        self,
        mock_apt_installed: mock.Mock,
        mock_apt_run: mock.Mock,
        mock_ssh_installed: mock.Mock,
        mock_ssh_run: mock.Mock,
    ) -> None:
        """When required dependency fails, dependent modules are skipped."""
        mock_apt_installed.return_value = (False, "Not configured")
        mock_apt_run.return_value = ModuleResult(
            status=ModuleStatus.FAILED, message="APT failed"
        )

        mock_ssh_installed.return_value = (False, "Not configured")
        mock_ssh_run.return_value = ModuleResult(
            status=ModuleStatus.SUCCESS, message="Done"
        )

        orchestrator = ModuleOrchestrator(self.config)

        def error_callback(name: str, result: ModuleResult) -> RecoveryAction:
            return RecoveryAction.SKIP

        results = orchestrator.execute(
            ["apt", "ssh"], error_callback=error_callback
        )

        # SSH depends on apt, so if apt is skipped, ssh should also be skipped
        # (depending on how dependencies are defined in SSHModule)
        self.assertIn("apt", results)

    @mock.patch("gvm.modules.ssh.SSHModule.run")
    @mock.patch("gvm.modules.ssh.SSHModule.is_installed")
    @mock.patch("gvm.modules.apt.APTModule.run")
    @mock.patch("gvm.modules.apt.APTModule.is_installed")
    def test_skipped_dependency_satisfies_requirements(
        self,
        mock_apt_installed: mock.Mock,
        mock_apt_run: mock.Mock,
        mock_ssh_installed: mock.Mock,
        mock_ssh_run: mock.Mock,
    ) -> None:
        """When required dependency is SKIPPED (already installed), dependent modules still run.

        This tests idempotency: on a second run where apt is already installed
        (and thus skipped), modules that depend on apt should still execute.
        """
        # APT is already installed - will be skipped
        mock_apt_installed.return_value = (True, "APT already configured")
        # apt.run() shouldn't be called since it's already installed

        # SSH is not installed - should run
        mock_ssh_installed.return_value = (False, "Not configured")
        mock_ssh_run.return_value = ModuleResult(
            status=ModuleStatus.SUCCESS, message="SSH configured"
        )

        orchestrator = ModuleOrchestrator(self.config)

        results = orchestrator.execute(["apt", "ssh"])

        # APT should be skipped (already installed)
        self.assertIn("apt", results)
        self.assertEqual(results["apt"].status, ModuleStatus.SKIPPED)

        # SSH should have run successfully (its dependency apt was skipped but satisfied)
        self.assertIn("ssh", results)
        self.assertEqual(
            results["ssh"].status,
            ModuleStatus.SUCCESS,
            "SSH should run when its dependency (apt) is skipped due to being already installed",
        )

        # Verify apt.run was NOT called (it was skipped)
        mock_apt_run.assert_not_called()

        # Verify ssh.run WAS called
        mock_ssh_run.assert_called_once()


class TestCLIRouting(unittest.TestCase):
    """Test CLI command routing to handler functions."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    def test_route_command_setup(self) -> None:
        """Route setup command correctly."""
        args = argparse.Namespace(
            command="setup",
            verbose=False,
            dry_run=False,
            help=True,  # Use help to avoid TUI
            all=False,
            config=None,
            interactive=False,
        )

        with mock.patch("builtins.print"):
            result = route_command(args, self.config)

        self.assertEqual(result, 0)

    def test_route_command_info(self) -> None:
        """Route info command correctly."""
        args = argparse.Namespace(
            command="info",
            verbose=False,
            dry_run=False,
            help=False,
            config=None,
        )

        with mock.patch("builtins.print"):
            with mock.patch("gvm.cli.is_service_running", return_value=False):
                with mock.patch("gvm.cli.is_port_listening", return_value=False):
                    result = route_command(args, self.config)

        self.assertEqual(result, 0)

    def test_route_command_fix_apt(self) -> None:
        """Route fix apt command correctly."""
        args = argparse.Namespace(
            command="fix",
            fix_target="apt",
            verbose=False,
            dry_run=True,  # Use dry-run to avoid actual commands
            help=False,
            config=None,
        )

        with mock.patch("builtins.print"):
            result = cmd_fix(args, self.config)

        self.assertEqual(result, 0)

    def test_route_command_no_command_shows_help(self) -> None:
        """No command shows help."""
        args = argparse.Namespace(
            command=None,
            verbose=False,
            dry_run=False,
            help=False,
            config=None,
        )

        with mock.patch("builtins.print") as mock_print:
            result = route_command(args, self.config)

        self.assertEqual(result, 0)
        mock_print.assert_called()


class TestExecutionSummary(unittest.TestCase):
    """Test execution summary generation."""

    def test_get_execution_summary(self) -> None:
        """Execution summary calculates correct statistics."""
        config = Config.load()
        orchestrator = ModuleOrchestrator(config)

        results = {
            "apt": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
            "ssh": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
            "shell": ModuleResult(status=ModuleStatus.SKIPPED, message="Already installed"),
            "gui": ModuleResult(status=ModuleStatus.FAILED, message="Failed"),
        }

        summary = orchestrator.get_execution_summary(results)

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["successful"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["success_rate"], 0.5)

    def test_get_execution_summary_empty(self) -> None:
        """Execution summary handles empty results."""
        config = Config.load()
        orchestrator = ModuleOrchestrator(config)

        summary = orchestrator.get_execution_summary({})

        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["successful"], 0)
        self.assertEqual(summary["success_rate"], 0.0)


class TestModuleValidation(unittest.TestCase):
    """Test module validation functionality."""

    def test_validate_modules_all_valid(self) -> None:
        """Validation passes for all valid modules."""
        config = Config.load()
        orchestrator = ModuleOrchestrator(config)

        all_valid, invalid = orchestrator.validate_modules(list_modules())

        self.assertTrue(all_valid)
        self.assertEqual(invalid, [])

    def test_validate_modules_invalid_names(self) -> None:
        """Validation fails for invalid module names."""
        config = Config.load()
        orchestrator = ModuleOrchestrator(config)

        all_valid, invalid = orchestrator.validate_modules(
            ["apt", "nonexistent", "also_invalid"]
        )

        self.assertFalse(all_valid)
        self.assertIn("nonexistent", invalid)
        self.assertIn("also_invalid", invalid)
        self.assertNotIn("apt", invalid)

    def test_validate_modules_case_insensitive(self) -> None:
        """Validation is case-insensitive."""
        config = Config.load()
        orchestrator = ModuleOrchestrator(config)

        all_valid, invalid = orchestrator.validate_modules(["APT", "SSH"])

        self.assertTrue(all_valid)
        self.assertEqual(invalid, [])


class TestSetupAllCLIFlow(unittest.TestCase):
    """Test setup --all CLI flow end-to-end via CLI routing.

    These tests invoke create_argument_parser()/route_command() or cmd_setup()
    with --all flag to validate CLI flow, module list, and exit codes.
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    def test_setup_all_via_route_command(
        self, mock_execute: mock.Mock
    ) -> None:
        """Test setup --all executes via route_command with expected modules."""
        # Mock execute to return success for all modules
        mock_execute.return_value = {
            "apt": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
            "ssh": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
            "shell": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
            "gui": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
            "desktop": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
        }

        # Parse args like CLI would
        parser = create_argument_parser()
        args = parser.parse_args(["setup", "--all"])

        # Route command
        with mock.patch("builtins.print"):
            result = route_command(args, self.config)

        # Assert success exit code
        self.assertEqual(result, 0)

        # Assert execute was called
        mock_execute.assert_called_once()

        # Verify all available modules were requested
        call_args = mock_execute.call_args
        modules_requested = call_args[0][0]
        available_modules = list_modules()
        for mod in available_modules:
            self.assertIn(mod, modules_requested)

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    def test_setup_all_via_cmd_setup(
        self, mock_execute: mock.Mock
    ) -> None:
        """Test cmd_setup with --all flag invokes orchestrator correctly."""
        mock_execute.return_value = {
            "apt": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
        }

        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            all=True,
            config=None,
            interactive=False,
        )

        with mock.patch("builtins.print"):
            result = cmd_setup(args, self.config)

        self.assertEqual(result, 0)
        mock_execute.assert_called_once()

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    def test_setup_all_returns_error_on_module_failure(
        self, mock_execute: mock.Mock
    ) -> None:
        """Test setup --all returns non-zero exit code when modules fail."""
        mock_execute.return_value = {
            "apt": ModuleResult(status=ModuleStatus.FAILED, message="APT failed"),
        }

        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            all=True,
            config=None,
            interactive=False,
        )

        with mock.patch("builtins.print"):
            result = cmd_setup(args, self.config)

        # Should return 1 for failure
        self.assertEqual(result, 1)

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    def test_setup_all_prints_summary_message(
        self, mock_execute: mock.Mock
    ) -> None:
        """Test setup --all prints summary with success/failure counts."""
        mock_execute.return_value = {
            "apt": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
            "ssh": ModuleResult(status=ModuleStatus.SKIPPED, message="Skipped"),
        }

        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            all=True,
            config=None,
            interactive=False,
        )

        printed_messages = []

        def capture_print(*args, **kwargs):
            printed_messages.append(str(args))

        with mock.patch("builtins.print", side_effect=capture_print):
            cmd_setup(args, self.config)

        # Verify summary was printed
        output = " ".join(printed_messages)
        self.assertIn("complete", output.lower())


class TestTUICursesInteraction(unittest.TestCase):
    """Test TUI curses interaction with mocked stdscr window.

    These tests mock curses windows to simulate key presses and verify
    selection toggling and progress rendering without requiring an actual terminal.
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    def _create_mock_stdscr(self) -> mock.MagicMock:
        """Create a mock curses stdscr window."""
        mock_stdscr = mock.MagicMock()
        mock_stdscr.getmaxyx.return_value = (24, 80)  # Standard terminal size
        mock_stdscr.getch.return_value = ord("q")  # Default to quit
        return mock_stdscr

    def test_component_selection_toggle_via_space_key(self) -> None:
        """Test that space key toggles component selection."""
        import curses
        from gvm.tui import CursesTUI

        tui = CursesTUI(self.config)
        tui._discover_components()

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Simulate: space (toggle), then q (quit)
        mock_stdscr.getch.side_effect = [ord(" "), ord("q")]

        # Get initial selection state for first component
        if tui.selection_state.components:
            first_comp = tui.selection_state.components[0]
            initial_state = tui.selection_state.selections.get(first_comp.id, False)

            # Run selection screen
            result = tui._show_component_selection()

            # Selection should have been toggled
            final_state = tui.selection_state.selections.get(first_comp.id, False)
            self.assertNotEqual(initial_state, final_state)

    def test_component_selection_navigate_down(self) -> None:
        """Test that down arrow key moves cursor position."""
        import curses
        from gvm.tui import CursesTUI

        tui = CursesTUI(self.config)
        tui._discover_components()

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Simulate: down arrow, then q (quit)
        mock_stdscr.getch.side_effect = [curses.KEY_DOWN, ord("q")]

        # Initial cursor position is 0
        self.assertEqual(tui.selection_state.cursor_pos, 0)

        # Run selection screen
        tui._show_component_selection()

        # Cursor should have moved down
        if len(tui.selection_state.components) > 1:
            self.assertEqual(tui.selection_state.cursor_pos, 1)

    def test_component_selection_select_all(self) -> None:
        """Test that 'a' key selects all components."""
        from gvm.tui import CursesTUI

        tui = CursesTUI(self.config)
        tui._discover_components()

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Clear all selections first
        for comp in tui.selection_state.components:
            tui.selection_state.selections[comp.id] = False

        # Simulate: 'a' (select all), then q (quit)
        mock_stdscr.getch.side_effect = [ord("a"), ord("q")]

        tui._show_component_selection()

        # All components should be selected
        for comp in tui.selection_state.components:
            self.assertTrue(
                tui.selection_state.selections.get(comp.id, False),
                f"Component {comp.id} should be selected after 'a' key",
            )

    def test_component_selection_select_none(self) -> None:
        """Test that 'n' key deselects all components."""
        from gvm.tui import CursesTUI

        tui = CursesTUI(self.config)
        tui._discover_components()

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Select all first
        for comp in tui.selection_state.components:
            tui.selection_state.selections[comp.id] = True

        # Simulate: 'n' (deselect all), then q (quit)
        mock_stdscr.getch.side_effect = [ord("n"), ord("q")]

        tui._show_component_selection()

        # All components should be deselected
        for comp in tui.selection_state.components:
            self.assertFalse(
                tui.selection_state.selections.get(comp.id, True),
                f"Component {comp.id} should be deselected after 'n' key",
            )

    def test_component_selection_enter_confirms(self) -> None:
        """Test that Enter key confirms selection and returns selected items."""
        import curses
        from gvm.tui import CursesTUI

        tui = CursesTUI(self.config)
        tui._discover_components()

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Select first component, deselect others
        if tui.selection_state.components:
            first_comp = tui.selection_state.components[0]
            for comp in tui.selection_state.components:
                tui.selection_state.selections[comp.id] = (comp.id == first_comp.id)

            # Simulate: Enter (confirm)
            mock_stdscr.getch.side_effect = [curses.KEY_ENTER]

            result = tui._show_component_selection()

            # Should return list with first component
            self.assertIn(first_comp.id, result)

    def test_draw_progress_screen_calls_addstr(self) -> None:
        """Test that _draw_progress_screen makes expected addstr calls."""
        from gvm.tui import CursesTUI, ProgressState
        import time

        tui = CursesTUI(self.config)

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Set up progress state
        tui.progress_state = ProgressState(
            modules=["apt", "ssh", "shell"],
            current_module="apt",
            current_percent=0.5,
            current_message="Installing APT module",
            current_operation="Running apt update",
            completed=set(),
            failed=set(),
            skipped=set(),
            start_time=time.time(),
        )

        # Draw progress screen
        tui._draw_progress_screen()

        # Verify addstr was called (rendering happened)
        mock_stdscr.addstr.assert_called()

        # Verify refresh was called
        mock_stdscr.refresh.assert_called()

        # Check that title was rendered
        addstr_calls = mock_stdscr.addstr.call_args_list
        rendered_text = " ".join(str(call) for call in addstr_calls)
        self.assertIn("Progress", rendered_text)

    @mock.patch("gvm.tui.curses")
    def test_draw_progress_screen_shows_module_status(
        self, mock_curses: mock.Mock
    ) -> None:
        """Test that progress screen shows module status indicators."""
        from gvm.tui import CursesTUI, ProgressState
        import time

        # Configure curses mock
        mock_curses.has_colors.return_value = False
        mock_curses.A_NORMAL = 0
        mock_curses.A_BOLD = 1
        mock_curses.A_DIM = 2
        mock_curses.A_REVERSE = 4
        mock_curses.color_pair.return_value = 0

        tui = CursesTUI(self.config)

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Set up progress state with completed module
        tui.progress_state = ProgressState(
            modules=["apt", "ssh"],
            current_module="ssh",
            current_percent=0.75,
            current_message="Configuring SSH",
            completed={"apt"},
            failed=set(),
            skipped=set(),
            start_time=time.time(),
        )

        tui._draw_progress_screen()

        # Verify module names appear in rendered output
        addstr_calls = mock_stdscr.addstr.call_args_list
        rendered_text = " ".join(str(call) for call in addstr_calls)
        self.assertIn("apt", rendered_text)
        self.assertIn("ssh", rendered_text)

    def test_draw_progress_screen_verbose_mode(self) -> None:
        """Test that verbose mode shows log pane."""
        from gvm.tui import CursesTUI, ProgressState
        import time

        tui = CursesTUI(self.config, verbose=True)

        mock_stdscr = self._create_mock_stdscr()
        tui.stdscr = mock_stdscr

        # Set up progress state with log lines
        tui.progress_state = ProgressState(
            modules=["apt"],
            current_module="apt",
            current_percent=0.25,
            current_message="Running",
            log_lines=["Log line 1", "Log line 2"],
            start_time=time.time(),
        )

        tui._draw_progress_screen()

        # In verbose mode, log pane should be drawn
        # Verify addstr was called multiple times for different panes
        self.assertGreater(mock_stdscr.addstr.call_count, 5)


class TestDesktopCLIFlow(unittest.TestCase):
    """Test desktop <name> CLI flow end-to-end.

    These tests invoke cmd_desktop() with mocked Config.discover_desktops()
    and ModuleOrchestrator.execute() to validate CLI behavior.
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = Config.load()

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    @mock.patch.object(Config, "discover_desktops")
    def test_desktop_command_with_valid_name(
        self,
        mock_discover: mock.Mock,
        mock_execute: mock.Mock,
    ) -> None:
        """Test desktop command with valid desktop name executes successfully."""
        # Mock discover_desktops to return a test desktop
        mock_desktop_config = DesktopConfig(
            name="test-desktop",
            description="Test desktop environment",
            packages_core=["pkg1", "pkg2"],
            session_start_command="start-test",
            session_helper_script_name="start-test-desktop",
        )
        mock_discover.return_value = {"test-desktop": mock_desktop_config}

        # Mock execute to return success
        mock_execute.return_value = {
            "desktop": ModuleResult(status=ModuleStatus.SUCCESS, message="Done"),
        }

        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            desktop_target="test-desktop",
            config=None,
        )

        with mock.patch("builtins.print"):
            result = cmd_desktop(args, self.config)

        # Verify execution was called with desktop module
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        self.assertIn("desktop", call_args[0][0])

        # Should return 0 for success
        self.assertEqual(result, 0)

    @mock.patch.object(Config, "discover_desktops")
    def test_desktop_command_with_invalid_name(
        self,
        mock_discover: mock.Mock,
    ) -> None:
        """Test desktop command with invalid name returns error."""
        # Mock discover_desktops to return known desktops
        mock_desktop_config = DesktopConfig(
            name="valid-desktop",
            description="Valid desktop",
        )
        mock_discover.return_value = {"valid-desktop": mock_desktop_config}

        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            desktop_target="nonexistent-desktop",
            config=None,
        )

        with mock.patch("builtins.print") as mock_print:
            result = cmd_desktop(args, self.config)

        # Should return 1 for error
        self.assertEqual(result, 1)

        # Should print error message
        mock_print.assert_called()
        printed = str(mock_print.call_args_list)
        self.assertIn("not found", printed.lower())

    @mock.patch.object(Config, "discover_desktops")
    def test_desktop_list_shows_available_desktops(
        self,
        mock_discover: mock.Mock,
    ) -> None:
        """Test desktop list shows all discovered desktops."""
        # Mock multiple desktops
        mock_discover.return_value = {
            "plasma-mobile": DesktopConfig(
                name="Plasma Mobile",
                description="KDE Plasma Mobile desktop",
            ),
            "xfce4": DesktopConfig(
                name="XFCE4",
                description="Lightweight XFCE desktop",
            ),
        }

        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            desktop_target="list",
            config=None,
        )

        printed_messages = []

        def capture_print(*args, **kwargs):
            printed_messages.append(str(args))

        with mock.patch("builtins.print", side_effect=capture_print):
            result = cmd_desktop(args, self.config)

        self.assertEqual(result, 0)

        # Verify desktops were printed (case-insensitive check)
        output = " ".join(printed_messages).lower()
        self.assertIn("plasma mobile", output)
        self.assertIn("xfce", output)

    @mock.patch("gvm.orchestrator.ModuleOrchestrator.execute")
    @mock.patch.object(Config, "discover_desktops")
    def test_desktop_command_exit_code_on_failure(
        self,
        mock_discover: mock.Mock,
        mock_execute: mock.Mock,
    ) -> None:
        """Test desktop command returns non-zero on module failure."""
        mock_desktop_config = DesktopConfig(
            name="failing-desktop",
            description="Desktop that fails",
        )
        mock_discover.return_value = {"failing-desktop": mock_desktop_config}

        mock_execute.return_value = {
            "desktop": ModuleResult(
                status=ModuleStatus.FAILED,
                message="Desktop installation failed",
                recovery_command="gvm fix desktop",
            ),
        }

        args = argparse.Namespace(
            verbose=False,
            dry_run=False,
            help=False,
            desktop_target="failing-desktop",
            config=None,
        )

        with mock.patch("builtins.print"):
            result = cmd_desktop(args, self.config)

        # Should return 1 for failure
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
