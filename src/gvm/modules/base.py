"""
Module system base classes and data structures.

This module defines the abstract base class and supporting data structures
for the GVM module system. All concrete modules (APT, SSH, Desktop, Shell, GUI)
must inherit from the Module base class and implement its abstract methods.

Architecture Overview:
    - Module: Abstract base class defining the contract for all modules
    - Dependency: Dataclass representing module dependencies (required/optional)
    - ModuleResult: Dataclass containing execution results with status and details
    - ModuleStatus: Enum for module execution outcomes (SUCCESS/FAILED/SKIPPED)
    - RecoveryAction: Enum for interactive error recovery choices

Example Usage:
    class APTModule(Module):
        name = "apt"
        description = "Configure APT package manager and install packages"
        dependencies = ()

        def is_installed(self) -> tuple[bool, str]:
            # Check if APT configuration already exists
            return (False, "APT not configured")

        def run(self, progress_callback) -> ModuleResult:
            self._report_progress(progress_callback, 0.0, "Starting APT configuration")
            # ... implementation ...
            return ModuleResult(status=ModuleStatus.SUCCESS, message="APT configured")

        def get_recovery_command(self) -> str:
            return "gvm fix apt"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional, Sequence

if TYPE_CHECKING:
    from gvm.config import Config


class ModuleStatus(Enum):
    """Execution status for module operations.

    Attributes:
        SUCCESS: Module executed successfully without errors
        FAILED: Module execution failed with an error
        SKIPPED: Module was skipped (user choice or optional dependency not met)
    """

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class RecoveryAction(Enum):
    """Actions available during interactive error recovery.

    When a module fails, the orchestrator can prompt the user to choose
    a recovery action. These values represent the available choices.

    Attributes:
        RETRY: Re-run the failed module from the beginning
        SKIP: Skip the failed module and continue with the next one
        ABORT: Stop execution entirely and exit
    """

    RETRY = "retry"
    SKIP = "skip"
    ABORT = "abort"


@dataclass
class Dependency:
    """Represents a dependency relationship between modules.

    Attributes:
        module_name: The name identifier of the required module
        required: If True, the dependency is mandatory and must succeed.
                  If False, the dependency is optional and will be auto-included
                  if the dependent module is selected, but failure won't block execution.
    """

    module_name: str
    required: bool = True


@dataclass
class ModuleResult:
    """Result of a module execution.

    Contains the outcome status, human-readable message, optional details
    for verbose output or error traces, and a suggested recovery command.

    Attributes:
        status: The execution status (SUCCESS, FAILED, or SKIPPED)
        message: Human-readable result message suitable for display
        details: Additional details such as error traces or verbose output.
                 May be None if no additional details are available.
        recovery_command: Suggested CLI command to recover from failure.
                         Typically set when status is FAILED.
    """

    status: ModuleStatus
    message: str
    details: Optional[str] = None
    recovery_command: Optional[str] = None


class Module(ABC):
    """Abstract base class for all GVM modules.

    Concrete modules must inherit from this class and implement all abstract
    methods. The module system uses this interface for dependency resolution,
    installation detection, and execution orchestration.

    Class Attributes:
        name: Unique module identifier (e.g., "apt", "ssh", "desktop")
        description: Human-readable description of the module's purpose
        dependencies: Tuple of Dependency objects declaring module dependencies.
                      Uses tuple (immutable) to prevent accidental shared state
                      between module classes.

    Instance Attributes:
        config: Configuration object containing user settings
        verbose: If True, show detailed operation information
        dry_run: If True, simulate execution without making changes

    Example:
        class SSHModule(Module):
            name = "ssh"
            description = "Configure SSH keys and authentication"
            dependencies = (Dependency("apt", required=True),)

            def is_installed(self) -> tuple[bool, str]:
                if Path("~/.ssh/id_ed25519").expanduser().exists():
                    return (True, "SSH key already exists")
                return (False, "No SSH key found")

            def run(self, progress_callback) -> ModuleResult:
                if self.dry_run:
                    return ModuleResult(
                        status=ModuleStatus.SUCCESS,
                        message="[DRY RUN] Would generate SSH key"
                    )
                # ... actual implementation ...
    """

    # Class attributes to be defined by subclasses
    name: str = ""
    description: str = ""
    dependencies: Sequence[Dependency] = ()

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize a module instance.

        Args:
            config: Configuration object with user settings and preferences
            verbose: Enable verbose output with detailed operation information
            dry_run: Simulate execution without making actual changes
        """
        self.config = config
        self.verbose = verbose
        self.dry_run = dry_run

    @abstractmethod
    def is_installed(self) -> tuple[bool, str]:
        """Check if the module's functionality is already installed/configured.

        This method should detect whether the module's target state already
        exists, allowing the orchestrator to skip unnecessary execution.

        Returns:
            A tuple of (is_installed, message) where:
                - is_installed: True if the module's functionality is present
                - message: Human-readable explanation of what was detected
                          or what's missing

        Examples:
            - ("apt" module): Check if apt.conf exists with expected settings
            - ("ssh" module): Check if SSH key already exists
            - ("desktop" module): Check if desktop configuration is present
        """
        ...

    @abstractmethod
    def run(
        self,
        progress_callback: Callable[[float, str, Optional[str]], None],
    ) -> ModuleResult:
        """Execute the module's main functionality.

        This method performs the actual work of the module. It should report
        progress via the callback and respect the dry_run flag for destructive
        operations.

        Args:
            progress_callback: Callback function to report progress with signature:
                - percent (float): Progress from 0.0 to 1.0
                - message (str): Module-level status message (always shown)
                - operation (Optional[str]): Detailed operation info (verbose only)

        Returns:
            ModuleResult containing:
                - status: SUCCESS, FAILED, or SKIPPED
                - message: Human-readable result description
                - details: Optional verbose output or error traces
                - recovery_command: Suggested recovery command on failure

        Note:
            Use self._report_progress() helper instead of calling the callback
            directly to ensure proper validation and verbose handling.
        """
        ...

    def get_recovery_command(self) -> str:
        """Return the CLI command to recover from module failure.

        Override this method in subclasses to provide custom recovery commands.
        The default implementation returns a standard fix command.

        Returns:
            CLI command string that can be run to attempt recovery
        """
        return f"gvm fix {self.name}"

    def _report_progress(
        self,
        callback: Optional[Callable[[float, str, Optional[str]], None]],
        percent: float,
        message: str,
        operation: Optional[str] = None,
    ) -> None:
        """Report progress through the callback with validation.

        This helper method validates the percent value, handles None callbacks
        gracefully, and respects the verbose flag for operation details.

        Args:
            callback: Progress callback function, or None for no-op
            percent: Progress percentage from 0.0 to 1.0
            message: Module-level status message (always passed to callback)
            operation: Detailed operation info (only passed if verbose is True)

        Raises:
            ValueError: If percent is not between 0.0 and 1.0
        """
        if callback is None:
            return

        if not 0.0 <= percent <= 1.0:
            raise ValueError(f"Progress percent must be between 0.0 and 1.0, got {percent}")

        # Only pass operation details if verbose mode is enabled
        operation_detail = operation if self.verbose else None
        callback(percent, message, operation_detail)
