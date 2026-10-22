"""Application controller exit and interrupted-child contracts."""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from launchline.__main__ import Application
from launchline.config import EntryConfig, LaunchLineConfig


class TestApplication:
    """Exercise the controller with input and process boundaries replaced."""

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [(None, 7), (FileNotFoundError, 1), (KeyboardInterrupt, 130)],
    )
    def test_exit_policy_propagates_child_outcome(
        self,
        failure: type[BaseException] | None,
        expected: int,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exit policy propagates exit, spawn failure, and interruption distinctly."""
        config = LaunchLineConfig(
            entries=(EntryConfig("safe", "unused"),),
            on_exit="exit",
            clear_on_launch=False,
        )
        with (
            patch("launchline.keys.KeyReader.read_key", return_value="1"),
            patch(
                "subprocess.run",
                side_effect=failure,
                return_value=subprocess.CompletedProcess([], 7),
            ),
            pytest.raises(SystemExit) as outcome,
        ):
            Application(config).run()
        assert outcome.value.code == expected, (
            "Child outcome must determine launcher status"
        )
        assert "\x1b[?1049l" in capsys.readouterr().out, (
            "Terminal must be restored before launching"
        )

    @pytest.mark.parametrize("failure", [None, FileNotFoundError, KeyboardInterrupt])
    def test_restart_policy_returns_to_menu(
        self, failure: type[BaseException] | None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Restart after normal, failed, or interrupted child, then allow Escape."""
        config = LaunchLineConfig(
            entries=(EntryConfig("safe", "unused"),), clear_on_launch=False
        )
        with (
            patch("launchline.keys.KeyReader.read_key", side_effect=["1", "escape"]),
            patch(
                "subprocess.run",
                side_effect=failure,
                return_value=subprocess.CompletedProcess([], 0),
            ),
            patch("builtins.input", return_value=""),
        ):
            Application(config).run()
        assert capsys.readouterr().out.count("\x1b[?1049l") == 2, (
            "Both menu sessions must restore the screen"
        )

    def test_check_config_does_not_enter_terminal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Validation mode must have no screen or child-process side effects."""
        path = tmp_path / "config.toml"
        path.write_text('[[entries]]\nname="safe"\ncommand="unused"', encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv", ["launchline", "--check-config", "--config", str(path)]
        )
        Application.main()
        assert capsys.readouterr().out == "Configuration valid: 1 entries\n", (
            "Validation output must remain machine-readable"
        )

    def test_interactive_cli_enables_interrupts_before_menu(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The actual CLI must restore inherited interrupt handling before input."""
        path = tmp_path / "config.toml"
        path.write_text('[[entries]]\nname="safe"\ncommand="unused"', encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["launchline", "--config", str(path)])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        with contextlib.ExitStack() as stack:
            handler = None
            if sys.platform == "win32":
                kernel = stack.enter_context(patch("ctypes.WinDLL"))
                handler = kernel.return_value.SetConsoleCtrlHandler
                handler.return_value = 1
            signal = stack.enter_context(patch("signal.signal"))
            stack.enter_context(
                patch("launchline.keys.KeyReader.read_key", return_value="escape")
            )
            Application.main()
        signal.assert_called_once()
        if handler is not None:
            handler.assert_called_once_with(None, False)
        assert "\x1b[?1049l" in capsys.readouterr().out, (
            "Interactive CLI must restore its screen"
        )

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows console API boundary")
    def test_console_interrupt_setup_failure_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OS failure to enable interrupts must fail clearly before the menu."""
        path = tmp_path / "config.toml"
        path.write_text('[[entries]]\nname="safe"\ncommand="unused"', encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["launchline", "--config", str(path)])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        with patch("ctypes.WinDLL") as kernel:
            kernel.return_value.SetConsoleCtrlHandler.return_value = 0
            with pytest.raises(SystemExit) as result:
                Application.main()
        assert result.value.code == 1, "Interrupt-setup failure must return 1"
