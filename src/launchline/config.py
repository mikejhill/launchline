"""TOML configuration loading and validation."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from launchline.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "launchline" / "config.toml"
ENV_VAR_NAME = "LAUNCHLINE_CONFIG"
VALID_ON_EXIT = ("restart", "exit")


@dataclass(frozen=True)
class EntryConfig:
    """Configuration for a single launchable entry."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    description: str = ""
    working_directory: Path | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LaunchLineConfig:
    """Top-level launcher configuration."""

    entries: tuple[EntryConfig, ...]
    on_exit: str = "restart"
    title: str = "LaunchLine"
    clear_on_launch: bool = True
    show_exit: bool = True


def resolve_config_path(cli_path: Path | None = None) -> Path:
    """Determine the config file path using the resolution order.

    Priority: CLI flag > environment variable > default path.

    Args:
        cli_path: Explicit path from ``--config`` flag, or None.

    Returns:
        Resolved path to an existing config file.

    Raises:
        ConfigurationError: If no config file is found.
    """
    if cli_path is not None:
        expanded = cli_path.expanduser()
        if not expanded.exists():
            raise ConfigurationError(f"Config file not found: {expanded}")
        return expanded

    env_path = os.environ.get(ENV_VAR_NAME)
    if env_path:
        expanded = Path(env_path).expanduser()
        if expanded.exists():
            return expanded
        raise ConfigurationError(
            f"Config file from {ENV_VAR_NAME} not found: {expanded}"
        )

    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH

    return _create_default_config()


STARTER_CONFIG = """\
# LaunchLine configuration
# See https://github.com/mikejhill/LaunchLine#configuration-reference

[settings]
# on_exit = "restart"   # "restart" (default) or "exit"
# title = "LaunchLine"
# clear_on_launch = true
# show_exit = true

[[entries]]
name = "PowerShell"
command = "pwsh"
description = "PowerShell 7"
"""


def _create_default_config() -> Path:
    """Create a starter config at the default path.

    Returns:
        Path to the newly created config file.
    """
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CONFIG_PATH.write_text(STARTER_CONFIG, encoding="utf-8")
    logger.info("Created starter config at %s", DEFAULT_CONFIG_PATH)
    return DEFAULT_CONFIG_PATH


def load_config(config_path: Path) -> LaunchLineConfig:
    """Load and validate a TOML config file.

    Args:
        config_path: Path to the TOML file.

    Returns:
        Validated LaunchLineConfig.

    Raises:
        ConfigurationError: If the file is invalid or has missing fields.
    """
    try:
        with config_path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {config_path}: {exc}") from exc

    settings = raw.get("settings", {})

    on_exit = settings.get("on_exit", "restart")
    if on_exit not in VALID_ON_EXIT:
        raise ConfigurationError(
            f"Invalid on_exit value: '{on_exit}'. "
            f"Must be one of: {', '.join(VALID_ON_EXIT)}"
        )

    title: str = settings.get("title", "LaunchLine")
    clear_on_launch: bool = settings.get("clear_on_launch", True)
    show_exit: bool = settings.get("show_exit", True)

    raw_entries: list[dict[str, object]] = raw.get("entries", [])
    if not raw_entries:
        raise ConfigurationError("No entries configured.")

    entries: list[EntryConfig] = []
    for i, entry_raw in enumerate(raw_entries, 1):
        name = entry_raw.get("name", "")
        command = entry_raw.get("command", "")
        if not name or not command:
            raise ConfigurationError(f"Entry {i}: 'name' and 'command' are required.")

        raw_args = entry_raw.get("args", [])
        if not isinstance(raw_args, list):
            raise ConfigurationError(f"Entry {i}: 'args' must be a list of strings.")

        wd_raw = entry_raw.get("working_directory")
        wd: Path | None = None
        if wd_raw:
            wd = Path(str(wd_raw)).expanduser()
            if not wd.exists():
                logger.warning(
                    "Entry '%s': working_directory does not exist: %s", name, wd
                )
                wd = None

        raw_env = entry_raw.get("env", {})
        if not isinstance(raw_env, dict):
            raise ConfigurationError(f"Entry {i}: 'env' must be a table of strings.")

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
        on_exit=on_exit,
        title=title,
        clear_on_launch=clear_on_launch,
        show_exit=show_exit,
    )
