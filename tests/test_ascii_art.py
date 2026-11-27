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
