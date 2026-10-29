"""Zero is a parent control at every submenu, independent of root settings."""

from unittest.mock import patch

import pytest

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.menus import ViewState
from launchline.ui import LaunchLineUI, MenuIntent


@pytest.mark.parametrize("show_exit", [False, True])
@pytest.mark.parametrize("numeric_trigger", [False, True])
@pytest.mark.parametrize("query", ["", "nomatch", "1"])
def test_submenu_zero_returns_back_even_during_search(
    show_exit: bool, numeric_trigger: bool, query: str
) -> None:
    """Zero must never launch entry 10 or quit from an active submenu search."""
    config = LaunchLineConfig(
        tuple(EntryConfig(f"Tool {i}", "unused") for i in range(12)),
        show_exit=show_exit,
        numeric_trigger=numeric_trigger,
    )
    ui = LaunchLineUI(config, submenu=True, _key_reader=lambda: "0")
    with (
        patch.object(ui, "_enter_alt_screen"),
        patch.object(ui, "_leave_alt_screen") as cleanup,
    ):
        choice, _state = ui.choose(ViewState(query=query, cursor=len(query)))
    assert choice.intent is MenuIntent.BACK
    assert choice.entry is None
    cleanup.assert_called_once()


@pytest.mark.parametrize("keys", [("up", "enter"), ("B", "a", "c", "k", "enter")])
def test_submenu_back_row_can_be_selected_by_keyboard(keys: tuple[str, ...]) -> None:
    """Both keyboard selection and fuzzy selection resolve the zero Back row."""
    events = iter(keys)
    ui = LaunchLineUI(
        LaunchLineConfig((EntryConfig("Tool", "unused"),), show_exit=False),
        submenu=True,
        _key_reader=lambda: next(events),
    )
    ui._reset()
    rows = [(row.number, row.entry.name) for row in ui._display_list()]
    assert rows == [(1, "Tool"), (0, "Back")]
    with patch.object(ui, "_enter_alt_screen"), patch.object(ui, "_leave_alt_screen"):
        choice, _state = ui.choose(ViewState())
    assert choice.intent is MenuIntent.BACK


@pytest.mark.parametrize("submenu", [False, True])
@pytest.mark.parametrize("query", ["", "nomatch"])
def test_ctrl_c_exits_instead_of_navigating_back(submenu: bool, query: str) -> None:
    """Global quit remains distinct from Back and always restores the terminal."""

    def interrupt() -> str:
        """The key reader raises KeyboardInterrupt for the actual Ctrl+C key."""
        raise KeyboardInterrupt

    ui = LaunchLineUI(
        LaunchLineConfig((), show_exit=False),
        submenu=submenu,
        _key_reader=interrupt,
    )
    with (
        patch.object(ui, "_enter_alt_screen"),
        patch.object(ui, "_leave_alt_screen") as cleanup,
    ):
        choice, _state = ui.choose(ViewState(query=query, cursor=len(query)))
    assert choice.intent is MenuIntent.EXIT
    cleanup.assert_called_once()
