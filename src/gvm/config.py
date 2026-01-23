"""Configuration system for GVM tool.

This module implements a layered configuration system with:
- Embedded defaults for zero-config operation
- TOML file support via Python 3.13's tomllib
- Priority chain: embedded defaults → repo config → XDG user config → CLI flags
- Replace-based merging (later values completely override earlier ones)
- Desktop discovery from TOML files in repository and user directories
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Embedded defaults ensure zero-config operation
EMBEDDED_DEFAULTS: dict = {
    "meta": {
        "tool_version": "1.0.0",
        "default_distro": "debian-trixie",
    },
    "environment": {
        "vm_user": "droid",
        "host_name": "GrapheneOS Terminal",
        "port_forward_note": "GrapheneOS Terminal Port Control will prompt to allow this port",
    },
    "ports": {
        "ssh_forward": 2222,
        "ssh_internal": 22,
    },
    "apt": {
        "retries": 10,
        "http_timeout": 60,
        "https_timeout": 60,
        "pipeline_depth": 0,
        "mirrors": [
            "https://deb.debian.org/debian",
            "https://security.debian.org/debian-security",
        ],
        "components": ["main", "contrib", "non-free", "non-free-firmware"],
    },
    "ssh": {
        "permit_root_login": "no",
        "password_auth": True,
        "pubkey_auth": True,
        "listen_address": "0.0.0.0",
    },
    "features": {
        "install_desktop": True,
        "install_shell_mods": True,
        "auto_display": True,
        "show_banner": True,
    },
    "banner": {
        "title": "GrapheneOS Linux VM Status",
        "show_ssh_note": True,
        "ssh_note": "Note: GrapheneOS Terminal Port Control will NOT expose port 22.",
    },
}


def _load_toml(path: Path) -> dict:
    """Load a TOML file and return its contents as a dictionary.

    Args:
        path: Path to the TOML file.

    Returns:
        Dictionary with TOML contents, or empty dict if file doesn't exist.

    Raises:
        SystemExit: If TOML parsing fails with a clear error message.
    """
    if not path.exists():
        return {}

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"Error parsing TOML file '{path}': {e}") from e


def _merge_configs(base: dict, override: dict) -> dict:
    """Merge two configuration dictionaries with full replace strategy.

    When the override dictionary provides a key, its value completely replaces
    the base value without recursive merging. This allows later configs to fully
    replace sections like `apt` or `ssh` rather than partially merging them.

    Args:
        base: Base configuration dictionary.
        override: Override configuration dictionary.

    Returns:
        New dictionary with merged configuration.
    """
    result = base.copy()

    for key, value in override.items():
        # Replace value entirely (no recursive merging)
        result[key] = value

    return result


@dataclass
class DesktopConfig:
    """Configuration for a desktop environment.

    Attributes:
        name: Canonical desktop identifier (lowercase, hyphenated, e.g., 'plasma-mobile').
        display_name: Human-readable name for UI display (e.g., 'Plasma Mobile').
        description: Human-readable description.
        packages_core: Required packages for the desktop.
        packages_optional: Nice-to-have packages.
        packages_wayland_helpers: Wayland support packages.
        packages_user: User-added packages from user config.
        environment_vars: Environment variables to set.
        files: File path → content templates mapping.
        session_start_command: Primary session start command.
        session_fallback_command: Fallback if primary fails.
        session_requires_dbus: Whether to wrap with dbus-run-session.
        session_helper_script_name: Name for helper script.
        conflicts_with: List of desktop names this desktop conflicts with.
        conflict_packages: Packages that conflict with this desktop.
    """

    name: str
    display_name: str = ""
    description: str = ""
    packages_core: list[str] = field(default_factory=list)
    packages_optional: list[str] = field(default_factory=list)
    packages_wayland_helpers: list[str] = field(default_factory=list)
    packages_user: list[str] = field(default_factory=list)
    environment_vars: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    session_start_command: str = ""
    session_fallback_command: str = ""
    session_requires_dbus: bool = True
    session_helper_script_name: str = ""
    conflicts_with: list[str] = field(default_factory=list)
    conflict_packages: list[str] = field(default_factory=list)

    @classmethod
    def from_toml(cls, toml_path: Path) -> DesktopConfig:
        """Load a DesktopConfig from a TOML file.

        Args:
            toml_path: Path to the TOML file.

        Returns:
            DesktopConfig instance populated from TOML data.

        Raises:
            SystemExit: If required fields are missing or TOML parsing fails.
        """
        data = _load_toml(toml_path)

        if not data:
            raise SystemExit(f"Failed to load desktop config from '{toml_path}'")

        meta = data.get("meta", {})
        packages = data.get("packages", {})
        environment = data.get("environment", {})
        files = data.get("files", {})
        session = data.get("session", {})
        conflicts = data.get("conflicts", {})

        name = meta.get("name")
        if not name:
            raise SystemExit(f"Desktop config '{toml_path}' missing required 'meta.name'")

        # Display name defaults to name if not provided
        display_name = meta.get("display_name", name)

        return cls(
            name=name,
            display_name=display_name,
            description=meta.get("description", ""),
            packages_core=packages.get("core", []),
            packages_optional=packages.get("optional", []),
            packages_wayland_helpers=packages.get("wayland_helpers", []),
            packages_user=packages.get("user_packages", []),
            environment_vars=environment.get("vars", []),
            files=files,
            session_start_command=session.get("start_command", ""),
            session_fallback_command=session.get("fallback_command", ""),
            session_requires_dbus=session.get("requires_dbus_session", True),
            session_helper_script_name=session.get("helper_script_name", ""),
            conflicts_with=conflicts.get("desktops", []),
            conflict_packages=conflicts.get("packages", []),
        )

    def get_all_packages(self) -> list[str]:
        """Return combined list of all packages.

        Returns:
            List containing core, optional, wayland_helpers, and user packages.
        """
        return (
            self.packages_core
            + self.packages_optional
            + self.packages_wayland_helpers
            + self.packages_user
        )


@dataclass
class Config:
    """Main configuration container for GVM tool.

    Attributes:
        meta: Tool metadata (version, default_distro).
        environment: Environment settings (vm_user, host_name, etc.).
        ports: Port configuration (ssh_forward, ssh_internal).
        apt: APT configuration (retries, timeouts, mirrors, components).
        ssh: SSH configuration (permit_root_login, password_auth, etc.).
        features: Feature flags (install_desktop, install_shell_mods, etc.).
        banner: Banner display settings (title, ssh_note, etc.).
        selected_desktop: Runtime-set desktop name for installation.
    """

    meta: dict = field(default_factory=dict)
    environment: dict = field(default_factory=dict)
    ports: dict = field(default_factory=dict)
    apt: dict = field(default_factory=dict)
    ssh: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    banner: dict = field(default_factory=dict)

    # Runtime configuration for module execution
    selected_desktop: Optional[str] = field(default=None, repr=False)

    # Internal cache for discovered desktops (not serialized)
    _desktop_cache: Optional[dict[str, "DesktopConfig"]] = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        """Create a Config instance from a dictionary.

        Args:
            data: Dictionary containing configuration data.

        Returns:
            Config instance with validated fields.
        """
        return cls(
            meta=data.get("meta", {}),
            environment=data.get("environment", {}),
            ports=data.get("ports", {}),
            apt=data.get("apt", {}),
            ssh=data.get("ssh", {}),
            features=data.get("features", {}),
            banner=data.get("banner", {}),
        )

    @classmethod
    def load(
        cls,
        cli_config_path: Optional[Path] = None,
        cli_overrides: Optional[dict] = None,
    ) -> Config:
        """Load configuration with priority chain.

        Priority order (later overrides earlier):
        1. Embedded defaults (EMBEDDED_DEFAULTS)
        2. Repository config (config/default.toml)
        3. XDG user config (~/.config/gvm/config.toml)
        4. CLI-specified config file (if provided)
        5. CLI flag overrides (if provided)

        Args:
            cli_config_path: Optional path to CLI-specified config file.
            cli_overrides: Optional dict of CLI flag overrides to apply last.

        Returns:
            Config instance with merged configuration from all sources.
        """
        # Start with deep copy of embedded defaults to prevent shared references
        config_data = copy.deepcopy(EMBEDDED_DEFAULTS)

        # Repository config path (relative to this module in src/gvm/)
        repo_config_path = Path(__file__).parent.parent.parent / "config" / "default.toml"
        if repo_config_path.exists():
            repo_config = _load_toml(repo_config_path)
            config_data = _merge_configs(config_data, repo_config)

        # XDG user config
        user_config_path = Path.home() / ".config" / "gvm" / "config.toml"
        if user_config_path.exists():
            user_config = _load_toml(user_config_path)
            config_data = _merge_configs(config_data, user_config)

        # CLI-specified config file
        if cli_config_path and cli_config_path.exists():
            cli_config = _load_toml(cli_config_path)
            config_data = _merge_configs(config_data, cli_config)

        # CLI flag overrides (highest priority)
        if cli_overrides:
            config_data = _merge_configs(config_data, cli_overrides)

        return cls.from_dict(config_data)

    def discover_desktops(self, force_refresh: bool = False) -> dict[str, DesktopConfig]:
        """Scan and load desktop TOML files from repository and user directories.

        Desktop files are identified by having 'meta.type == "desktop"' in their
        TOML content. User configs can override repository configs with the same name.

        Results are cached for performance. Use force_refresh=True to bypass cache.

        Args:
            force_refresh: If True, bypass cache and re-scan directories.

        Returns:
            Dictionary mapping desktop names to DesktopConfig instances.
        """
        # Return cached result if available
        if self._desktop_cache is not None and not force_refresh:
            return self._desktop_cache

        desktops: dict[str, DesktopConfig] = {}

        # Scan repository packages directory
        repo_packages_dir = Path(__file__).parent.parent.parent / "config" / "packages"
        desktops = self._scan_desktop_directory(repo_packages_dir, desktops)

        # Scan user packages directory (can override repository configs)
        user_packages_dir = Path.home() / ".config" / "gvm" / "packages"
        desktops = self._scan_desktop_directory(user_packages_dir, desktops)

        # Cache the result
        self._desktop_cache = desktops

        return desktops

    def _scan_desktop_directory(
        self, directory: Path, desktops: dict[str, DesktopConfig]
    ) -> dict[str, DesktopConfig]:
        """Scan a directory for desktop TOML files.

        Args:
            directory: Path to scan for TOML files.
            desktops: Existing desktops dictionary to update.

        Returns:
            Updated desktops dictionary.
        """
        if not directory.exists():
            return desktops

        for toml_file in directory.glob("*.toml"):
            try:
                data = _load_toml(toml_file)
                meta = data.get("meta", {})

                # Only process desktop type configs
                if meta.get("type") != "desktop":
                    continue

                desktop_config = DesktopConfig.from_toml(toml_file)
                desktops[desktop_config.name] = desktop_config

            except SystemExit:
                # Skip files that fail to parse
                continue

        return desktops

    # Convenience property accessors for common settings
    @property
    def vm_user(self) -> str:
        """Get the VM user name."""
        return self.environment.get("vm_user", "droid")

    @property
    def host_name(self) -> str:
        """Get the host name."""
        return self.environment.get("host_name", "GrapheneOS Terminal")

    @property
    def ssh_forward_port(self) -> int:
        """Get the SSH forward port."""
        return self.ports.get("ssh_forward", 2222)

    @property
    def ssh_internal_port(self) -> int:
        """Get the SSH internal port."""
        return self.ports.get("ssh_internal", 22)

    @property
    def apt_retries(self) -> int:
        """Get APT retry count."""
        return self.apt.get("retries", 10)

    @property
    def apt_http_timeout(self) -> int:
        """Get APT HTTP timeout."""
        return self.apt.get("http_timeout", 60)

    @property
    def apt_https_timeout(self) -> int:
        """Get APT HTTPS timeout."""
        return self.apt.get("https_timeout", 60)

    @property
    def install_desktop(self) -> bool:
        """Check if desktop installation is enabled."""
        return self.features.get("install_desktop", True)

    @property
    def install_shell_mods(self) -> bool:
        """Check if shell modifications are enabled."""
        return self.features.get("install_shell_mods", True)

    @property
    def show_banner(self) -> bool:
        """Check if banner should be shown."""
        return self.features.get("show_banner", True)
