"""Tests for subprocess execution and post-exit logic."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.exceptions import LaunchError
from launchline.runner import EntryRunner


class TestEntryRunner:
    """Tests for the EntryRunner class."""

    def _make_runner(
        self,
        *,
        clear_on_launch: bool = False,
        on_exit: str = "restart",
    ) -> EntryRunner:
        config = LaunchLineConfig(
            entries=(),
            on_exit=on_exit,
            clear_on_launch=clear_on_launch,
        )
        return EntryRunner(config)

    @patch("launchline.runner.subprocess.run")
    def test_launches_command_with_args(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Test", command="my-tool", args=("--flag",))
        runner = self._make_runner()

        exit_code = runner.launch(entry)

        assert exit_code == 0
        call_args = mock_run.call_args
        assert call_args[0][0] == ["my-tool", "--flag"]

    @patch("launchline.runner.subprocess.run")
    def test_returns_subprocess_exit_code(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=42)
        entry = EntryConfig(name="Test", command="my-tool")
        runner = self._make_runner()

        assert runner.launch(entry) == 42

    @patch("launchline.runner.subprocess.run")
    def test_sets_env_on_subprocess(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Test", command="my-tool", env={"MY_VAR": "my_value"})
        runner = self._make_runner()
        runner.launch(entry)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["MY_VAR"] == "my_value"

    @patch("launchline.runner.subprocess.run")
    def test_sets_cwd_on_subprocess(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Test", command="my-tool", working_directory=tmp_path)
        runner = self._make_runner()
        runner.launch(entry)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == str(tmp_path)

    @patch("launchline.runner.subprocess.run")
    def test_no_cwd_when_not_configured(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Test", command="my-tool")
        runner = self._make_runner()
        runner.launch(entry)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] is None

    @patch("launchline.runner.subprocess.run")
    def test_raises_launch_error_on_file_not_found(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("not found")
        entry = EntryConfig(name="Test", command="nonexistent-tool")
        runner = self._make_runner()

        with pytest.raises(LaunchError, match="Command not found"):
            runner.launch(entry)

    @patch("launchline.runner.subprocess.run")
    def test_raises_launch_error_on_os_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("permission denied")
        entry = EntryConfig(name="Test", command="my-tool")
        runner = self._make_runner()

        with pytest.raises(LaunchError, match="permission denied"):
            runner.launch(entry)

    @patch("launchline.runner.EntryRunner._clear_screen")
    @patch("launchline.runner.subprocess.run")
    def test_clears_screen_when_configured(
        self, mock_run: MagicMock, mock_clear: MagicMock
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Test", command="my-tool")
        runner = self._make_runner(clear_on_launch=True)
        runner.launch(entry)

        mock_clear.assert_called_once()

    @patch("launchline.runner.EntryRunner._clear_screen")
    @patch("launchline.runner.subprocess.run")
    def test_skips_clear_when_not_configured(
        self, mock_run: MagicMock, mock_clear: MagicMock
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Test", command="my-tool")
        runner = self._make_runner(clear_on_launch=False)
        runner.launch(entry)

        mock_clear.assert_not_called()

    @patch("launchline.runner.subprocess.run")
    def test_expands_tilde_in_env_values(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(
            name="Test", command="my-tool", env={"HOME_DIR": "~/projects"}
        )
        runner = self._make_runner()
        runner.launch(entry)

        call_kwargs = mock_run.call_args[1]
        env_value = call_kwargs["env"]["HOME_DIR"]
        assert "~" not in env_value, f"Expected tilde to be expanded, got '{env_value}'"

    @patch("launchline.runner.subprocess.run")
    def test_preserves_env_values_without_tilde(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(
            name="Test", command="my-tool", env={"MY_VAR": "/absolute/path"}
        )
        runner = self._make_runner()
        runner.launch(entry)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["MY_VAR"] == "/absolute/path"


class TestClearScreen:
    """Tests for the _clear_screen static method."""

    @patch("sys.stdout")
    def test_writes_ansi_clear(self, mock_stdout: MagicMock) -> None:
        EntryRunner._clear_screen()
        written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "\033[2J" in written
        assert "\033[H" in written


class TestSetTerminalTitle:
    """Tests for the _set_terminal_title static method."""

    @patch("sys.stdout")
    def test_writes_osc_title_sequence(self, mock_stdout: MagicMock) -> None:
        EntryRunner._set_terminal_title("My Tool")
        written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "\033]0;My Tool\a" in written


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only batch file handling")
class TestBatchFileLaunch:
    """Tests for .bat/.cmd file handling on Windows."""

    def _make_runner(self) -> EntryRunner:
        config = LaunchLineConfig(
            entries=(),
            on_exit="restart",
            clear_on_launch=False,
        )
        return EntryRunner(config)

    @patch("launchline.runner.EntryRunner._set_terminal_title")
    @patch("launchline.runner.subprocess.run")
    def test_bat_file_launched_via_cmd(
        self, mock_run: MagicMock, mock_title: MagicMock
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(
            name="Cygwin",
            command="C:\\cygwin64\\Cygwin.bat",
            args=("--login",),
        )
        runner = self._make_runner()
        runner.launch(entry)

        mock_title.assert_called_once_with("Cygwin")
        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["cmd.exe", "/c"]
        assert cmd[2] == "C:\\cygwin64\\Cygwin.bat"
        assert cmd[3] == "--login"

    @patch("launchline.runner.EntryRunner._set_terminal_title")
    @patch("launchline.runner.subprocess.run")
    def test_cmd_file_launched_via_cmd(
        self, mock_run: MagicMock, mock_title: MagicMock
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Script", command="setup.cmd")
        runner = self._make_runner()
        runner.launch(entry)

        mock_title.assert_called_once_with("Script")
        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["cmd.exe", "/c"]

    @patch("launchline.runner.EntryRunner._set_terminal_title")
    @patch("launchline.runner.subprocess.run")
    def test_exe_not_wrapped_in_cmd(
        self, mock_run: MagicMock, mock_title: MagicMock
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="Tool", command="my-tool")
        runner = self._make_runner()
        runner.launch(entry)

        mock_title.assert_called_once_with("Tool")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "my-tool"
