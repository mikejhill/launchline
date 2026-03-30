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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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
            the matching entry (when ≤9 entries and no active query).
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

        Priority: CLI flag → environment variable → default path.
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
        if env_path:
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
            with config_path.open("rb") as f:
                raw = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"Invalid TOML in {config_path}: {exc}") from exc

        settings = raw.get("settings", {})

        title: str = settings.get("title", "LaunchLine")

        on_exit = settings.get("on_exit", "restart")
        if on_exit not in ConfigLoader.VALID_ON_EXIT:
            raise ConfigurationError(
                f"Invalid on_exit value: '{on_exit}'. "
                f"Must be one of: {', '.join(ConfigLoader.VALID_ON_EXIT)}"
            )

        show_exit: bool = settings.get("show_exit", True)
        clear_on_launch: bool = settings.get("clear_on_launch", True)
        ghost_text: bool = settings.get("ghost_text", True)
        numeric_trigger: bool = settings.get("numeric_trigger", True)

        raw_entries: list[dict[str, object]] = raw.get("entries", [])
        if not raw_entries:
            raise ConfigurationError("No entries configured.")

        entries: list[EntryConfig] = []
        for i, entry_raw in enumerate(raw_entries, 1):
            name = entry_raw.get("name", "")
            command = entry_raw.get("command", "")
            if not name or not command:
                raise ConfigurationError(
                    f"Entry {i}: 'name' and 'command' are required."
                )

            raw_args = entry_raw.get("args", [])
            if not isinstance(raw_args, list):
                raise ConfigurationError(
                    f"Entry {i}: 'args' must be a list of strings."
                )

            wd_raw = entry_raw.get("working_directory")
            wd: Path | None = None
            if wd_raw:
                wd = Path(str(wd_raw)).expanduser()
                if not wd.exists():
                    logger.warning(
                        "Entry '%s': working_directory does not exist: %s",
                        name,
                        wd,
                    )
                    wd = None

            raw_env = entry_raw.get("env", {})
            if not isinstance(raw_env, dict):
                raise ConfigurationError(
                    f"Entry {i}: 'env' must be a table of strings."
                )

            entries.append(
                EntryConfig(
                    name=str(name),
                    command=str(command),
                    args=tuple(str(a) for a in raw_args),
                    description=str(entry_raw.get("description", "")),
                    working_directory=wd,
                    env={str(k): str(v) for k, v in raw_env.items()},
                )
            )

        return LaunchLineConfig(
            entries=tuple(entries),
            title=title,
            on_exit=on_exit,
            show_exit=show_exit,
            clear_on_launch=clear_on_launch,
            ghost_text=ghost_text,
            numeric_trigger=numeric_trigger,
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
        ConfigLoader.DEFAULT_PATH.write_text(
            ConfigLoader.STARTER_CONFIG, encoding="utf-8"
        )
        logger.info("Created starter config at %s", ConfigLoader.DEFAULT_PATH)
        return ConfigLoader.DEFAULT_PATH
