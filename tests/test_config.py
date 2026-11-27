from __future__ import annotations

import json

import pytest

from george.config import DEFAULT_SUBREDDITS, ConfigError, load_settings


def test_missing_token_fails_fast(tmp_path):
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_settings({"DATA_DIR": str(tmp_path)})


def test_defaults(tmp_path):
    s = load_settings({"DISCORD_TOKEN": "abc", "DATA_DIR": str(tmp_path)})
    assert s.command_prefix == "$"
    assert s.subreddits == DEFAULT_SUBREDDITS
    assert s.db_path == tmp_path.resolve() / "george.db"
    assert s.guild_ids == ()
    assert s.owner_ids == frozenset()


def test_lists_and_numbers(tmp_path):
    s = load_settings(
        {
            "DISCORD_TOKEN": "abc",
            "DATA_DIR": str(tmp_path),
            "OWNER_IDS": "1, 2",
            "GUILD_IDS": "10,20,",
            "SUBREDDITS": "memes, aww",
            "MP3_MAX_CONCURRENT": "3",
            "SYNC_COMMANDS": "no",
        }
    )
    assert s.owner_ids == {1, 2}
    assert s.guild_ids == (10, 20)
    assert s.subreddits == ("memes", "aww")
    assert s.mp3_max_concurrent == 3
    assert s.sync_commands is False


@pytest.mark.parametrize(
    ("key", "value"), [("GUILD_IDS", "abc"), ("MP3_MAX_CONCURRENT", "0"), ("BACKUP_KEEP", "x")]
)
def test_invalid_values(tmp_path, key, value):
    with pytest.raises(ConfigError, match=key):
        load_settings({"DISCORD_TOKEN": "abc", "DATA_DIR": str(tmp_path), key: value})


def test_legacy_token_file(tmp_path):
    (tmp_path / "token.json").write_text(json.dumps({"discordToken": "legacy"}))
    assert load_settings({"DATA_DIR": str(tmp_path)}).discord_token == "legacy"


def test_env_token_wins_over_legacy_file(tmp_path):
    (tmp_path / "token.json").write_text(json.dumps({"discordToken": "legacy"}))
    s = load_settings({"DATA_DIR": str(tmp_path), "DISCORD_TOKEN": "env"})
    assert s.discord_token == "env"


def test_ffmpeg_path_alias_and_winget_detection(tmp_path, monkeypatch):
    import george.config as config

    s = load_settings({"DISCORD_TOKEN": "x", "DATA_DIR": str(tmp_path), "FFMPEG_PATH": "C:/ff"})
    assert s.ffmpeg_location == "C:/ff"

    monkeypatch.setattr(config.shutil, "which", lambda name: None)  # not on PATH
    winget_bin = tmp_path / "Microsoft/WinGet/Packages/Gyan.FFmpeg_abc/ffmpeg-8.0-full_build/bin"
    winget_bin.mkdir(parents=True)
    (winget_bin / "ffmpeg.exe").write_bytes(b"")
    s = load_settings(
        {"DISCORD_TOKEN": "x", "DATA_DIR": str(tmp_path), "LOCALAPPDATA": str(tmp_path)}
    )
    assert s.ffmpeg_location == str(winget_bin)
