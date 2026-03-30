"""Tests for the command-line interface argument parser."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from launchline.cli import CommandLineInterface


class TestParseArgs:
    """Tests for CommandLineInterface.parse_args."""

    def test_no_args_returns_none_config(self) -> None:
        """Default invocation leaves config unset."""
        args = CommandLineInterface.parse_args([])
        assert args.config is None, (
            f"Expected config=None with no arguments, got {args.config!r}"
        )

    def test_no_args_defaults_to_warning_level(self) -> None:
        """Default log level is WARNING (int 30)."""
        args = CommandLineInterface.parse_args([])
        assert args.log_level == logging.WARNING, (
            f"Expected log_level=WARNING ({logging.WARNING}), got {args.log_level}"
        )

    def test_config_flag_returns_path(self, tmp_path: Path) -> None:
        """--config stores a Path object."""
        cfg = tmp_path / "custom.toml"
        args = CommandLineInterface.parse_args(["--config", str(cfg)])
        assert args.config == cfg, f"Expected config={cfg}, got {args.config}"

    @pytest.mark.parametrize(
        ("level_name", "level_int"),
        [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
        ],
    )
    def test_log_level_converted_to_int(self, level_name: str, level_int: int) -> None:
        """Each --log-level choice maps to its logging module constant."""
        args = CommandLineInterface.parse_args(["--log-level", level_name])
        assert args.log_level == level_int, (
            f"--log-level {level_name} should map to {level_int}, got {args.log_level}"
        )

    def test_invalid_log_level_exits_with_error(self) -> None:
        """Unrecognised --log-level causes a non-zero exit."""
        with pytest.raises(SystemExit) as exc_info:
            CommandLineInterface.parse_args(["--log-level", "TRACE"])
        assert exc_info.value.code != 0, (
            f"Expected non-zero exit for invalid log level, got {exc_info.value.code}"
        )

    def test_help_flag_exits_cleanly(self) -> None:
        """--help exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            CommandLineInterface.parse_args(["--help"])
        assert exc_info.value.code == 0, (
            f"Expected exit code 0 for --help, got {exc_info.value.code}"
        )

    def test_unknown_argument_exits_with_error(self) -> None:
        """Unrecognised arguments cause a non-zero exit."""
        with pytest.raises(SystemExit) as exc_info:
            CommandLineInterface.parse_args(["--nope"])
        assert exc_info.value.code != 0, (
            f"Expected non-zero exit for unknown flag, got {exc_info.value.code}"
        )

    def test_config_and_log_level_together(self, tmp_path: Path) -> None:
        """Both flags can be combined."""
        cfg = tmp_path / "my.toml"
        args = CommandLineInterface.parse_args(
            ["--config", str(cfg), "--log-level", "DEBUG"]
        )
        assert args.config == cfg, f"Expected config={cfg}, got {args.config}"
        assert args.log_level == logging.DEBUG, (
            f"Expected DEBUG ({logging.DEBUG}), got {args.log_level}"
        )

    def test_icon_path_flag_parsed(self) -> None:
        """--icon-path flag is stored as boolean True."""
        args = CommandLineInterface.parse_args(["--icon-path"])
        assert args.icon_path is True, (
            f"Expected icon_path=True, got {args.icon_path!r}"
        )

    def test_icon_path_defaults_to_false(self) -> None:
        """icon_path defaults to False when not specified."""
        args = CommandLineInterface.parse_args([])
        assert args.icon_path is False, (
            f"Expected icon_path=False by default, got {args.icon_path!r}"
        )

    def test_config_path_flag_parsed(self) -> None:
        """--config-path flag is stored as boolean True."""
        args = CommandLineInterface.parse_args(["--config-path"])
        assert args.config_path is True, (
            f"Expected config_path=True, got {args.config_path!r}"
        )

    def test_config_path_defaults_to_false(self) -> None:
        """config_path defaults to False when not specified."""
        args = CommandLineInterface.parse_args([])
        assert args.config_path is False, (
            f"Expected config_path=False by default, got {args.config_path!r}"
        )


class TestIconPath:
    """Tests for CommandLineInterface.icon_path."""

    def test_icon_path_returns_existing_file(self) -> None:
        """Bundled icon file must exist at the returned path."""
        path = CommandLineInterface.icon_path()
        assert path.exists(), f"Bundled icon not found at {path}"
        assert path.suffix == ".ico", f"Expected .ico file, got {path.suffix}"


class TestConfigPathFlag:
    """Tests for --config-path flag behaviour via main()."""

    def test_prints_explicit_config_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--config-path with --config prints the explicit path."""
        cfg = tmp_path / "custom.toml"
        cfg.write_text("[settings]\n[[entries]]\nname='x'\ncommand='y'\n")

        from launchline.__main__ import main

        monkeypatch.setattr(
            "sys.argv", ["launchline", "--config-path", "--config", str(cfg)],
        )
        main()
        assert capsys.readouterr().out.strip() == str(cfg), (
            "Expected --config-path to print the explicit config file path"
        )

    def test_prints_default_config_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--config-path without --config resolves via standard lookup."""
        cfg = tmp_path / "config.toml"
        cfg.write_text("[settings]\n[[entries]]\nname='x'\ncommand='y'\n")

        from launchline.__main__ import main
        from launchline.config import ConfigLoader

        monkeypatch.setattr(ConfigLoader, "DEFAULT_PATH", cfg)
        monkeypatch.setattr("sys.argv", ["launchline", "--config-path"])
        monkeypatch.delenv("LAUNCHLINE_CONFIG", raising=False)
        main()
        assert capsys.readouterr().out.strip() == str(cfg), (
            "Expected --config-path to print the default config file path"
        )
