"""Image → ASCII art (.txt) and ASCII art → image, in black and white.

Convention: dark "ink" on a light background, like a .txt file opened in an
editor. A space is white, `@` is black. `invert=True` flips that (for art meant
to be viewed as light text on a dark background, e.g. in Discord's dark theme).

Characters are about twice as tall as they are wide. So an image is sampled
with half as many rows as columns per pixel, and each character becomes a cell
twice as tall as wide when turning ASCII back into an image.

Animated images (GIF, WebP) become several frames in one .txt, each starting
with a header line like `=== frame 2/12, 80 ms ===`. Turning such a file back
into an image gives an animated GIF.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import math
import re
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from george.errors import UserFacingError

# From light to dark.
RAMP = " .:-=+*#%@"
CHAR_ASPECT = 0.5  # character width / height

MIN_WIDTH, MAX_WIDTH, DEFAULT_WIDTH = 20, 300, 100
MAX_ROWS = 500
MAX_INPUT_PIXELS = 40_000_000
MAX_ANIMATED_PIXELS = 4_000_000  # per frame
MAX_IMAGE_BYTES = 15 * 1024 * 1024

MAX_FRAMES = 50
MAX_ANIMATION_CHARS = 400_000  # all frames together
DEFAULT_FRAME_MS = 100
MIN_FRAME_MS = 20  # browsers and Discord treat shorter GIF delays as 100 ms

MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_TEXT_COLS = 500
MAX_TEXT_ROWS = 500
MAX_OUTPUT_WIDTH = 3000
MAX_ANIMATION_WIDTH = 800

STYLES = ("smooth", "blocks", "text")

FRAME_HEADER = "=== frame {index}/{total}, {duration} ms ==="
FRAME_RE = re.compile(r"^=== frame (\d+)/(\d+), (\d+) ms ===\s*$")

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


@dataclass(frozen=True, slots=True)
class AsciiFrame:
    lines: list[str]
    duration_ms: int = 0

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


@dataclass(frozen=True, slots=True)
class Rendered:
    data: bytes
    extension: str  # ".png" or ".gif"
    frames: int


# -- image → ASCII ---------------------------------------------------------------------


def _open_image(data: bytes) -> Image.Image:
    if len(data) > MAX_IMAGE_BYTES:
        raise UserFacingError(f"That image is too big (max {MAX_IMAGE_BYTES // (1024 * 1024)} MB).")
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_INPUT_PIXELS:
            raise UserFacingError("That image is way too big for me. Try a smaller one.")
        img.load()
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


def _frames(img: Image.Image) -> list[tuple[Image.Image, int]]:
    """Grayscale frames with their duration in ms. Long animations are thinned out
    evenly to MAX_FRAMES; the durations of dropped frames are added to the kept ones."""
    total = getattr(img, "n_frames", 1)
    if total <= 1:
        with contextlib.suppress(OSError, ValueError, SyntaxError):  # broken EXIF: keep as is
            img = ImageOps.exif_transpose(img) or img
        return [(_to_grayscale(img), 0)]

    if img.width * img.height > MAX_ANIMATED_PIXELS:
        raise UserFacingError("That animation is too big for me. Try a smaller one.")
    durations = []
    for i in range(total):
        img.seek(i)
        durations.append(int(img.info.get("duration") or DEFAULT_FRAME_MS))

    keep = min(total, MAX_FRAMES)
    starts = [round(k * total / keep) for k in range(keep)] + [total]
    frames = []
    for start, end in itertools.pairwise(starts):
        img.seek(start)
        frames.append(
            (_to_grayscale(img.convert("RGBA")), max(MIN_FRAME_MS, sum(durations[start:end])))
        )
    return frames


def grid_size(img_width: int, img_height: int, width: int) -> tuple[int, int]:
    """Columns and rows of the ASCII art for an image of the given size."""
    width = max(MIN_WIDTH, min(MAX_WIDTH, width))
    rows = max(1, round(width * img_height / img_width * CHAR_ASPECT))
    if rows > MAX_ROWS:
        width = max(1, round(width * MAX_ROWS / rows))
        rows = MAX_ROWS
    return width, rows


def _contrast_lut(images: list[Image.Image], cutoff: float = 0.01) -> list[int]:
    """One brightness stretch for all frames (per-frame stretching would flicker)."""
    hist = [0] * 256
    for im in images:
        for i, count in enumerate(im.histogram()):
            hist[i] += count
    total = sum(hist)
    lo_limit, hi_limit = total * cutoff, total * (1 - cutoff)
    running, lo, hi = 0, 0, 255
    for i, count in enumerate(hist):
        if running <= lo_limit < running + count:
            lo = i
        if running < hi_limit <= running + count:
            hi = i
        running += count
    if hi <= lo:
        return list(range(256))
    return [max(0, min(255, round((i - lo) * 255 / (hi - lo)))) for i in range(256)]


def _to_lines(small: Image.Image, invert: bool) -> list[str]:
    cols = small.width
    levels = len(RAMP) - 1
    pixels = small.tobytes()
    lines = []
    for row in range(small.height):
        chars = []
        for value in pixels[row * cols : (row + 1) * cols]:
            darkness = value if invert else 255 - value
            chars.append(RAMP[round(darkness * levels / 255)])
        lines.append("".join(chars).rstrip())
    return lines


def image_to_ascii_frames(
    data: bytes, *, width: int = DEFAULT_WIDTH, invert: bool = False
) -> list[AsciiFrame]:
    """Convert image bytes to ASCII art: one frame, or several for an animation."""
    frames = _frames(_open_image(data))
    first = frames[0][0]
    cols, rows = grid_size(first.width, first.height, width)
    if len(frames) > 1 and len(frames) * cols * rows > MAX_ANIMATION_CHARS:
        scale = math.sqrt(MAX_ANIMATION_CHARS / (len(frames) * cols * rows))
        cols, rows = grid_size(first.width, first.height, max(1, math.floor(cols * scale)))
        cols = min(cols, max(1, MAX_ANIMATION_CHARS // (len(frames) * rows)))

    def resize(gray: Image.Image) -> Image.Image:
        method = Image.Resampling.BOX if gray.width >= cols else Image.Resampling.BICUBIC
        return gray.resize((cols, rows), method)

    smalls = [resize(gray) for gray, _ in frames]
    lut = _contrast_lut(smalls)
    return [
        AsciiFrame(_to_lines(small.point(lut), invert), duration)
        for small, (_, duration) in zip(smalls, frames, strict=True)
    ]


def format_frames(frames: list[AsciiFrame]) -> str:
    """The .txt content: plain art for one frame, header lines between frames otherwise."""
    if len(frames) == 1:
        return frames[0].text
    parts = []
    for i, frame in enumerate(frames, start=1):
        header = FRAME_HEADER.format(index=i, total=len(frames), duration=frame.duration_ms)
        parts.append(header + "\n" + frame.text)
    return "".join(parts)


def image_to_ascii(data: bytes, *, width: int = DEFAULT_WIDTH, invert: bool = False) -> str:
    """Convert image bytes to the text of an ASCII art .txt (with `\\n` line endings)."""
    return format_frames(image_to_ascii_frames(data, width=width, invert=invert))


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


def _raw_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")


def split_lines(text: str) -> list[str]:
    """Lines of a single piece of ASCII art, without surrounding blank lines or a
    Markdown code fence (e.g. when copied from Discord)."""
    lines = _raw_lines(text)

    def trim() -> None:
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

    trim()
    if lines and re.fullmatch(r"\s*```\w*\s*", lines[0]):
        lines.pop(0)
        if lines and re.fullmatch(r"\s*```\s*", lines[-1]):
            lines.pop()
        trim()
    return lines


def parse_frames(text: str) -> list[AsciiFrame]:
    """Split a .txt into frames. Without frame headers, the whole text is one frame."""
    lines = _raw_lines(text)
    if not any(FRAME_RE.match(line) for line in lines):
        return [AsciiFrame(split_lines(text))]

    if lines and lines[-1] == "":
        lines.pop()  # the file's final newline
    # Blank rows inside a frame are kept: they position the art within the frame.
    frames: list[AsciiFrame] = []
    current: list[str] | None = None
    duration = DEFAULT_FRAME_MS
    for line in lines:
        match = FRAME_RE.match(line)
        if match:
            if current is not None:
                frames.append(AsciiFrame(current, duration))
            current, duration = [], max(MIN_FRAME_MS, int(match.group(3)))
        elif current is not None:
            current.append(line)
    if current is not None:
        frames.append(AsciiFrame(current, duration))
    if len(frames) > MAX_FRAMES:
        raise UserFacingError(f"That's too many frames ({len(frames)}). The limit is {MAX_FRAMES}.")
    return frames


@lru_cache(maxsize=8)
def _monospace_font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """A monospace font if the system has one, else Pillow's default. (font, is_monospace)"""
    for name in MONOSPACE_FONTS:
        try:
            return ImageFont.truetype(name, size), True
        except OSError:
            continue
    return ImageFont.load_default(size=size), False


def _coverage(ch: str) -> float:
    """Fraction of a character cell covered by ink, measured by rendering it."""
    font, _ = _monospace_font(32)
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


def _validate_grid(frames: list[AsciiFrame]) -> tuple[int, int]:
    cols = max((len(line) for f in frames for line in f.lines), default=0)
    rows = max((len(f.lines) for f in frames), default=0)
    if cols == 0 or rows == 0:
        raise UserFacingError("That file is empty, there's nothing to draw.")
    if cols > MAX_TEXT_COLS or rows > MAX_TEXT_ROWS:
        raise UserFacingError(
            f"That's too big ({cols}×{rows} characters). The limit is "
            f"{MAX_TEXT_COLS}×{MAX_TEXT_ROWS}."
        )
    if len(frames) > 1 and len(frames) * cols * rows > 2 * MAX_ANIMATION_CHARS:
        raise UserFacingError(
            "That animation is too big for me. Use fewer frames or a smaller width."
        )
    return cols, rows


def _render_gray(
    lines: list[str], cols: int, rows: int, style: str, invert: bool, max_width: int
) -> Image.Image:
    values = bytearray()
    for i in range(rows):
        line = lines[i] if i < len(lines) else ""
        for ch in line.ljust(cols):
            darkness = char_density(ch)
            values.append(round(255 * darkness) if invert else round(255 * (1 - darkness)))
    grid = Image.frombytes("L", (cols, rows), bytes(values))
    cell_w = max(2, min(8, max_width // cols))
    cell_h = round(cell_w / CHAR_ASPECT)
    resample = Image.Resampling.NEAREST if style == "blocks" else Image.Resampling.BICUBIC
    return grid.resize((cols * cell_w, rows * cell_h), resample)


class _TextRenderer:
    """Draws characters into a fixed grid. Every distinct character is rendered once
    and then pasted, which keeps animations fast."""

    def __init__(self, cols: int, max_width: int, invert: bool) -> None:
        self.font_size = max(6, min(16, math.floor(max_width / cols / 0.6)))
        self.font, _ = _monospace_font(self.font_size)
        self.cell_w = max(1, math.ceil(self.font_size * 0.6))
        self.cell_h = round(self.cell_w / CHAR_ASPECT)
        self.ink, self.paper = (255, 0) if invert else (0, 255)
        self.margin = self.cell_w
        self._glyphs: dict[str, Image.Image] = {}

    def _glyph(self, ch: str) -> Image.Image:
        glyph = self._glyphs.get(ch)
        if glyph is None:
            glyph = Image.new("L", (self.cell_w, self.cell_h), 0)
            ImageDraw.Draw(glyph).text(
                (self.cell_w / 2, self.cell_h / 2), ch, fill=255, font=self.font, anchor="mm"
            )
            self._glyphs[ch] = glyph
        return glyph

    def render(self, lines: list[str], cols: int, rows: int) -> Image.Image:
        size = (cols * self.cell_w + 2 * self.margin, rows * self.cell_h + 2 * self.margin)
        img = Image.new("L", size, self.paper)
        for row, line in enumerate(lines[:rows]):
            y = self.margin + row * self.cell_h
            for col, ch in enumerate(line[:cols]):
                if ch == " ":
                    continue
                x = self.margin + col * self.cell_w
                img.paste(self.ink, (x, y, x + self.cell_w, y + self.cell_h), self._glyph(ch))
        return img


def render_ascii(text: str, *, style: str = "smooth", invert: bool = False) -> Rendered:
    """Turn ASCII art back into a black-and-white picture: a PNG, or an animated GIF
    if the text has frame headers.

    smooth: each character becomes a gray level, smoothly scaled up (closest to a picture)
    blocks: the same, but as sharp pixel blocks
    text:   the characters themselves, drawn in a monospace font
    """
    if style not in STYLES:
        raise UserFacingError(f"Unknown style {style!r}. Use one of: {', '.join(STYLES)}.")
    frames = parse_frames(text)
    cols, rows = _validate_grid(frames)
    animated = len(frames) > 1
    max_width = MAX_ANIMATION_WIDTH if animated else MAX_OUTPUT_WIDTH

    if style == "text":
        renderer = _TextRenderer(cols, max_width, invert)
        images = [renderer.render(f.lines, cols, rows) for f in frames]
    else:
        images = [_render_gray(f.lines, cols, rows, style, invert, max_width) for f in frames]

    buf = io.BytesIO()
    if not animated:
        images[0].save(buf, format="PNG", optimize=True)
        return Rendered(buf.getvalue(), ".png", 1)
    images[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=[f.duration_ms or DEFAULT_FRAME_MS for f in frames],
        loop=0,
    )
    return Rendered(buf.getvalue(), ".gif", len(frames))


def ascii_to_image(text: str, *, style: str = "smooth", invert: bool = False) -> bytes:
    """PNG (or GIF for animations) bytes of `render_ascii`."""
    return render_ascii(text, style=style, invert=invert).data


def output_name(filename: str, suffix: str) -> str:
    """`cat.png` → `cat-ascii.txt` style names, safe for Discord uploads."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("_")[:60] or "george"
    return stem + suffix
