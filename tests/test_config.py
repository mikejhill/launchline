"""Tests for TOML configuration loading and validation."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from launchline.config import (
    ENV_VAR_NAME,
    STARTER_CONFIG,
    VALID_ON_EXIT,
    EntryConfig,
    LaunchLineConfig,
    load_config,
    resolve_config_path,
)
from launchline.exceptions import ConfigurationError

_README = Path(__file__).resolve().parent.parent / "README.md"


class TestLoadConfig:
    """Tests for the load_config function."""

    def test_loads_valid_config(self, sample_toml: Path) -> None:
        config = load_config(sample_toml)
        assert isinstance(config, LaunchLineConfig)
        assert len(config.entries) == 2
        assert config.entries[0].name == "Alpha"
        assert config.entries[0].command == "alpha-cmd"
        assert config.entries[0].description == "First tool"
        assert config.entries[1].name == "Beta"

    def test_default_settings(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[[entries]]\nname = "X"\ncommand = "x"\n', encoding="utf-8")
        config = load_config(cfg)
        assert config.on_exit == "restart"
        assert config.title == "LaunchLine"
        assert config.clear_on_launch is True

    def test_custom_settings(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[settings]\non_exit = "exit"\ntitle = "My Launcher"\n'
            "clear_on_launch = false\n\n"
            '[[entries]]\nname = "X"\ncommand = "x"\n',
            encoding="utf-8",
        )
        config = load_config(cfg)
        assert config.on_exit == "exit"
        assert config.title == "My Launcher"
        assert config.clear_on_launch is False

    def test_entry_args_parsed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\nargs = ["--flag", "val"]\n',
            encoding="utf-8",
        )
        config = load_config(cfg)
        assert config.entries[0].args == ("--flag", "val")

    def test_entry_env_parsed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\n[entries.env]\nFOO = "bar"\n',
            encoding="utf-8",
        )
        config = load_config(cfg)
        assert config.entries[0].env == {"FOO": "bar"}

    def test_rejects_empty_entries(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("[settings]\n", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="No entries configured"):
            load_config(cfg)

    def test_rejects_missing_name(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[[entries]]\ncommand = "x"\n', encoding="utf-8")
        with pytest.raises(ConfigurationError, match="'name' and 'command'"):
            load_config(cfg)

    def test_rejects_missing_command(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[[entries]]\nname = "X"\n', encoding="utf-8")
        with pytest.raises(ConfigurationError, match="'name' and 'command'"):
            load_config(cfg)

    def test_rejects_invalid_on_exit(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[settings]\non_exit = "crash"\n\n[[entries]]\nname = "X"\ncommand = "x"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match="Invalid on_exit"):
            load_config(cfg)

    def test_rejects_malformed_toml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("this is not valid toml [[[", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="Invalid TOML"):
            load_config(cfg)

    def test_working_directory_expanded(self, tmp_path: Path) -> None:
        wd = tmp_path / "work"
        wd.mkdir()
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            f'[[entries]]\nname = "X"\ncommand = "x"\n'
            f'working_directory = "{wd.as_posix()}"\n',
            encoding="utf-8",
        )
        config = load_config(cfg)
        assert config.entries[0].working_directory == wd

    def test_missing_working_directory_becomes_none(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\n'
            'working_directory = "/nonexistent/path"\n',
            encoding="utf-8",
        )
        config = load_config(cfg)
        assert config.entries[0].working_directory is None

    def test_rejects_invalid_args_type(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\nargs = "not-a-list"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match="'args' must be a list"):
            load_config(cfg)

    def test_rejects_invalid_env_type(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\nenv = "not-a-table"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match="'env' must be a table"):
            load_config(cfg)


class TestResolveConfigPath:
    """Tests for the resolve_config_path function."""

    def test_cli_path_takes_priority(self, sample_toml: Path) -> None:
        result = resolve_config_path(sample_toml)
        assert result == sample_toml

    def test_cli_path_missing_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.toml"
        with pytest.raises(ConfigurationError, match="not found"):
            resolve_config_path(missing)

    def test_env_var_path(
        self, sample_toml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_VAR_NAME, str(sample_toml))
        result = resolve_config_path(None)
        assert result == sample_toml

    def test_env_var_missing_file_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_VAR_NAME, str(tmp_path / "nope.toml"))
        with pytest.raises(ConfigurationError, match=ENV_VAR_NAME):
            resolve_config_path(None)

    def test_no_config_creates_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        default_path = tmp_path / "launchline" / "config.toml"
        monkeypatch.setattr(
            "launchline.config.DEFAULT_CONFIG_PATH",
            default_path,
        )
        result = resolve_config_path(None)
        assert result == default_path
        assert default_path.exists()
        assert default_path.read_text(encoding="utf-8") == STARTER_CONFIG

    def test_created_config_is_loadable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        default_path = tmp_path / "launchline" / "config.toml"
        monkeypatch.setattr(
            "launchline.config.DEFAULT_CONFIG_PATH",
            default_path,
        )
        config_path = resolve_config_path(None)
        config = load_config(config_path)
        assert len(config.entries) >= 1


class TestConfigReferenceSync:
    """Verify the README config reference matches the actual code."""

    @staticmethod
    def _readme_table_keys(heading: str) -> set[str]:
        """Extract the first-column keys from a markdown table under *heading*."""
        text = _README.read_text(encoding="utf-8")
        escaped = re.escape(heading)
        pattern = (
            rf"### {escaped}\s*\n(?:.*\n)*?"
            r"\|.*\|.*\|\n\|[-\s|:]+\|\n((?:\|.*\|\n)*)"
        )
        m = re.search(pattern, text)
        assert m, f"Table under '{heading}' not found in README"
        keys: set[str] = set()
        for line in m.group(1).strip().splitlines():
            cells = [c.strip() for c in line.split("|")]
            # cells[0] is empty (before first |), cells[1] is the key
            key = cells[1].strip("`").strip()
            if key:
                keys.add(key)
        return keys

    def test_settings_fields_match_readme(self) -> None:
        code_fields = {f.name for f in dataclasses.fields(LaunchLineConfig)} - {
            "entries"
        }
        readme_fields = self._readme_table_keys("`[settings]`")
        assert readme_fields == code_fields

    def test_entry_fields_match_readme(self) -> None:
        code_fields = {f.name for f in dataclasses.fields(EntryConfig)}
        readme_fields = self._readme_table_keys("`[[entries]]`")
        assert readme_fields == code_fields

    def test_valid_on_exit_values_in_readme(self) -> None:
        text = _README.read_text(encoding="utf-8")
        for value in VALID_ON_EXIT:
            assert f"`{value}`" in text or f'`"{value}"`' in text
