"""QR code generation, fully in memory (no shared files on disk)."""

from __future__ import annotations

import io

import segno

from george.errors import UserFacingError

MAX_QR_INPUT = 1500


def make_qr_png(text: str, *, scale: int = 10) -> bytes:
    text = text.strip()
    if not text:
        raise UserFacingError(
            "Please put something behind the command, or I can't put anything in it."
        )
    if len(text) > MAX_QR_INPUT:
        raise UserFacingError(f"That's too much for one QR code (max {MAX_QR_INPUT} characters).")
    try:
        qr = segno.make_qr(text)
    except segno.DataOverflowError as exc:
        raise UserFacingError("That's too much for one QR code. Try something shorter.") from exc
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=4)
    return buf.getvalue()
