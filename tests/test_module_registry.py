"""Tests for module registry and abstract base class enforcement.

This module validates:
- Registry lookup via get_module_class() with valid/invalid names
- list_modules() output correctness
- Abstract base class enforcement (Module cannot be instantiated directly)
- Immutability of dependencies attribute across module classes

Run with: python -m pytest tests/test_module_registry.py -v
Or standalone: python tests/test_module_registry.py
"""

from __future__ import annotations

import unittest
from typing import Sequence

from gvm.config import Config
from gvm.modules import (
    AVAILABLE_MODULES,
    Dependency,
    Module,
    ModuleResult,
    ModuleStatus,
    get_module_class,
    list_modules,
)
from gvm.modules.apt import APTModule


class TestModuleRegistry(unittest.TestCase):
    """Test cases for module registry functions."""

    def test_get_module_class_valid_name(self) -> None:
        """get_module_class returns correct class for valid module name."""
        module_class = get_module_class("apt")
        self.assertIsNotNone(module_class)
        self.assertIs(module_class, APTModule)

    def test_get_module_class_case_insensitive(self) -> None:
        """get_module_class handles case-insensitive lookups."""
        self.assertIs(get_module_class("APT"), APTModule)
        self.assertIs(get_module_class("Apt"), APTModule)
        self.assertIs(get_module_class("aPt"), APTModule)

    def test_get_module_class_with_whitespace(self) -> None:
        """get_module_class strips whitespace from names."""
        self.assertIs(get_module_class("  apt  "), APTModule)
        self.assertIs(get_module_class("\tapt\n"), APTModule)

    def test_get_module_class_invalid_name(self) -> None:
        """get_module_class returns None for unknown module names."""
        self.assertIsNone(get_module_class("nonexistent"))
        self.assertIsNone(get_module_class(""))
        self.assertIsNone(get_module_class("invalid_module"))

    def test_list_modules_returns_sorted_list(self) -> None:
        """list_modules returns a sorted list of module names."""
        modules = list_modules()
        self.assertIsInstance(modules, list)
        self.assertEqual(modules, sorted(modules))

    def test_list_modules_contains_apt(self) -> None:
        """list_modules includes the apt module."""
        modules = list_modules()
        self.assertIn("apt", modules)

    def test_available_modules_dict_consistency(self) -> None:
        """AVAILABLE_MODULES dict matches list_modules output."""
        modules = list_modules()
        self.assertEqual(set(modules), set(AVAILABLE_MODULES.keys()))


class TestModuleAbstractBase(unittest.TestCase):
    """Test cases for Module abstract base class enforcement."""

    def test_cannot_instantiate_module_directly(self) -> None:
        """Instantiating Module directly raises TypeError."""
        config = Config.load()
        with self.assertRaises(TypeError) as context:
            Module(config)  # type: ignore[abstract]

        # Verify the error mentions abstract methods
        error_msg = str(context.exception)
        self.assertIn("abstract", error_msg.lower())

    def test_subclass_must_implement_abstract_methods(self) -> None:
        """Subclass without abstract methods raises TypeError."""

        class IncompleteModule(Module):
            name = "incomplete"
            description = "Missing abstract methods"
            dependencies = ()

        config = Config.load()
        with self.assertRaises(TypeError) as context:
            IncompleteModule(config)  # type: ignore[abstract]

        error_msg = str(context.exception)
        self.assertIn("abstract", error_msg.lower())

    def test_complete_subclass_can_be_instantiated(self) -> None:
        """Subclass with all abstract methods can be instantiated."""

        class CompleteModule(Module):
            name = "complete"
            description = "Has all required methods"
            dependencies = ()

            def is_installed(self) -> tuple[bool, str]:
                return (False, "Not installed")

            def run(self, progress_callback) -> ModuleResult:
                return ModuleResult(
                    status=ModuleStatus.SUCCESS,
                    message="Done",
                )

        config = Config.load()
        module = CompleteModule(config)
        self.assertIsInstance(module, Module)
        self.assertEqual(module.name, "complete")


class TestDependenciesImmutability(unittest.TestCase):
    """Test cases for dependencies attribute immutability."""

    def test_base_module_dependencies_is_tuple(self) -> None:
        """Module base class dependencies is an immutable tuple."""
        self.assertIsInstance(Module.dependencies, tuple)

    def test_apt_module_dependencies_is_tuple(self) -> None:
        """APTModule dependencies is an immutable tuple."""
        self.assertIsInstance(APTModule.dependencies, tuple)

    def test_dependencies_not_shared_between_classes(self) -> None:
        """Each module class has its own dependencies reference."""

        class ModuleA(Module):
            name = "module_a"
            description = "Test module A"
            dependencies = (Dependency("apt", required=True),)

            def is_installed(self) -> tuple[bool, str]:
                return (False, "")

            def run(self, progress_callback) -> ModuleResult:
                return ModuleResult(status=ModuleStatus.SUCCESS, message="")

        class ModuleB(Module):
            name = "module_b"
            description = "Test module B"
            dependencies = ()

            def is_installed(self) -> tuple[bool, str]:
                return (False, "")

            def run(self, progress_callback) -> ModuleResult:
                return ModuleResult(status=ModuleStatus.SUCCESS, message="")

        # Verify they have different dependencies
        self.assertNotEqual(ModuleA.dependencies, ModuleB.dependencies)
        self.assertEqual(len(ModuleA.dependencies), 1)
        self.assertEqual(len(ModuleB.dependencies), 0)

        # Verify base class dependencies unchanged
        self.assertEqual(len(Module.dependencies), 0)

    def test_dependencies_type_annotation(self) -> None:
        """Module.dependencies has Sequence type annotation."""
        # Access type hints from the class
        hints = Module.__annotations__
        self.assertIn("dependencies", hints)
        # The annotation should be Sequence[Dependency]
        self.assertIn("Sequence", str(hints["dependencies"]))


class TestModuleInstantiation(unittest.TestCase):
    """Test cases for module instantiation and configuration."""

    def test_apt_module_instantiation(self) -> None:
        """APTModule can be instantiated with config."""
        config = Config.load()
        module = APTModule(config)

        self.assertEqual(module.name, "apt")
        self.assertFalse(module.verbose)
        self.assertFalse(module.dry_run)
        self.assertIs(module.config, config)

    def test_apt_module_with_flags(self) -> None:
        """APTModule respects verbose and dry_run flags."""
        config = Config.load()
        module = APTModule(config, verbose=True, dry_run=True)

        self.assertTrue(module.verbose)
        self.assertTrue(module.dry_run)

    def test_get_recovery_command(self) -> None:
        """get_recovery_command returns correct command."""
        config = Config.load()
        module = APTModule(config)

        self.assertEqual(module.get_recovery_command(), "gvm fix apt")


if __name__ == "__main__":
    unittest.main()
