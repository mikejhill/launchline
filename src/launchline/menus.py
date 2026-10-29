"""Session-owned menu snapshots, nested navigation, refresh and retry semantics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from launchline.config import EntryConfig, LaunchLineConfig, MenuConfig, ProviderConfig
from launchline.providers import MenuProvider, ProviderError

logger = logging.getLogger(__name__)
MAX_CACHED_MENUS = 128


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
    last_used: int = 0
    error: str | None = None
    view: ViewState = field(default_factory=ViewState)
    children: list[MenuFrame] = field(default_factory=list)


class MenuSession:
    """Own a bounded navigation stack and last-good provider snapshots per session."""

    def __init__(
        self,
        config: LaunchLineConfig,
        provider: Provider | None = None,
        observer: Callable[[str], None] | None = None,
    ) -> None:
        """Store declarations without running providers until load is requested."""
        self._clock = 0
        self._provider = provider or MenuProvider()
        self._observer = observer
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
        self._touch()
        frame.loaded = True
        try:
            if frame.declaration.provider is not None and self._observer is not None:
                self._observer(frame.declaration.title)
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
        self._touch()
        self._evict()

    def back(self) -> bool:
        """Return to parent; refresh only when that parent's policy requests it."""
        if self.depth == 1:
            return False
        self._stack.pop()
        self._touch()
        if (
            self.current.declaration.refresh_on_return
            and self.current.declaration.provider is not None
        ):
            self.refresh()
        return True

    def _touch(self) -> None:
        """Record deterministic LRU order without a wall-clock dependency."""
        self._clock += 1
        self.current.last_used = self._clock

    def _evict(self) -> None:
        """Bound cached menu instances while retaining every active ancestor."""
        while True:
            frames = [(self._stack[0], None)]
            for frame, _parent in frames:
                frames.extend((child, frame) for child in frame.children)
            if len(frames) <= MAX_CACHED_MENUS:
                return
            candidates = [
                (frame, parent)
                for frame, parent in frames
                if parent is not None
                and all(frame is not active for active in self._stack)
            ]
            if not candidates:
                return
            frame, parent = min(candidates, key=lambda item: item[0].last_used)
            if parent is not None:
                parent.children = [
                    child for child in parent.children if child is not frame
                ]


class MenuApplication:
    """Compose the existing terminal UI and runner with nested menu lifecycle."""

    def __init__(self, config: LaunchLineConfig) -> None:
        """Own this interactive session without resolving providers in construction."""
        self._config = config
        self._session = MenuSession(config, observer=self._loading)

    @staticmethod
    def _loading(title: str) -> None:
        """Show bounded-provider progress outside the alternate screen."""
        import sys

        sys.stderr.write(f"Loading menu: {title}\n")
        sys.stderr.flush()

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
            refresh = EntryConfig(
                "Retry provider" if frame.error is not None else "Refresh menu",
                "",
                description="Regenerate this menu (Ctrl+R)",
            )
            controls = (refresh,) if frame.declaration.provider else ()
            status = (
                " [provider failed]"
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
            ui = LaunchLineUI(visible, submenu=self._session.depth > 1)
            choice, frame.view = ui.choose(frame.view)
            if choice.intent is MenuIntent.REFRESH or choice.entry is refresh:
                try:
                    self._session.refresh()
                except KeyboardInterrupt as error:
                    raise SystemExit(130) from error
                continue
            if choice.intent is MenuIntent.BACK:
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
