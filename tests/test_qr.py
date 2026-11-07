from __future__ import annotations

import pytest

from george.errors import UserFacingError
from george.services.qr import MAX_QR_INPUT, make_qr_png


def test_makes_png():
    png = make_qr_png("https://example.com")
    assert png.startswith(b"\x89PNG")


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_QR_INPUT + 1)])
def test_rejects_bad_input(text):
    with pytest.raises(UserFacingError):
        make_qr_png(text)


def test_each_call_is_independent():
    assert make_qr_png("a") != make_qr_png("b")
