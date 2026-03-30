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
