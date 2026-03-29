"""Platform-aware single-keypress reader and Kitty protocol decoder."""

from __future__ import annotations

import contextlib
import sys
import time


class KeyReader:
    """Platform-aware single-keypress reader."""

    @staticmethod
    def read_key(timeout: float | None = None) -> str:
        """Read a single keypress and return a normalised key name.

        Returns one of: ``"up"``, ``"down"``, ``"enter"``, ``"escape"``,
        ``"backspace"``, ``"ctrl-backspace"``, ``"ctrl-a"``, ``"ctrl-e"``,
        ``"ctrl-u"``, ``"ctrl-k"``, ``"ctrl-w"``, ``"alt-backspace"``,
        a single printable character, or ``""`` for unknown special keys.

        Args:
            timeout: Optional timeout in seconds. If provided and no key is
                pressed before timeout expires, returns ``""``.
        """
        if sys.platform == "win32":
            return KeyReader._read_key_windows(timeout)
        return KeyReader._read_key_unix(timeout)

    @staticmethod
    def _read_key_windows(timeout: float | None = None) -> str:
        import msvcrt

        if timeout is not None:
            deadline = time.monotonic() + timeout
            while not msvcrt.kbhit():
                if time.monotonic() >= deadline:
                    return ""
                time.sleep(0.01)

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "up"
            if ch2 == "P":
                return "down"
            if ch2 == "\x7f":
                return "ctrl-backspace"
            return ""
        if ch == "\r":
            return "enter"
        if ch == "\x1b":
            # Kitty protocol sends CSI sequences starting with ESC [.
            # Peek to see if this is a CSI sequence rather than bare Escape.
            if msvcrt.kbhit():
                ch2 = msvcrt.getwch()
                if ch2 == "[":
                    return KeyReader._read_csi_sequence_windows()
                # Unknown ESC sequence — discard the second char
            return "escape"
        if ch == "\x08":
            return "backspace"
        if ch == "\x7f":
            return "ctrl-backspace"
        if ch == "\x01":
            return "ctrl-a"
        if ch == "\x02":
            return "ctrl-b"
        if ch == "\x04":
            return "ctrl-d"
        if ch == "\x05":
            return "ctrl-e"
        if ch == "\x06":
            return "ctrl-f"
        if ch == "\x0b":
            return "ctrl-k"
        if ch == "\x15":
            return "ctrl-u"
        if ch == "\x17":
            return "ctrl-w"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch

    @staticmethod
    def _read_csi_sequence_windows() -> str:
        """Parse a CSI sequence on Windows after ``ESC [`` has been consumed.

        Uses ``msvcrt`` to read characters until a terminator is found.
        """
        import msvcrt

        buf: list[str] = []
        deadline = time.monotonic() + 0.1
        while True:
            while not msvcrt.kbhit():
                if time.monotonic() >= deadline:
                    return ""  # incomplete sequence
                time.sleep(0.001)
            ch = msvcrt.getwch()
            if ch.isdigit() or ch in ";:":
                buf.append(ch)
            elif ch.isalpha() or ch in "~u":
                return KeyReader._dispatch_csi("".join(buf), ch)
            else:
                return ""

    @staticmethod
    def _read_key_unix(
        timeout: float | None = None,
    ) -> str:  # pragma: no cover — not testable on Windows CI
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)  # type: ignore[attr-defined]
        try:
            tty.setraw(fd)  # type: ignore[attr-defined]
            if timeout is not None:
                ready, _, _ = select.select([fd], [], [], timeout)
                if not ready:
                    return ""
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # Peek for CSI start; works for both Kitty protocol
                # (ESC key → CSI 27 u) and legacy terminals.
                ready, _, _ = select.select([fd], [], [], 0.05)
                if not ready:
                    return "escape"
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    return KeyReader._read_csi_sequence(fd)
                if ch2 == "\x7f":
                    return "alt-backspace"
                if ch2 == "d":
                    return "alt-d"
                if ch2 == "f":
                    return "alt-f"
                if ch2 == "b":
                    return "alt-b"
                return "escape"
            if ch == "\r":
                return "enter"
            if ch == "\x7f":
                return "backspace"
            if ch == "\x01":
                return "ctrl-a"
            if ch == "\x02":
                return "ctrl-b"
            if ch == "\x04":
                return "ctrl-d"
            if ch == "\x05":
                return "ctrl-e"
            if ch == "\x06":
                return "ctrl-f"
            if ch == "\x0b":
                return "ctrl-k"
            if ch == "\x15":
                return "ctrl-u"
            if ch == "\x17":
                return "ctrl-w"
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)  # type: ignore[attr-defined]

    # -- Kitty keyboard protocol helpers ------------------------------------

    @staticmethod
    def _read_csi_sequence(
        fd: int,
    ) -> str:  # pragma: no cover — not testable on Windows CI
        """Parse a CSI sequence after ``ESC [`` has been consumed.

        Handles both legacy CSI (arrow keys, functional keys) and Kitty
        protocol ``CSI u`` sequences.
        """
        import select

        buf: list[str] = []
        while True:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if not ready:
                return ""  # incomplete sequence
            ch = sys.stdin.read(1)
            if ch.isdigit() or ch in ";:":
                buf.append(ch)
            elif ch.isalpha() or ch in "~u":
                return KeyReader._dispatch_csi("".join(buf), ch)
            else:
                return ""

    @staticmethod
    def _dispatch_csi(params: str, terminator: str) -> str:
        """Map a parsed CSI sequence to a normalised key name."""
        if terminator == "A":
            return "up"
        if terminator == "B":
            return "down"
        if terminator == "u":
            return KeyReader._decode_kitty_key(params)
        return ""

    @staticmethod
    def _decode_kitty_key(params: str) -> str:
        """Decode a Kitty protocol ``CSI … u`` key event.

        Args:
            params: The text between ``CSI`` (``ESC [``) and the ``u``
                terminator. Format: ``codepoint[;modifiers[:event_type]]``.

        Returns:
            A normalised key name, or ``""`` for unhandled keys.
        """
        fields = params.split(";")
        key_str = fields[0].split(":")[0]
        try:
            codepoint = int(key_str) if key_str else 0
        except ValueError:
            return ""

        modifiers = 0
        if len(fields) > 1 and fields[1]:
            mod_parts = fields[1].split(":")
            with contextlib.suppress(ValueError):
                modifiers = int(mod_parts[0]) - 1
            # Ignore release events (event_type == 3)
            if len(mod_parts) > 1:
                with contextlib.suppress(ValueError):
                    if int(mod_parts[1]) == 3:
                        return ""

        ctrl = bool(modifiers & 4)
        alt = bool(modifiers & 2)

        if codepoint == 27:
            return "escape"
        if codepoint == 13:
            return "enter"
        if codepoint == 127:
            if ctrl:
                return "ctrl-backspace"
            if alt:
                return "alt-backspace"
            return "backspace"

        if ctrl and 97 <= codepoint <= 122:
            letter = chr(codepoint)
            if letter == "c":
                raise KeyboardInterrupt
            _ctrl_map: dict[str, str] = {
                "a": "ctrl-a",
                "b": "ctrl-b",
                "d": "ctrl-d",
                "e": "ctrl-e",
                "f": "ctrl-f",
                "h": "ctrl-h",
                "k": "ctrl-k",
                "u": "ctrl-u",
                "w": "ctrl-w",
            }
            return _ctrl_map.get(letter, "")

        if alt and not ctrl and 97 <= codepoint <= 122:
            _alt_map: dict[str, str] = {
                "b": "alt-b",
                "d": "alt-d",
                "f": "alt-f",
            }
            return _alt_map.get(chr(codepoint), "")

        if not ctrl and not alt and 32 <= codepoint <= 126:
            return chr(codepoint)

        return ""
