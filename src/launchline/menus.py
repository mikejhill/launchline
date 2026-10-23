"""Session-owned menu snapshots, nested navigation, refresh and retry semantics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Protocol

from launchline.config import EntryConfig, LaunchLineConfig, MenuConfig, ProviderConfig
from launchline.providers import MenuProvider, ProviderError

logger = logging.getLogger(__name__)


class Provider(Protocol):
    """Typed process boundary used by the deterministic lifecycle controller."""

    def resolve(
        self, provider: ProviderConfig, *, depth: int
    ) -> tuple[EntryConfig, ...]:
        """Resolve one explicitly configured provider."""
        ...


@dataclass(frozen=True, slots=True)
class ViewState:
    """Search and selection state restored against a possibly refreshed snapshot."""

    query: str = ""
    cursor: int = 0
    selected: EntryConfig | None = None
    viewport: int = 0


@dataclass(slots=True)
class MenuFrame:
    """A cached menu instance and its retained child instances."""

    declaration: MenuConfig
    origin: EntryConfig | None = None
    entries: tuple[EntryConfig, ...] = ()
    loaded: bool = False
    error: str | None = None
    view: ViewState = field(default_factory=ViewState)
    children: list[MenuFrame] = field(default_factory=list)


class MenuSession:
    """Own a bounded navigation stack and last-good provider snapshots per session."""

    def __init__(
        self, config: LaunchLineConfig, provider: Provider | None = None
    ) -> None:
        """Store declarations without running providers until load is requested."""
        self._provider = provider or MenuProvider()
        self._stack = [
            MenuFrame(
                MenuConfig(
                    config.entries,
                    config.title,
                    config.provider,
                    config.refresh_on_return,
                )
            )
        ]

    @property
    def current(self) -> MenuFrame:
        """Return the current frame with its last-good snapshot and view state."""
        return self._stack[-1]

    @property
    def depth(self) -> int:
        """Return the number of active menus, counting root."""
        return len(self._stack)

    @property
    def title(self) -> str:
        """Return a breadcrumb built only from validated display text."""
        return " / ".join(frame.declaration.title for frame in self._stack)

    @staticmethod
    def same_entry(previous: EntryConfig, current: EntryConfig) -> bool:
        """Use explicit stable ids, otherwise exact declaration equality."""
        return (
            previous.id == current.id
            if previous.id and current.id
            else previous == current
        )

    def ensure_loaded(self) -> None:
        """Resolve a menu once, including caching failure until an explicit retry."""
        if not self.current.loaded:
            self.refresh()

    def refresh(self) -> bool:
        """Replace the snapshot atomically on success; retain it on provider failure."""
        frame = self.current
        frame.loaded = True
        try:
            entries = (
                frame.declaration.entries
                if frame.declaration.provider is None
                else self._provider.resolve(
                    frame.declaration.provider, depth=self.depth - 1
                )
            )
        except ProviderError as error:
            frame.error = str(error)
            logger.error("Menu provider failed: %s", error)
            return False
        frame.entries = entries
        frame.error = None
        frame.children = [
            child
            for child in frame.children
            if child.origin is not None
            and any(
                self.same_entry(child.origin, entry) and child.declaration == entry.menu
                for entry in entries
            )
        ]
        return True

    def open(self, entry: EntryConfig) -> None:
        """Open a current submenu and reuse its unchanged cached instance."""
        if entry.menu is None or entry not in self.current.entries:
            raise ValueError("Only a current submenu can be opened.")
        if self.depth >= 16:
            raise ProviderError("Menus may be nested at most 16 levels including root.")
        child = next(
            (
                item
                for item in self.current.children
                if item.origin is not None
                and self.same_entry(item.origin, entry)
                and item.declaration == entry.menu
            ),
            None,
        )
        if child is None:
            child = MenuFrame(entry.menu, entry)
            self.current.children.append(child)
        self._stack.append(child)
        self.ensure_loaded()

    def back(self) -> bool:
        """Return to parent; refresh only when that parent's policy requests it."""
        if self.depth == 1:
            return False
        self._stack.pop()
        if (
            self.current.declaration.refresh_on_return
            and self.current.declaration.provider is not None
        ):
            self.refresh()
        return True


class MenuApplication:
    """Compose the existing terminal UI and runner with nested menu lifecycle."""

    def __init__(self, config: LaunchLineConfig) -> None:
        """Own this interactive session without resolving providers in construction."""
        self._config = config
        self._session = MenuSession(config)

    def run(self) -> None:
        """Navigate, refresh and launch only explicitly selected leaf commands."""
        from launchline.exceptions import LaunchError
        from launchline.runner import EntryRunner
        from launchline.ui import LaunchLineUI, MenuIntent

        while True:
            try:
                self._session.ensure_loaded()
            except KeyboardInterrupt as error:
                raise SystemExit(130) from error
            frame = self._session.current
            back = EntryConfig("Back", "", description="Return to parent menu")
            refresh = EntryConfig(
                "Retry provider" if frame.error is not None else "Refresh menu",
                "",
                description="Regenerate this menu (Ctrl+R)",
            )
            controls = ((refresh,) if frame.declaration.provider else ()) + (
                (back,) if self._session.depth > 1 else ()
            )
            status = (
                " [provider failed; cached snapshot retained]"
                if frame.error is not None
                else " [empty]"
                if not frame.entries
                else ""
            )
            visible = replace(
                self._config,
                entries=frame.entries + controls,
                title=self._session.title + status,
            )
            ui = LaunchLineUI(visible)
            choice, frame.view = ui.choose(frame.view)
            if choice.intent is MenuIntent.REFRESH or choice.entry is refresh:
                try:
                    self._session.refresh()
                except KeyboardInterrupt as error:
                    raise SystemExit(130) from error
                continue
            if choice.intent is MenuIntent.BACK or choice.entry is back:
                try:
                    if not self._session.back():
                        return
                except KeyboardInterrupt as error:
                    raise SystemExit(130) from error
                continue
            if choice.entry is None:
                return
            entry = choice.entry
            if entry.menu is not None:
                try:
                    self._session.open(entry)
                except ProviderError as error:
                    logger.error("Cannot open menu: %s", error)
                except KeyboardInterrupt as error:
                    raise SystemExit(130) from error
                continue
            try:
                code = EntryRunner(self._config).launch(entry)
            except LaunchError as error:
                logger.error("Cannot launch entry: %s", error)
                code = 1
            except KeyboardInterrupt:
                code = 130
            if self._config.on_exit == "exit":
                raise SystemExit(code)
