"""Cross-platform compatibility tests.

Covers platform-dispatch logic, Kitty protocol fallback behaviour,
ANSI terminal sequences, and OS-dependent configuration defaults.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.keys import KeyReader
from launchline.runner import EntryRunner
from launchline.ui import LaunchLineUI

# ---------------------------------------------------------------------------
# KeyReader platform dispatch
# ---------------------------------------------------------------------------


class TestKeyReaderPlatformDispatch:
    """Verify read_key dispatches to the correct platform handler."""

    @patch.object(KeyReader, "_read_key_windows", return_value="enter")
    @patch("launchline.keys.sys")
    def test_dispatches_to_windows_on_win32(
        self, mock_sys: MagicMock, mock_win: MagicMock
    ) -> None:
        mock_sys.platform = "win32"
        result = KeyReader.read_key()
        mock_win.assert_called_once_with(None)
        assert result == "enter"

    @patch.object(KeyReader, "_read_key_unix", return_value="escape")
    @patch("launchline.keys.sys")
    def test_dispatches_to_unix_on_linux(
        self, mock_sys: MagicMock, mock_unix: MagicMock
    ) -> None:
        mock_sys.platform = "linux"
        result = KeyReader.read_key()
        mock_unix.assert_called_once_with(None)
        assert result == "escape"

    @patch.object(KeyReader, "_read_key_unix", return_value="up")
    @patch("launchline.keys.sys")
    def test_dispatches_to_unix_on_darwin(
        self, mock_sys: MagicMock, mock_unix: MagicMock
    ) -> None:
        mock_sys.platform = "darwin"
        result = KeyReader.read_key()
        mock_unix.assert_called_once_with(None)
        assert result == "up"

    @patch.object(KeyReader, "_read_key_windows", return_value="a")
    @patch("launchline.keys.sys")
    def test_timeout_forwarded_to_windows(
        self, mock_sys: MagicMock, mock_win: MagicMock
    ) -> None:
        mock_sys.platform = "win32"
        KeyReader.read_key(timeout=2.5)
        mock_win.assert_called_once_with(2.5)

    @patch.object(KeyReader, "_read_key_unix", return_value="a")
    @patch("launchline.keys.sys")
    def test_timeout_forwarded_to_unix(
        self, mock_sys: MagicMock, mock_unix: MagicMock
    ) -> None:
        mock_sys.platform = "linux"
        KeyReader.read_key(timeout=1.0)
        mock_unix.assert_called_once_with(1.0)


# ---------------------------------------------------------------------------
# Windows key reader: legacy (non-Kitty) paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt only available on Windows")
class TestWindowsLegacyKeyReader:
    """Tests for the Windows msvcrt-based key reader's legacy paths."""

    @patch("msvcrt.getwch")
    def test_return_key_maps_to_enter(self, mock_getwch: MagicMock) -> None:
        r"""Carriage return (\r) maps to 'enter'."""
        mock_getwch.return_value = "\r"
        assert KeyReader._read_key_windows() == "enter"

    @patch("msvcrt.getwch")
    def test_backspace_key_maps_to_backspace(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x08"
        assert KeyReader._read_key_windows() == "backspace"

    @patch("msvcrt.getwch")
    def test_del_char_maps_to_ctrl_backspace(self, mock_getwch: MagicMock) -> None:
        """DEL (0x7F) outside an extended sequence maps to ctrl-backspace."""
        mock_getwch.return_value = "\x7f"
        assert KeyReader._read_key_windows() == "ctrl-backspace"

    @patch("msvcrt.getwch")
    def test_ctrl_a_returns_ctrl_a(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x01"
        assert KeyReader._read_key_windows() == "ctrl-a"

    @patch("msvcrt.getwch")
    def test_ctrl_b_returns_ctrl_b(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x02"
        assert KeyReader._read_key_windows() == "ctrl-b"

    @patch("msvcrt.getwch")
    def test_ctrl_d_returns_ctrl_d(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x04"
        assert KeyReader._read_key_windows() == "ctrl-d"

    @patch("msvcrt.getwch")
    def test_ctrl_e_returns_ctrl_e(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x05"
        assert KeyReader._read_key_windows() == "ctrl-e"

    @patch("msvcrt.getwch")
    def test_ctrl_f_returns_ctrl_f(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x06"
        assert KeyReader._read_key_windows() == "ctrl-f"

    @patch("msvcrt.getwch")
    def test_ctrl_k_returns_ctrl_k(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x0b"
        assert KeyReader._read_key_windows() == "ctrl-k"

    @patch("msvcrt.getwch")
    def test_ctrl_u_returns_ctrl_u(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x15"
        assert KeyReader._read_key_windows() == "ctrl-u"

    @patch("msvcrt.getwch")
    def test_ctrl_w_returns_ctrl_w(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x17"
        assert KeyReader._read_key_windows() == "ctrl-w"

    @patch("msvcrt.getwch")
    def test_ctrl_c_raises_keyboard_interrupt(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "\x03"
        with pytest.raises(KeyboardInterrupt):
            KeyReader._read_key_windows()

    @patch("msvcrt.getwch")
    def test_printable_char_passes_through(self, mock_getwch: MagicMock) -> None:
        mock_getwch.return_value = "z"
        assert KeyReader._read_key_windows() == "z"

    @patch("msvcrt.getwch")
    def test_extended_arrow_up_returns_up(self, mock_getwch: MagicMock) -> None:
        r"""Extended key prefix \xe0 + H maps to 'up'."""
        mock_getwch.side_effect = ["\xe0", "H"]
        assert KeyReader._read_key_windows() == "up"

    @patch("msvcrt.getwch")
    def test_extended_arrow_down_returns_down(self, mock_getwch: MagicMock) -> None:
        r"""Extended key prefix \xe0 + P maps to 'down'."""
        mock_getwch.side_effect = ["\xe0", "P"]
        assert KeyReader._read_key_windows() == "down"

    @patch("msvcrt.getwch")
    def test_extended_del_returns_ctrl_backspace(self, mock_getwch: MagicMock) -> None:
        """Extended key prefix + DEL maps to ctrl-backspace."""
        mock_getwch.side_effect = ["\xe0", "\x7f"]
        assert KeyReader._read_key_windows() == "ctrl-backspace"

    @patch("msvcrt.getwch")
    def test_unknown_extended_key_returns_empty(self, mock_getwch: MagicMock) -> None:
        """Unknown extended key (e.g. F1) returns empty string."""
        mock_getwch.side_effect = ["\x00", ";"]  # \x00 prefix + F1 scan code
        assert KeyReader._read_key_windows() == ""

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_esc_then_unknown_char_returns_escape(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """ESC followed by a non-bracket char discards the second char."""
        mock_getwch.side_effect = ["\x1b", "x"]
        mock_kbhit.side_effect = [True]
        assert KeyReader._read_key_windows() == "escape"

    @patch("msvcrt.kbhit")
    def test_timeout_returns_empty(self, mock_kbhit: MagicMock) -> None:
        """When timeout expires before a key is pressed, returns ''."""
        mock_kbhit.return_value = False
        result = KeyReader._read_key_windows(timeout=0.02)
        assert result == "", f"Expected empty on timeout, got {result!r}"


# ---------------------------------------------------------------------------
# Windows CSI sequence parser: edge cases
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt only available on Windows")
class TestWindowsCSIEdgeCases:
    """Edge cases for CSI sequence parsing on Windows."""

    @patch("msvcrt.kbhit")
    def test_incomplete_sequence_times_out(self, mock_kbhit: MagicMock) -> None:
        """If no terminator arrives within the deadline, returns ''."""
        mock_kbhit.return_value = False
        result = KeyReader._read_csi_sequence_windows()
        assert result == ""

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_unknown_terminator_char_returns_empty(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Non-alpha, non-~ character terminates with empty result."""
        mock_getwch.return_value = "!"
        mock_kbhit.return_value = True
        result = KeyReader._read_csi_sequence_windows()
        assert result == ""

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_tilde_terminator_dispatches(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Tilde-terminated sequences (e.g. ~) are dispatched."""
        # CSI 1 ~ is an unrecognised sequence
        mock_getwch.side_effect = ["1", "~"]
        mock_kbhit.return_value = True
        result = KeyReader._read_csi_sequence_windows()
        assert result == ""  # unrecognised, but validly dispatched

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_semicolon_and_colon_in_params(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Semicolons and colons are collected as parameter separators."""
        # ESC [ 27 ; 1 : 1 u → escape key with event type 1 (press)
        mock_getwch.side_effect = ["2", "7", ";", "1", ":", "1", "u"]
        mock_kbhit.return_value = True
        result = KeyReader._read_csi_sequence_windows()
        assert result == "escape"


# ---------------------------------------------------------------------------
# Kitty protocol decoder: comprehensive edge cases
# ---------------------------------------------------------------------------


class TestKittyProtocolEdgeCases:
    """Additional edge cases for _decode_kitty_key and _dispatch_csi."""

    def test_invalid_codepoint_returns_empty(self) -> None:
        """Non-numeric codepoint gracefully returns empty."""
        assert KeyReader._decode_kitty_key("abc") == ""

    def test_ctrl_takes_precedence_over_alt(self) -> None:
        """When both Ctrl and Alt are set, the Ctrl mapping wins."""
        # modifier 7 = 1 + alt(2) + ctrl(4)
        assert KeyReader._decode_kitty_key("97;7") == "ctrl-a"

    def test_ctrl_alt_unmapped_letter_returns_empty(self) -> None:
        """Ctrl+Alt on an unmapped letter returns empty (via ctrl branch)."""
        # modifier 7 = 1 + alt(2) + ctrl(4); 'z' is not in _ctrl_map
        assert KeyReader._decode_kitty_key("122;7") == ""

    def test_modifier_with_empty_value(self) -> None:
        """Empty modifier field doesn't crash."""
        assert KeyReader._decode_kitty_key("97;") == "a"

    def test_event_type_press(self) -> None:
        """Press event (type 1) is not filtered."""
        assert KeyReader._decode_kitty_key("13;1:1") == "enter"

    def test_event_type_repeat(self) -> None:
        """Repeat event (type 2) is not filtered."""
        assert KeyReader._decode_kitty_key("13;1:2") == "enter"

    def test_event_type_release_filtered(self) -> None:
        """Release event (type 3) is always filtered."""
        assert KeyReader._decode_kitty_key("13;1:3") == ""

    def test_space_key(self) -> None:
        """Space (codepoint 32) passes through as printable."""
        assert KeyReader._decode_kitty_key("32") == " "

    def test_tilde_key(self) -> None:
        """Tilde (codepoint 126) is the last printable ASCII."""
        assert KeyReader._decode_kitty_key("126") == "~"

    def test_below_printable_range_returns_empty(self) -> None:
        """Codepoint 31 (unit separator) is below printable range."""
        assert KeyReader._decode_kitty_key("31") == ""

    def test_above_printable_range_returns_empty(self) -> None:
        """Codepoint 128+ is outside the handled range."""
        assert KeyReader._decode_kitty_key("200") == ""

    def test_unmapped_ctrl_letter_returns_empty(self) -> None:
        """Ctrl+Z (not in the _ctrl_map) returns empty."""
        assert KeyReader._decode_kitty_key("122;5") == ""

    def test_unmapped_alt_letter_returns_empty(self) -> None:
        """Alt+Z (not in the _alt_map) returns empty."""
        assert KeyReader._decode_kitty_key("122;3") == ""

    def test_dispatch_csi_unrecognised_terminator(self) -> None:
        """Terminators other than A, B, u return empty."""
        assert KeyReader._dispatch_csi("1", "C") == ""
        assert KeyReader._dispatch_csi("1", "D") == ""
        assert KeyReader._dispatch_csi("1", "~") == ""


# ---------------------------------------------------------------------------
# Runner: cross-platform command wrapping
# ---------------------------------------------------------------------------


class TestRunnerCrossPlatform:
    """Ensure .bat/.cmd wrapping only occurs on Windows."""

    def _make_runner(self) -> EntryRunner:
        config = LaunchLineConfig(entries=(), on_exit="restart", clear_on_launch=False)
        return EntryRunner(config)

    @patch("launchline.runner.subprocess.run")
    @patch("launchline.runner.sys")
    def test_bat_not_wrapped_on_non_windows(
        self, mock_sys: MagicMock, mock_run: MagicMock
    ) -> None:
        """On Linux/macOS, .bat files are NOT wrapped with cmd.exe."""
        mock_sys.platform = "linux"
        mock_sys.stdin = sys.stdin
        mock_sys.stdout = sys.stdout
        mock_sys.stderr = sys.stderr
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        entry = EntryConfig(name="Script", command="script.bat", args=("--flag",))
        runner = self._make_runner()
        runner.launch(entry)

        cmd = mock_run.call_args[0][0]
        assert cmd == ["script.bat", "--flag"]

    @patch("launchline.runner.subprocess.run")
    @patch("launchline.runner.sys")
    def test_bat_wrapped_on_windows(
        self, mock_sys: MagicMock, mock_run: MagicMock
    ) -> None:
        """On Windows, .bat files ARE wrapped with cmd.exe /c."""
        mock_sys.platform = "win32"
        mock_sys.stdin = sys.stdin
        mock_sys.stdout = sys.stdout
        mock_sys.stderr = sys.stderr
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        entry = EntryConfig(name="Script", command="script.bat")
        runner = self._make_runner()
        runner.launch(entry)

        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["cmd.exe", "/c"], (
            f"Windows .bat should be wrapped with cmd.exe /c, got {cmd[:2]}"
        )

    @patch("launchline.runner.subprocess.run")
    @patch("launchline.runner.sys")
    def test_cmd_wrapped_on_windows(
        self, mock_sys: MagicMock, mock_run: MagicMock
    ) -> None:
        """On Windows, .cmd files ARE wrapped with cmd.exe /c."""
        mock_sys.platform = "win32"
        mock_sys.stdin = sys.stdin
        mock_sys.stdout = sys.stdout
        mock_sys.stderr = sys.stderr
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        entry = EntryConfig(name="Script", command="setup.CMD")
        runner = self._make_runner()
        runner.launch(entry)

        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["cmd.exe", "/c"], (
            f"Windows .cmd should be wrapped with cmd.exe /c, got {cmd[:2]}"
        )

    @patch("launchline.runner.subprocess.run")
    @patch("launchline.runner.sys")
    def test_regular_command_never_wrapped(
        self, mock_sys: MagicMock, mock_run: MagicMock
    ) -> None:
        """Normal commands (no .bat/.cmd) are never wrapped, any platform."""
        for platform in ("win32", "linux", "darwin"):
            mock_sys.platform = platform
            mock_sys.stdin = sys.stdin
            mock_sys.stdout = sys.stdout
            mock_sys.stderr = sys.stderr
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            entry = EntryConfig(name="Tool", command="my-tool", args=("--help",))
            runner = self._make_runner()
            runner.launch(entry)

            cmd = mock_run.call_args[0][0]
            assert cmd == ["my-tool", "--help"], f"Failed on {platform}"


# ---------------------------------------------------------------------------
# Runner: tilde expansion in env values
# ---------------------------------------------------------------------------


class TestRunnerEnvExpansion:
    """Tilde expansion in entry env values is cross-platform."""

    def _make_runner(self) -> EntryRunner:
        config = LaunchLineConfig(entries=(), on_exit="restart", clear_on_launch=False)
        return EntryRunner(config)

    @patch("launchline.runner.subprocess.run")
    def test_tilde_expanded_to_home_dir(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="T", command="t", env={"DIR": "~/stuff"})
        self._make_runner().launch(entry)

        env_val = mock_run.call_args[1]["env"]["DIR"]
        assert "~" not in env_val, f"Tilde should be expanded, got {env_val!r}"
        assert Path(env_val) == Path.home() / "stuff", (
            f"Expected home/stuff, got {env_val!r}"
        )

    @patch("launchline.runner.subprocess.run")
    def test_no_tilde_leaves_value_unchanged(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        entry = EntryConfig(name="T", command="t", env={"VAR": "plain-value"})
        self._make_runner().launch(entry)

        assert mock_run.call_args[1]["env"]["VAR"] == "plain-value"


# ---------------------------------------------------------------------------
# UI: alternate screen and terminal ANSI sequences
# ---------------------------------------------------------------------------


class TestUIAlternateScreen:
    """Verify ANSI sequences emitted for alternate screen management."""

    @patch("sys.stdout")
    def test_enter_alt_screen_sequences(self, mock_stdout: MagicMock) -> None:
        """Entering alternate screen emits xterm alt buffer + Kitty push."""
        config = LaunchLineConfig(entries=(), title="Test")
        ui = LaunchLineUI(config)
        ui._enter_alt_screen()

        written = "".join(c.args[0] for c in mock_stdout.write.call_args_list)
        # Alt screen buffer
        assert "\033[?1049h" in written, "Should emit xterm alt screen sequence"
        # Kitty keyboard protocol push
        assert "\033[>1u" in written, "Should emit Kitty keyboard push"
        # Cursor home + clear
        assert "\033[H" in written, "Should emit cursor home"
        assert "\033[2J" in written, "Should emit clear screen"
        # OSC title
        assert "\033]0;Test\a" in written, "Should emit OSC title sequence"

    @patch("sys.stdout")
    def test_leave_alt_screen_sequences(self, mock_stdout: MagicMock) -> None:
        """Leaving alternate screen pops Kitty and restores main buffer."""
        LaunchLineUI._leave_alt_screen()

        written = "".join(c.args[0] for c in mock_stdout.write.call_args_list)
        # Kitty keyboard protocol pop
        assert "\033[<u" in written, "Should emit Kitty keyboard pop"
        # Exit alt screen buffer
        assert "\033[?1049l" in written, "Should emit alt screen exit"

    @patch("sys.stdout")
    def test_ui_set_terminal_title(self, mock_stdout: MagicMock) -> None:
        """UI title setter emits standard OSC 0 sequence."""
        LaunchLineUI._set_terminal_title("My Launcher")

        written = "".join(c.args[0] for c in mock_stdout.write.call_args_list)
        assert "\033]0;My Launcher\a" in written, (
            "Should emit OSC title with 'My Launcher'"
        )


# ---------------------------------------------------------------------------
# Config: default path is valid on all platforms
# ---------------------------------------------------------------------------
