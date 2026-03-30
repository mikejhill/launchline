#!/usr/bin/env python3
"""Generate terminal screenshots of LaunchLine for documentation.

Renders the LaunchLine TUI into PNG images and animated GIFs using
``pyte`` for terminal emulation and ``Pillow`` for image rendering.

Usage::

    uv run --group screenshots python tools/generate_screenshots.py

Output is written to ``docs/images/``.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyte
from PIL import Image, ImageDraw, ImageFont

# Ensure the project source is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.ui import LaunchLineUI

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

TERM_COLS = 72
TERM_ROWS = 20

# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------

_FONT_CANDIDATES: list[Path] = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "CascadiaMono.ttf",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "consola.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSansMono.ttf"),
]

FONT_SIZE = 15
LINE_HEIGHT_FACTOR = 1.35


def _find_font() -> Path:
    """Locate a monospace TrueType font on the system."""
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    msg = "No monospace TrueType font found. Install Cascadia Mono or DejaVu Sans Mono."
    raise FileNotFoundError(msg)


# ---------------------------------------------------------------------------
# Color scheme — CGA (Windows Terminal built-in)
# ---------------------------------------------------------------------------

BG_COLOR = (0, 0, 0)
FG_COLOR = (170, 170, 170)

_ANSI_16: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "red": (170, 0, 0),
    "green": (0, 170, 0),
    "brown": (170, 85, 0),  # pyte calls yellow "brown"
    "blue": (0, 0, 170),
    "magenta": (170, 0, 170),
    "cyan": (0, 170, 170),
    "white": (170, 170, 170),
    "brightblack": (85, 85, 85),
    "brightred": (255, 85, 85),
    "brightgreen": (85, 255, 85),
    "brightyellow": (255, 255, 85),
    "brightbrown": (255, 255, 85),
    "brightblue": (85, 85, 255),
    "brightmagenta": (255, 85, 255),
    "brightcyan": (85, 255, 255),
    "brightwhite": (255, 255, 255),
}

_ANSI_16_BY_INDEX: list[tuple[int, int, int]] = [
    _ANSI_16["black"],
    _ANSI_16["red"],
    _ANSI_16["green"],
    _ANSI_16["brown"],
    _ANSI_16["blue"],
    _ANSI_16["magenta"],
    _ANSI_16["cyan"],
    _ANSI_16["white"],
    _ANSI_16["brightblack"],
    _ANSI_16["brightred"],
    _ANSI_16["brightgreen"],
    _ANSI_16["brightyellow"],
    _ANSI_16["brightblue"],
    _ANSI_16["brightmagenta"],
    _ANSI_16["brightcyan"],
    _ANSI_16["brightwhite"],
]

_CUBE_INTENSITIES = (0, 95, 135, 175, 215, 255)


def _color_256_to_rgb(n: int) -> tuple[int, int, int]:
    """Convert a 256-colour index to an RGB triple."""
    if n < 16:
        return _ANSI_16_BY_INDEX[n]
    if n < 232:
        n -= 16
        return (
            _CUBE_INTENSITIES[n // 36],
            _CUBE_INTENSITIES[(n % 36) // 6],
            _CUBE_INTENSITIES[n % 6],
        )
    v = 8 + (n - 232) * 10
    return (v, v, v)


def _resolve_color(
    raw: str,
    default: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Resolve a pyte colour attribute to an RGB triple.

    Pyte may represent colours as ``"default"``, a named colour
    (``"brightgreen"``), a 256-colour index string (``"69"``), or a
    6-character hex string (``"5f87ff"``).
    """
    if raw == "default":
        return default
    key = raw.replace(" ", "").lower()
    if key in _ANSI_16:
        return _ANSI_16[key]
    with contextlib.suppress(ValueError):
        return _color_256_to_rgb(int(raw))
    # pyte sometimes stores 256-color values as 6-char hex RGB strings
    if len(raw) == 6:
        with contextlib.suppress(ValueError):
            return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    return default


# ---------------------------------------------------------------------------
# Terminal window chrome
# ---------------------------------------------------------------------------

CHROME_PAD_X = 20
CHROME_PAD_Y_TOP = 12
CHROME_PAD_Y_BOTTOM = 16
TITLEBAR_H = 40
CORNER_R = 10
TITLEBAR_BG = (20, 20, 20)
DOT_COLORS = ((255, 95, 86), (255, 189, 46), (39, 201, 63))

# ---------------------------------------------------------------------------
# Demo configuration (generic — no personal data)
# ---------------------------------------------------------------------------

DEMO_ENTRIES = (
    EntryConfig(
        name="GitHub Copilot CLI",
        command="ghcs",
        description="AI-powered CLI assistant",
    ),
    EntryConfig(
        name="PowerShell",
        command="pwsh",
        description="PowerShell 7",
    ),
    EntryConfig(
        name="Python",
        command="python",
        description="Python 3.13 REPL",
    ),
    EntryConfig(
        name="Node.js",
        command="node",
        description="Node.js REPL",
    ),
    EntryConfig(
        name="Docker Desktop",
        command="docker",
        description="Manage containers",
    ),
    EntryConfig(
        name="Git Bash",
        command="bash",
        description="Git for Windows shell",
    ),
)

DEMO_CONFIG = LaunchLineConfig(
    entries=DEMO_ENTRIES,
    title="LaunchLine",
    show_exit=True,
)

DEMO_CWD = "/home/user/projects/my-app"
DEMO_HOME = "/home/user"

# ---------------------------------------------------------------------------
# Screen data model
# ---------------------------------------------------------------------------


@dataclass
class ScreenCell:
    """One character cell with resolved colours."""

    char: str = " "
    fg: tuple[int, int, int] = field(default_factory=lambda: FG_COLOR)
    bg: tuple[int, int, int] = field(default_factory=lambda: BG_COLOR)
    bold: bool = False


# ---------------------------------------------------------------------------
# Capture engine — runs the UI inside pyte
# ---------------------------------------------------------------------------


class TerminalCapture:
    """Feeds LaunchLineUI ANSI output through pyte to extract cell data."""

    def __init__(self, cols: int = TERM_COLS, rows: int = TERM_ROWS) -> None:
        self.cols = cols
        self.rows = rows
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.Stream(self.screen)

    def capture_frame(self, ui: LaunchLineUI) -> list[list[ScreenCell]]:
        """Render the UI once and return the resulting cell grid."""
        self.screen.reset()

        buf = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = buf
        try:
            ui._render()
        finally:
            sys.stdout = original_stdout

        self.stream.feed(buf.getvalue())
        return self._extract_cells()

    def _extract_cells(self) -> list[list[ScreenCell]]:
        grid: list[list[ScreenCell]] = []
        for row_idx in range(self.rows):
            row: list[ScreenCell] = []
            line = self.screen.buffer[row_idx]
            for col_idx in range(self.cols):
                ch: Any = line[col_idx]
                fg = _resolve_color(ch.fg, FG_COLOR)
                bg = _resolve_color(ch.bg, BG_COLOR)
                if ch.reverse:
                    fg, bg = bg, fg
                row.append(ScreenCell(char=ch.data, fg=fg, bg=bg, bold=ch.bold))
            grid.append(row)
        return grid


# ---------------------------------------------------------------------------
# Image renderer
# ---------------------------------------------------------------------------


class TerminalRenderer:
    """Converts cell grids into PNG images with terminal window chrome."""

    def __init__(self, font_path: Path | None = None) -> None:
        path = font_path or _find_font()
        self.font = ImageFont.truetype(str(path), FONT_SIZE)
        bbox = self.font.getbbox("M")
        self.cw = bbox[2] - bbox[0]  # cell width
        self.ch = int(FONT_SIZE * LINE_HEIGHT_FACTOR)  # cell height
        self.ty_off = max(0, (self.ch - (bbox[3] - bbox[1])) // 2)

    # -- public API ---------------------------------------------------------

    def render_png(
        self,
        grid: list[list[ScreenCell]],
        path: Path,
    ) -> None:
        """Render a single frame to a PNG file."""
        img = self._paint(grid)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(path), "PNG")
        print(f"  Saved {path}  ({img.width}x{img.height})")

    def render_gif(
        self,
        grids: list[list[list[ScreenCell]]],
        path: Path,
        *,
        durations: list[int] | None = None,
    ) -> None:
        """Stitch multiple frames into an animated GIF.

        Args:
            grids: Cell grids for each frame.
            path: Output file path.
            durations: Per-frame durations in milliseconds. If ``None``,
                every frame defaults to 500 ms.
        """
        if not grids:
            return
        frames = [self._paint(g) for g in grids]
        if durations is None:
            durations = [500] * len(frames)

        path.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            str(path),
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
        )
        print(f"  Saved {path}  ({len(frames)} frames)")

    # -- internal -----------------------------------------------------------

    def _paint(self, grid: list[list[ScreenCell]]) -> Image.Image:
        """Render a cell grid to an RGB image with terminal window chrome."""
        rows = len(grid)
        cols = len(grid[0]) if grid else 0

        content_w = cols * self.cw
        content_h = rows * self.ch

        img_w = content_w + 2 * CHROME_PAD_X
        img_h = content_h + TITLEBAR_H + CHROME_PAD_Y_TOP + CHROME_PAD_Y_BOTTOM

        img = Image.new("RGB", (img_w, img_h), BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Rounded window background
        draw.rounded_rectangle(
            [0, 0, img_w - 1, img_h - 1],
            radius=CORNER_R,
            fill=BG_COLOR,
        )

        # Title bar
        draw.rounded_rectangle(
            [0, 0, img_w - 1, TITLEBAR_H],
            radius=CORNER_R,
            fill=TITLEBAR_BG,
        )
        # Square off the bottom edge of the title bar
        draw.rectangle(
            [0, TITLEBAR_H - CORNER_R, img_w - 1, TITLEBAR_H],
            fill=TITLEBAR_BG,
        )

        # Traffic-light dots
        dot_r = 6
        dot_spacing = 20
        dot_y = TITLEBAR_H // 2
        for i, colour in enumerate(DOT_COLORS):
            cx = CHROME_PAD_X + 2 + i * dot_spacing
            draw.ellipse(
                [cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r],
                fill=colour,
            )

        # Terminal content
        origin_x = CHROME_PAD_X
        origin_y = TITLEBAR_H + CHROME_PAD_Y_TOP
        for r_idx, row in enumerate(grid):
            y = origin_y + r_idx * self.ch
            for c_idx, cell in enumerate(row):
                x = origin_x + c_idx * self.cw
                if cell.bg != BG_COLOR:
                    draw.rectangle(
                        [x, y, x + self.cw, y + self.ch],
                        fill=cell.bg,
                    )
                if cell.char and cell.char != " ":
                    ty = y + self.ty_off
                    draw.text(
                        (x, ty),
                        cell.char,
                        fill=cell.fg,
                        font=self.font,
                    )
                    if cell.bold:
                        draw.text(
                            (x + 1, ty),
                            cell.char,
                            fill=cell.fg,
                            font=self.font,
                        )
        return img


# ---------------------------------------------------------------------------
# Environment patches — deterministic rendering
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patched_env():  # type: ignore[no-untyped-def]
    """Patch terminal size, CWD, and home for reproducible screenshots."""
    fake_size = os.terminal_size((TERM_COLS, TERM_ROWS))
    with (
        patch(
            "launchline.ui._get_terminal_size",
            return_value=fake_size,
        ),
        patch("os.getcwd", return_value=DEMO_CWD),
        patch(
            "os.path.expanduser",
            side_effect=lambda p: DEMO_HOME if p == "~" else p,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """A static screenshot: key presses to apply, then capture."""

    name: str
    keys: list[str]
    filename: str


SCENARIOS: list[Scenario] = [
    Scenario(
        name="Main launcher view",
        keys=[],
        filename="hero.png",
    ),
    Scenario(
        name="Fuzzy search for 'py'",
        keys=["p", "y"],
        filename="search.png",
    ),
    Scenario(
        name="Arrow-key navigation",
        keys=["down", "down"],
        filename="navigate.png",
    ),
]

GIF_KEY_SEQUENCE: list[tuple[list[str], int]] = [
    ([], 1200),  # initial view — pause to read
    (["p"], 250),  # type "p"
    (["o"], 250),  # → "po"
    (["w"], 250),  # → "pow"
    (["backspace"], 250),  # → "po"
    (["backspace"], 250),  # → "p"
    (["backspace"], 600),  # → "" (all entries) — brief pause
    (["down"], 400),  # navigate
    (["down"], 400),  # navigate
    (["down"], 1500),  # final position — long pause
]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _make_ui() -> LaunchLineUI:
    return LaunchLineUI(DEMO_CONFIG, _key_reader=lambda: "")


def _generate_screenshots(
    capture: TerminalCapture,
    renderer: TerminalRenderer,
    out: Path,
) -> None:
    for scenario in SCENARIOS:
        print(f"  [{scenario.name}]")
        ui = _make_ui()
        ui._reset()
        for key in scenario.keys:
            ui._on_key(key)
        with _patched_env():
            grid = capture.capture_frame(ui)
        renderer.render_png(grid, out / scenario.filename)


def _generate_gif(
    capture: TerminalCapture,
    renderer: TerminalRenderer,
    out: Path,
) -> None:
    print("  [Animated demo]")
    grids: list[list[list[ScreenCell]]] = []
    durations: list[int] = []
    ui = _make_ui()
    ui._reset()
    for keys, ms in GIF_KEY_SEQUENCE:
        for key in keys:
            ui._on_key(key)
        with _patched_env():
            grids.append(capture.capture_frame(ui))
        durations.append(ms)
    renderer.render_gif(grids, out / "demo.gif", durations=durations)


def main() -> None:
    """Entry point — generate all screenshots and GIFs."""
    out = Path(__file__).resolve().parent.parent / "docs" / "images"
    font = _find_font()
    print(f"Font:   {font}")
    print(f"Output: {out}\n")

    capture = TerminalCapture()
    renderer = TerminalRenderer(font)

    print("Static screenshots:")
    _generate_screenshots(capture, renderer, out)
    print("\nAnimated GIF:")
    _generate_gif(capture, renderer, out)
    print("\nDone!")


if __name__ == "__main__":
    main()
