"""Controller integration across real processes and deliberate UI choices."""

from __future__ import annotations

import json
import sys
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from launchline.__main__ import Application
from launchline.config import EntryConfig, LaunchLineConfig, MenuConfig, ProviderConfig
from launchline.menus import MenuApplication, ViewState
from launchline.ui import MenuChoice, MenuIntent


class ScriptedUI:
    """A UI boundary that selects only entries in the controller's actual view."""

    def __init__(self, script: MenuScript, config: LaunchLineConfig) -> None:
        """Retain this exact controller-produced snapshot."""
        self._script = script
        self._config = config

    def choose(self, _state: ViewState) -> tuple[MenuChoice, ViewState]:
        """Supply a deliberate user action without replacing menu lifecycle logic."""
        action = self._script.actions.popleft()
        if isinstance(action, MenuIntent):
            return MenuChoice(action), ViewState()
        selected = next(entry for entry in self._config.entries if entry.name == action)
        return MenuChoice(MenuIntent.ENTRY, selected), ViewState(selected=selected)


class MenuScript:
    """Own a sequence of user choices and observable rendered configurations."""

    def __init__(self, *actions: str | MenuIntent) -> None:
        """Store choices in a per-test queue."""
        self.actions = deque(actions)
        self.views: list[LaunchLineConfig] = []

    def create(self, config: LaunchLineConfig) -> ScriptedUI:
        """Capture production-generated snapshots before supplying a UI boundary."""
        self.views.append(config)
        return ScriptedUI(self, config)


class TestMenuApplication:
    """Exercise the application with actual leaf/provider processes."""

    @pytest.fixture(autouse=True)
    def _usable_stdin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[None]:
        """Give actual selected subprocesses a real inherited file descriptor."""
        path = tmp_path / "stdin"
        path.write_text("", encoding="utf-8")
        with path.open("r", encoding="utf-8") as stream:
            monkeypatch.setattr(sys, "stdin", stream)
            yield

    @staticmethod
    def _child(leaf: EntryConfig | None = None) -> EntryConfig:
        """Build one nested menu with an optional harmless leaf."""
        return EntryConfig(
            "Child", "", menu=MenuConfig((leaf,) if leaf else (), title="Child")
        )

    def test_selected_leaf_propagates_real_status_through_application_dispatch(
        self,
    ) -> None:
        """Route nested selection through the real application entry point."""
        leaf = EntryConfig("Safe", sys.executable, ("-c", "raise SystemExit(7)"))
        script = MenuScript("Child", "Safe")
        config = LaunchLineConfig(
            (self._child(leaf),), on_exit="exit", clear_on_launch=False
        )
        with (
            patch("launchline.ui.LaunchLineUI", side_effect=script.create),
            pytest.raises(SystemExit) as result,
        ):
            Application(config).run()
        assert result.value.code == 7, (
            "Actual selected child status must reach the application"
        )
        assert not script.actions, "Every scripted user selection must be consumed"

    def test_back_and_global_exit_do_not_execute_an_unselected_leaf(
        self, tmp_path: Path
    ) -> None:
        """Navigation must never execute a configured command implicitly."""
        marker = tmp_path / "unexpected"
        leaf = EntryConfig(
            "Unsafe unless selected",
            sys.executable,
            ("-c", "from pathlib import Path; Path(" + repr(str(marker)) + ").touch()"),
        )
        script = MenuScript("Child", "Back", MenuIntent.BACK)
        with patch("launchline.ui.LaunchLineUI", side_effect=script.create):
            MenuApplication(LaunchLineConfig((self._child(leaf),))).run()
        assert not marker.exists(), "Back must not execute unselected leaf commands"
        assert [view.title for view in script.views] == [
            "LaunchLine",
            "LaunchLine / Child",
            "LaunchLine",
        ], "Back must restore the parent's view"

    @pytest.mark.parametrize("policy", ["restart", "exit"])
    def test_launch_failure_follows_global_exit_policy(self, policy: str) -> None:
        """Missing selected executables must report failure or return to their menu."""
        leaf = EntryConfig("Missing", "nonexistent-launchline-menu-leaf-91c7")
        script = MenuScript("Child", "Missing", MenuIntent.EXIT)
        app = MenuApplication(
            LaunchLineConfig(
                (self._child(leaf),), on_exit=policy, clear_on_launch=False
            )
        )
        with patch("launchline.ui.LaunchLineUI", side_effect=script.create):
            if policy == "exit":
                with pytest.raises(SystemExit) as result:
                    app.run()
                assert result.value.code == 1, "Failed launch must return status 1"
            else:
                app.run()
                assert not script.actions, "Restart policy must present the menu again"

    def test_actual_provider_refresh_row_and_cached_back_navigation(
        self, tmp_path: Path
    ) -> None:
        """Visible refresh and Back rows must execute only their intended providers."""
        counter = tmp_path / "calls"
        payload = json.dumps({"entries": [{"name": "Child", "menu": {}}]})
        code = (
            "import sys; from pathlib import Path; p=Path("
            + repr(str(counter))
            + "); p.write_text("
            + "str(int(p.read_text())+1) if p.exists() else '1'); sys.stdout.write("
            + repr(payload)
            + ")"
        )
        provider = ProviderConfig(EntryConfig("p", sys.executable, ("-c", code)))
        script = MenuScript("Child", MenuIntent.BACK, "Refresh menu", MenuIntent.EXIT)
        with patch("launchline.ui.LaunchLineUI", side_effect=script.create):
            MenuApplication(LaunchLineConfig((), provider=provider)).run()
        assert counter.read_text(encoding="utf-8") == "2", (
            "Only initial load and explicit refresh may execute this provider"
        )

    @pytest.mark.parametrize("where", ["initial", "refresh", "open", "back"])
    def test_provider_cancellation_at_each_navigation_boundary_returns_130(
        self, where: str
    ) -> None:
        """Interrupted provider calls must not enter a retry or navigation loop."""
        provider = ProviderConfig(EntryConfig("p", "unused"))
        child = self._child()
        actions: tuple[str | MenuIntent, ...]
        if where == "open":
            child = EntryConfig("Child", "", menu=MenuConfig(provider=provider))
            config = LaunchLineConfig((child,))
            actions = ("Child",)
            results: list[object] = [KeyboardInterrupt()]
        else:
            config = LaunchLineConfig(
                (), provider=provider, refresh_on_return=where == "back"
            )
            actions = (
                (MenuIntent.REFRESH,)
                if where == "refresh"
                else ("Child", "Back")
                if where == "back"
                else ()
            )
            results = (
                [KeyboardInterrupt()]
                if where == "initial"
                else [(child,), KeyboardInterrupt()]
            )
        script = MenuScript(*actions)
        with (
            patch("launchline.ui.LaunchLineUI", side_effect=script.create),
            patch("launchline.providers.MenuProvider.resolve", side_effect=results),
            pytest.raises(SystemExit) as result,
        ):
            MenuApplication(config).run()
        assert result.value.code == 130, "Provider cancellation must use status 130"
