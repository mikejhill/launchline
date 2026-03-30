"""Tests for TUI logic and fuzzy matching."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.fuzzy import FuzzyMatcher
from launchline.keys import KeyReader
from launchline.ui import (
    _EXIT_ENTRY,
    LaunchLineUI,
    _UserExitError,
)


class TestFuzzyScore:
    """Tests for the FuzzyMatcher.score method."""

    def test_empty_query_matches_everything(self) -> None:
        assert FuzzyMatcher.score("", "anything") == 0

    def test_exact_match(self) -> None:
        score = FuzzyMatcher.score("abc", "abc")
        assert score is not None, "Exact match should return a score, got None"
        assert score > 0, f"Exact match score should be positive, got {score}"

    def test_no_match_returns_none(self) -> None:
        result = FuzzyMatcher.score("xyz", "abc")
        assert result is None, f"Non-matching query should return None, got {result}"

    def test_case_insensitive(self) -> None:
        assert FuzzyMatcher.score("ABC", "abc") is not None, (
            "Upper query vs lower candidate should still match"
        )
        assert FuzzyMatcher.score("abc", "ABC") is not None, (
            "Lower query vs upper candidate should still match"
        )

    def test_subsequence_match(self) -> None:
        score = FuzzyMatcher.score("cl", "Claude Code")
        assert score is not None, "Subsequence 'cl' should match 'Claude Code'"

    def test_contiguous_scores_higher(self) -> None:
        contiguous = FuzzyMatcher.score("cla", "Claude")
        sparse = FuzzyMatcher.score("cla", "xcxlxax")
        assert contiguous is not None, "Contiguous 'cla' in 'Claude' should match"
        assert sparse is not None, "Sparse 'cla' in 'xcxlxax' should match"
        assert contiguous > sparse, (
            f"Contiguous match ({contiguous}) should score higher "
            f"than sparse match ({sparse})"
        )

    def test_word_boundary_bonus(self) -> None:
        boundary = FuzzyMatcher.score("cc", "Claude Code")
        mid = FuzzyMatcher.score("cc", "success")
        assert boundary is not None, (
            "'cc' should match word boundaries in 'Claude Code'"
        )
        assert mid is not None, "'cc' should match mid-word in 'success'"
        assert boundary > mid, (
            f"Word-boundary match ({boundary}) should score higher "
            f"than mid-word match ({mid})"
        )

    def test_partial_match_returns_none(self) -> None:
        result = FuzzyMatcher.score("abcz", "abc")
        assert result is None, (
            f"Query 'abcz' has unmatched 'z' in 'abc', should return None, got {result}"
        )

    @pytest.mark.parametrize(
        ("query", "candidate", "expected_match"),
        [
            ("ps", "PowerShell", True),
            ("git", "GitHub Copilot CLI", True),
            ("zzz", "GitHub Copilot CLI", False),
            ("c", "Claude Code", True),
            ("cx", "Codex CLI", True),
        ],
    )
    def test_various_matches(
        self, query: str, candidate: str, expected_match: bool
    ) -> None:
        result = FuzzyMatcher.score(query, candidate)
        assert (result is not None) == expected_match, (
            f"score({query!r}, {candidate!r}) = {result}, "
            f"expected {'match' if expected_match else 'no match'}"
        )


class TestLaunchLineUIFiltering:
    """Tests for the filtering and state management of LaunchLineUI."""

    def test_initial_visible_equals_all(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        assert len(ui._visible) == len(sample_config.entries), (
            f"Initial visible count ({len(ui._visible)}) should equal "
            f"entry count ({len(sample_config.entries)})"
        )

    def test_fuzzy_filter_narrows_results(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "clau"
        ui._update_filter()
        assert len(ui._visible) == 1, (
            f"Filtering by 'clau' should yield 1 result, got {len(ui._visible)}"
        )

    def test_fuzzy_filter_resets_highlight(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._highlight_idx = 2
        ui._query = "cop"
        ui._update_filter()
        assert ui._highlight_idx == 0

    def test_empty_query_shows_all(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "copilot"
        ui._update_filter()
        assert len(ui._visible) < len(sample_config.entries)
        ui._query = ""
        ui._update_filter()
        assert len(ui._visible) == len(sample_config.entries)

    def test_no_matches_gives_empty_list(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "zzzzz"
        ui._update_filter()
        assert len(ui._visible) == 0, (
            f"Query 'zzzzz' should match nothing, got {len(ui._visible)} results"
        )

    def test_fuzzy_results_sorted_by_score(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "c"
        ui._update_filter()
        # All entries with 'c' should appear, best match first
        names = [ne.entry.name for ne in ui._visible]
        assert len(names) >= 2, (
            f"Query 'c' should match at least 2 entries, got {names}"
        )


class TestLaunchLineUINumericFilter:
    """Tests for numeric prefix filtering with >9 entries."""

    def test_numeric_filter_by_prefix(
        self, many_entries_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(many_entries_config)
        ui._reset()
        ui._query = "1"
        ui._update_filter()
        # Entries 1, 10, 11, 12 have numbers starting with "1"
        numbers = [ne.number for ne in ui._visible]
        assert 1 in numbers, "Entry 1 should appear for numeric prefix '1'"
        assert 10 in numbers, "Entry 10 should appear for numeric prefix '1'"
        assert 11 in numbers, "Entry 11 should appear for numeric prefix '1'"
        assert 12 in numbers, "Entry 12 should appear for numeric prefix '1'"
        assert 2 not in numbers, "Entry 2 should not appear for numeric prefix '1'"

    def test_numeric_filter_two_digits(
        self, many_entries_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(many_entries_config)
        ui._reset()
        ui._query = "12"
        ui._update_filter()
        assert len(ui._visible) == 1, (
            f"Two-digit prefix '12' should match exactly 1 entry, "
            f"got {len(ui._visible)}"
        )


class TestLaunchLineUIDisplayList:
    """Tests for the display list (visible + exit)."""

    def test_display_list_appends_exit(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        dl = ui._display_list()
        assert dl[-1].number == 0
        assert dl[-1].entry is _EXIT_ENTRY, "Last display item should be the exit entry"
        assert len(dl) == len(sample_config.entries) + 1, (
            f"Display list should have entries + exit = "
            f"{len(sample_config.entries) + 1}, got {len(dl)}"
        )


class TestLaunchLineUIKeyHandling:
    """Tests for the _on_key method."""

    def test_enter_selects_highlighted(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("enter")
        assert result is not None, "Enter should select the highlighted entry"

    def test_down_then_enter(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._on_key("down")
        result = ui._on_key("enter")
        assert result is not None, "Enter should select the highlighted entry"

    def test_up_at_top_wraps_to_exit(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._on_key("up")
        # display_list has entries + exit, so wrapping goes to last = exit
        dl = ui._display_list()
        assert ui._highlight_idx == len(dl) - 1

    def test_down_past_exit_wraps_to_top(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        dl = ui._display_list()
        for _ in range(len(dl) - 1):
            ui._on_key("down")
        assert ui._highlight_idx == len(dl) - 1
        ui._on_key("down")
        assert ui._highlight_idx == 0

    def test_enter_on_exit_returns_exit_entry(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        # Navigate to exit (last in display list)
        dl = ui._display_list()
        for _ in range(len(dl) - 1):
            ui._on_key("down")
        result = ui._on_key("enter")
        assert result is _EXIT_ENTRY, "Selecting exit row should return _EXIT_ENTRY"

    def test_escape_with_query_clears(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "test"
        ui._cursor = 4
        ui._update_filter()
        result = ui._on_key("escape")
        assert result is None  # continue
        assert ui._query == "", "Escape should clear the query"
        assert ui._cursor == 0, "Escape should reset cursor to 0"

    def test_escape_without_query_raises_exit(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        with pytest.raises(_UserExitError):
            ui._on_key("escape")

    def test_digit_immediate_launch_with_few_entries(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("2")
        assert result is not None, "Digit 2 should immediately launch entry 2"

    def test_invalid_digit_ignored(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("9")  # only 4 entries
        assert result is None, "Digit beyond entry count should be ignored"

    def test_zero_returns_exit_entry(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("0")
        assert result is _EXIT_ENTRY, "Digit 0 should return the exit entry"

    def test_zero_appended_to_existing_query(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "1"
        ui._cursor = 1
        ui._update_filter()
        result = ui._on_key("0")
        assert ui._query == "10"
        # Not an exit — just a query update
        assert result is None or isinstance(result, EntryConfig)

    def test_digit_enters_numeric_mode_with_many_entries(
        self, many_entries_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(many_entries_config)
        ui._reset()
        result = ui._on_key("1")
        assert result is None, (
            "Ambiguous digit should enter query mode, not auto-launch"
        )
        assert ui._query == "1", "Digit should be appended to query"
        assert len(ui._visible) > 1, (
            "Ambiguous numeric prefix should show multiple entries"
        )

    def test_backspace_removes_character(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "cl"
        ui._cursor = 2
        ui._update_filter()
        ui._on_key("backspace")
        assert ui._query == "c"
        assert ui._cursor == 1


class TestLaunchLineUITextEditing:
    """Tests for Emacs/PowerShell text editing bindings."""

    def test_ctrl_a_moves_cursor_to_start(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 5
        ui._on_key("ctrl-a")
        assert ui._cursor == 0

    def test_ctrl_e_moves_cursor_to_end(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 2
        ui._on_key("ctrl-e")
        assert ui._cursor == 5

    def test_ctrl_u_kills_line_before_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcdef"
        ui._cursor = 3
        ui._on_key("ctrl-u")
        assert ui._query == "def"
        assert ui._cursor == 0

    def test_ctrl_k_kills_line_after_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcdef"
        ui._cursor = 3
        ui._on_key("ctrl-k")
        assert ui._query == "abc"

    def test_ctrl_w_deletes_word_back(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello world"
        ui._cursor = 11
        ui._on_key("ctrl-w")
        assert ui._query == "hello "
        assert ui._cursor == 6

    def test_ctrl_backspace_deletes_word_back(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 13
        ui._on_key("ctrl-backspace")
        assert ui._query == "one two "
        assert ui._cursor == 8

    def test_backspace_at_cursor_mid_position(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcd"
        ui._cursor = 2
        ui._on_key("backspace")
        assert ui._query == "acd"
        assert ui._cursor == 1

    def test_char_insert_at_cursor_mid(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        # Start fresh to avoid digit-launch behavior
        ui._query = "ac"
        ui._cursor = 1
        ui._update_filter()
        ui._on_key("b")
        assert ui._query == "abc"
        assert ui._cursor == 2

    def test_ctrl_b_moves_cursor_back(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 3
        ui._on_key("ctrl-b")
        assert ui._cursor == 2

    def test_ctrl_b_at_start_stays(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 0
        ui._on_key("ctrl-b")
        assert ui._cursor == 0

    def test_ctrl_f_moves_cursor_forward(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 2
        ui._on_key("ctrl-f")
        assert ui._cursor == 3

    def test_ctrl_f_at_end_stays(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 5
        ui._on_key("ctrl-f")
        assert ui._cursor == 5

    def test_ctrl_d_deletes_char_under_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcdef"
        ui._cursor = 2
        ui._on_key("ctrl-d")
        assert ui._query == "abdef"
        assert ui._cursor == 2

    def test_ctrl_d_at_end_does_nothing(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abc"
        ui._cursor = 3
        ui._on_key("ctrl-d")
        assert ui._query == "abc"

    def test_ctrl_d_on_empty_query_exits(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        with pytest.raises(_UserExitError):
            ui._on_key("ctrl-d")

    def test_ctrl_h_backspace_alias(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcd"
        ui._cursor = 3
        ui._on_key("ctrl-h")
        assert ui._query == "abd"
        assert ui._cursor == 2

    def test_alt_b_moves_word_back(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 13
        ui._on_key("alt-b")
        assert ui._cursor == 8

    def test_alt_f_moves_word_forward(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 0
        ui._on_key("alt-f")
        assert ui._cursor == 4

    def test_alt_d_deletes_word_forward(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 4
        ui._on_key("alt-d")
        assert ui._query == "one three"
        assert ui._cursor == 4

    def test_alt_d_at_end_does_nothing(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 5
        ui._on_key("alt-d")
        assert ui._query == "hello"


class TestLaunchLineUIRun:
    """Tests for the LaunchLineUI.run() public API."""

    def test_run_returns_entry_on_enter(self, sample_config: LaunchLineConfig) -> None:
        keys = iter(["enter"])
        ui = LaunchLineUI(sample_config, _key_reader=lambda: next(keys))
        result = ui.run()
        assert result is not None, "run() with 'enter' should return an entry"

    def test_run_returns_none_on_escape(self, sample_config: LaunchLineConfig) -> None:
        keys = iter(["escape"])
        ui = LaunchLineUI(sample_config, _key_reader=lambda: next(keys))
        result = ui.run()
        assert result is None, "run() with 'escape' should return None"

    def test_run_returns_none_on_keyboard_interrupt(
        self, sample_config: LaunchLineConfig
    ) -> None:
        def raise_interrupt() -> str:
            raise KeyboardInterrupt

        ui = LaunchLineUI(sample_config, _key_reader=raise_interrupt)
        result = ui.run()
        assert result is None, "KeyboardInterrupt should cause run() to return None"

    def test_run_navigates_and_selects(self, sample_config: LaunchLineConfig) -> None:
        keys = iter(["down", "down", "enter"])
        ui = LaunchLineUI(sample_config, _key_reader=lambda: next(keys))
        result = ui.run()
        assert result is not None, "Navigate + enter should select an entry"

    def test_run_returns_none_on_exit_entry(
        self, sample_config: LaunchLineConfig
    ) -> None:
        keys = iter(["0"])
        ui = LaunchLineUI(sample_config, _key_reader=lambda: next(keys))
        result = ui.run()
        assert result is None, "Selecting exit entry should make run() return None"

    """Tests for viewport scrolling with many entries."""

    _TERM_PATCH = "launchline.ui._get_terminal_size"

    def test_viewport_scrolls_down(self, many_entries_config: LaunchLineConfig) -> None:
        size = os.terminal_size((80, 20))
        with patch(self._TERM_PATCH, return_value=size):
            ui = LaunchLineUI(many_entries_config)
            ui._reset()
            # max_visible = min(20 - 9, 10) = 10; 12 entries + exit = 13
            for _ in range(11):
                ui._on_key("down")
            assert ui._viewport_offset > 0, (
                f"Expected viewport to scroll with highlight at "
                f"{ui._highlight_idx}, "
                f"but offset was {ui._viewport_offset}"
            )

    def test_viewport_scrolls_back_up(
        self, many_entries_config: LaunchLineConfig
    ) -> None:
        size = os.terminal_size((80, 20))
        with patch(self._TERM_PATCH, return_value=size):
            ui = LaunchLineUI(many_entries_config)
            ui._reset()
            for _ in range(11):
                ui._on_key("down")
            for _ in range(11):
                ui._on_key("up")
            assert ui._highlight_idx == 0
            assert ui._viewport_offset == 0

    def test_max_list_height_capped_at_10(self) -> None:
        size = os.terminal_size((80, 50))
        with patch(self._TERM_PATCH, return_value=size):
            config = LaunchLineConfig(entries=())
            ui = LaunchLineUI(config)
            assert ui._max_visible_entries() == 10

    def test_max_list_height_shrinks_for_small_terminal(self) -> None:
        size = os.terminal_size((80, 12))
        with patch(self._TERM_PATCH, return_value=size):
            config = LaunchLineConfig(entries=())
            ui = LaunchLineUI(config)
            assert ui._max_visible_entries() < 10


class TestLaunchLineUIGhostText:
    """Tests for the autocomplete ghost text."""

    def test_ghost_shows_highlighted_name(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ghost = ui._ghost_text()
        assert ghost == "GitHub Copilot CLI"

    def test_ghost_shows_name_regardless_of_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "test"
        ui._cursor = 2  # cursor not at end — still shows hint
        ghost = ui._ghost_text()
        assert ghost == "GitHub Copilot CLI"

    def test_ghost_empty_when_no_visible(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "zzzzz"
        ui._cursor = 5
        ui._update_filter()
        ghost = ui._ghost_text()
        assert ghost == ""

    def test_ghost_shows_exit_when_exit_highlighted(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        # Navigate up from top to wrap to Exit (last in display list)
        ui._on_key("up")
        ghost = ui._ghost_text()
        assert ghost == "Exit"

    def test_ghost_text_enabled_by_default(
        self, sample_config: LaunchLineConfig
    ) -> None:
        """Ghost text is enabled by default (ghost_text=True)."""
        ui = LaunchLineUI(sample_config)
        assert ui._ghost_text_enabled is True, "ghost_text should default to True"

    def test_ghost_text_disabled_via_config(self) -> None:
        """Ghost text hidden when ghost_text=False."""
        config = LaunchLineConfig(
            entries=(EntryConfig(name="Tool", command="tool"),),
            ghost_text=False,
        )
        ui = LaunchLineUI(config)
        assert ui._ghost_text_enabled is False, (
            "ghost_text=False should disable the feature"
        )


class TestInstantNumericLaunch:
    """Tests for the instant_numeric_launch feature flag."""

    def test_enabled_by_default(self, sample_config: LaunchLineConfig) -> None:
        """Instant numeric launch is enabled by default."""
        ui = LaunchLineUI(sample_config)
        assert ui._instant_numeric_launch is True

    def test_digit_launches_immediately_when_enabled(
        self, sample_config: LaunchLineConfig
    ) -> None:
        """With instant_numeric_launch=True and ≤9 entries, digit launches."""
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("2")
        assert result is not None, "Digit 2 should immediately launch"
        assert result.name == "Claude Code"

    def test_digit_enters_query_when_disabled(self) -> None:
        """With instant_numeric_launch=False, digit goes to search query."""
        config = LaunchLineConfig(
            entries=(
                EntryConfig(name="Alpha", command="a"),
                EntryConfig(name="Beta", command="b"),
            ),
            instant_numeric_launch=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        result = ui._on_key("1")
        assert result is None, (
            "Digit should not launch when instant_numeric_launch=False"
        )
        assert ui._query == "1", "Digit should be appended to query"

    def test_disabled_numeric_query_also_fuzzy_matches_names(self) -> None:
        """When disabled, numeric query matches both numbers and names."""
        config = LaunchLineConfig(
            entries=(
                EntryConfig(name="Item A", command="a"),
                EntryConfig(name="Item B", command="b"),
                EntryConfig(name="Item 2x", command="c"),
            ),
            instant_numeric_launch=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        ui._query = "2"
        ui._cursor = 1
        ui._update_filter()
        names = [ne.entry.name for ne in ui._visible]
        # Entry #2 ("Item B") matches by number prefix
        assert "Item B" in names, "Entry #2 should appear via number prefix match"
        # Entry #3 ("Item 2x") matches by fuzzy name (contains "2")
        assert "Item 2x" in names, "'Item 2x' should appear via fuzzy name match on '2'"

    def test_disabled_number_matches_ranked_before_name_matches(self) -> None:
        """Number prefix matches appear before fuzzy name matches."""
        config = LaunchLineConfig(
            entries=(
                EntryConfig(name="Version 1 tool", command="a"),
                EntryConfig(name="Other", command="b"),
                EntryConfig(name="Another", command="c"),
            ),
            instant_numeric_launch=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        ui._query = "1"
        ui._cursor = 1
        ui._update_filter()
        # Entry #1 ("Version 1 tool") matches by number prefix
        # "Version 1 tool" also has "1" in the name but number match is first
        assert len(ui._visible) >= 1, "Should have at least the number match"
        assert ui._visible[0].number == 1, (
            f"First result should be entry #1 (number match), "
            f"got entry #{ui._visible[0].number}"
        )

    def test_disabled_no_auto_launch_on_single_numeric_match(self) -> None:
        """When disabled, single numeric match does NOT auto-launch."""
        config = LaunchLineConfig(
            entries=(
                EntryConfig(name="Alpha", command="a"),
                EntryConfig(name="Beta", command="b"),
            ),
            instant_numeric_launch=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        # Type "2" — only entry #2 matches by number
        result = ui._on_key("2")
        assert result is None, (
            "Should not auto-launch even with single numeric match "
            "when instant_numeric_launch=False"
        )

    def test_zero_still_exits_when_disabled(self) -> None:
        """Pressing 0 with no query still returns exit entry."""
        config = LaunchLineConfig(
            entries=(EntryConfig(name="Tool", command="t"),),
            instant_numeric_launch=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        result = ui._on_key("0")
        assert result is _EXIT_ENTRY, (
            "0 should still select exit even with instant_numeric_launch=False"
        )


class TestKittyProtocolDecoder:
    """Tests for the Kitty keyboard protocol CSI u decoder."""

    def test_escape_codepoint_returns_escape(self) -> None:
        assert KeyReader._decode_kitty_key("27") == "escape"

    def test_enter_codepoint_returns_enter(self) -> None:
        assert KeyReader._decode_kitty_key("13") == "enter"

    def test_backspace_codepoint_returns_backspace(self) -> None:
        assert KeyReader._decode_kitty_key("127") == "backspace"

    def test_ctrl_backspace_returns_ctrl_backspace(self) -> None:
        # modifier 5 = 1 + ctrl(4)
        assert KeyReader._decode_kitty_key("127;5") == "ctrl-backspace"

    def test_alt_backspace_returns_alt_backspace(self) -> None:
        # modifier 3 = 1 + alt(2)
        assert KeyReader._decode_kitty_key("127;3") == "alt-backspace"

    def test_ctrl_a_returns_ctrl_a(self) -> None:
        assert KeyReader._decode_kitty_key("97;5") == "ctrl-a"

    def test_ctrl_e_returns_ctrl_e(self) -> None:
        assert KeyReader._decode_kitty_key("101;5") == "ctrl-e"

    def test_ctrl_k_returns_ctrl_k(self) -> None:
        assert KeyReader._decode_kitty_key("107;5") == "ctrl-k"

    def test_ctrl_u_returns_ctrl_u(self) -> None:
        assert KeyReader._decode_kitty_key("117;5") == "ctrl-u"

    def test_ctrl_w_returns_ctrl_w(self) -> None:
        assert KeyReader._decode_kitty_key("119;5") == "ctrl-w"

    def test_ctrl_b_returns_ctrl_b(self) -> None:
        assert KeyReader._decode_kitty_key("98;5") == "ctrl-b"

    def test_ctrl_d_returns_ctrl_d(self) -> None:
        assert KeyReader._decode_kitty_key("100;5") == "ctrl-d"

    def test_ctrl_f_returns_ctrl_f(self) -> None:
        assert KeyReader._decode_kitty_key("102;5") == "ctrl-f"

    def test_ctrl_h_returns_ctrl_h(self) -> None:
        assert KeyReader._decode_kitty_key("104;5") == "ctrl-h"

    def test_alt_b_returns_alt_b(self) -> None:
        # modifier 3 = 1 + alt(2)
        assert KeyReader._decode_kitty_key("98;3") == "alt-b"

    def test_alt_d_returns_alt_d(self) -> None:
        assert KeyReader._decode_kitty_key("100;3") == "alt-d"

    def test_alt_f_returns_alt_f(self) -> None:
        assert KeyReader._decode_kitty_key("102;3") == "alt-f"

    def test_ctrl_c_raises_keyboard_interrupt(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            KeyReader._decode_kitty_key("99;5")

    def test_printable_chars_return_literal(self) -> None:
        assert KeyReader._decode_kitty_key("97") == "a"
        assert KeyReader._decode_kitty_key("65") == "A"
        assert KeyReader._decode_kitty_key("48") == "0"

    def test_release_event_returns_empty(self) -> None:
        # modifier 1; event_type 3 = release
        assert KeyReader._decode_kitty_key("27;1:3") == ""

    def test_unknown_codepoint_returns_empty(self) -> None:
        # Private use area key
        assert KeyReader._decode_kitty_key("57358") == ""

    def test_empty_params_returns_empty(self) -> None:
        assert KeyReader._decode_kitty_key("") == ""

    def test_csi_arrow_a_returns_up_b_returns_down(self) -> None:
        assert KeyReader._dispatch_csi("", "A") == "up"
        assert KeyReader._dispatch_csi("", "B") == "down"


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt only available on Windows")
class TestWindowsCSISequenceParsing:
    """Tests for CSI sequence parsing on the Windows code path."""

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_esc_bracket_dispatches_csi_sequence(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """ESC followed by [ triggers CSI parsing (e.g., arrow up)."""
        mock_getwch.side_effect = ["\x1b", "[", "A"]
        mock_kbhit.side_effect = [True, True]
        assert KeyReader._read_key_windows() == "up"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_ctrl_backspace_on_windows(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Ctrl+Backspace via Kitty protocol: ESC [ 127 ; 5 u."""
        mock_getwch.side_effect = ["\x1b", "[", "1", "2", "7", ";", "5", "u"]
        mock_kbhit.side_effect = [True] + [True] * 7
        assert KeyReader._read_key_windows() == "ctrl-backspace"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_ctrl_c_on_windows(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Ctrl+C via Kitty protocol: ESC [ 99 ; 5 u raises KeyboardInterrupt."""
        mock_getwch.side_effect = ["\x1b", "[", "9", "9", ";", "5", "u"]
        mock_kbhit.side_effect = [True] + [True] * 6
        with pytest.raises(KeyboardInterrupt):
            KeyReader._read_key_windows()

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_escape_key_on_windows(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Escape via Kitty protocol: ESC [ 27 u."""
        mock_getwch.side_effect = ["\x1b", "[", "2", "7", "u"]
        mock_kbhit.side_effect = [True] + [True] * 4
        assert KeyReader._read_key_windows() == "escape"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_bare_escape_no_following_chars(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Bare ESC with nothing following returns 'escape'."""
        mock_getwch.return_value = "\x1b"
        mock_kbhit.return_value = False
        assert KeyReader._read_key_windows() == "escape"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_ctrl_backspace_with_numlock(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Ctrl+Backspace with NumLock: ESC [ 127 ; 133 u (133 = 1+4+128)."""
        mock_getwch.side_effect = ["\x1b", "[", "1", "2", "7", ";", "1", "3", "3", "u"]
        mock_kbhit.side_effect = [True] + [True] * 9
        assert KeyReader._read_key_windows() == "ctrl-backspace"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_printable_char_on_windows(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Printable char via Kitty: ESC [ 97 u → 'a'."""
        mock_getwch.side_effect = ["\x1b", "[", "9", "7", "u"]
        mock_kbhit.side_effect = [True] + [True] * 4
        assert KeyReader._read_key_windows() == "a"

    def test_dispatch_csi_kitty_u(self) -> None:
        assert KeyReader._dispatch_csi("27", "u") == "escape"

    def test_dispatch_csi_unknown_terminator(self) -> None:
        assert KeyReader._dispatch_csi("", "C") == ""
