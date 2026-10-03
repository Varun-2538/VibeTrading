"""
Generate the Android splash images: the logo with the app name beneath it.

Bubblewrap's generated splash is the icon alone. This composes the icon and
the wordmark into the same drawable, at every density, so the app names itself
while the web view loads.

The system paints SPLASH_SCREEN_BACKGROUND_COLOR behind this image and draws it
centred at its natural size, so the canvas keeps the dimensions bubblewrap
already shipped - anything larger risks overflowing a small screen - and the
background stays transparent.

Run from the android/ directory:

    python tools/make_splash.py

Archivo is the app's display face. It is a Google font fetched on demand and
cached outside the repo rather than vendored, since the repo only needs the
rasterised result.
"""
from pathlib import Path
from urllib.request import urlopen
import sys

from PIL import Image, ImageDraw, ImageFont

# Bubblewrap's densities and canvas sizes, in pixels.
DENSITIES = {
    "mdpi": 300,
    "hdpi": 450,
    "xhdpi": 600,
    "xxhdpi": 900,
    "xxxhdpi": 1200,
}

APP_NAME = "VibeTrading Club"

# --vt-ink from the web app's palette, so the splash and the first paint agree.
INK = (230, 244, 239, 255)

ARCHIVO_URL = (
    "https://github.com/google/fonts/raw/main/ofl/archivo/Archivo%5Bwdth,wght%5D.ttf"
)
FONT_CACHE = Path.home() / ".cache" / "vibetrading" / "Archivo.ttf"

# Proportions of the canvas width.
# The mark reads as an afterthought if the name is much wider than it, so the
# name is held well inside the canvas rather than filling it.
LOGO_FRACTION = 0.54
TEXT_WIDTH_FRACTION = 0.74
GAP_FRACTION = 0.08

ANDROID_RES = Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "res"
LOGO = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "icons" / "icon-512.png"
)


def font_path() -> Path:
    if FONT_CACHE.exists() and FONT_CACHE.stat().st_size > 50_000:
        return FONT_CACHE
    FONT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"fetching Archivo -> {FONT_CACHE}")
    with urlopen(ARCHIVO_URL) as response:
        FONT_CACHE.write_bytes(response.read())
    return FONT_CACHE


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    # Archivo is variable and its axes are ordered Weight then Width. Passing
    # them the other way round silently renders Thin at maximum width, which
    # looks like a different typeface rather than an error.
    axes = [axis["name"] for axis in font.get_variation_axes()]
    assert axes == [b"Weight", b"Width"], f"unexpected axis order: {axes}"
    font.set_variation_by_axes([800.0, 100.0])  # ExtraBold, normal width
    return font


def fit_font(path: Path, text: str, target_width: int) -> ImageFont.FreeTypeFont:
    """The largest size whose rendered width stays inside target_width."""
    size = 8
    best = load_font(path, size)
    while size < 400:
        candidate = load_font(path, size + 2)
        if candidate.getbbox(text)[2] > target_width:
            break
        size += 2
        best = candidate
    return best


def compose(canvas: int, logo: Image.Image, path: Path) -> Image.Image:
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    logo_size = int(canvas * LOGO_FRACTION)
    mark = logo.resize((logo_size, logo_size), Image.LANCZOS)

    font = fit_font(path, APP_NAME, int(canvas * TEXT_WIDTH_FRACTION))
    left, top, right, bottom = font.getbbox(APP_NAME)
    text_w, text_h = right - left, bottom - top

    gap = int(canvas * GAP_FRACTION)
    block_h = logo_size + gap + text_h
    y = (canvas - block_h) // 2

    image.paste(mark, ((canvas - logo_size) // 2, y), mark)
    draw.text(
        ((canvas - text_w) // 2 - left, y + logo_size + gap - top),
        APP_NAME,
        font=font,
        fill=INK,
    )
    return image


def main() -> int:
    if not LOGO.exists():
        print(f"logo not found: {LOGO}", file=sys.stderr)
        return 1

    path = font_path()
    logo = Image.open(LOGO).convert("RGBA")

    for density, canvas in DENSITIES.items():
        out = ANDROID_RES / f"drawable-{density}" / "splash.png"
        if not out.parent.exists():
            print(f"skipping {density}: {out.parent} missing", file=sys.stderr)
            continue
        compose(canvas, logo, path).save(out)
        print(f"{density:8} {canvas}x{canvas} -> {out.relative_to(ANDROID_RES.parents[3])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
