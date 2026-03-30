"""Tests for subprocess execution and post-exit logic."""

from __future__ import annotations

import subprocess
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
        assert call_kwargs["cwd"] is None, (
            "cwd should be None when no working_directory configured"
        )

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


class TestClearScreen:
    """Tests for the _clear_screen static method."""

    @patch("sys.stdout")
    def test_writes_ansi_clear(self, mock_stdout: MagicMock) -> None:
        EntryRunner._clear_screen()
        written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "\033[2J" in written, "Should contain ANSI erase-screen sequence"
        assert "\033[H" in written, "Should contain ANSI cursor-home sequence"


class TestSetTerminalTitle:
    """Tests for the _set_terminal_title static method."""

    @patch("sys.stdout")
    def test_writes_osc_title_sequence(self, mock_stdout: MagicMock) -> None:
        EntryRunner._set_terminal_title("My Tool")
        written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "\033]0;My Tool\a" in written, (
            "Should contain OSC title sequence for 'My Tool'"
        )

    @patch("sys.stdout")
    def test_special_characters_in_title(self, mock_stdout: MagicMock) -> None:
        """Titles with spaces and punctuation render correctly."""
        EntryRunner._set_terminal_title("GitHub Copilot (v2)")
        written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "\033]0;GitHub Copilot (v2)\a" in written, (
            "Should handle special characters in title"
        )


class TestTitlePrefix:
    """Tests for title_prefix prepending to terminal tab titles."""

    @patch("launchline.runner.subprocess.run")
    @patch("sys.stdout")
    def test_title_prefix_prepended_to_entry_name(
        self, mock_stdout: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        config = LaunchLineConfig(entries=(), clear_on_launch=False)
        runner = EntryRunner(config)
        entry = EntryConfig(
            name="Copilot", command="copilot", title_prefix="\U0001f916"
        )

        runner.launch(entry)

        written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "\033]0;\U0001f916 Copilot\a" in written, (
            f"Tab title should be '\U0001f916 Copilot', got: {written!r}"
        )

    @patch("launchline.runner.subprocess.run")
    @patch("sys.stdout")
    def test_empty_title_prefix_uses_name_only(
        self, mock_stdout: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        config = LaunchLineConfig(entries=(), clear_on_launch=False)
        runner = EntryRunner(config)
        entry = EntryConfig(name="Copilot", command="copilot")

        runner.launch(entry)

        written = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "\033]0;Copilot\a" in written, (
            f"Tab title should be 'Copilot' without prefix, got: {written!r}"
        )
