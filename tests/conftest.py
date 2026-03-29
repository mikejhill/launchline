"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from launchline.config import EntryConfig, LaunchLineConfig


@pytest.fixture
def sample_config() -> LaunchLineConfig:
    """A typical launcher config with a few entries."""
    return LaunchLineConfig(
        entries=(
            EntryConfig(name="GitHub Copilot CLI", command="copilot"),
            EntryConfig(name="Claude Code", command="claude"),
            EntryConfig(
                name="Codex CLI",
                command="codex",
                args=("--full-auto",),
                description="OpenAI coding agent",
            ),
            EntryConfig(name="PowerShell", command="pwsh", description="PowerShell 7"),
        ),
        on_exit="restart",
        title="Test LaunchLine",
    )


@pytest.fixture
def many_entries_config() -> LaunchLineConfig:
    """A config with >9 entries to exercise numeric disambiguation."""
    entries = tuple(
        EntryConfig(name=f"Tool {i}", command=f"tool-{i}") for i in range(1, 13)
    )
    return LaunchLineConfig(entries=entries)


@pytest.fixture
def sample_toml(tmp_path: Path) -> Path:
    """Write a valid TOML config file and return its path."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """\
[settings]
on_exit = "restart"
title = "Test"

[[entries]]
name = "Alpha"
command = "alpha-cmd"
description = "First tool"

[[entries]]
name = "Beta"
command = "beta-cmd"
""",
        encoding="utf-8",
    )
    return config_file
