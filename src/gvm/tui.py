"""Curses-based TUI for GVM tool.

This module implements the interactive terminal user interface with:
- Component selection screen with checkbox navigation
- Progress display with split-screen layout
- Error recovery prompts
- Post-setup menu
"""

from __future__ import annotations

import curses
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from gvm.modules import ModuleResult, ModuleStatus, RecoveryAction, list_modules
from gvm.orchestrator import ModuleOrchestrator

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from gvm.config import Config


class Screen(Enum):
    """TUI screen identifiers."""

    COMPONENT_SELECTION = "component_selection"
    PROGRESS = "progress"
    ERROR_RECOVERY = "error_recovery"
    POST_SETUP = "post_setup"


@dataclass
class Component:
    """Represents a selectable component in the TUI.

    Attributes:
        id: Module identifier (e.g., "apt", "desktop:plasma-mobile")
        name: Display name
        description: Human-readable description
        default_selected: Whether selected by default
    """

    id: str
    name: str
    description: str
    default_selected: bool = False


@dataclass
class SelectionState:
    """Tracks selection state for the component selection screen.

    Attributes:
        components: List of available components
        selections: Map of component id to selected state
        cursor_pos: Current cursor position
        scroll_offset: Scroll offset for long lists
    """

    components: list[Component] = field(default_factory=list)
    selections: dict[str, bool] = field(default_factory=dict)
    cursor_pos: int = 0
    scroll_offset: int = 0


@dataclass
class ProgressState:
    """Tracks progress display state.

    Attributes:
        modules: List of module names being executed
        current_module: Currently executing module
        current_percent: Current module progress (0.0-1.0)
        current_message: Current status message
        current_operation: Current operation detail (verbose)
        completed: Set of completed module names
        failed: Set of failed module names
        skipped: Set of skipped module names
        log_lines: Log buffer for verbose mode
        start_time: Execution start time
    """

    modules: list[str] = field(default_factory=list)
    current_module: str = ""
    current_percent: float = 0.0
    current_message: str = ""
    current_operation: str = ""
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    log_lines: list[str] = field(default_factory=list)
    start_time: float = 0.0


class CursesTUI:
    """Curses-based interactive TUI for GVM setup.

    Implements four main screens:
    1. Component selection with checkbox navigation
    2. Progress display with status and log panes
    3. Error recovery prompts
    4. Post-setup menu

    Args:
        config: Configuration object
        verbose: Enable verbose output with log pane
        dry_run: Simulate execution without changes
    """

    # Selection persistence file path
    SELECTION_FILE = Path.home() / ".config" / "gvm" / "last-selection.json"

    # Maximum log buffer size
    MAX_LOG_LINES = 1000

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize the TUI.

        Args:
            config: Configuration object with user settings
            verbose: Enable verbose output with detailed log pane
            dry_run: Simulate execution without making changes
        """
        self.config = config
        self.verbose = verbose
        self.dry_run = dry_run

        self.stdscr: Optional[curses.window] = None
        self.selection_state = SelectionState()
        self.progress_state = ProgressState()
        self.results: dict[str, ModuleResult] = {}

        # Recovery action from error screen
        self._recovery_action: Optional[RecoveryAction] = None
        self._error_module: str = ""
        self._error_result: Optional[ModuleResult] = None

    def run(self) -> int:
        """Main entry point for the TUI.

        Returns:
            Exit code (0 for success, non-zero for errors).
        """
        try:
            return curses.wrapper(self._main_loop)
        except KeyboardInterrupt:
            return 130  # Standard exit code for Ctrl+C
        except Exception:
            logger.exception("TUI encountered an unexpected error")
            return 1

    def _main_loop(self, stdscr: curses.window) -> int:
        """Main TUI loop.

        Args:
            stdscr: Curses standard screen window.

        Returns:
            Exit code.
        """
        self.stdscr = stdscr

        # Configure curses
        curses.curs_set(0)  # Hide cursor
        curses.use_default_colors()

        # Initialize color pairs if available
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_GREEN, -1)  # Success
            curses.init_pair(2, curses.COLOR_RED, -1)  # Error
            curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Warning/Running
            curses.init_pair(4, curses.COLOR_CYAN, -1)  # Info

        # Discover and show component selection
        self._discover_components()
        self._load_last_selections()
        selected = self._show_component_selection()

        if not selected:
            return 0  # User quit without selection

        # Save selections for next time
        self._save_selections()

        # Execute selected modules
        self.results = self._show_progress(selected)

        # Show post-setup menu
        action = self._show_post_setup_menu()

        if action == "start_desktop":
            self._start_desktop()

        return 0

    def _discover_components(self) -> None:
        """Discover available components (modules and desktops)."""
        components: list[Component] = []

        # Base modules
        base_modules = {
            "apt": ("APT Configuration", "Configure APT package manager with hardening"),
            "ssh": ("SSH Server", "Configure SSH server for remote access"),
            "shell": ("Shell Customizations", "Apply shell configurations and aliases"),
            "gui": ("GUI Helpers", "Install GUI helper scripts"),
        }

        available = list_modules()

        for module_name in available:
            if module_name in base_modules:
                name, desc = base_modules[module_name]
            else:
                name = module_name.title()
                desc = f"Configure {module_name}"

            # Default: apt, ssh, shell, gui are selected by default
            default_selected = module_name in ("apt", "ssh", "shell", "gui")

            components.append(
                Component(
                    id=module_name,
                    name=name,
                    description=desc,
                    default_selected=default_selected,
                )
            )

        # Desktop environments
        desktops = self.config.discover_desktops()

        for desktop_name, desktop_config in sorted(desktops.items()):
            components.append(
                Component(
                    id=f"desktop:{desktop_name}",
                    name=desktop_config.name,
                    description=desktop_config.description or "Desktop environment",
                    default_selected=False,
                )
            )

        self.selection_state.components = components

        # Initialize selections with defaults
        for comp in components:
            self.selection_state.selections[comp.id] = comp.default_selected

    def _load_last_selections(self) -> None:
        """Load previous selections from file."""
        if not self.SELECTION_FILE.exists():
            return

        try:
            data = json.loads(self.SELECTION_FILE.read_text())
            saved_selections = data.get("selections", {})

            # Apply saved selections to known components
            for comp in self.selection_state.components:
                if comp.id in saved_selections:
                    self.selection_state.selections[comp.id] = saved_selections[comp.id]

        except (json.JSONDecodeError, IOError):
            pass  # Use defaults on error

    def _save_selections(self) -> None:
        """Save current selections to file."""
        self.SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": "1.0",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "selections": self.selection_state.selections,
        }

        try:
            self.SELECTION_FILE.write_text(json.dumps(data, indent=2))
        except IOError:
            pass  # Ignore save errors

    def _show_component_selection(self) -> list[str]:
        """Display component selection screen.

        Returns:
            List of selected component IDs, or empty list if user quit.
        """
        if self.stdscr is None:
            return []

        state = self.selection_state

        while True:
            self.stdscr.clear()
            height, width = self.stdscr.getmaxyx()

            # Title
            title = "GrapheneOS Debian VM Setup - Component Selection"
            self.stdscr.addstr(0, max(0, (width - len(title)) // 2), title, curses.A_BOLD)

            # Subtitle
            if self.dry_run:
                subtitle = "[DRY RUN MODE]"
                self.stdscr.addstr(1, max(0, (width - len(subtitle)) // 2), subtitle, curses.A_DIM)

            # Calculate visible area
            list_start_y = 3
            list_height = height - 6  # Leave room for footer
            visible_components = min(len(state.components), list_height)

            # Adjust scroll offset based on cursor position
            if state.cursor_pos < state.scroll_offset:
                state.scroll_offset = state.cursor_pos
            elif state.cursor_pos >= state.scroll_offset + visible_components:
                state.scroll_offset = state.cursor_pos - visible_components + 1

            # Draw components
            for i in range(visible_components):
                comp_idx = state.scroll_offset + i
                if comp_idx >= len(state.components):
                    break

                comp = state.components[comp_idx]
                y = list_start_y + i

                # Selection checkbox
                checkbox = "[x]" if state.selections.get(comp.id, False) else "[ ]"

                # Highlight current item
                if comp_idx == state.cursor_pos:
                    attr = curses.A_REVERSE
                else:
                    attr = curses.A_NORMAL

                # Format line
                line = f" {checkbox} {comp.name}"
                desc = f" - {comp.description}"

                # Truncate if needed
                max_len = width - 2
                if len(line) + len(desc) > max_len:
                    desc = desc[: max_len - len(line) - 3] + "..."

                try:
                    self.stdscr.addstr(y, 0, line, attr)
                    if len(line) < max_len:
                        self.stdscr.addstr(y, len(line), desc[: max_len - len(line)], attr | curses.A_DIM)
                except curses.error:
                    pass  # Ignore drawing errors at screen edge

            # Scroll indicators
            if state.scroll_offset > 0:
                try:
                    self.stdscr.addstr(list_start_y - 1, width - 3, " ^ ", curses.A_DIM)
                except curses.error:
                    pass
            if state.scroll_offset + visible_components < len(state.components):
                try:
                    self.stdscr.addstr(list_start_y + visible_components, width - 3, " v ", curses.A_DIM)
                except curses.error:
                    pass

            # Footer
            footer_y = height - 2
            footer = "  [Space] Toggle  [a] All  [n] None  [Enter] Confirm  [q] Quit  "
            try:
                self.stdscr.addstr(footer_y, 0, "-" * width, curses.A_DIM)
                self.stdscr.addstr(footer_y + 1, max(0, (width - len(footer)) // 2), footer, curses.A_DIM)
            except curses.error:
                pass

            self.stdscr.refresh()

            # Handle input
            try:
                key = self.stdscr.getch()
            except curses.error:
                continue

            if key == curses.KEY_RESIZE:
                continue  # Redraw on resize
            elif key in (ord("q"), ord("Q"), 27):  # q, Q, or Escape
                return []
            elif key in (curses.KEY_UP, ord("k")):
                state.cursor_pos = max(0, state.cursor_pos - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                state.cursor_pos = min(len(state.components) - 1, state.cursor_pos + 1)
            elif key == ord(" "):
                # Toggle selection
                comp = state.components[state.cursor_pos]
                state.selections[comp.id] = not state.selections.get(comp.id, False)
            elif key in (ord("a"), ord("A")):
                # Select all
                for comp in state.components:
                    state.selections[comp.id] = True
            elif key in (ord("n"), ord("N")):
                # Deselect all
                for comp in state.components:
                    state.selections[comp.id] = False
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                # Confirm selection
                selected = [
                    comp.id
                    for comp in state.components
                    if state.selections.get(comp.id, False)
                ]
                return selected

    def _show_progress(self, modules: list[str]) -> dict[str, ModuleResult]:
        """Display progress screen and execute modules.

        Args:
            modules: List of module IDs to execute.

        Returns:
            Dictionary of module results.
        """
        if self.stdscr is None:
            return {}

        # Separate base modules from desktop selections
        base_modules = []
        desktop_selection = None

        for mod_id in modules:
            if mod_id.startswith("desktop:"):
                desktop_selection = mod_id.split(":", 1)[1]
            else:
                base_modules.append(mod_id)

        # Initialize progress state
        self.progress_state = ProgressState(
            modules=base_modules.copy(),
            start_time=time.time(),
        )

        # Add desktop to modules list if selected
        if desktop_selection:
            self.progress_state.modules.append(f"desktop:{desktop_selection}")

        # Create orchestrator
        orchestrator = ModuleOrchestrator(
            self.config,
            verbose=self.verbose,
            dry_run=self.dry_run,
        )

        # Progress callback
        def progress_callback(
            percent: float, message: str, operation: Optional[str]
        ) -> None:
            self.progress_state.current_percent = percent
            self.progress_state.current_message = message

            # Extract current module from message format "[module_name] ..."
            # or "Processing module: module_name"
            if message.startswith("[") and "]" in message:
                module_name = message[1:message.index("]")]
                self.progress_state.current_module = module_name
            elif message.startswith("Processing module: "):
                module_name = message[len("Processing module: "):]
                self.progress_state.current_module = module_name

            if operation:
                self.progress_state.current_operation = operation
                if self.verbose:
                    self._add_log_line(operation)
            self._draw_progress_screen()

        # Error callback
        def error_callback(module_name: str, result: ModuleResult) -> RecoveryAction:
            self.progress_state.failed.add(module_name)
            return self._show_error_recovery(module_name, result)

        # Execute modules
        try:
            results = orchestrator.execute(
                base_modules,
                progress_callback=progress_callback,
                error_callback=error_callback,
            )

            # Track completed modules
            for name, result in results.items():
                if result.status == ModuleStatus.SUCCESS:
                    self.progress_state.completed.add(name)
                elif result.status == ModuleStatus.SKIPPED:
                    self.progress_state.skipped.add(name)

            return results

        except Exception as e:
            self._add_log_line(f"Error: {e}")
            return {}

    def _draw_progress_screen(self) -> None:
        """Draw the progress display screen."""
        if self.stdscr is None:
            return

        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()

        state = self.progress_state

        # Title
        title = "GrapheneOS Debian VM Setup - Installation Progress"
        try:
            self.stdscr.addstr(0, max(0, (width - len(title)) // 2), title, curses.A_BOLD)
        except curses.error:
            pass

        if self.verbose:
            # Three-pane layout
            status_height = max(4, (height - 4) * 40 // 100)
            detail_height = max(2, (height - 4) * 20 // 100)
            log_height = height - 4 - status_height - detail_height
        else:
            # Two-pane layout
            status_height = max(4, (height - 4) * 60 // 100)
            detail_height = height - 4 - status_height
            log_height = 0

        # Status pane
        self._draw_status_pane(2, status_height, width)

        # Detail pane
        self._draw_detail_pane(2 + status_height, detail_height, width)

        # Log pane (verbose only)
        if self.verbose and log_height > 0:
            self._draw_log_pane(2 + status_height + detail_height, log_height, width)

        self.stdscr.refresh()

    def _draw_status_pane(self, start_y: int, height: int, width: int) -> None:
        """Draw the component status pane."""
        if self.stdscr is None:
            return

        state = self.progress_state

        try:
            self.stdscr.addstr(start_y, 0, "Components:", curses.A_BOLD)
        except curses.error:
            pass

        y = start_y + 1
        for mod in state.modules:
            if y >= start_y + height:
                break

            # Status indicator
            if mod in state.completed:
                indicator = "✓"
                attr = curses.color_pair(1) if curses.has_colors() else curses.A_NORMAL
            elif mod in state.failed:
                indicator = "✗"
                attr = curses.color_pair(2) if curses.has_colors() else curses.A_NORMAL
            elif mod in state.skipped:
                indicator = "-"
                attr = curses.A_DIM
            elif mod == state.current_module:
                indicator = "▶"
                attr = curses.color_pair(3) if curses.has_colors() else curses.A_REVERSE
            else:
                indicator = "⏳"
                attr = curses.A_DIM

            line = f"  [{indicator}] {mod}"
            try:
                self.stdscr.addstr(y, 0, line[:width - 1], attr)
            except curses.error:
                pass

            y += 1

    def _draw_detail_pane(self, start_y: int, height: int, width: int) -> None:
        """Draw the current operation detail pane."""
        if self.stdscr is None:
            return

        state = self.progress_state

        try:
            self.stdscr.addstr(start_y, 0, "-" * width, curses.A_DIM)
        except curses.error:
            pass

        # Progress bar
        bar_width = min(40, width - 20)
        filled = int(bar_width * state.current_percent)
        bar = "=" * filled + ">" + " " * max(0, bar_width - filled - 1)

        elapsed = time.time() - state.start_time
        elapsed_str = f"{int(elapsed)}s"

        progress_line = f"[{bar}] {state.current_percent:.0%} ({elapsed_str})"
        try:
            self.stdscr.addstr(start_y + 1, 2, progress_line[:width - 4])
        except curses.error:
            pass

        # Current message
        if state.current_message:
            try:
                self.stdscr.addstr(start_y + 2, 2, state.current_message[:width - 4])
            except curses.error:
                pass

        # Current operation (if verbose)
        if self.verbose and state.current_operation:
            try:
                self.stdscr.addstr(start_y + 3, 4, state.current_operation[:width - 6], curses.A_DIM)
            except curses.error:
                pass

    def _draw_log_pane(self, start_y: int, height: int, width: int) -> None:
        """Draw the scrollable log pane (verbose mode)."""
        if self.stdscr is None:
            return

        state = self.progress_state

        try:
            self.stdscr.addstr(start_y, 0, "-" * width, curses.A_DIM)
            self.stdscr.addstr(start_y, 2, " Log ", curses.A_BOLD)
        except curses.error:
            pass

        # Show last N lines that fit
        visible_lines = height - 1
        start_line = max(0, len(state.log_lines) - visible_lines)

        for i, line in enumerate(state.log_lines[start_line:]):
            if i >= visible_lines:
                break
            try:
                self.stdscr.addstr(start_y + 1 + i, 2, line[:width - 4], curses.A_DIM)
            except curses.error:
                pass

    def _add_log_line(self, line: str) -> None:
        """Add a line to the log buffer.

        Args:
            line: Log line to add.
        """
        self.progress_state.log_lines.append(line)

        # Trim buffer if too large
        if len(self.progress_state.log_lines) > self.MAX_LOG_LINES:
            self.progress_state.log_lines = self.progress_state.log_lines[-self.MAX_LOG_LINES:]

    def _show_error_recovery(self, module_name: str, result: ModuleResult) -> RecoveryAction:
        """Display error recovery screen and get user choice.

        Args:
            module_name: Name of the failed module.
            result: Module result with error details.

        Returns:
            User's chosen recovery action.
        """
        if self.stdscr is None:
            return RecoveryAction.ABORT

        self._error_module = module_name
        self._error_result = result

        while True:
            self.stdscr.clear()
            height, width = self.stdscr.getmaxyx()

            # Title
            title = "Setup Failed"
            try:
                self.stdscr.addstr(0, max(0, (width - len(title)) // 2), title, curses.A_BOLD)
            except curses.error:
                pass

            # Error icon and module name
            y = 3
            try:
                error_line = f"  ✗  Module '{module_name}' failed"
                attr = curses.color_pair(2) if curses.has_colors() else curses.A_BOLD
                self.stdscr.addstr(y, 0, error_line, attr)
            except curses.error:
                pass

            # Error message
            y += 2
            try:
                self.stdscr.addstr(y, 0, "Error:", curses.A_BOLD)
                y += 1
                msg = result.message[:width - 4] if result.message else "Unknown error"
                self.stdscr.addstr(y, 2, msg)
            except curses.error:
                pass

            # Error details (if available)
            if result.details:
                y += 2
                try:
                    self.stdscr.addstr(y, 0, "Details:", curses.A_BOLD)
                    y += 1
                    # Show first few lines of details
                    detail_lines = result.details.split("\n")[:5]
                    for line in detail_lines:
                        if y >= height - 8:
                            break
                        self.stdscr.addstr(y, 2, line[:width - 4], curses.A_DIM)
                        y += 1
                except curses.error:
                    pass

            # Recovery command suggestion
            if result.recovery_command:
                y += 1
                try:
                    self.stdscr.addstr(y, 0, "Recovery command:", curses.A_BOLD)
                    y += 1
                    self.stdscr.addstr(y, 2, result.recovery_command[:width - 4])
                except curses.error:
                    pass

            # Recovery options
            options_y = height - 5
            try:
                self.stdscr.addstr(options_y, 0, "-" * width, curses.A_DIM)
                self.stdscr.addstr(options_y + 1, 0, "Choose an action:", curses.A_BOLD)
                self.stdscr.addstr(options_y + 2, 2, "[R] Retry   - Re-run the failed module")
                self.stdscr.addstr(options_y + 3, 2, "[S] Skip    - Skip and continue with remaining modules")
                self.stdscr.addstr(options_y + 4, 2, "[A] Abort   - Stop execution entirely")
            except curses.error:
                pass

            self.stdscr.refresh()

            # Handle input
            try:
                key = self.stdscr.getch()
            except curses.error:
                continue

            if key == curses.KEY_RESIZE:
                continue
            elif key in (ord("r"), ord("R")):
                return RecoveryAction.RETRY
            elif key in (ord("s"), ord("S")):
                return RecoveryAction.SKIP
            elif key in (ord("a"), ord("A"), ord("q"), ord("Q"), 27):
                return RecoveryAction.ABORT

    def _show_post_setup_menu(self) -> str:
        """Display post-setup menu screen.

        Returns:
            Selected action: "start_desktop", "info", or "quit".
        """
        if self.stdscr is None:
            return "quit"

        # Check for installed desktops
        installed_desktops = self._detect_installed_desktops()

        while True:
            self.stdscr.clear()
            height, width = self.stdscr.getmaxyx()

            # Title
            title = "GrapheneOS Debian VM Setup"
            try:
                self.stdscr.addstr(0, max(0, (width - len(title)) // 2), title, curses.A_BOLD)
            except curses.error:
                pass

            # Success message
            y = 2
            try:
                success_msg = "✓ Setup Complete!"
                attr = curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
                self.stdscr.addstr(y, max(0, (width - len(success_msg)) // 2), success_msg, attr)
            except curses.error:
                pass

            # Summary
            y = 5
            try:
                self.stdscr.addstr(y, 0, "Summary:", curses.A_BOLD)
                y += 1

                completed = len(self.progress_state.completed)
                failed = len(self.progress_state.failed)
                skipped = len(self.progress_state.skipped)
                total = len(self.progress_state.modules)

                self.stdscr.addstr(y, 2, f"Total modules: {total}")
                y += 1

                if completed > 0:
                    attr = curses.color_pair(1) if curses.has_colors() else curses.A_NORMAL
                    self.stdscr.addstr(y, 2, f"Completed: {completed}", attr)
                    y += 1

                if failed > 0:
                    attr = curses.color_pair(2) if curses.has_colors() else curses.A_NORMAL
                    self.stdscr.addstr(y, 2, f"Failed: {failed}", attr)
                    y += 1

                if skipped > 0:
                    self.stdscr.addstr(y, 2, f"Skipped: {skipped}", curses.A_DIM)
                    y += 1
            except curses.error:
                pass

            # Menu options
            menu_y = height - 8
            try:
                self.stdscr.addstr(menu_y, 0, "-" * width, curses.A_DIM)
                self.stdscr.addstr(menu_y + 1, 0, "Options:", curses.A_BOLD)

                if installed_desktops:
                    self.stdscr.addstr(menu_y + 2, 2, "[S] Start Desktop")
                else:
                    self.stdscr.addstr(menu_y + 2, 2, "[S] Start Desktop (no desktop installed)", curses.A_DIM)

                self.stdscr.addstr(menu_y + 3, 2, "[I] System Info")
                self.stdscr.addstr(menu_y + 4, 2, "[Q] Quit")
            except curses.error:
                pass

            self.stdscr.refresh()

            # Handle input
            try:
                key = self.stdscr.getch()
            except curses.error:
                continue

            if key == curses.KEY_RESIZE:
                continue
            elif key in (ord("s"), ord("S")):
                if installed_desktops:
                    if len(installed_desktops) == 1:
                        return "start_desktop"
                    else:
                        # Show desktop submenu
                        desktop = self._show_desktop_submenu(installed_desktops)
                        if desktop:
                            self._selected_desktop = desktop
                            return "start_desktop"
            elif key in (ord("i"), ord("I")):
                self._show_info_screen()
            elif key in (ord("q"), ord("Q"), 27):
                return "quit"

    def _detect_installed_desktops(self) -> list[str]:
        """Detect installed desktop helper scripts.

        Returns:
            List of installed desktop names.
        """
        desktops = []
        local_bin = Path.home() / ".local" / "bin"

        if not local_bin.exists():
            return desktops

        # Check for known helper scripts
        for item in local_bin.iterdir():
            if item.name.startswith("start-") and item.is_file():
                desktop_name = item.name[6:]  # Remove "start-" prefix
                desktops.append(desktop_name)

        return desktops

    def _show_desktop_submenu(self, desktops: list[str]) -> Optional[str]:
        """Show desktop selection submenu.

        Args:
            desktops: List of available desktop names.

        Returns:
            Selected desktop name or None.
        """
        if self.stdscr is None:
            return None

        cursor = 0

        while True:
            self.stdscr.clear()
            height, width = self.stdscr.getmaxyx()

            # Title
            title = "Select Desktop Environment"
            try:
                self.stdscr.addstr(0, max(0, (width - len(title)) // 2), title, curses.A_BOLD)
            except curses.error:
                pass

            # Desktop list
            y = 3
            for i, desktop in enumerate(desktops):
                attr = curses.A_REVERSE if i == cursor else curses.A_NORMAL
                try:
                    self.stdscr.addstr(y + i, 2, f"  {desktop}  ", attr)
                except curses.error:
                    pass

            # Footer
            try:
                self.stdscr.addstr(height - 2, 0, "  [Enter] Select  [q] Back  ", curses.A_DIM)
            except curses.error:
                pass

            self.stdscr.refresh()

            try:
                key = self.stdscr.getch()
            except curses.error:
                continue

            if key == curses.KEY_RESIZE:
                continue
            elif key in (curses.KEY_UP, ord("k")):
                cursor = max(0, cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = min(len(desktops) - 1, cursor + 1)
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                return desktops[cursor]
            elif key in (ord("q"), ord("Q"), 27):
                return None

    def _show_info_screen(self) -> None:
        """Display system information screen."""
        if self.stdscr is None:
            return

        from gvm.utils.system import (
            detect_debian_codename,
            is_port_listening,
            is_service_running,
        )

        while True:
            self.stdscr.clear()
            height, width = self.stdscr.getmaxyx()

            # Title
            title = "System Information"
            try:
                self.stdscr.addstr(0, max(0, (width - len(title)) // 2), title, curses.A_BOLD)
            except curses.error:
                pass

            y = 3

            # Debian version
            codename = detect_debian_codename()
            try:
                self.stdscr.addstr(y, 0, f"Debian Version:    {codename or 'Unknown'}")
            except curses.error:
                pass

            # SSH status
            y += 2
            ssh_running = is_service_running("ssh") or is_service_running("sshd")
            ssh_port = self.config.ssh_forward_port
            port_listening = is_port_listening(ssh_port)

            try:
                self.stdscr.addstr(y, 0, f"SSH Service:       {'Running' if ssh_running else 'Not Running'}")
                y += 1
                self.stdscr.addstr(y, 0, f"SSH Port {ssh_port}:      {'Listening' if port_listening else 'Not Listening'}")
            except curses.error:
                pass

            # Installed desktops
            y += 2
            desktops = self._detect_installed_desktops()
            try:
                self.stdscr.addstr(y, 0, "Installed Desktops:", curses.A_BOLD)
                y += 1
                if desktops:
                    for desktop in desktops:
                        self.stdscr.addstr(y, 2, desktop)
                        y += 1
                else:
                    self.stdscr.addstr(y, 2, "(none)", curses.A_DIM)
            except curses.error:
                pass

            # Footer
            try:
                self.stdscr.addstr(height - 2, 0, "  Press any key to return  ", curses.A_DIM)
            except curses.error:
                pass

            self.stdscr.refresh()

            try:
                key = self.stdscr.getch()
                if key != curses.KEY_RESIZE:
                    break
            except curses.error:
                break

    def _start_desktop(self) -> None:
        """Start the selected desktop environment."""
        desktops = self._detect_installed_desktops()

        if not desktops:
            return

        # Get desktop to start
        desktop = getattr(self, "_selected_desktop", None)
        if desktop is None:
            desktop = desktops[0]

        helper_script = Path.home() / ".local" / "bin" / f"start-{desktop}"

        if helper_script.exists():
            # Clean up curses before launching desktop
            if self.stdscr:
                curses.endwin()

            try:
                subprocess.Popen(
                    [str(helper_script)],
                    start_new_session=True,
                )
            except Exception:
                pass  # Ignore launch errors
