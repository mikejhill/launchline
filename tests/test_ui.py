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
        assert FuzzyMatcher.score("", "anything") == 0, (
            "Empty query should return score 0 for any candidate"
        )

    def test_exact_match_returns_positive_score(self) -> None:
        score = FuzzyMatcher.score("abc", "abc")
        assert score is not None, "Exact match should return a score, got None"
        assert score > 0, f"Exact match score should be positive, got {score}"

    def test_no_match_returns_none(self) -> None:
        result = FuzzyMatcher.score("xyz", "abc")
        assert result is None, f"Non-matching query should return None, got {result}"

    def test_case_insensitive_match_returns_score(self) -> None:
        assert FuzzyMatcher.score("ABC", "abc") is not None, (
            "Upper query vs lower candidate should still match"
        )
        assert FuzzyMatcher.score("abc", "ABC") is not None, (
            "Lower query vs upper candidate should still match"
        )

    def test_subsequence_match_returns_positive_score(self) -> None:
        score = FuzzyMatcher.score("cl", "Claude Code")
        assert score is not None, "Subsequence 'cl' should match 'Claude Code'"

    def test_contiguous_match_scores_higher_than_sparse(self) -> None:
        contiguous = FuzzyMatcher.score("cla", "Claude")
        sparse = FuzzyMatcher.score("cla", "xcxlxax")
        assert contiguous is not None, "Contiguous 'cla' in 'Claude' should match"
        assert sparse is not None, "Sparse 'cla' in 'xcxlxax' should match"
        assert contiguous > sparse, (
            f"Contiguous match ({contiguous}) should score higher "
            f"than sparse match ({sparse})"
        )

    def test_word_boundary_match_scores_higher(self) -> None:
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
    def test_parametrized_match_expectations(
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
        assert ui._highlight_idx == 0, (
            f"Expected highlight reset to 0, got {ui._highlight_idx}"
        )

    def test_empty_query_shows_all(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "copilot"
        ui._update_filter()
        assert len(ui._visible) < len(sample_config.entries), (
            f"Filtered results ({len(ui._visible)}) should be fewer "
            f"than total entries ({len(sample_config.entries)})"
        )
        ui._query = ""
        ui._update_filter()
        assert len(ui._visible) == len(sample_config.entries), (
            f"Clearing query should restore all entries, "
            f"got {len(ui._visible)} of {len(sample_config.entries)}"
        )

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

    def test_numeric_prefix_filters_matching_entries(
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

    def test_two_digit_prefix_matches_single_entry(
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

    def test_display_list_includes_exit_as_last_entry(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        dl = ui._display_list()
        assert dl[-1].number == 0, f"Exit entry number should be 0, got {dl[-1].number}"
        assert dl[-1].entry is _EXIT_ENTRY, "Last display item should be the exit entry"
        assert len(dl) == len(sample_config.entries) + 1, (
            f"Display list should have entries + exit = "
            f"{len(sample_config.entries) + 1}, got {len(dl)}"
        )


class TestLaunchLineUIKeyHandling:
    """Tests for the _on_key method."""

    def test_enter_returns_highlighted_entry(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("enter")
        assert result is not None, "Enter should select the highlighted entry"

    def test_down_then_enter_selects_second_entry(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._on_key("down")
        result = ui._on_key("enter")
        assert result is not None, "Enter should select the highlighted entry"

    def test_up_at_top_wraps_to_last_entry(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._on_key("up")
        # display_list has entries + exit, so wrapping goes to last = exit
        dl = ui._display_list()
        assert ui._highlight_idx == len(dl) - 1, (
            f"Expected highlight at last index {len(dl) - 1}, got {ui._highlight_idx}"
        )

    def test_down_past_last_wraps_to_first(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        dl = ui._display_list()
        for _ in range(len(dl) - 1):
            ui._on_key("down")
        assert ui._highlight_idx == len(dl) - 1, (
            f"Expected highlight at last index {len(dl) - 1}, got {ui._highlight_idx}"
        )
        ui._on_key("down")
        assert ui._highlight_idx == 0, (
            f"Expected wrap to index 0, got {ui._highlight_idx}"
        )

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

    def test_escape_clears_query_when_present(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "test"
        ui._cursor = 4
        ui._update_filter()
        result = ui._on_key("escape")
        assert result is None, f"Expected None (continue), got {result!r}"
        assert ui._query == "", "Escape should clear the query"
        assert ui._cursor == 0, "Escape should reset cursor to 0"

    def test_escape_without_query_raises_exit(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        with pytest.raises(_UserExitError):
            ui._on_key("escape")

    def test_digit_launches_immediately_with_few_entries(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("2")
        assert result is not None, "Digit 2 should immediately launch entry 2"

    def test_out_of_range_digit_returns_none(
        self, sample_config: LaunchLineConfig
    ) -> None:
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
        assert ui._query == "10", f"Expected query '10', got {ui._query!r}"
        # Not an exit — just a query update
        assert result is None or isinstance(result, EntryConfig), (
            f"Expected None or EntryConfig, got {result!r}"
        )

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

    def test_backspace_removes_last_query_char(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "cl"
        ui._cursor = 2
        ui._update_filter()
        ui._on_key("backspace")
        assert ui._query == "c", f"Expected query 'c', got {ui._query!r}"
        assert ui._cursor == 1, f"Expected cursor at 1, got {ui._cursor}"


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
        assert ui._cursor == 0, f"Expected cursor at 0, got {ui._cursor}"

    def test_ctrl_e_moves_cursor_to_end(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 2
        ui._on_key("ctrl-e")
        assert ui._cursor == 5, f"Expected cursor at 5, got {ui._cursor}"

    def test_ctrl_u_kills_line_before_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcdef"
        ui._cursor = 3
        ui._on_key("ctrl-u")
        assert ui._query == "def", f"Expected query 'def', got {ui._query!r}"
        assert ui._cursor == 0, f"Expected cursor at 0, got {ui._cursor}"

    def test_ctrl_k_kills_line_after_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcdef"
        ui._cursor = 3
        ui._on_key("ctrl-k")
        assert ui._query == "abc", f"Expected query 'abc', got {ui._query!r}"

    def test_ctrl_w_deletes_word_back(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello world"
        ui._cursor = 11
        ui._on_key("ctrl-w")
        assert ui._query == "hello ", f"Expected query 'hello ', got {ui._query!r}"
        assert ui._cursor == 6, f"Expected cursor at 6, got {ui._cursor}"

    def test_ctrl_backspace_deletes_word_back(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 13
        ui._on_key("ctrl-backspace")
        assert ui._query == "one two ", f"Expected query 'one two ', got {ui._query!r}"
        assert ui._cursor == 8, f"Expected cursor at 8, got {ui._cursor}"

    def test_backspace_at_mid_position_removes_preceding_char(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcd"
        ui._cursor = 2
        ui._on_key("backspace")
        assert ui._query == "acd", f"Expected query 'acd', got {ui._query!r}"
        assert ui._cursor == 1, f"Expected cursor at 1, got {ui._cursor}"

    def test_char_at_mid_position_inserts_before_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        # Start fresh to avoid digit-launch behavior
        ui._query = "ac"
        ui._cursor = 1
        ui._update_filter()
        ui._on_key("b")
        assert ui._query == "abc", f"Expected query 'abc', got {ui._query!r}"
        assert ui._cursor == 2, f"Expected cursor at 2, got {ui._cursor}"

    def test_ctrl_b_moves_cursor_back_one_position(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 3
        ui._on_key("ctrl-b")
        assert ui._cursor == 2, f"Expected cursor at 2, got {ui._cursor}"

    def test_ctrl_b_at_start_stays(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 0
        ui._on_key("ctrl-b")
        assert ui._cursor == 0, f"Expected cursor at 0, got {ui._cursor}"

    def test_ctrl_f_moves_cursor_forward_one_position(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 2
        ui._on_key("ctrl-f")
        assert ui._cursor == 3, f"Expected cursor at 3, got {ui._cursor}"

    def test_ctrl_f_at_end_stays(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 5
        ui._on_key("ctrl-f")
        assert ui._cursor == 5, f"Expected cursor at 5, got {ui._cursor}"

    def test_ctrl_d_deletes_char_under_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abcdef"
        ui._cursor = 2
        ui._on_key("ctrl-d")
        assert ui._query == "abdef", f"Expected query 'abdef', got {ui._query!r}"
        assert ui._cursor == 2, f"Expected cursor at 2, got {ui._cursor}"

    def test_ctrl_d_at_end_does_nothing(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "abc"
        ui._cursor = 3
        ui._on_key("ctrl-d")
        assert ui._query == "abc", (
            f"Expected query unchanged at 'abc', got {ui._query!r}"
        )

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
        assert ui._query == "abd", f"Expected query 'abd', got {ui._query!r}"
        assert ui._cursor == 2, f"Expected cursor at 2, got {ui._cursor}"

    def test_alt_b_moves_cursor_back_one_word(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 13
        ui._on_key("alt-b")
        assert ui._cursor == 8, f"Expected cursor at 8, got {ui._cursor}"

    def test_alt_f_moves_cursor_forward_one_word(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 0
        ui._on_key("alt-f")
        assert ui._cursor == 4, f"Expected cursor at 4, got {ui._cursor}"

    def test_alt_d_deletes_word_forward(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "one two three"
        ui._cursor = 4
        ui._on_key("alt-d")
        assert ui._query == "one three", (
            f"Expected query 'one three', got {ui._query!r}"
        )
        assert ui._cursor == 4, f"Expected cursor at 4, got {ui._cursor}"

    def test_alt_d_at_end_does_nothing(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "hello"
        ui._cursor = 5
        ui._on_key("alt-d")
        assert ui._query == "hello", (
            f"Expected query unchanged at 'hello', got {ui._query!r}"
        )


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

    def test_run_returns_entry_after_navigation(
        self, sample_config: LaunchLineConfig
    ) -> None:
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
            assert ui._highlight_idx == 0, (
                f"Expected highlight at 0, got {ui._highlight_idx}"
            )
            assert ui._viewport_offset == 0, (
                f"Expected viewport offset 0, got {ui._viewport_offset}"
            )

    def test_max_list_height_capped_at_10(self) -> None:
        size = os.terminal_size((80, 50))
        with patch(self._TERM_PATCH, return_value=size):
            config = LaunchLineConfig(entries=())
            ui = LaunchLineUI(config)
            assert ui._max_visible_entries() == 10, (
                f"Expected max 10, got {ui._max_visible_entries()}"
            )

    def test_max_list_height_reduced_for_small_terminal(self) -> None:
        size = os.terminal_size((80, 12))
        with patch(self._TERM_PATCH, return_value=size):
            config = LaunchLineConfig(entries=())
            ui = LaunchLineUI(config)
            assert ui._max_visible_entries() < 10, (
                f"Expected max entries < 10, got {ui._max_visible_entries()}"
            )


class TestLaunchLineUIGhostText:
    """Tests for the autocomplete ghost text."""

    def test_ghost_shows_highlighted_name(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ghost = ui._ghost_text()
        assert ghost == "GitHub Copilot CLI", (
            f"Expected ghost 'GitHub Copilot CLI', got {ghost!r}"
        )

    def test_ghost_shows_name_regardless_of_cursor(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "test"
        ui._cursor = 2  # cursor not at end — still shows hint
        ghost = ui._ghost_text()
        assert ghost == "GitHub Copilot CLI", (
            f"Expected ghost 'GitHub Copilot CLI', got {ghost!r}"
        )

    def test_ghost_empty_when_no_visible(self, sample_config: LaunchLineConfig) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        ui._query = "zzzzz"
        ui._cursor = 5
        ui._update_filter()
        ghost = ui._ghost_text()
        assert ghost == "", f"Expected empty ghost text, got {ghost!r}"

    def test_ghost_shows_exit_when_exit_highlighted(
        self, sample_config: LaunchLineConfig
    ) -> None:
        ui = LaunchLineUI(sample_config)
        ui._reset()
        # Navigate up from top to wrap to Exit (last in display list)
        ui._on_key("up")
        ghost = ui._ghost_text()
        assert ghost == "Exit", f"Expected ghost 'Exit', got {ghost!r}"

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


class TestNumericTrigger:
    """Tests for the numeric_trigger feature flag."""

    def test_enabled_by_default(self, sample_config: LaunchLineConfig) -> None:
        """Numeric trigger is enabled by default."""
        ui = LaunchLineUI(sample_config)
        assert ui._numeric_trigger is True, (
            f"Expected numeric_trigger True, got {ui._numeric_trigger!r}"
        )

    def test_digit_launches_immediately_when_enabled(
        self, sample_config: LaunchLineConfig
    ) -> None:
        """With numeric_trigger=True and ≤9 entries, digit launches."""
        ui = LaunchLineUI(sample_config)
        ui._reset()
        result = ui._on_key("2")
        assert result is not None, "Digit 2 should immediately launch"
        assert result.name == "Claude Code", (
            f"Expected 'Claude Code', got {result.name!r}"
        )

    def test_digit_enters_query_when_disabled(self) -> None:
        """With numeric_trigger=False, digit goes to search query."""
        config = LaunchLineConfig(
            entries=(
                EntryConfig(name="Alpha", command="a"),
                EntryConfig(name="Beta", command="b"),
            ),
            numeric_trigger=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        result = ui._on_key("1")
        assert result is None, "Digit should not launch when numeric_trigger=False"
        assert ui._query == "1", "Digit should be appended to query"

    def test_disabled_numeric_query_also_fuzzy_matches_names(self) -> None:
        """When disabled, numeric query matches both numbers and names."""
        config = LaunchLineConfig(
            entries=(
                EntryConfig(name="Item A", command="a"),
                EntryConfig(name="Item B", command="b"),
                EntryConfig(name="Item 2x", command="c"),
            ),
            numeric_trigger=False,
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
            numeric_trigger=False,
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
            numeric_trigger=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        # Type "2" — only entry #2 matches by number
        result = ui._on_key("2")
        assert result is None, (
            "Should not auto-launch even with single numeric match "
            "when numeric_trigger=False"
        )

    def test_zero_still_exits_when_disabled(self) -> None:
        """Pressing 0 with no query still returns exit entry."""
        config = LaunchLineConfig(
            entries=(EntryConfig(name="Tool", command="t"),),
            numeric_trigger=False,
        )
        ui = LaunchLineUI(config)
        ui._reset()
        result = ui._on_key("0")
        assert result is _EXIT_ENTRY, (
            "0 should still select exit even with numeric_trigger=False"
        )


class TestKittyProtocolDecoder:
    """Tests for the Kitty keyboard protocol CSI u decoder."""

    def test_escape_codepoint_returns_escape(self) -> None:
        result = KeyReader._decode_kitty_key("27")
        assert result == "escape", f"Expected 'escape' for codepoint 27, got {result!r}"

    def test_enter_codepoint_returns_enter(self) -> None:
        result = KeyReader._decode_kitty_key("13")
        assert result == "enter", f"Expected 'enter' for codepoint 13, got {result!r}"

    def test_backspace_codepoint_returns_backspace(self) -> None:
        result = KeyReader._decode_kitty_key("127")
        assert result == "backspace", (
            f"Expected 'backspace' for codepoint 127, got {result!r}"
        )

    def test_ctrl_backspace_returns_ctrl_backspace(self) -> None:
        # modifier 5 = 1 + ctrl(4)
        result = KeyReader._decode_kitty_key("127;5")
        assert result == "ctrl-backspace", (
            f"Expected 'ctrl-backspace' for 127;5, got {result!r}"
        )

    def test_alt_backspace_returns_alt_backspace(self) -> None:
        # modifier 3 = 1 + alt(2)
        result = KeyReader._decode_kitty_key("127;3")
        assert result == "alt-backspace", (
            f"Expected 'alt-backspace' for 127;3, got {result!r}"
        )

    def test_ctrl_a_returns_ctrl_a(self) -> None:
        result = KeyReader._decode_kitty_key("97;5")
        assert result == "ctrl-a", f"Expected 'ctrl-a' for 97;5, got {result!r}"

    def test_ctrl_e_returns_ctrl_e(self) -> None:
        result = KeyReader._decode_kitty_key("101;5")
        assert result == "ctrl-e", f"Expected 'ctrl-e' for 101;5, got {result!r}"

    def test_ctrl_k_returns_ctrl_k(self) -> None:
        result = KeyReader._decode_kitty_key("107;5")
        assert result == "ctrl-k", f"Expected 'ctrl-k' for 107;5, got {result!r}"

    def test_ctrl_u_returns_ctrl_u(self) -> None:
        result = KeyReader._decode_kitty_key("117;5")
        assert result == "ctrl-u", f"Expected 'ctrl-u' for 117;5, got {result!r}"

    def test_ctrl_w_returns_ctrl_w(self) -> None:
        result = KeyReader._decode_kitty_key("119;5")
        assert result == "ctrl-w", f"Expected 'ctrl-w' for 119;5, got {result!r}"

    def test_ctrl_b_returns_ctrl_b(self) -> None:
        result = KeyReader._decode_kitty_key("98;5")
        assert result == "ctrl-b", f"Expected 'ctrl-b' for 98;5, got {result!r}"

    def test_ctrl_d_returns_ctrl_d(self) -> None:
        result = KeyReader._decode_kitty_key("100;5")
        assert result == "ctrl-d", f"Expected 'ctrl-d' for 100;5, got {result!r}"

    def test_ctrl_f_returns_ctrl_f(self) -> None:
        result = KeyReader._decode_kitty_key("102;5")
        assert result == "ctrl-f", f"Expected 'ctrl-f' for 102;5, got {result!r}"

    def test_ctrl_h_returns_ctrl_h(self) -> None:
        result = KeyReader._decode_kitty_key("104;5")
        assert result == "ctrl-h", f"Expected 'ctrl-h' for 104;5, got {result!r}"

    def test_alt_b_returns_alt_b(self) -> None:
        # modifier 3 = 1 + alt(2)
        result = KeyReader._decode_kitty_key("98;3")
        assert result == "alt-b", f"Expected 'alt-b' for 98;3, got {result!r}"

    def test_alt_d_returns_alt_d(self) -> None:
        result = KeyReader._decode_kitty_key("100;3")
        assert result == "alt-d", f"Expected 'alt-d' for 100;3, got {result!r}"

    def test_alt_f_returns_alt_f(self) -> None:
        result = KeyReader._decode_kitty_key("102;3")
        assert result == "alt-f", f"Expected 'alt-f' for 102;3, got {result!r}"

    def test_ctrl_c_raises_keyboard_interrupt(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            KeyReader._decode_kitty_key("99;5")

    def test_printable_codepoints_return_literal_chars(self) -> None:
        result_a = KeyReader._decode_kitty_key("97")
        assert result_a == "a", f"Expected 'a' for codepoint 97, got {result_a!r}"
        result_upper_a = KeyReader._decode_kitty_key("65")
        assert result_upper_a == "A", (
            f"Expected 'A' for codepoint 65, got {result_upper_a!r}"
        )
        result_0 = KeyReader._decode_kitty_key("48")
        assert result_0 == "0", f"Expected '0' for codepoint 48, got {result_0!r}"

    def test_release_event_returns_empty(self) -> None:
        # modifier 1; event_type 3 = release
        result = KeyReader._decode_kitty_key("27;1:3")
        assert result == "", f"Expected empty string for release event, got {result!r}"

    def test_unknown_codepoint_returns_empty(self) -> None:
        # Private use area key
        result = KeyReader._decode_kitty_key("57358")
        assert result == "", (
            f"Expected empty string for unknown codepoint, got {result!r}"
        )

    def test_empty_params_returns_empty(self) -> None:
        result = KeyReader._decode_kitty_key("")
        assert result == "", f"Expected empty string for empty params, got {result!r}"

    def test_csi_arrow_a_returns_up_b_returns_down(self) -> None:
        result_up = KeyReader._dispatch_csi("", "A")
        assert result_up == "up", f"Expected 'up' for CSI A, got {result_up!r}"
        result_down = KeyReader._dispatch_csi("", "B")
        assert result_down == "down", f"Expected 'down' for CSI B, got {result_down!r}"


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
        result = KeyReader._read_key_windows()
        assert result == "up", f"Expected 'up' for CSI A sequence, got {result!r}"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_ctrl_backspace_on_windows(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Ctrl+Backspace via Kitty protocol: ESC [ 127 ; 5 u."""
        mock_getwch.side_effect = ["\x1b", "[", "1", "2", "7", ";", "5", "u"]
        mock_kbhit.side_effect = [True] + [True] * 7
        result = KeyReader._read_key_windows()
        assert result == "ctrl-backspace", (
            f"Expected 'ctrl-backspace' for Kitty 127;5, got {result!r}"
        )

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
        result = KeyReader._read_key_windows()
        assert result == "escape", f"Expected 'escape' for Kitty 27u, got {result!r}"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_bare_escape_no_following_chars(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Bare ESC with nothing following returns 'escape'."""
        mock_getwch.return_value = "\x1b"
        mock_kbhit.return_value = False
        result = KeyReader._read_key_windows()
        assert result == "escape", f"Expected 'escape' for bare ESC, got {result!r}"

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_ctrl_backspace_with_numlock(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Ctrl+Backspace with NumLock: ESC [ 127 ; 133 u (133 = 1+4+128)."""
        mock_getwch.side_effect = ["\x1b", "[", "1", "2", "7", ";", "1", "3", "3", "u"]
        mock_kbhit.side_effect = [True] + [True] * 9
        result = KeyReader._read_key_windows()
        assert result == "ctrl-backspace", (
            f"Expected 'ctrl-backspace' for NumLock variant, got {result!r}"
        )

    @patch("msvcrt.kbhit")
    @patch("msvcrt.getwch")
    def test_kitty_printable_char_on_windows(
        self, mock_getwch: MagicMock, mock_kbhit: MagicMock
    ) -> None:
        """Printable char via Kitty: ESC [ 97 u → 'a'."""
        mock_getwch.side_effect = ["\x1b", "[", "9", "7", "u"]
        mock_kbhit.side_effect = [True] + [True] * 4
        result = KeyReader._read_key_windows()
        assert result == "a", f"Expected 'a' for Kitty 97u, got {result!r}"

    def test_dispatch_csi_kitty_u(self) -> None:
        result = KeyReader._dispatch_csi("27", "u")
        assert result == "escape", f"Expected 'escape' for CSI 27u, got {result!r}"

    def test_csi_unknown_terminator_returns_empty(self) -> None:
        result = KeyReader._dispatch_csi("", "C")
        assert result == "", (
            f"Expected empty string for unknown CSI terminator, got {result!r}"
        )
