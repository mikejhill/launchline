"""Deterministic menu scaling and snapshot invalidation contracts."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.menus import ViewState
from launchline.ui import LaunchLineUI


class TraversalGuard(tuple):
    """Reject full-menu traversal after the initial view has been prepared."""

    def __iter__(self) -> object:
        """Fail when rendering or navigation rescans immutable menu entries."""
        raise AssertionError("Hot frames must not traverse the full menu")


class TestMenuScaling:
    """Protect algorithmic work bounds independently of host clock speed."""

    @pytest.mark.parametrize("count", [10, 1000, 10000])
    def test_warm_navigation_and_render_do_not_scan_menu(
        self, count: int, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Warm frames reuse the snapshot and visit only viewport entries."""
        entries = tuple(
            EntryConfig(f"Tool {index}", "unused") for index in range(count)
        )
        ui = LaunchLineUI(LaunchLineConfig(entries=entries))
        ui.restore_state(ViewState())
        snapshot = ui._display_list()
        ui._all_entries = TraversalGuard(ui._all_entries)
        ui._visible = TraversalGuard(ui._visible)

        with patch(
            "launchline.ui._get_terminal_size", return_value=os.terminal_size((100, 30))
        ):
            for _ in range(12):
                ui._on_key("down")
                ui._render()
                assert ui._display_list() is snapshot

        assert ui._on_key("enter") == entries[12 % (count + 1)]
        assert "Tool" in capsys.readouterr().out

    @pytest.mark.parametrize("show_exit", [True, False])
    def test_search_edit_reset_and_no_matches_rebuild_snapshot(
        self, show_exit: bool
    ) -> None:
        """Cached views never retain stale rows after query edits or reset."""
        entries = (EntryConfig("Alpha", "unused"), EntryConfig("Beta", "unused"))
        ui = LaunchLineUI(LaunchLineConfig(entries=entries, show_exit=show_exit))
        ui.restore_state(ViewState())
        assert ui._on_key("enter") == entries[0]
        for query, expected in (
            ("b", entries[1]),
            ("zz", None),
            ("", entries[0]),
            ("ex", None),
        ):
            ui.restore_state(ViewState(query=query, cursor=len(query)))
            selected = ui._on_key("enter")
            if query == "ex" and show_exit:
                assert selected is not None
                assert selected.name == "Exit"
            else:
                assert selected == expected
        ui._reset()
        assert ui._on_key("enter") == entries[0]

    def test_restored_selection_and_width_include_offscreen_entries(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Restoring a distant selection preserves viewport and full-menu alignment."""
        entries = tuple(EntryConfig(f"Tool {index}", "unused") for index in range(30))
        entries += (EntryConfig("An offscreen long tool name", "unused"),)
        ui = LaunchLineUI(LaunchLineConfig(entries=entries))
        ui.restore_state(ViewState(selected=entries[20], viewport=15))
        ui._render()
        assert ui._on_key("enter") is entries[20]
        assert "Tool 20".ljust(len(entries[-1].name)) in capsys.readouterr().out
