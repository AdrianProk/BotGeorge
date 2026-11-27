from __future__ import annotations

import io

import pytest
from PIL import Image

from george.errors import UserFacingError
from george.services import ascii_art
from george.services.ascii_art import (
    RAMP,
    ascii_to_image,
    char_density,
    decode_text,
    grid_size,
    image_to_ascii,
    output_name,
    split_lines,
)


def png(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def gradient(width=200, height=100) -> Image.Image:
    """White on the left, black on the right."""
    img = Image.new("L", (width, height))
    img.putdata([255 - int(255 * x / (width - 1)) for _ in range(height) for x in range(width)])
    return img


def test_gradient_goes_from_light_to_dark():
    text = image_to_ascii(png(gradient()), width=40)
    lines = text.splitlines()
    assert len(lines) == 10  # 40 * 100/200 * 0.5
    line = lines[0].ljust(40)
    assert line[0] == " " and line[-1] == "@"
    densities = [RAMP.index(c) for c in line]
    assert densities == sorted(densities)


def test_invert_flips_the_ramp():
    line = image_to_ascii(png(gradient()), width=40, invert=True).splitlines()[0]
    assert line[0] == "@"
    assert len(line) < 40  # the dark (now light) end is spaces, stripped at line end


def test_width_and_aspect():
    assert grid_size(200, 100, 100) == (100, 25)
    assert grid_size(200, 100, 5) == (ascii_art.MIN_WIDTH, 5)
    assert grid_size(200, 100, 10_000)[0] == ascii_art.MAX_WIDTH
    cols, rows = grid_size(10, 10_000, 300)  # very tall image: rows are capped
    assert rows == ascii_art.MAX_ROWS and cols >= 1


def test_transparent_areas_become_white():
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))  # fully transparent black
    img.paste((0, 0, 0, 255), (0, 0, 50, 100))  # left half solid black
    line = image_to_ascii(png(img), width=20).splitlines()[0]
    assert set(line[:10]) == {"@"}
    assert line[10:].strip() == ""


@pytest.mark.parametrize("fmt", ["JPEG", "GIF", "WEBP", "BMP"])
def test_other_formats(fmt):
    img = gradient().convert("RGB")
    assert "@" in image_to_ascii(png(img, fmt), width=30)


def test_not_an_image():
    with pytest.raises(UserFacingError, match="image"):
        image_to_ascii(b"hello, not an image", width=50)


def test_huge_image_is_rejected():
    big = png(Image.new("1", (8000, 6000)))
    with pytest.raises(UserFacingError, match="too big"):
        image_to_ascii(big)


# -- ASCII → image --------------------------------------------------------------------


def test_decode_text_variants():
    assert decode_text("héllo".encode()) == "héllo"
    assert decode_text(b"\xef\xbb\xbfhi") == "hi"  # UTF-8 BOM (Notepad)
    assert decode_text("héllo".encode("cp1252")) == "héllo"
    with pytest.raises(UserFacingError):
        decode_text(b"\x89PNG\x00\x00")
    with pytest.raises(UserFacingError):
        decode_text(b"x" * (ascii_art.MAX_TEXT_BYTES + 1))


def test_split_lines_handles_crlf_tabs_and_code_fences():
    text = "\r\n```\r\n a\tb\r\n@@\r\n```\r\n\r\n"
    assert split_lines(text) == [" a  b", "@@"]
    assert split_lines("```txt\n\n  x\n```") == ["  x"]
    assert split_lines("  x\n\n  y\n") == ["  x", "", "  y"]  # inner blank lines stay


def test_char_density():
    assert char_density(" ") == 0.0
    assert char_density("@") == 1.0
    assert char_density("█") == 1.0
    assert 0 < char_density(".") < char_density("o") < char_density("M") <= 1.0
    assert 0 <= char_density("€") <= 1.0
    assert char_density("\x07") == 0.0


@pytest.mark.parametrize("style", ["smooth", "blocks"])
def test_round_trip_keeps_light_and_dark(style):
    text = image_to_ascii(png(gradient()), width=40)
    img = Image.open(io.BytesIO(ascii_to_image(text, style=style)))
    assert img.mode == "L"
    w, h = img.size
    assert abs(w / h - 2.0) < 0.1  # original aspect ratio 2:1 is preserved
    left = img.getpixel((2, h // 2))
    right = img.getpixel((w - 3, h // 2))
    assert left > 200 and right < 50


def test_blocks_are_sharp_and_invert_works():
    img = Image.open(io.BytesIO(ascii_to_image(" @\n @", style="blocks")))
    assert set(img.tobytes()) == {0, 255}
    inv = Image.open(io.BytesIO(ascii_to_image(" @\n @", style="blocks", invert=True)))
    assert inv.getpixel((0, 0)) == 0 and img.getpixel((0, 0)) == 255


def test_text_style_draws_characters():
    img = Image.open(io.BytesIO(ascii_to_image("/\\_/\\\n( o.o )", style="text")))
    assert img.width > img.height
    assert min(img.tobytes()) < 100  # some ink
    assert max(img.tobytes()) == 255  # white paper


@pytest.mark.parametrize(
    "text",
    ["", "   \n  \n", "x" * (ascii_art.MAX_TEXT_COLS + 1), "x\n" * (ascii_art.MAX_TEXT_ROWS + 1)],
)
def test_bad_ascii_input(text):
    with pytest.raises(UserFacingError):
        ascii_to_image(text)


def test_unknown_style():
    with pytest.raises(UserFacingError):
        ascii_to_image("@", style="color")


def test_output_name():
    assert output_name("My Cat.photo.PNG", "-ascii.txt") == "My_Cat_photo-ascii.txt"
    assert output_name("???.txt", ".png") == "george.png"


# -- animations --------------------------------------------------------------------------


def animated_gif(frames: int = 6, duration: int = 80) -> bytes:
    # Consecutive frames always differ (Pillow merges identical ones when saving).
    images = []
    for i in range(frames):
        im = Image.new("L", (120, 60), 255)
        x = (i * 7) % 100
        im.paste(0, (x, 10, x + 20, 50))  # a black block moving right
        images.append(im)
    buf = io.BytesIO()
    images[0].save(buf, "GIF", save_all=True, append_images=images[1:], duration=duration, loop=0)
    return buf.getvalue()


def test_animated_gif_becomes_frames_and_back():
    frames = ascii_art.image_to_ascii_frames(animated_gif(), width=40)
    assert len(frames) == 6
    assert {f.duration_ms for f in frames} == {80}
    # The block moves right: its first column grows frame by frame.
    starts = [min(line.index("@") for line in f.lines if "@" in line) for f in frames]
    assert starts == sorted(starts) and starts[0] < starts[-1]

    text = ascii_art.format_frames(frames)
    assert text.startswith("=== frame 1/6, 80 ms ===\n")
    parsed = ascii_art.parse_frames(text)
    assert [f.lines for f in parsed] == [f.lines for f in frames]

    for style in ascii_art.STYLES:
        rendered = ascii_art.render_ascii(text, style=style)
        gif = Image.open(io.BytesIO(rendered.data))
        assert rendered.extension == ".gif" and rendered.frames == 6
        assert gif.n_frames == 6
        assert gif.info["duration"] == 80


def test_long_animations_are_thinned_out_keeping_total_time():
    frames = ascii_art.image_to_ascii_frames(animated_gif(frames=120, duration=30), width=20)
    assert len(frames) == ascii_art.MAX_FRAMES
    assert sum(f.duration_ms for f in frames) == 120 * 30


def test_animation_size_is_capped():
    frames = ascii_art.image_to_ascii_frames(animated_gif(frames=50), width=300)
    total = sum(len(f.lines) * max((len(line) for line in f.lines), default=0) for f in frames)
    assert total <= ascii_art.MAX_ANIMATION_CHARS


def test_frames_keep_leading_blank_rows():
    text = "=== frame 1/2, 50 ms ===\n\n\n  @\n=== frame 2/2, 50 ms ===\n  @\n"
    first, second = ascii_art.parse_frames(text)
    assert first.lines == ["", "", "  @"]
    assert second.lines == ["  @"]
    # Blank rows at the end of a frame are kept too (the art may sit at the top).
    third = ascii_art.parse_frames("=== frame 1/1, 50 ms ===\n@\n\n\n")[0]
    assert third.lines == ["@", "", ""]


def test_static_image_is_a_single_png():
    rendered = ascii_art.render_ascii("@@\n..")
    assert rendered.extension == ".png" and rendered.frames == 1
