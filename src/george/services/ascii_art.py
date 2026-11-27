"""Image → ASCII art (.txt) and ASCII art → image, in black and white.

Convention: dark "ink" on a light background, like a .txt file opened in an
editor. A space is white, `@` is black. `invert=True` flips that (for art meant
to be viewed as light text on a dark background, e.g. in Discord's dark theme).

Characters are about twice as tall as they are wide. So an image is sampled
with half as many rows as columns per pixel, and each character becomes a cell
twice as tall as wide when turning ASCII back into an image.
"""

from __future__ import annotations

import io
import itertools
import math
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from george.errors import UserFacingError

# From light to dark.
RAMP = " .:-=+*#%@"
CHAR_ASPECT = 0.5  # character width / height

MIN_WIDTH, MAX_WIDTH, DEFAULT_WIDTH = 20, 300, 100
MAX_ROWS = 500
MAX_INPUT_PIXELS = 40_000_000
MAX_IMAGE_BYTES = 15 * 1024 * 1024

MAX_TEXT_BYTES = 1024 * 1024
MAX_TEXT_COLS = 500
MAX_TEXT_ROWS = 500
MAX_OUTPUT_WIDTH = 3000

STYLES = ("smooth", "blocks", "text")

# Common "block" characters used in Unicode art.
BLOCK_DENSITY = {
    "█": 1.0,
    "▓": 0.75,
    "▒": 0.5,
    "░": 0.25,
    "▀": 0.5,
    "▄": 0.5,
    "▌": 0.5,
    "▐": 0.5,
    "■": 0.6,
    " ": 0.0,  # no-break space
}

MONOSPACE_FONTS = (
    "DejaVuSansMono.ttf",  # Linux / Docker image (fonts-dejavu-core)
    "LiberationMono-Regular.ttf",
    "consola.ttf",  # Windows
    "cour.ttf",
    "Menlo.ttc",  # macOS
    "Courier New.ttf",
)


# -- image → ASCII ---------------------------------------------------------------------


def _open_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_INPUT_PIXELS:
            raise UserFacingError("That image is way too big for me. Try a smaller one.")
        img.load()  # first frame of animated images
        img = ImageOps.exif_transpose(img) or img
    except Image.DecompressionBombError:
        raise UserFacingError("That image is way too big for me. Try a smaller one.") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise UserFacingError("That doesn't look like an image I can read.") from None
    return img


def _to_grayscale(img: Image.Image) -> Image.Image:
    """Grayscale, with transparent areas treated as white paper."""
    if img.mode in {"RGBA", "LA", "PA"} or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, rgba)
    return img.convert("L")


def grid_size(img_width: int, img_height: int, width: int) -> tuple[int, int]:
    """Columns and rows of the ASCII art for an image of the given size."""
    width = max(MIN_WIDTH, min(MAX_WIDTH, width))
    rows = max(1, round(width * img_height / img_width * CHAR_ASPECT))
    if rows > MAX_ROWS:
        width = max(1, round(width * MAX_ROWS / rows))
        rows = MAX_ROWS
    return width, rows


def image_to_ascii(data: bytes, *, width: int = DEFAULT_WIDTH, invert: bool = False) -> str:
    """Convert image bytes to ASCII art. Returns the text with `\\n` line endings."""
    if len(data) > MAX_IMAGE_BYTES:
        raise UserFacingError(f"That image is too big (max {MAX_IMAGE_BYTES // (1024 * 1024)} MB).")
    gray = _to_grayscale(_open_image(data))
    cols, rows = grid_size(gray.width, gray.height, width)

    small = gray.resize(
        (cols, rows), Image.Resampling.BOX if gray.width >= cols else Image.Resampling.BICUBIC
    )
    small = ImageOps.autocontrast(small, cutoff=1)

    levels = len(RAMP) - 1
    pixels = small.tobytes()
    lines = []
    for row in range(rows):
        chars = []
        for value in pixels[row * cols : (row + 1) * cols]:
            darkness = value if invert else 255 - value
            chars.append(RAMP[round(darkness * levels / 255)])
        lines.append("".join(chars).rstrip())
    return "\n".join(lines) + "\n"


# -- ASCII → image ---------------------------------------------------------------------


def decode_text(data: bytes) -> str:
    """Decode an uploaded .txt (UTF-8 with or without BOM, or Windows-1252)."""
    if len(data) > MAX_TEXT_BYTES:
        raise UserFacingError(f"That file is too big (max {MAX_TEXT_BYTES // 1024} KB).")
    if b"\x00" in data:
        raise UserFacingError("That doesn't look like a text file.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def split_lines(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")

    def trim() -> None:
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

    trim()
    # Remove a Markdown code fence, e.g. when ASCII art was copied from Discord.
    if lines and re.fullmatch(r"\s*```\w*\s*", lines[0]):
        lines.pop(0)
        if lines and re.fullmatch(r"\s*```\s*", lines[-1]):
            lines.pop()
        trim()
    return lines


@lru_cache(maxsize=1)
def _measure_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _monospace_font(32)[0]


def _coverage(ch: str) -> float:
    """Fraction of a character cell covered by ink, measured by rendering it."""
    font = _measure_font()
    size = 32
    img = Image.new("L", (size, size * 2), 0)
    ImageDraw.Draw(img).text((size // 2, size), ch, fill=255, font=font, anchor="mm")
    return sum(img.tobytes()) / (255 * img.width * img.height)


@lru_cache(maxsize=1)
def _ramp_calibration() -> list[tuple[float, float]]:
    """(measured coverage, ramp darkness) pairs, increasing in both."""
    points = []
    best = -1.0
    for i, ch in enumerate(RAMP):
        cov = max(_coverage(ch), best)  # keep it monotonic
        best = cov
        points.append((cov, i / (len(RAMP) - 1)))
    return points


@lru_cache(maxsize=4096)
def char_density(ch: str) -> float:
    """How dark a character looks: 0.0 (white) to 1.0 (black)."""
    if ch in RAMP:
        return RAMP.index(ch) / (len(RAMP) - 1)
    if ch in BLOCK_DENSITY:
        return BLOCK_DENSITY[ch]
    if ch.isspace() or not ch.isprintable():
        return 0.0
    # Any other character: map its measured ink coverage onto the ramp's scale,
    # so ASCII art made with other character sets still comes out right.
    cov = _coverage(ch)
    points = _ramp_calibration()
    if cov <= points[0][0]:
        return 0.0
    for (c0, d0), (c1, d1) in itertools.pairwise(points):
        if cov <= c1:
            return d0 + (d1 - d0) * ((cov - c0) / (c1 - c0) if c1 > c0 else 1.0)
    return 1.0


def _monospace_font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """A monospace font if the system has one, else Pillow's default. (font, is_monospace)"""
    for name in MONOSPACE_FONTS:
        try:
            return ImageFont.truetype(name, size), True
        except OSError:
            continue
    return ImageFont.load_default(size=size), False


def _validate_grid(lines: list[str]) -> tuple[int, int]:
    if not lines:
        raise UserFacingError("That file is empty, there's nothing to draw.")
    cols, rows = max(len(line) for line in lines), len(lines)
    if cols > MAX_TEXT_COLS or rows > MAX_TEXT_ROWS:
        raise UserFacingError(
            f"That's too big ({cols}×{rows} characters). The limit is "
            f"{MAX_TEXT_COLS}×{MAX_TEXT_ROWS}."
        )
    if cols == 0:
        raise UserFacingError("That file is empty, there's nothing to draw.")
    return cols, rows


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def ascii_to_image(text: str, *, style: str = "smooth", invert: bool = False) -> bytes:
    """Turn ASCII art back into a black-and-white PNG.

    smooth: each character becomes a gray level, smoothly scaled up (closest to a picture)
    blocks: the same, but as sharp pixel blocks
    text:   the characters themselves, drawn in a monospace font
    """
    if style not in STYLES:
        raise UserFacingError(f"Unknown style {style!r}. Use one of: {', '.join(STYLES)}.")
    lines = split_lines(text)
    cols, rows = _validate_grid(lines)
    if style == "text":
        return _render_text(lines, cols, rows, invert)

    values = bytearray()
    for line in lines:
        for ch in line.ljust(cols):
            darkness = char_density(ch)
            values.append(round(255 * darkness) if invert else round(255 * (1 - darkness)))
    grid = Image.frombytes("L", (cols, rows), bytes(values))

    cell_w = max(2, min(8, MAX_OUTPUT_WIDTH // cols))
    cell_h = round(cell_w / CHAR_ASPECT)
    resample = Image.Resampling.NEAREST if style == "blocks" else Image.Resampling.BICUBIC
    return _to_png(grid.resize((cols * cell_w, rows * cell_h), resample))


def _render_text(lines: list[str], cols: int, rows: int, invert: bool) -> bytes:
    font_size = max(8, min(16, math.floor(MAX_OUTPUT_WIDTH / cols / 0.6)))
    font, _ = _monospace_font(font_size)
    cell_w = max(1, math.ceil(font_size * 0.6))
    cell_h = round(cell_w / CHAR_ASPECT)
    ink, paper = (255, 0) if invert else (0, 255)
    margin = cell_w
    img = Image.new("L", (cols * cell_w + 2 * margin, rows * cell_h + 2 * margin), paper)
    draw = ImageDraw.Draw(img)
    # Draw every character centred in its own cell, so the grid stays exact even
    # when the font isn't perfectly monospace.
    for row, line in enumerate(lines):
        y = margin + row * cell_h + cell_h / 2
        for col, ch in enumerate(line):
            if ch == " ":
                continue
            x = margin + col * cell_w + cell_w / 2
            draw.text((x, y), ch, fill=ink, font=font, anchor="mm")
    return _to_png(img)


def output_name(filename: str, suffix: str) -> str:
    """`cat.png` → `cat-ascii.txt` style names, safe for Discord uploads."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("_")[:60] or "george"
    return stem + suffix
