from __future__ import annotations

from george.bot import GeorgeBot
from george.config import load_settings

EXPECTED = {
    "hello",
    "name",
    "help",
    "version",
    "prompt",
    "fuckyou",
    "compliment",
    "random",
    "addprompt",
    "addswear",
    "addcompliment",
    "addrandom",
    "content",
    "meme",
    "qr",
    "mp3",
    "ytdlp",
}


async def test_setup_registers_prefix_and_slash_commands(tmp_path):
    settings = load_settings(
        {
            "DISCORD_TOKEN": "x",
            "DATA_DIR": str(tmp_path),
            "SYNC_COMMANDS": "0",
            "LOG_TO_FILE": "0",
            "YTDLP_AUTO_UPDATE": "0",
        }
    )
    bot = GeorgeBot(settings)
    try:
        await bot.setup_hook()
        prefix = {c.name for c in bot.commands}
        slash = {c.name for c in bot.tree.get_commands()}
        if not bot.ffmpeg_available():
            EXPECTED.difference_update({"mp3", "ytdlp"})
        assert prefix >= EXPECTED
        assert slash >= EXPECTED
        # Old command spellings keep working through case-insensitivity and aliases.
        for old in ("Meme", "Mp3", "CreateQR", "addPrompt", "addCompliment"):
            if old.lower() == "mp3" and "mp3" not in prefix:
                continue
            assert bot.get_command(old) is not None, old
        assert await bot.content.count("prompt") > 0
    finally:
        await bot.close()
