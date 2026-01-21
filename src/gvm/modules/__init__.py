"""
GVM Module System.

This module provides the registry and lookup functions for all GVM modules.
Concrete module implementations are registered in AVAILABLE_MODULES and can
be retrieved by name using get_module_class().

Public API:
    AVAILABLE_MODULES: Dict mapping normalized module names to module classes
    get_module_class(name): Retrieve a module class by name
    list_modules(): Get a list of all available module names

Re-exported from base:
    Module, ModuleStatus, ModuleResult, Dependency, RecoveryAction
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gvm.modules.apt import APTModule
from gvm.modules.base import (
    Dependency,
    Module,
    ModuleResult,
    ModuleStatus,
    RecoveryAction,
)
from gvm.modules.desktop import DesktopModule
from gvm.modules.gui import GUIModule
from gvm.modules.shell import ShellModule
from gvm.modules.ssh import SSHModule

if TYPE_CHECKING:
    from typing import Optional

# Registry of available modules, mapping normalized names to module classes.
AVAILABLE_MODULES: dict[str, type[Module]] = {
    "apt": APTModule,
    "desktop": DesktopModule,
    "ssh": SSHModule,
    "shell": ShellModule,
    "gui": GUIModule,
}

__all__ = [
    # Registry
    "AVAILABLE_MODULES",
    "get_module_class",
    "list_modules",
    # Utility
    "normalize_module_name",
    # Re-exported from base
    "Dependency",
    "Module",
    "ModuleResult",
    "ModuleStatus",
    "RecoveryAction",
]


def normalize_module_name(name: str) -> str:
    """Normalize a module name for consistent lookup.

    Converts the name to lowercase and strips whitespace to ensure
    consistent matching regardless of how the name is provided.

    Args:
        name: The module name to normalize

    Returns:
        Normalized module name string
    """
    return name.lower().strip()


def get_module_class(name: str) -> Optional[type[Module]]:
    """Retrieve a module class by name.

    Performs a case-insensitive lookup against AVAILABLE_MODULES.

    Args:
        name: The module name to look up (case-insensitive)

    Returns:
        The module class if found, None otherwise

    Example:
        >>> module_cls = get_module_class("apt")
        >>> if module_cls:
        ...     module = module_cls(config)
    """
    normalized = normalize_module_name(name)
    return AVAILABLE_MODULES.get(normalized)


def list_modules() -> list[str]:
    """Get a list of all available module names.

    Returns:
        Sorted list of module name strings

    Example:
        >>> for name in list_modules():
        ...     print(f"Available: {name}")
    """
    return sorted(AVAILABLE_MODULES.keys())
