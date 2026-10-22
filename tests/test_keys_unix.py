"""Portable tests of Unix keyboard decoding and terminal restoration policy."""

from __future__ import annotations

import sys
from collections import deque
from types import ModuleType, SimpleNamespace

import pytest

from launchline.keys import KeyReader


class UnixConsoleBoundary:
    """Deterministic OS byte input and terminal-mode collaborators."""

    def __init__(self, text: str) -> None:
        self.bytes = deque(bytes([value]) for value in text.encode("utf-8"))
        self.modes: list[str] = []

    def read(self, _fd: int, _count: int) -> bytes:
        """Supply exactly the next kernel byte, including EOF."""
        return self.bytes.popleft() if self.bytes else b""

    def select(
        self,
        readers: list[int],
        _writers: list[int],
        _errors: list[int],
        _timeout: float | None,
    ) -> tuple[list[int], list[int], list[int]]:
        """Report kernel readiness based on unread bytes."""
        return (readers if self.bytes else [], [], [])

    def get_mode(self, _fd: int) -> list[int]:
        """Capture a terminal mode snapshot."""
        return [1]

    def set_raw(self, _fd: int, when: int = 2) -> None:
        """Record entry into raw mode."""
        self.modes.append("raw")
        if when == 2:
            self.bytes.clear()

    def restore(self, _fd: int, _when: int, _old: list[int]) -> None:
        """Record restoration after every outcome."""
        self.modes.append("restore")

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Replace only platform APIs and stream metadata, not decoder logic."""
        termios = ModuleType("termios")
        termios.tcgetattr = self.get_mode
        termios.tcsetattr = self.restore
        termios.TCSADRAIN = 1
        termios.TCSANOW = 0
        tty = ModuleType("tty")
        tty.setraw = self.set_raw
        monkeypatch.setitem(sys.modules, "termios", termios)
        monkeypatch.setitem(sys.modules, "tty", tty)
        monkeypatch.setattr("os.read", self.read)
        monkeypatch.setattr("select.select", self.select)
        monkeypatch.setattr(
            "launchline.keys.sys",
            SimpleNamespace(
                platform="linux",
                stdin=SimpleNamespace(fileno=lambda: 42, encoding="utf-8"),
            ),
        )
        monkeypatch.setattr(KeyReader, "_pending_unix", None)


class TestUnixKeyboard:
    """Test input semantics independently of availability of Unix kernel APIs."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("a", "a"),
            ("猫", "猫"),
            ("\r", "enter"),
            ("\x7f", "backspace"),
            ("\x01", "ctrl-a"),
            ("\x02", "ctrl-b"),
            ("\x04", "ctrl-d"),
            ("\x05", "ctrl-e"),
            ("\x06", "ctrl-f"),
            ("\x0b", "ctrl-k"),
            ("\x15", "ctrl-u"),
            ("\x17", "ctrl-w"),
            ("\x1b", "escape"),
            ("\x1b[A", "up"),
            ("\x1b[B", "down"),
            ("\x1b[97u", "a"),
            ("\x1bb", "alt-b"),
            ("\x1bf", "alt-f"),
            ("\x1bd", "alt-d"),
            ("\x1b\x7f", "alt-backspace"),
            ("\x1b[", ""),
            ("\x1b[?", ""),
        ],
    )
    def test_decodes_key_and_restores_mode(
        self, text: str, expected: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decode the key and restore the original terminal mode."""
        console = UnixConsoleBoundary(text)
        console.install(monkeypatch)
        assert KeyReader.read_key() == expected, (text, expected)
        assert console.modes == ["raw", "restore"], (
            "Every read must restore terminal mode"
        )

    def test_unicode_burst_has_no_buffered_key_loss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Consecutive UTF-8 characters remain available to readiness polling."""
        console = UnixConsoleBoundary("é猫")
        console.install(monkeypatch)
        assert [KeyReader.read_key(0.1), KeyReader.read_key(0.1)] == ["é", "猫"], (
            "Buffered text must not hide bytes from select"
        )

    def test_escape_preserves_queued_numeric_input(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fast digit following Escape is retained for the next menu read."""
        console = UnixConsoleBoundary("\x1b1")
        console.install(monkeypatch)
        assert [KeyReader.read_key(0.1), KeyReader.read_key(0.1)] == ["escape", "1"], (
            "Escape must not discard a queued digit"
        )

    def test_timeout_restores_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An input timeout must leave terminal attributes restored."""
        console = UnixConsoleBoundary("")
        console.install(monkeypatch)
        assert KeyReader.read_key(0.1) == "", "Timeout must produce no key"
        assert console.modes == ["raw", "restore"], (
            "Timeout must restore terminal state"
        )

    @pytest.mark.parametrize("text", ["", "\x03"])
    def test_eof_and_interrupt_restore_mode(
        self, text: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EOF and Ctrl+C must restore terminal attributes before propagating."""
        console = UnixConsoleBoundary(text)
        console.install(monkeypatch)
        with pytest.raises(EOFError if text == "" else KeyboardInterrupt):
            KeyReader.read_key()
        assert console.modes == ["raw", "restore"], (
            "Exceptional exit must restore terminal mode"
        )
