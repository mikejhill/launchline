"""Generate ICO and PNG icon files from the LaunchLine SVG source.

Renders the SVG geometry at high resolution using Pillow, then
downscales with LANCZOS resampling for clean anti-aliased output.
Round stroke linecaps are simulated by drawing filled circles at
line endpoints.

Usage::

    uv run --group screenshots python tools/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PKG_ASSETS = ROOT / "src" / "launchline" / "assets"

# ---------------------------------------------------------------------------
# SVG geometry (from assets/launchline.svg at 64x64 viewBox)
# ---------------------------------------------------------------------------

BG_FILL = (17, 24, 39)  # #111827
BG_STROKE = (55, 65, 81)  # #374151
GRAY = (100, 116, 139)  # #64748B
WHITE = (248, 250, 252)  # #F8FAFC
GREEN = (34, 197, 94)  # #22C55E


def _render(size: int) -> Image.Image:
    """Render the icon at *size* x *size* pixels with supersampling."""
    supersample = 8
    hi = size * supersample
    s = hi / 64.0

    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background rounded rectangle with border
    draw.rounded_rectangle(
        [int(2 * s), int(2 * s), int(62 * s), int(62 * s)],
        radius=int(10 * s),
        fill=BG_FILL,
        outline=BG_STROKE,
        width=max(1, int(1 * s)),
    )

    def _round_line(
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[int, int, int],
        width: float,
    ) -> None:
        """Draw a line with round linecaps (circles at each endpoint)."""
        w = max(1, int(width * s))
        r = w / 2.0
        draw.line(
            [int(x1 * s), int(y1 * s), int(x2 * s), int(y2 * s)],
            fill=color,
            width=w,
        )
        # Round caps
        for cx, cy in [(x1, y1), (x2, y2)]:
            px, py = cx * s, cy * s
            draw.ellipse(
                [px - r, py - r, px + r, py + r],
                fill=color,
            )

    # Top line
    _round_line(12, 15, 52, 15, GRAY, 3)
    # Middle line (text cursor)
    _round_line(13, 32, 39, 32, WHITE, 4)
    # Bottom line
    _round_line(12, 49, 52, 49, GRAY, 3)

    # Green play indicator — circle + arrow
    cr = int(2.5 * s)
    cx, cy = int(40 * s), int(32 * s)
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=GREEN)

    _round_line(40, 32, 51, 32, GREEN, 4)  # horizontal
    _round_line(43, 24, 51, 32, GREEN, 4)  # top chevron
    _round_line(43, 40, 51, 32, GREEN, 4)  # bottom chevron

    # Downscale with high-quality resampling
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Generate ICO and PNG files in the assets directories."""
    ico_sizes = [16, 32, 48, 64, 128, 256]
    images = [_render(sz) for sz in ico_sizes]

    # Multi-size ICO — project root assets and installed package assets
    for dest in [ASSETS, PKG_ASSETS]:
        dest.mkdir(parents=True, exist_ok=True)
        ico_path = dest / "launchline.ico"
        images[-1].save(
            ico_path,
            format="ICO",
            append_images=images[:-1],
        )
        print(f"  ICO ({len(ico_sizes)} sizes) -> {ico_path}")

    # 256px PNG (project root only — for GitHub social preview)
    png_path = ASSETS / "launchline.png"
    images[-1].save(png_path, format="PNG")
    print(f"  PNG (256x256)       -> {png_path}")


if __name__ == "__main__":
    main()
