"""
Module orchestrator for GVM tool.

This module implements the ModuleOrchestrator class, which is responsible for
dependency resolution, execution ordering, and interactive error recovery
for the GVM module system.

Architecture Overview:
    The orchestrator sits between the UI layer and the module layer:
    - Receives module selections from the UI
    - Resolves dependencies using topological sort (Kahn's algorithm)
    - Executes modules in dependency order
    - Provides progress callbacks with throttling
    - Supports interactive error recovery via callback pattern

Key Features:
    - Dependency Resolution: Topological sort with cycle detection
    - Optional Dependencies: Auto-included when dependent module is selected
    - Progress Throttling: Limits callback frequency to 10 updates/second
    - Error Recovery: Callback-based pattern allowing RETRY, SKIP, or ABORT

Example Usage:
    config = Config.load()
    orchestrator = ModuleOrchestrator(config, verbose=True)

    def on_progress(percent, message, operation):
        print(f"{percent:.0%}: {message}")

    def on_error(module_name, result):
        print(f"Module {module_name} failed: {result.message}")
        return RecoveryAction.SKIP

    results = orchestrator.execute(
        ["desktop", "ssh"],
        progress_callback=on_progress,
        error_callback=on_error
    )

    summary = orchestrator.get_execution_summary(results)
    print(f"Completed: {summary['successful']}/{summary['total']}")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

from gvm.modules import (
    Dependency,
    Module,
    ModuleResult,
    ModuleStatus,
    RecoveryAction,
    get_module_class,
    list_modules,
    normalize_module_name,
)

if TYPE_CHECKING:
    from gvm.config import Config


@dataclass
class ModuleNode:
    """Represents a module in the dependency graph.

    This dataclass is used internally during dependency resolution to track
    module relationships and enable cycle detection.

    Attributes:
        module: The module instance
        dependencies: List of dependency module names this module depends on
        required_by: List of module names that depend on this module
                     (reverse dependencies for error reporting)
    """

    module: Module
    dependencies: list[str] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)


@dataclass
class ExecutionContext:
    """Tracks execution progress during module orchestration.

    This dataclass maintains state throughout the execution process,
    allowing the orchestrator to track progress, store results, and
    manage skipped modules.

    Attributes:
        total_modules: Total number of modules to execute
        completed: Number of modules that have completed (success or skip)
        results: Map of module name to its execution result
        skipped: Set of module names that were skipped
    """

    total_modules: int
    completed: int = 0
    results: dict[str, ModuleResult] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)


class ModuleOrchestrator:
    """Orchestrates module execution with dependency resolution and error recovery.

    The orchestrator is responsible for:
    1. Loading module instances from the registry
    2. Resolving dependencies using topological sort (Kahn's algorithm)
    3. Executing modules in correct dependency order
    4. Handling progress reporting with throttling
    5. Supporting interactive error recovery

    Args:
        config: Configuration object with user settings
        verbose: Enable verbose output with detailed operation information
        dry_run: Simulate execution without making actual changes

    Example:
        orchestrator = ModuleOrchestrator(config)

        # Validate modules before execution
        valid, invalid = orchestrator.validate_modules(["apt", "ssh"])
        if not valid:
            print(f"Invalid modules: {invalid}")
            return

        # Execute with callbacks
        results = orchestrator.execute(
            ["desktop"],
            progress_callback=lambda p, m, o: print(f"{p:.0%}: {m}"),
            error_callback=lambda n, r: RecoveryAction.SKIP
        )
    """

    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            config: Configuration object containing user settings and preferences
            verbose: Enable verbose output with detailed operation information
            dry_run: Simulate execution without making actual changes
        """
        self.config = config
        self.verbose = verbose
        self.dry_run = dry_run
        self.modules: dict[str, Module] = {}

    def load_modules(self, module_names: list[str]) -> None:
        """Load module instances from the registry.

        Iterates through the provided module names, retrieves their classes
        from the registry, and instantiates them with the orchestrator's
        configuration settings. Module names are normalized to lowercase.

        Args:
            module_names: List of module names to load

        Raises:
            ValueError: If any module name is not found in the registry

        Example:
            orchestrator.load_modules(["apt", "ssh"])
            # Modules are now available in orchestrator.modules
        """
        for name in module_names:
            normalized_name = normalize_module_name(name)

            if normalized_name in self.modules:
                # Already loaded, skip
                continue

            module_class = get_module_class(normalized_name)
            if module_class is None:
                available = list_modules()
                raise ValueError(
                    f"Unknown module: {normalized_name}. Available modules: {available}"
                )

            self.modules[normalized_name] = module_class(
                self.config,
                self.verbose,
                self.dry_run,
            )

    def resolve_dependencies(
        self, requested_modules: list[str]
    ) -> tuple[list[str], set[str]]:
        """Resolve dependencies and return modules in execution order.

        Uses Kahn's algorithm for topological sorting with cycle detection.
        Optional dependencies are automatically included when their dependent
        module is selected. Module names are normalized to lowercase.

        Args:
            requested_modules: List of module names requested for execution

        Returns:
            Tuple of (ordered_modules, optional_auto_included) where:
                - ordered_modules: List of module names in dependency order
                  (dependencies come before dependents)
                - optional_auto_included: Set of module names that were
                  auto-included as optional dependencies (not explicitly requested)

        Raises:
            ValueError: If unknown modules are requested or circular
                       dependencies are detected

        Example:
            # If desktop depends on apt, and apt has no dependencies:
            order, optional = orchestrator.resolve_dependencies(["desktop"])
            # Returns: (["apt", "desktop"], set())
        """
        # Normalize requested module names
        normalized_requested = [normalize_module_name(m) for m in requested_modules]
        requested_set = set(normalized_requested)

        # Build dependency graph
        # dependents[dep] = set of modules that depend on dep (reverse adjacency list)
        dependents: dict[str, set[str]] = {}
        # in_degree[module] = number of dependencies this module has
        in_degree: dict[str, int] = {}
        all_modules: set[str] = set()

        # Track modules that were auto-included as optional dependencies
        optional_auto_included: set[str] = set()

        # Queue for processing modules (BFS to collect all dependencies)
        to_process = list(normalized_requested)
        processed: set[str] = set()

        while to_process:
            module_name = to_process.pop(0)

            if module_name in processed:
                continue
            processed.add(module_name)
            all_modules.add(module_name)

            # Load module if not already loaded
            if module_name not in self.modules:
                self.load_modules([module_name])

            module = self.modules[module_name]

            # Initialize entries for this module
            if module_name not in dependents:
                dependents[module_name] = set()
            if module_name not in in_degree:
                in_degree[module_name] = 0

            # Process dependencies
            for dep in module.dependencies:
                dep_name = normalize_module_name(dep.module_name)
                all_modules.add(dep_name)

                # Track if this dependency is optional and was not explicitly requested
                if not dep.required and dep_name not in requested_set:
                    optional_auto_included.add(dep_name)

                # Add dependency to processing queue
                if dep_name not in processed:
                    to_process.append(dep_name)

                # Initialize entries for dependency
                if dep_name not in dependents:
                    dependents[dep_name] = set()
                if dep_name not in in_degree:
                    in_degree[dep_name] = 0

                # Add edge: module depends on dep_name
                # Track that module_name is a dependent of dep_name
                if module_name not in dependents[dep_name]:
                    dependents[dep_name].add(module_name)
                    # Increment in_degree for the dependent module (module_name)
                    in_degree[module_name] += 1

        # Load any remaining unloaded modules
        unloaded = [m for m in all_modules if m not in self.modules]
        if unloaded:
            self.load_modules(unloaded)

        # Topological sort using Kahn's algorithm
        # Start with modules that have no dependencies (in_degree == 0)
        queue = [m for m in all_modules if in_degree.get(m, 0) == 0]
        result: list[str] = []

        while queue:
            # Take a module with no remaining dependencies
            module_name = queue.pop(0)
            result.append(module_name)

            # Reduce in_degree for modules that depend on this one
            for dependent in dependents.get(module_name, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Cycle detection: if we didn't process all modules, there's a cycle
        if len(result) != len(all_modules):
            cycle_modules = all_modules - set(result)
            raise ValueError(
                f"Circular dependency detected involving: {sorted(cycle_modules)}. "
                "Cannot proceed with installation."
            )

        return result, optional_auto_included

    def _create_throttled_callback(
        self,
        callback: Callable[[float, str, Optional[str]], None],
    ) -> Callable[[float, str, Optional[str], bool], None]:
        """Create a throttled version of the progress callback.

        Wraps the provided callback to limit updates to a maximum of
        10 per second (100ms intervals), preventing UI flooding while
        maintaining responsiveness.

        Args:
            callback: The original progress callback function

        Returns:
            Throttled callback function with signature:
                (percent, message, operation, force) -> None
            The force parameter allows bypassing throttling for important
            updates like final completion messages.

        Example:
            throttled = orchestrator._create_throttled_callback(my_callback)
            throttled(0.5, "Processing...", None, False)  # May be rate-limited
            throttled(1.0, "Complete", None, True)  # Always fires
        """
        last_update_time: list[float] = [0.0]

        def throttled(
            percent: float,
            message: str,
            operation: Optional[str] = None,
            force: bool = False,
        ) -> None:
            now = time.time()
            # 100ms = 0.1 seconds = max 10 updates per second
            # force=True bypasses throttling for important updates
            if force or now - last_update_time[0] >= 0.1:
                callback(percent, message, operation)
                last_update_time[0] = now

        return throttled

    def execute(
        self,
        module_names: list[str],
        progress_callback: Optional[Callable[[float, str, Optional[str]], None]] = None,
        error_callback: Optional[Callable[[str, ModuleResult], RecoveryAction]] = None,
    ) -> dict[str, ModuleResult]:
        """Execute modules in dependency order with error recovery support.

        This is the main execution method that:
        1. Resolves dependencies to determine execution order
        2. Checks if each module is already installed
        3. Executes modules with progress reporting
        4. Handles failures via the error callback

        Args:
            module_names: List of module names to execute
            progress_callback: Optional callback for progress updates with signature:
                - percent (float): Overall progress from 0.0 to 1.0
                - message (str): Current status message
                - operation (Optional[str]): Detailed operation info (verbose mode)
            error_callback: Optional callback for error recovery decisions.
                When a module fails, this callback is invoked with:
                - module_name (str): Name of the failed module
                - result (ModuleResult): Failure details including recovery command
                Must return a RecoveryAction (RETRY, SKIP, or ABORT).
                If None, defaults to SKIP for optional auto-included modules
                (not explicitly requested), and ABORT for requested or required modules.

        Returns:
            Dictionary mapping module names to their execution results

        Raises:
            ValueError: If unknown modules are requested or circular
                       dependencies are detected

        Example:
            results = orchestrator.execute(
                ["desktop", "ssh"],
                progress_callback=lambda p, m, o: print(f"{p:.0%}: {m}"),
                error_callback=lambda n, r: RecoveryAction.RETRY
            )

            for name, result in results.items():
                print(f"{name}: {result.status.value}")
        """
        # Step 1: Resolve dependencies
        ordered_modules, optional_auto_included = self.resolve_dependencies(module_names)

        # Step 2: Initialize execution context
        context = ExecutionContext(total_modules=len(ordered_modules))

        # Step 3: Create throttled callback if provided
        throttled_callback: Optional[
            Callable[[float, str, Optional[str], bool], None]
        ] = None
        if progress_callback is not None:
            throttled_callback = self._create_throttled_callback(progress_callback)

        # Step 4: Execute modules in order
        for module_name in ordered_modules:
            module = self.modules[module_name]

            # Calculate overall progress
            if context.total_modules > 0:
                overall_progress = context.completed / context.total_modules
            else:
                overall_progress = 1.0

            # Report starting this module
            if throttled_callback is not None:
                throttled_callback(
                    overall_progress,
                    f"Processing module: {module_name}",
                    None,
                    False,
                )

            # Step 4.1: Check if module is already installed
            is_installed, install_msg = module.is_installed()
            if is_installed:
                result = ModuleResult(
                    status=ModuleStatus.SKIPPED,
                    message=install_msg,
                )
                context.results[module_name] = result
                context.skipped.add(module_name)
                context.completed += 1

                if throttled_callback is not None:
                    new_progress = context.completed / context.total_modules
                    throttled_callback(
                        new_progress,
                        f"Skipped {module_name}: {install_msg}",
                        None,
                        False,
                    )
                continue

            # Step 4.2: Check required dependencies succeeded
            failed_required_deps: list[str] = []
            for dep in module.dependencies:
                if not dep.required:
                    # Optional dependencies don't block execution
                    continue

                dep_name = normalize_module_name(dep.module_name)
                dep_result = context.results.get(dep_name)

                if dep_result is None:
                    # Dependency wasn't in the execution list (shouldn't happen
                    # after resolve_dependencies, but handle defensively)
                    failed_required_deps.append(dep_name)
                elif dep_result.status != ModuleStatus.SUCCESS:
                    # Required dependency did not succeed
                    failed_required_deps.append(dep_name)

            if failed_required_deps:
                # Skip this module because required dependencies failed
                failed_deps_str = ", ".join(failed_required_deps)
                result = ModuleResult(
                    status=ModuleStatus.SKIPPED,
                    message=f"Skipped due to failed required dependencies: {failed_deps_str}",
                    recovery_command=module.get_recovery_command(),
                )
                context.results[module_name] = result
                context.skipped.add(module_name)
                context.completed += 1

                if throttled_callback is not None:
                    new_progress = context.completed / context.total_modules
                    throttled_callback(
                        new_progress,
                        f"Skipped {module_name}: required dependencies failed ({failed_deps_str})",
                        None,
                        False,
                    )
                continue

            # Step 4.3: Execute module with retry loop
            while True:
                try:
                    # Create a module-specific progress callback that scales
                    # within the overall progress range
                    def module_progress(
                        percent: float,
                        message: str,
                        operation: Optional[str] = None,
                        _module_name: str = module_name,
                        _base_progress: float = overall_progress,
                        _context: ExecutionContext = context,
                    ) -> None:
                        if throttled_callback is not None:
                            # Scale module progress within its slice of overall progress
                            module_slice = 1.0 / _context.total_modules
                            scaled_progress = _base_progress + (percent * module_slice)
                            throttled_callback(
                                min(scaled_progress, 1.0),
                                f"[{_module_name}] {message}",
                                operation,
                                False,
                            )

                    result = module.run(module_progress)
                    context.results[module_name] = result

                    if result.status == ModuleStatus.SUCCESS:
                        context.completed += 1
                        if throttled_callback is not None:
                            new_progress = context.completed / context.total_modules
                            throttled_callback(
                                new_progress,
                                f"Completed: {module_name}",
                                None,
                                False,
                            )
                        break

                    elif result.status == ModuleStatus.FAILED:
                        # Handle failure via error callback
                        if error_callback is None:
                            # For optional auto-included modules, default to SKIP
                            # For requested or required modules, default to ABORT
                            if module_name in optional_auto_included:
                                action = RecoveryAction.SKIP
                            else:
                                action = RecoveryAction.ABORT
                        else:
                            action = error_callback(module_name, result)

                        if action == RecoveryAction.RETRY:
                            # Continue retry loop
                            continue
                        elif action == RecoveryAction.SKIP:
                            # Update result status and mark as skipped
                            context.results[module_name] = ModuleResult(
                                status=ModuleStatus.SKIPPED,
                                message=f"Skipped after failure: {result.message}",
                                details=result.details,
                                recovery_command=result.recovery_command,
                            )
                            context.skipped.add(module_name)
                            context.completed += 1
                            break
                        else:  # RecoveryAction.ABORT
                            # Return partial results immediately
                            return context.results

                    else:
                        # SKIPPED status from run() - treat as completed
                        context.skipped.add(module_name)
                        context.completed += 1
                        break

                except Exception as e:
                    # Wrap exception in ModuleResult
                    result = ModuleResult(
                        status=ModuleStatus.FAILED,
                        message=str(e),
                        details=None,
                        recovery_command=module.get_recovery_command(),
                    )
                    context.results[module_name] = result

                    # Handle failure via error callback
                    if error_callback is None:
                        # For optional auto-included modules, default to SKIP
                        # For requested or required modules, default to ABORT
                        if module_name in optional_auto_included:
                            action = RecoveryAction.SKIP
                        else:
                            action = RecoveryAction.ABORT
                    else:
                        action = error_callback(module_name, result)

                    if action == RecoveryAction.RETRY:
                        continue
                    elif action == RecoveryAction.SKIP:
                        context.results[module_name] = ModuleResult(
                            status=ModuleStatus.SKIPPED,
                            message=f"Skipped after exception: {e}",
                            recovery_command=module.get_recovery_command(),
                        )
                        context.skipped.add(module_name)
                        context.completed += 1
                        break
                    else:  # RecoveryAction.ABORT
                        return context.results

        # Step 5: Final progress report (force=True to bypass throttling)
        if throttled_callback is not None:
            throttled_callback(1.0, "Execution complete", None, True)

        return context.results

    def get_execution_summary(self, results: dict[str, ModuleResult]) -> dict:
        """Generate a summary of execution results.

        Analyzes the results dictionary to provide aggregate statistics
        about module execution outcomes.

        Args:
            results: Dictionary of module names to their execution results

        Returns:
            Dictionary containing:
                - total: Total number of modules
                - successful: Count of modules with SUCCESS status
                - failed: Count of modules with FAILED status
                - skipped: Count of modules with SKIPPED status
                - success_rate: Ratio of successful to total (0.0-1.0)

        Example:
            results = orchestrator.execute(["apt", "ssh"])
            summary = orchestrator.get_execution_summary(results)
            print(f"Success rate: {summary['success_rate']:.0%}")
        """
        total = len(results)
        successful = sum(
            1 for r in results.values() if r.status == ModuleStatus.SUCCESS
        )
        failed = sum(
            1 for r in results.values() if r.status == ModuleStatus.FAILED
        )
        skipped = sum(
            1 for r in results.values() if r.status == ModuleStatus.SKIPPED
        )

        success_rate = successful / total if total > 0 else 0.0

        return {
            "total": total,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "success_rate": success_rate,
        }

    def validate_modules(self, module_names: list[str]) -> tuple[bool, list[str]]:
        """Validate that all module names exist in the registry.

        Checks each provided module name against the available modules
        in the registry without loading them. Names are normalized before lookup.

        Args:
            module_names: List of module names to validate

        Returns:
            Tuple of (all_valid, invalid_names) where:
                - all_valid: True if all modules exist in registry
                - invalid_names: List of module names that weren't found
                               (returned as originally provided, not normalized)

        Example:
            valid, invalid = orchestrator.validate_modules(["apt", "unknown"])
            if not valid:
                print(f"Unknown modules: {invalid}")
        """
        invalid_names: list[str] = []

        for name in module_names:
            normalized_name = normalize_module_name(name)
            if get_module_class(normalized_name) is None:
                invalid_names.append(name)

        all_valid = len(invalid_names) == 0
        return (all_valid, invalid_names)
