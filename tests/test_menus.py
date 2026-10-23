"""Recursive declarations and deterministic menu snapshot lifecycle contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from launchline.config import (
    ConfigLoader,
    EntryConfig,
    LaunchLineConfig,
    MenuConfig,
    ProviderConfig,
)
from launchline.exceptions import ConfigurationError
from launchline.menus import MenuSession, ViewState
from launchline.providers import ProviderError
from launchline.ui import LaunchLineUI, MenuIntent


class RecordedProvider:
    """A process-boundary collaborator with ordered results and observable calls."""

    def __init__(self, *results: tuple[EntryConfig, ...] | ProviderError) -> None:
        """Keep per-test provider results without sharing global state."""
        self.results = list(results)
        self.calls = 0

    def resolve(
        self, provider: ProviderConfig, *, depth: int
    ) -> tuple[EntryConfig, ...]:
        """Return the next process result or a concrete provider failure."""
        assert provider.entry.command == "provider", (
            "Expected configured provider boundary"
        )
        assert depth < 16, "The controller must bound provider nesting"
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, ProviderError):
            raise result
        return result


class TestMenuDeclarations:
    """Parse optional menus without executing arbitrary configured commands."""

    @pytest.mark.parametrize(
        "body",
        [
            '[[entries]]\nname="x"\ncommand="x"\n[entries.menu]',
            '[[entries]]\nname="x"\nargs=[]\n[entries.menu]',
            '[provider]\ncommand="x"\ntimeout_seconds=true',
            '[provider]\ncommand="x"\ntimeout_seconds=0',
            '[provider]\ncommand="x"\ntimeout_seconds=301',
            'entries=[]\n[provider]\ncommand="x"',
            '[[entries]]\nid="same"\nname="x"\ncommand="x"\n[[entries]]\nid="same"\nname="y"\ncommand="y"',
            '[[entries]]\nname="x"\n[entries.menu]\nentries=[{name="broken"}]',
        ],
    )
    def test_invalid_declarations_fail_at_load(self, tmp_path: Path, body: str) -> None:
        """Reject ambiguous or malformed declarations before execution."""
        path = tmp_path / "config.toml"
        path.write_text(body, encoding="utf-8")
        with pytest.raises(ConfigurationError):
            ConfigLoader.load(path)

    def test_static_nested_empty_menu_is_valid(self, tmp_path: Path) -> None:
        """Empty submenus remain navigable while old empty root configs still fail."""
        path = tmp_path / "config.toml"
        path.write_text(
            '[[entries]]\nname="Projects"\n[entries.menu]\ntitle="Empty projects"',
            encoding="utf-8",
        )
        config = ConfigLoader.load(path)
        assert config.entries[0].menu == MenuConfig(title="Empty projects"), (
            "Empty submenu must retain its title and Back navigation"
        )

    def test_config_load_does_not_execute_provider(self, tmp_path: Path) -> None:
        """A nonexistent provider is declaratively valid and runs only when opened."""
        path = tmp_path / "config.toml"
        path.write_text(
            '[settings]\nrefresh_on_return=true\n[provider]\ncommand="nonexistent-config-check-provider"',
            encoding="utf-8",
        )
        config = ConfigLoader.load(path)
        assert config.entries == (), "Dynamic root must not require static entries"
        assert config.provider is not None, (
            "Dynamic root must not require static entries"
        )
        assert config.refresh_on_return, "Root return policy must be loaded explicitly"

    def test_depth_limit_rejects_deep_static_menus(self) -> None:
        """Reject nesting beyond the shared limit before constructing runtime frames."""
        node: dict[str, object] = {"name": "leaf", "command": "unused"}
        for _ in range(16):
            node = {"name": "nested", "menu": {"entries": [node]}}
        with pytest.raises(ConfigurationError, match="16 levels"):
            ConfigLoader.parse_entries([node])


class TestMenuSession:
    """Exercise session ownership, cached navigation, atomic refresh and retry."""

    def test_child_provider_is_lazy_and_cached_across_reentry(self) -> None:
        """Entering a selected child resolves once; parent construction never does."""
        leaf = EntryConfig("tool", "unused")
        child = EntryConfig(
            "Projects",
            "",
            menu=MenuConfig(provider=ProviderConfig(EntryConfig("p", "provider"))),
        )
        boundary = RecordedProvider((leaf,))
        session = MenuSession(LaunchLineConfig((child,)), boundary)
        session.ensure_loaded()
        assert boundary.calls == 0, (
            "Loading a static parent must not run child providers"
        )
        session.open(child)
        assert session.current.entries == (leaf,), (
            "Selected child must show generated results"
        )
        assert session.back(), "Child must return to parent"
        session.open(child)
        assert boundary.calls == 1, "Default cache must survive back and reentry"
        assert session.title == "LaunchLine / LaunchLine", (
            "Breadcrumb must reflect the active stack"
        )

    def test_refresh_parent_on_return_replaces_snapshot_and_invalidates_changed_child(
        self,
    ) -> None:
        """Regenerate parents and invalidate changed child declarations."""
        child = EntryConfig("Projects", "", id="projects", menu=MenuConfig())
        changed = EntryConfig(
            "New projects", "", id="projects", menu=MenuConfig(title="Changed")
        )
        provider = ProviderConfig(EntryConfig("p", "provider"))
        boundary = RecordedProvider((child,), (changed,))
        session = MenuSession(
            LaunchLineConfig((), provider=provider, refresh_on_return=True), boundary
        )
        session.ensure_loaded()
        session.open(child)
        assert session.back(), "Returning from submenu must retain root"
        assert session.current.entries == (changed,), (
            "Parent must regenerate according to its policy"
        )
        assert not session.current.children, (
            "Changed menu declarations must invalidate cached children"
        )
        assert MenuSession.same_entry(child, changed), (
            "Explicit ids must preserve selection across rename"
        )

    def test_failure_retains_snapshot_and_retry_recovers(self) -> None:
        """Retain good entries and require an explicit retry after failure."""
        leaf = EntryConfig("tool", "unused")
        provider = ProviderConfig(EntryConfig("p", "provider"))
        boundary = RecordedProvider((leaf,), ProviderError("failed"), ())
        session = MenuSession(LaunchLineConfig((), provider=provider), boundary)
        session.ensure_loaded()
        assert not session.refresh(), "A failed refresh must report failure"
        assert session.current.entries == (leaf,), (
            "The last valid snapshot must be retained"
        )
        session.ensure_loaded()
        assert boundary.calls == 2, "Failure must wait for explicit user retry"
        assert session.refresh(), "Explicit retry must recover"
        assert session.current.entries == (), "An empty successful snapshot is valid"
        assert session.current.error is None, "An empty successful snapshot is valid"
        assert not session.back(), "Back at root must exit rather than underflow"

    def test_removed_child_is_not_reused_and_leaf_cannot_be_opened(self) -> None:
        """Reject stale navigation targets and commands as menu nodes."""
        child = EntryConfig("Projects", "", menu=MenuConfig())
        boundary = RecordedProvider((child,), ())
        session = MenuSession(
            LaunchLineConfig((), provider=ProviderConfig(EntryConfig("p", "provider"))),
            boundary,
        )
        session.ensure_loaded()
        session.open(child)
        session.back()
        session.refresh()
        assert not session.current.children, (
            "Removed nodes must lose cached descendants"
        )
        with pytest.raises(ValueError, match="current submenu"):
            session.open(child)


class TestMenuView:
    """Restore query and valid identity through public UI state methods."""

    def test_restore_stable_id_after_reorder_and_fallback_after_removal(self) -> None:
        """Restore search and select the refreshed stable identity."""
        old = EntryConfig("tool old", "unused", id="stable")
        fresh = EntryConfig("tool new", "unused", id="stable")
        ui = LaunchLineUI(
            LaunchLineConfig((EntryConfig("tool other", "unused"), fresh))
        )
        ui.restore_state(ViewState("tool", 4, old, 0))
        state = ui.capture_state()
        assert state.query == "tool", "Search cursor must survive refresh"
        assert state.cursor == 4, "Search cursor must survive refresh"
        assert state.selected is fresh, (
            "Stable identity must survive reordering and rename"
        )
        ui = LaunchLineUI(LaunchLineConfig((EntryConfig("tool other", "unused"),)))
        ui.restore_state(state)
        assert ui.capture_state().selected is not fresh, (
            "Removed selections must fall back safely"
        )

    @pytest.mark.parametrize(
        ("keys", "intent"),
        [
            (["escape"], MenuIntent.BACK),
            (["ctrl-r"], MenuIntent.REFRESH),
            (["ctrl-d"], MenuIntent.EXIT),
        ],
    )
    def test_menu_control_intents_are_distinct(
        self, keys: list[str], intent: MenuIntent, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Back, refresh and global quit must not be conflated with launching tools."""
        reader = iter(keys)
        ui = LaunchLineUI(
            LaunchLineConfig((EntryConfig("tool", "unused"),)),
            _key_reader=lambda: next(reader),
        )
        choice, _state = ui.choose(ViewState())
        assert choice.intent is intent, "Expected an explicit control intent"
        assert choice.entry is None, "Expected an explicit control intent"
        output = capsys.readouterr().out
        assert "\x1b[?1049h" in output, "Every menu control must restore the terminal"
        assert "\x1b[?1049l" in output, "Every menu control must restore the terminal"
