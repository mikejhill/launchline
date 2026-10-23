"""TOML configuration loading and validation.

This module defines the configuration data model
(:class:`EntryConfig`, :class:`LaunchLineConfig`) and provides
:class:`ConfigLoader` for resolving, loading, validating, and
bootstrapping TOML configuration files.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from launchline.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EntryConfig:
    """Configuration for a single launchable entry.

    Attributes:
        name: Display name shown in the launcher menu.
        command: Executable command to run (e.g. ``"pwsh"``).
        args: Additional command-line arguments passed to the command.
        description: Short description shown beside the entry name.
        working_directory: Working directory for the subprocess, or
            ``None`` to inherit the launcher's CWD.
        env: Extra environment variables merged into the subprocess
            environment.
    """

    name: str
    command: str
    args: tuple[str, ...] = ()
    description: str = ""
    working_directory: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    id: str = ""
    menu: MenuConfig | None = None


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Explicit trusted executable and bounded menu generation deadline."""

    entry: EntryConfig
    timeout_seconds: int = 10


@dataclass(frozen=True, slots=True)
class MenuConfig:
    """A static or generated menu with session caching and return policy."""

    entries: tuple[EntryConfig, ...] = ()
    title: str = "LaunchLine"
    provider: ProviderConfig | None = None
    refresh_on_return: bool = False


@dataclass(frozen=True, slots=True)
class LaunchLineConfig:
    """Top-level launcher configuration.

    Attributes:
        entries: Ordered tuple of launchable entries.
        title: Text displayed in the header and terminal title bar.
        on_exit: Behaviour after a launched process exits —
            ``"restart"`` (re-show the menu) or ``"exit"`` (quit).
        show_exit: Whether to display the ``Exit`` option (shortcut
            ``0``) in the menu.
        clear_on_launch: Whether to clear the screen before launching.
        ghost_text: Whether to show an autocomplete hint on the prompt
            line with the highlighted entry's name.
        numeric_trigger: Whether pressing a digit immediately launches
            the matching entry (when <=9 entries and no active query).
            When ``False``, digits always enter the search query and
            fuzzy-match against both numbers and names.
    """

    entries: tuple[EntryConfig, ...]
    title: str = "LaunchLine"
    on_exit: str = "restart"
    show_exit: bool = True
    clear_on_launch: bool = True
    ghost_text: bool = True
    numeric_trigger: bool = True
    provider: ProviderConfig | None = None
    refresh_on_return: bool = False


class ConfigLoader:
    """Resolves, loads, validates, and bootstraps TOML config files.

    All methods are static; the class serves as a logical namespace.
    """

    DEFAULT_PATH: Path = Path.home() / ".config" / "launchline" / "config.toml"
    """Default file-system location for the configuration file."""

    ENV_VAR_NAME: str = "LAUNCHLINE_CONFIG"
    """Environment variable that overrides the default config path."""

    VALID_ON_EXIT: tuple[str, ...] = ("restart", "exit")
    """Permitted values for the ``on_exit`` setting."""

    STARTER_CONFIG: str = """\
# LaunchLine configuration
# See https://github.com/mikejhill/launchline#configuration-reference

[settings]
# title = "LaunchLine"
# on_exit = "restart"   # "restart" (default) or "exit"
# show_exit = true
# clear_on_launch = true
# ghost_text = true
# numeric_trigger = true

[[entries]]
name = "PowerShell"
command = "pwsh"
description = "PowerShell 7"
"""
    """Template written when no config file exists yet."""

    @staticmethod
    def resolve_path(cli_path: Path | None = None) -> Path:
        """Determine the config file path using the resolution order.

        Priority: CLI flag -> environment variable -> default path.
        If no config file exists at any location, a starter config is
        created automatically at :attr:`DEFAULT_PATH`.

        Args:
            cli_path: Explicit path from ``--config`` flag, or ``None``.

        Returns:
            Resolved path to an existing config file.

        Raises:
            ConfigurationError: If a specified path does not exist.
        """
        if cli_path is not None:
            expanded = cli_path.expanduser()
            if not expanded.exists():
                raise ConfigurationError(f"Config file not found: {expanded}")
            return expanded

        env_path = os.environ.get(ConfigLoader.ENV_VAR_NAME)
        if env_path is not None and env_path != "":
            expanded = Path(env_path).expanduser()
            if expanded.exists():
                return expanded
            raise ConfigurationError(
                f"Config file from {ConfigLoader.ENV_VAR_NAME} not found: {expanded}"
            )

        if ConfigLoader.DEFAULT_PATH.exists():
            return ConfigLoader.DEFAULT_PATH

        return ConfigLoader._create_default()

    @staticmethod
    def load(config_path: Path) -> LaunchLineConfig:
        """Load and validate a TOML config file.

        Reads the file, validates all settings and entries, and returns
        a fully populated :class:`LaunchLineConfig`.

        Args:
            config_path: Path to the TOML file.

        Returns:
            A validated ``LaunchLineConfig`` instance.

        Raises:
            ConfigurationError: If the file contains invalid TOML,
                unknown setting values, or malformed entries.
        """
        try:
            with config_path.open("rb") as stream:
                raw = ConfigLoader._table(tomllib.load(stream), "config")
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"Invalid TOML in {config_path}: {exc}") from exc

        settings = ConfigLoader._table(raw.get("settings", {}), "settings")
        title = ConfigLoader._value(settings, "title", "LaunchLine", str)
        on_exit = ConfigLoader._value(settings, "on_exit", "restart", str)
        if on_exit not in ConfigLoader.VALID_ON_EXIT:
            raise ConfigurationError(
                f"Invalid on_exit value: '{on_exit}'. Must be one of: restart, exit"
            )
        menu = ConfigLoader._menu(raw, title, depth=0, root=True)
        return LaunchLineConfig(
            entries=menu.entries,
            title=title,
            provider=menu.provider,
            refresh_on_return=ConfigLoader._value(
                settings, "refresh_on_return", False, bool
            ),
            on_exit=on_exit,
            show_exit=ConfigLoader._value(settings, "show_exit", True, bool),
            clear_on_launch=ConfigLoader._value(
                settings, "clear_on_launch", True, bool
            ),
            ghost_text=ConfigLoader._value(settings, "ghost_text", True, bool),
            numeric_trigger=ConfigLoader._value(
                settings, "numeric_trigger", True, bool
            ),
        )

    @staticmethod
    def _table(value: object, label: str) -> dict[str, object]:
        """Validate an untyped TOML table boundary."""
        if not isinstance(value, dict):
            raise ConfigurationError(f"{label} must be a table.")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConfigurationError(f"{label} keys must be strings.")
            result[key] = item
        return result

    @staticmethod
    def _value[T](
        table: dict[str, object], key: str, default: T, expected: type[T]
    ) -> T:
        """Return a correctly typed scalar without coercion."""
        value = table.get(key, default)
        if not isinstance(value, expected):
            raise ConfigurationError(f"'{key}' must be a {expected.__name__}.")
        if isinstance(value, str) and any(
            ord(char) < 32 or 127 <= ord(char) <= 159 for char in value
        ):
            raise ConfigurationError(f"'{key}' must not contain control characters.")
        return value

    @staticmethod
    def _entry(value: object, index: int, depth: int = 0) -> EntryConfig:
        """Convert one validated entry without losing invalid values."""
        table = ConfigLoader._table(value, f"Entry {index}")
        name = ConfigLoader._value(table, "name", "", str)
        command = ConfigLoader._value(table, "command", "", str)
        submenu = None
        if "menu" in table:
            if "command" in table or any(
                key in table for key in ("args", "env", "working_directory")
            ):
                raise ConfigurationError(
                    f"Entry {index}: menu and command fields are exclusive."
                )
            submenu = ConfigLoader._menu(table["menu"], name, depth=depth + 1)
        if not name or (not command and submenu is None):
            raise ConfigurationError(
                f"Entry {index}: 'name' and 'command' are required."
            )
        args = table.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ConfigurationError(
                f"Entry {index}: 'args' must be a list of strings."
            )
        typed_args = tuple(arg for arg in args if isinstance(arg, str))
        env = ConfigLoader._table(table.get("env", {}), f"Entry {index}: 'env'")
        if not all(isinstance(item, str) for item in env.values()):
            raise ConfigurationError(
                f"Entry {index}: 'env' must be a table of strings."
            )
        typed_env = {key: item for key, item in env.items() if isinstance(item, str)}
        if any("\0" in arg for arg in typed_args) or any(
            not key or "=" in key or "\0" in key or "\0" in item
            for key, item in typed_env.items()
        ):
            raise ConfigurationError(f"Entry {index}: invalid NUL or environment key.")
        wd_text = ConfigLoader._value(table, "working_directory", "", str)
        wd = Path(wd_text).expanduser() if wd_text else None
        if wd is not None and not wd.is_dir():
            logger.warning(
                "Entry '%s': invalid working_directory: %s",
                name,
                wd,
            )
            wd = None
        return EntryConfig(
            name=name,
            command=command,
            args=typed_args,
            description=ConfigLoader._value(table, "description", "", str),
            working_directory=wd,
            env=typed_env,
            id=ConfigLoader._value(table, "id", "", str),
            menu=submenu,
        )

    @staticmethod
    def parse_entries(value: object, *, depth: int = 0) -> tuple[EntryConfig, ...]:
        """Validate entries with shared depth, size and identity rules."""
        if not isinstance(value, list) or len(value) > 1000:
            raise ConfigurationError("entries must be an array of at most 1000 tables.")
        entries = tuple(
            ConfigLoader._entry(item, index, depth)
            for index, item in enumerate(value, 1)
        )
        identities = [entry.id for entry in entries if entry.id]
        if len(set(identities)) != len(identities):
            raise ConfigurationError("Entry ids must be unique within each menu.")
        return entries

    @staticmethod
    def _menu(
        value: object, title: str, *, depth: int, root: bool = False
    ) -> MenuConfig:
        """Parse a menu declaration without executing any configured provider."""
        if depth >= 16:
            raise ConfigurationError(
                "Menus may be nested at most 16 levels including root."
            )
        table = ConfigLoader._table(value, "menu")
        provider = None
        if "provider" in table:
            if "entries" in table:
                raise ConfigurationError(
                    "A menu must declare entries or provider, not both."
                )
            raw = ConfigLoader._table(table["provider"], "provider")
            if "menu" in raw:
                raise ConfigurationError("A provider must be an executable command.")
            executable = ConfigLoader._entry({**raw, "name": "menu provider"}, 1)
            timeout = raw.get("timeout_seconds", 10)
            if type(timeout) is not int or not 1 <= timeout <= 300:
                raise ConfigurationError(
                    "timeout_seconds must be an integer from 1 to 300."
                )
            provider = ProviderConfig(executable, timeout)
        entries = ConfigLoader.parse_entries(table.get("entries", []), depth=depth)
        if root and not entries and provider is None:
            raise ConfigurationError(
                "No entries configured; entries must be a nonempty array of tables."
            )
        return MenuConfig(
            entries,
            ConfigLoader._value(table, "title", title, str),
            provider,
            ConfigLoader._value(table, "refresh_on_return", False, bool),
        )

    @staticmethod
    def _create_default() -> Path:
        """Create a starter config at :attr:`DEFAULT_PATH`.

        Creates parent directories as needed and writes
        :attr:`STARTER_CONFIG` to the file.

        Returns:
            Path to the newly created config file.
        """
        ConfigLoader.DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with ConfigLoader.DEFAULT_PATH.open("x", encoding="utf-8") as stream:
                stream.write(ConfigLoader.STARTER_CONFIG)
        except FileExistsError:
            return ConfigLoader.DEFAULT_PATH
        logger.info("Created starter config at %s", ConfigLoader.DEFAULT_PATH)
        return ConfigLoader.DEFAULT_PATH
