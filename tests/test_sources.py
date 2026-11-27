from __future__ import annotations

from types import SimpleNamespace

from george.cogs.sources import (
    ascii_text_in_message,
    find_youtube_url,
    qr_text_in_message,
    youtube_url_in_message,
)

VID = "dQw4w9WgXcQ"


def message(content="", attachments=(), embeds=(), clean=None):
    return SimpleNamespace(
        content=content,
        clean_content=content if clean is None else clean,
        attachments=list(attachments),
        embeds=list(embeds),
        jump_url="https://discord.com/channels/1/2/3",
    )


def test_find_youtube_url_in_text():
    assert find_youtube_url(f"listen to this!! <https://youtu.be/{VID}> so good") == (
        f"https://www.youtube.com/watch?v={VID}"
    )
    assert find_youtube_url("https://example.com and nothing else") is None
    assert find_youtube_url("") is None


def test_youtube_url_from_embed():
    msg = message("check", embeds=[SimpleNamespace(url=f"https://www.youtube.com/watch?v={VID}")])
    assert youtube_url_in_message(msg) == f"https://www.youtube.com/watch?v={VID}"


def test_ascii_text_in_message():
    assert (
        ascii_text_in_message(message("look:\n```\n /\\_/\\\n( o.o )\n```"))
        == " /\\_/\\\n( o.o )\n"
    )
    assert ascii_text_in_message(message("@@\n..")) == "@@\n.."
    assert ascii_text_in_message(message("just one line")) is None


def test_qr_text_in_message():
    assert qr_text_in_message(message("hi <@123>", clean="hi @Adi")) == "hi @Adi"
    att = SimpleNamespace(url="https://cdn.discordapp.com/a.png")
    assert qr_text_in_message(message("", attachments=[att])) == att.url
    assert qr_text_in_message(message("")) == "https://discord.com/channels/1/2/3"
