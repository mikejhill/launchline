"""Tests for TOML configuration loading and validation."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from launchline.config import (
    ConfigLoader,
    EntryConfig,
    LaunchLineConfig,
)
from launchline.exceptions import ConfigurationError

_README = Path(__file__).resolve().parent.parent / "README.md"


class TestLoadConfig:
    """Tests for ConfigLoader.load."""

    def test_loads_valid_config(self, sample_toml: Path) -> None:
        config = ConfigLoader.load(sample_toml)
        assert isinstance(config, LaunchLineConfig), (
            f"Expected LaunchLineConfig, got {type(config).__name__}"
        )
        assert len(config.entries) == 2, (
            f"Expected 2 entries, got {len(config.entries)}"
        )

    def test_default_settings(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[[entries]]\nname = "X"\ncommand = "x"\n', encoding="utf-8")
        config = ConfigLoader.load(cfg)
        assert config.on_exit == "restart", (
            f"Default on_exit should be 'restart', got {config.on_exit!r}"
        )
        assert config.title == "LaunchLine", (
            f"Default title should be 'LaunchLine', got {config.title!r}"
        )
        assert config.clear_on_launch is True, "Default clear_on_launch should be True"
        assert config.ghost_text is True, "Default ghost_text should be True"
        assert config.numeric_trigger is True, "Default numeric_trigger should be True"

    def test_custom_settings(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[settings]\non_exit = "exit"\ntitle = "My Launcher"\n'
            "clear_on_launch = false\n"
            "ghost_text = false\n"
            "numeric_trigger = false\n\n"
            '[[entries]]\nname = "X"\ncommand = "x"\n',
            encoding="utf-8",
        )
        config = ConfigLoader.load(cfg)
        assert config.on_exit == "exit", (
            f"Custom on_exit should be 'exit', got {config.on_exit!r}"
        )
        assert config.title == "My Launcher", (
            f"Custom title should be 'My Launcher', got {config.title!r}"
        )
        assert config.clear_on_launch is False, "Custom clear_on_launch should be False"
        assert config.ghost_text is False, "Custom ghost_text should be False"
        assert config.numeric_trigger is False, "Custom numeric_trigger should be False"

    def test_entry_args_parsed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\nargs = ["--flag", "val"]\n',
            encoding="utf-8",
        )
        config = ConfigLoader.load(cfg)
        assert config.entries[0].args == ("--flag", "val")

    def test_entry_env_parsed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\n[entries.env]\nFOO = "bar"\n',
            encoding="utf-8",
        )
        config = ConfigLoader.load(cfg)
        assert config.entries[0].env == {"FOO": "bar"}

    def test_rejects_empty_entries(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("[settings]\n", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="No entries configured"):
            ConfigLoader.load(cfg)

    def test_rejects_missing_name(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[[entries]]\ncommand = "x"\n', encoding="utf-8")
        with pytest.raises(ConfigurationError, match="'name' and 'command'"):
            ConfigLoader.load(cfg)

    def test_rejects_missing_command(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[[entries]]\nname = "X"\n', encoding="utf-8")
        with pytest.raises(ConfigurationError, match="'name' and 'command'"):
            ConfigLoader.load(cfg)

    def test_rejects_invalid_on_exit(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[settings]\non_exit = "crash"\n\n[[entries]]\nname = "X"\ncommand = "x"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match="Invalid on_exit"):
            ConfigLoader.load(cfg)

    def test_rejects_malformed_toml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("this is not valid toml [[[", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="Invalid TOML"):
            ConfigLoader.load(cfg)

    def test_working_directory_expanded(self, tmp_path: Path) -> None:
        wd = tmp_path / "work"
        wd.mkdir()
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            f'[[entries]]\nname = "X"\ncommand = "x"\n'
            f'working_directory = "{wd.as_posix()}"\n',
            encoding="utf-8",
        )
        config = ConfigLoader.load(cfg)
        assert config.entries[0].working_directory == wd, (
            f"Expected working_directory={wd}, "
            f"got {config.entries[0].working_directory}"
        )

    def test_missing_working_directory_becomes_none(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\n'
            'working_directory = "/nonexistent/path"\n',
            encoding="utf-8",
        )
        config = ConfigLoader.load(cfg)
        assert config.entries[0].working_directory is None, (
            "Non-existent working_directory should resolve to None"
        )

    def test_rejects_invalid_args_type(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\nargs = "not-a-list"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match="'args' must be a list"):
            ConfigLoader.load(cfg)

    def test_rejects_invalid_env_type(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[[entries]]\nname = "X"\ncommand = "x"\nenv = "not-a-table"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match="'env' must be a table"):
            ConfigLoader.load(cfg)


class TestResolveConfigPath:
    """Tests for ConfigLoader.resolve_path."""

    def test_cli_path_takes_priority(self, sample_toml: Path) -> None:
        result = ConfigLoader.resolve_path(sample_toml)
        assert result == sample_toml

    def test_cli_path_missing_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.toml"
        with pytest.raises(ConfigurationError, match="not found"):
            ConfigLoader.resolve_path(missing)

    def test_env_var_path(
        self, sample_toml: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ConfigLoader.ENV_VAR_NAME, str(sample_toml))
        result = ConfigLoader.resolve_path(None)
        assert result == sample_toml

    def test_env_var_missing_file_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ConfigLoader.ENV_VAR_NAME, str(tmp_path / "nope.toml"))
        with pytest.raises(ConfigurationError, match=ConfigLoader.ENV_VAR_NAME):
            ConfigLoader.resolve_path(None)

    def test_no_config_creates_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ConfigLoader.ENV_VAR_NAME, raising=False)
        default_path = tmp_path / "launchline" / "config.toml"
        monkeypatch.setattr(
            "launchline.config.ConfigLoader.DEFAULT_PATH",
            default_path,
        )
        result = ConfigLoader.resolve_path(None)
        assert result == default_path
        assert default_path.exists(), "Default config file should have been created"
        assert default_path.read_text(encoding="utf-8") == (
            ConfigLoader.STARTER_CONFIG
        ), "Default config should contain STARTER_CONFIG"

    def test_created_config_is_loadable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ConfigLoader.ENV_VAR_NAME, raising=False)
        default_path = tmp_path / "launchline" / "config.toml"
        monkeypatch.setattr(
            "launchline.config.ConfigLoader.DEFAULT_PATH",
            default_path,
        )
        config_path = ConfigLoader.resolve_path(None)
        config = ConfigLoader.load(config_path)
        assert len(config.entries) >= 1, (
            "Auto-created config should have at least 1 entry"
        )


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
        for value in ConfigLoader.VALID_ON_EXIT:
            assert f"`{value}`" in text or f'`"{value}"`' in text, (
                f"on_exit value '{value}' not documented in README"
            )
