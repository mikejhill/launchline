"""TUI rendering and input loop for the LaunchLine launcher.

This module provides :class:`LaunchLineUI`, which drives the interactive
terminal interface: rendering the entry list, handling keyboard input,
fuzzy filtering, viewport scrolling, and alternate-screen management.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.fuzzy import FuzzyMatcher
from launchline.keys import KeyReader

logger = logging.getLogger(__name__)

_MAX_LIST_HEIGHT = 10
"""Maximum number of entry rows to display before scrolling."""

# header(4) + cwd(1) + sep_above(1) + prompt(1) + sep_below(1) + footer(1)
_CHROME_LINES = 9
"""Fixed number of non-entry rows consumed by the UI chrome."""

_DEFAULT_SIZE = os.terminal_size((80, 24))
"""Fallback terminal dimensions when the real size cannot be detected."""


def _get_terminal_size() -> os.terminal_size:
    """Return the terminal size with a safe fallback."""
    try:
        return os.get_terminal_size()
    except OSError:
        return _DEFAULT_SIZE


# ---------------------------------------------------------------------------
# Internal signals
# ---------------------------------------------------------------------------


class _UserExitError(Exception):
    """Internal signal raised when the user wants to quit the launcher.

    This exception is caught inside :meth:`LaunchLineUI.run` and never
    propagates to callers.
    """


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


@dataclass
class _NumberedEntry:
    """An entry paired with its 1-based display number.

    Attributes:
        number: Ordinal display number (1-based for entries, 0 for exit).
        entry: The underlying configuration entry.
    """

    number: int
    entry: EntryConfig


_EXIT_ENTRY = EntryConfig(name="Exit", command="", description="Close the launcher")
"""Sentinel entry representing the 'Exit' option in the launcher menu."""


# ---------------------------------------------------------------------------
# LaunchLine UI
# ---------------------------------------------------------------------------


class LaunchLineUI:
    """Interactive TUI for selecting a CLI tool to launch.

    Renders a bordered header, a fuzzy-search prompt, a scrollable entry
    list with numbered shortcuts, and a footer with keybinding hints.
    The entire UI runs inside the terminal's alternate screen buffer so
    that normal scrollback is preserved.
    """

    def __init__(
        self,
        config: LaunchLineConfig,
        *,
        _key_reader: Callable[[], str] | None = None,
    ) -> None:
        """Initialise the UI with a launcher configuration.

        Args:
            config: Application configuration containing the entries to
                display and behavioural settings.
            _key_reader: Optional override for the key-reading callable.
                Defaults to :meth:`KeyReader.read_key` with a 50 ms
                timeout.  Primarily used for testing.
        """
        self._config = config
        self._all_entries: tuple[_NumberedEntry, ...] = tuple(
            _NumberedEntry(number=i + 1, entry=e) for i, e in enumerate(config.entries)
        )
        self._exit_entry = _NumberedEntry(number=0, entry=_EXIT_ENTRY)
        self._show_exit = config.show_exit
        self._ghost_text_enabled = config.ghost_text
        self._instant_numeric_launch = config.instant_numeric_launch
        self._key_reader = _key_reader or (lambda: KeyReader.read_key(timeout=0.05))

        # Mutable state — reset on each run()
        self._query: str = ""
        self._cursor: int = 0
        self._highlight_idx: int = 0
        self._visible: list[_NumberedEntry] = []
        self._exit_visible: bool = True
        self._viewport_offset: int = 0

    # -- public API ---------------------------------------------------------

    def run(self) -> EntryConfig | None:
        """Display the launcher and wait for user selection.

        Returns:
            The selected ``EntryConfig``, or ``None`` if the user exits.
        """
        self._reset()
        self._enter_alt_screen()
        try:
            dirty = True
            last_size: tuple[int, int] | None = None
            while True:
                size = _get_terminal_size()
                current_size = (size.columns, size.lines)
                if dirty or current_size != last_size:
                    self._render()
                    last_size = current_size
                    dirty = False

                key = self._key_reader()
                if not key:
                    continue
                entry = self._on_key(key)
                dirty = True
                if entry is not None:
                    if entry is _EXIT_ENTRY:
                        return None
                    return entry
        except (KeyboardInterrupt, _UserExitError):
            return None
        finally:
            self._leave_alt_screen()

    # -- state management ---------------------------------------------------

    def _reset(self) -> None:
        """Reset all mutable state to initial values."""
        self._query = ""
        self._cursor = 0
        self._highlight_idx = 0
        self._visible = list(self._all_entries)
        self._exit_visible = self._show_exit
        self._viewport_offset = 0

    # -- display list (visible + exit) -------------------------------------

    def _display_list(self) -> list[_NumberedEntry]:
        """Return the full display list: visible entries plus exit (if shown).

        The exit entry is always appended at the end when it matches the
        current filter.
        """
        if self._exit_visible:
            return [*self._visible, self._exit_entry]
        return list(self._visible)

    # -- key handling -------------------------------------------------------

    def _on_key(self, key: str) -> EntryConfig | None:
        """Process a single keypress.

        Returns:
            An ``EntryConfig`` to launch, or ``None`` to continue the loop.

        Raises:
            _UserExitError: When the user wants to quit.
        """
        if key == "escape":
            if self._query:
                self._query = ""
                self._cursor = 0
                self._update_filter()
                return None
            raise _UserExitError

        if key == "enter":
            dl = self._display_list()
            if dl:
                return dl[self._highlight_idx].entry
            return None

        if key == "up":
            dl = self._display_list()
            if dl:
                if self._highlight_idx > 0:
                    self._highlight_idx -= 1
                else:
                    self._highlight_idx = len(dl) - 1
                self._ensure_highlight_visible()
            return None

        if key == "down":
            dl = self._display_list()
            if dl:
                if self._highlight_idx < len(dl) - 1:
                    self._highlight_idx += 1
                else:
                    self._highlight_idx = 0
                self._ensure_highlight_visible()
            return None

        if key == "backspace":
            if self._query and self._cursor > 0:
                self._query = (
                    self._query[: self._cursor - 1] + self._query[self._cursor :]
                )
                self._cursor -= 1
                self._update_filter()
            return None

        if key == "ctrl-backspace" or key == "alt-backspace":
            if self._query and self._cursor > 0:
                self._delete_word_back()
                self._update_filter()
            return None

        if key == "ctrl-w":
            if self._query and self._cursor > 0:
                self._delete_word_back()
                self._update_filter()
            return None

        if key == "ctrl-u":
            if self._query:
                self._query = self._query[self._cursor :]
                self._cursor = 0
                self._update_filter()
            return None

        if key == "ctrl-k":
            if self._cursor < len(self._query):
                self._query = self._query[: self._cursor]
                self._update_filter()
            return None

        if key == "ctrl-a":
            self._cursor = 0
            return None

        if key == "ctrl-b":
            if self._cursor > 0:
                self._cursor -= 1
            return None

        if key == "ctrl-d":
            if self._query and self._cursor < len(self._query):
                self._query = (
                    self._query[: self._cursor] + self._query[self._cursor + 1 :]
                )
                self._update_filter()
            elif not self._query:
                raise _UserExitError
            return None

        if key == "ctrl-e":
            self._cursor = len(self._query)
            return None

        if key == "ctrl-f":
            if self._cursor < len(self._query):
                self._cursor += 1
            return None

        if key == "ctrl-h":
            if self._query and self._cursor > 0:
                self._query = (
                    self._query[: self._cursor - 1] + self._query[self._cursor :]
                )
                self._cursor -= 1
                self._update_filter()
            return None

        if key == "alt-b":
            self._cursor = self._word_boundary_back()
            return None

        if key == "alt-d":
            if self._cursor < len(self._query):
                end = self._word_boundary_forward()
                self._query = self._query[: self._cursor] + self._query[end:]
                self._update_filter()
            return None

        if key == "alt-f":
            self._cursor = self._word_boundary_forward()
            return None

        # Printable character
        if len(key) == 1 and key.isprintable():
            return self._on_char(key)

        return None

    def _word_boundary_back(self) -> int:
        """Find the cursor position one word backward."""
        i = self._cursor
        while i > 0 and self._query[i - 1] == " ":
            i -= 1
        while i > 0 and self._query[i - 1] != " ":
            i -= 1
        return i

    def _word_boundary_forward(self) -> int:
        """Find the cursor position one word forward."""
        i = self._cursor
        n = len(self._query)
        while i < n and self._query[i] != " ":
            i += 1
        while i < n and self._query[i] == " ":
            i += 1
        return i

    def _delete_word_back(self) -> None:
        """Delete one word backward from cursor position."""
        left = self._query[: self._cursor]
        right = self._query[self._cursor :]
        # Skip trailing spaces, then skip non-spaces
        i = len(left)
        while i > 0 and left[i - 1] == " ":
            i -= 1
        while i > 0 and left[i - 1] != " ":
            i -= 1
        self._query = left[:i] + right
        self._cursor = i

    def _on_char(self, ch: str) -> EntryConfig | None:
        """Handle a printable character input.

        Supports immediate numeric selection (single-digit when ≤9
        entries and ``instant_numeric_launch`` is enabled), '0' for
        exit, and appending to the fuzzy query.  Triggers auto-launch
        when a numeric query narrows to one match.

        Args:
            ch: A single printable character.

        Returns:
            An ``EntryConfig`` to launch immediately, or ``None`` to
            continue the input loop.
        """
        # "0" with no active query selects exit (when exit is shown)
        if not self._query and ch == "0" and self._show_exit:
            return _EXIT_ENTRY

        # Immediate single-digit launch when ≤9 total entries
        if (
            self._instant_numeric_launch
            and not self._query
            and ch.isdigit()
            and len(self._all_entries) <= 9
        ):
            num = int(ch)
            if 1 <= num <= len(self._all_entries):
                return self._all_entries[num - 1].entry
            return None  # invalid digit — ignore

        self._query = self._query[: self._cursor] + ch + self._query[self._cursor :]
        self._cursor += 1
        self._update_filter()

        # Auto-launch if exactly one numeric match remains
        if (
            self._instant_numeric_launch
            and self._query.isdigit()
            and len(self._visible) == 1
        ):
            return self._visible[0].entry

        return None

    # -- filtering ----------------------------------------------------------

    def _update_filter(self) -> None:
        """Recompute the visible entry list from the current query.

        Three modes:
        - Empty query: show all entries.
        - Numeric query with ``instant_numeric_launch`` enabled:
          prefix-match against entry display numbers only.
        - Numeric query with ``instant_numeric_launch`` disabled:
          prefix-match against entry numbers *and* fuzzy-match entry
          names, with number matches ranked first.
        - Text query: fuzzy-match against entry names, sorted by score.

        Also resets the highlight and viewport to the top.
        """
        if not self._query:
            self._visible = list(self._all_entries)
            self._exit_visible = self._show_exit
        elif self._query.isdigit() and self._instant_numeric_launch:
            # Numeric prefix filter against entry numbers
            self._visible = [
                ne for ne in self._all_entries if str(ne.number).startswith(self._query)
            ]
            self._exit_visible = self._show_exit and "0".startswith(self._query)
        elif self._query.isdigit():
            # Numeric + fuzzy: number prefix matches first, then name
            # matches, deduplicated
            number_matches = [
                ne for ne in self._all_entries if str(ne.number).startswith(self._query)
            ]
            number_match_set = {id(ne) for ne in number_matches}
            scored: list[tuple[int, _NumberedEntry]] = []
            for ne in self._all_entries:
                if id(ne) not in number_match_set:
                    s = FuzzyMatcher.score(self._query, ne.entry.name)
                    if s is not None:
                        scored.append((s, ne))
            scored.sort(key=lambda x: x[0], reverse=True)
            self._visible = number_matches + [ne for _, ne in scored]
            self._exit_visible = self._show_exit and "0".startswith(self._query)
        else:
            # Fuzzy search against entry names
            scored = []
            for ne in self._all_entries:
                s = FuzzyMatcher.score(self._query, ne.entry.name)
                if s is not None:
                    scored.append((s, ne))
            scored.sort(key=lambda x: x[0], reverse=True)
            self._visible = [ne for _, ne in scored]
            self._exit_visible = self._show_exit and (
                FuzzyMatcher.score(self._query, self._exit_entry.entry.name) is not None
            )

        self._highlight_idx = 0
        self._viewport_offset = 0

    # -- viewport -----------------------------------------------------------

    def _max_visible_entries(self) -> int:
        """Calculate the maximum entry rows that fit in the terminal.

        Accounts for the fixed UI chrome (header, prompt, separators,
        footer) and caps the result at ``_MAX_LIST_HEIGHT``.
        """
        term_height = _get_terminal_size().lines
        available = max(1, term_height - _CHROME_LINES)
        return min(available, _MAX_LIST_HEIGHT)

    def _ensure_highlight_visible(self) -> None:
        """Scroll the viewport so the highlighted entry remains on screen.

        Adjusts ``_viewport_offset`` up or down as needed to keep the
        highlighted index within the visible window.
        """
        max_vis = self._max_visible_entries()
        if self._highlight_idx < self._viewport_offset:
            self._viewport_offset = self._highlight_idx
        elif self._highlight_idx >= self._viewport_offset + max_vis:
            self._viewport_offset = self._highlight_idx - max_vis + 1

    # -- rendering ----------------------------------------------------------

    # ANSI SGR colour codes used throughout the renderer.
    _HEADER_ACCENT = "\033[38;5;69m"  # Cornflower blue (header borders)
    _ACTIVE_ACCENT = "\033[92m"  # Bright green (highlighted entry)
    _GRAY = "\033[90m"  # Dark gray (descriptions, chrome)
    _DIM = "\033[2m"  # Dim attribute
    _BOLD = "\033[1m"  # Bold attribute
    _WHITE = "\033[97m"  # Bright white (query text, title)
    _RESET = "\033[0m"  # Reset all attributes

    def _render(self) -> None:
        """Redraw the entire launcher screen in a single buffered write.

        Composes the full screen layout using ANSI escape sequences:
        bordered header, current working directory, search prompt with
        ghost-text autocomplete hint, scrollable entry list with an
        optional scrollbar, and a footer with keybinding hints.  The
        cursor is positioned on the prompt line after rendering.
        """
        tw = _get_terminal_size().columns
        th = _get_terminal_size().lines
        max_vis = self._max_visible_entries()

        dl = self._display_list()
        total_items = len(dl)
        viewport = dl[self._viewport_offset : self._viewport_offset + max_vis]

        num_width = len(str(len(self._all_entries))) if self._all_entries else 1
        max_name_len = max(
            (len(ne.entry.name) for ne in self._all_entries),
            default=0,
        )
        max_name_len = max(max_name_len, len("Exit"))

        sep = f"{self._GRAY}{'\u2500' * tw}{self._RESET}"

        buf = ""
        row = 1

        # -- Header (3 lines) --
        title = self._config.title
        header_inner = max(4, min(tw - 2, 72))
        subtitle = "Select a tool to launch."
        subtitle_plain = f" {subtitle} "
        subtitle_fill = max(0, header_inner - len(subtitle_plain))

        buf += (
            f"\033[{row};1H"
            f"{self._HEADER_ACCENT}\u256d{'\u2500' * header_inner}\u256e{self._RESET}"
            f"\033[K"
        )
        row += 1

        title_text = f" {title} "
        title_fill = max(0, header_inner - len(title_text))
        buf += (
            f"\033[{row};1H"
            f"{self._HEADER_ACCENT}\u2502{self._RESET}"
            f"{self._BOLD}{self._WHITE}{title_text}{self._RESET}"
            f"{' ' * title_fill}"
            f"{self._HEADER_ACCENT}\u2502{self._RESET}"
            f"\033[K"
        )
        row += 1
        buf += (
            f"\033[{row};1H"
            f"{self._HEADER_ACCENT}\u2502{self._RESET}"
            f"{self._GRAY}{subtitle_plain}{self._RESET}"
            f"{' ' * subtitle_fill}"
            f"{self._HEADER_ACCENT}\u2502{self._RESET}"
            f"\033[K"
        )
        row += 1

        buf += (
            f"\033[{row};1H"
            f"{self._HEADER_ACCENT}\u2570{'\u2500' * header_inner}\u256f{self._RESET}"
            f"\033[K"
        )
        row += 1

        # -- CWD (1 line, gray) --
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home) :]
        buf += f"\033[{row};1H {self._GRAY}{cwd}{self._RESET}\033[K"
        row += 1

        # -- Separator above prompt --
        buf += f"\033[{row};1H{sep}\033[K"
        row += 1

        # -- Prompt line --
        hint = self._ghost_text() if self._ghost_text_enabled else ""
        hint_str = f" {self._GRAY}({hint}){self._RESET}" if hint else ""
        no_match = (
            f" {self._GRAY}(no matches){self._RESET}"
            if self._query and not self._display_list()
            else ""
        )
        buf += (
            f"\033[{row};1H"
            f"{self._ACTIVE_ACCENT}\u276f{self._RESET} "
            f"{self._WHITE}{self._BOLD}{self._query}{self._RESET}"
            f"{hint_str}{no_match}"
            f"\033[K"
        )
        prompt_row = row
        row += 1

        # -- Separator below prompt --
        buf += f"\033[{row};1H{sep}\033[K"
        row += 1

        # -- Scrollbar computation --
        needs_scrollbar = total_items > max_vis and max_vis > 0
        if needs_scrollbar:
            thumb_size = max(1, round(max_vis * max_vis / total_items))
            thumb_top = round(self._viewport_offset * max_vis / total_items)
            thumb_top = min(thumb_top, max_vis - thumb_size)

        # -- Entry rows with scrollbar --
        for i in range(max_vis):
            # Scrollbar character
            if needs_scrollbar:
                in_thumb = thumb_top <= i < thumb_top + thumb_size
                sb = (
                    f"{self._ACTIVE_ACCENT}\u2503{self._RESET}"
                    if in_thumb
                    else f"{self._GRAY}\u2502{self._RESET}"
                )
            else:
                sb = " "

            if i < len(viewport):
                ne = viewport[i]
                actual_idx = self._viewport_offset + i
                is_hl = actual_idx == self._highlight_idx

                num_str = str(ne.number).rjust(num_width)
                name_pad = ne.entry.name.ljust(max_name_len)
                desc_text = ne.entry.description
                desc = f"  {self._GRAY}{desc_text}{self._RESET}" if desc_text else ""
                marker = "\u25b8" if is_hl else " "

                if is_hl:
                    hl_desc = (
                        f"  {self._ACTIVE_ACCENT}{desc_text}{self._RESET}"
                        if desc_text
                        else ""
                    )
                    line = (
                        f"{sb} {self._ACTIVE_ACCENT}{self._BOLD}{marker} {num_str}  "
                        f"{name_pad}{self._RESET}{hl_desc}"
                    )
                else:
                    line = (
                        f"{sb} {marker} {self._GRAY}{num_str}  {name_pad}"
                        f"{desc}{self._RESET}"
                    )

                buf += f"\033[{row};1H{line}\033[K"
            else:
                buf += f"\033[{row};1H{sb}\033[K"
            row += 1

        # -- Clear remaining rows between list and footer --
        footer_row = th
        while row < footer_row:
            buf += f"\033[{row};1H\033[K"
            row += 1

        # -- Footer hint (last line) --
        footer_hint = (
            f"{self._GRAY}"
            f"#=select  "
            f"type=search  "
            f"\u2191\u2193=navigate  "
            f"Esc=back  "
            f"Ctrl+C=quit"
            f"{self._RESET}"
        )
        buf += f"\033[{th};1H{footer_hint}\033[K"

        # Position cursor on prompt line
        cursor_col = len("\u276f ") + self._cursor + 1
        buf += f"\033[{prompt_row};{cursor_col}H"

        sys.stdout.write(buf)
        sys.stdout.flush()

    def _ghost_text(self) -> str:
        """Return the highlighted entry's name for autocomplete hint."""
        dl = self._display_list()
        if dl and self._highlight_idx < len(dl):
            return dl[self._highlight_idx].entry.name
        return ""

    # -- alternate screen ---------------------------------------------------

    @staticmethod
    def _set_terminal_title(title: str) -> None:
        """Set the terminal tab/window title via OSC escape sequence."""
        sys.stdout.write(f"\033]0;{title}\a")
        sys.stdout.flush()

    def _enter_alt_screen(self) -> None:
        """Switch to the alternate screen buffer and set terminal title.

        Pushes Kitty keyboard protocol flag 1 (disambiguate escape codes)
        so that terminals supporting the protocol report keys without
        ambiguity.  Terminals that do not support the protocol silently
        ignore the sequence.
        """
        self._set_terminal_title(self._config.title)
        sys.stdout.write("\033[?1049h\033[>1u\033[H\033[2J")
        sys.stdout.flush()

    @staticmethod
    def _leave_alt_screen() -> None:
        """Switch back to the main screen buffer.

        Pops the Kitty keyboard protocol enhancement pushed on entry.
        """
        sys.stdout.write("\033[<u\033[?1049l")
        sys.stdout.flush()
