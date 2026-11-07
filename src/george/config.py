"""Typed settings, read from environment variables (and an optional `.env` file)."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = (
    "Animemes",
    "anime_irl",
    "hopeposting",
    "meme",
    "me_irl",
    "girlsfrontline",
    "GFLNeuralCloud",
    "FunnyAnimals",
)


DEFAULT_USER_AGENT = "python:botgeorge:v1.0 (private Discord bot)"


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    data_dir: Path
    command_prefix: str = "$"
    log_level: str = "INFO"
    log_to_file: bool = True
    owner_ids: frozenset[int] = field(default_factory=frozenset)
    guild_ids: tuple[int, ...] = ()
    sync_commands: bool = True
    owner_log_channel_id: int | None = None

    subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = DEFAULT_USER_AGENT
    meme_max_bytes: int = 25 * 1024 * 1024

    mp3_max_duration_s: int = 15 * 60
    mp3_max_concurrent: int = 2
    mp3_job_timeout_s: int = 600
    ffmpeg_location: str | None = None

    ytdlp_auto_update: bool = True
    ytdlp_update_interval_h: int = 6
    ytdlp_channel: str = "stable"

    backup_keep: int = 7

    @property
    def db_path(self) -> Path:
        return self.data_dir / "george.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def ytdlp_dir(self) -> Path:
        return self.data_dir / "yt-dlp"

    @property
    def heartbeat_path(self) -> Path:
        return self.data_dir / "heartbeat"


def _int_list(raw: str | None, name: str) -> tuple[int, ...]:
    if not raw:
        return ()
    try:
        return tuple(int(part) for part in raw.replace(" ", "").split(",") if part)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a comma-separated list of numeric IDs") from exc


def _str_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(raw: str | None, default: int, name: str, minimum: int = 1) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _optional_int(raw: str | None, name: str) -> int | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a numeric ID") from exc


def _legacy_token(data_dir: Path) -> str | None:
    """Support the old `data/token.json` file for one release."""
    path = data_dir / "token.json"
    if not path.is_file():
        return None
    try:
        token = json.loads(path.read_text(encoding="utf-8")).get("discordToken")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise ConfigError(f"Could not read legacy token file {path}: {exc}") from exc
    if token:
        log.warning("Using legacy %s. Move the token to DISCORD_TOKEN in .env.", path)
    return token or None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build settings from `env` (defaults to the process environment + `.env`)."""
    if env is None:
        from dotenv import find_dotenv, load_dotenv

        # Prefer a .env in the current folder, fall back to searching upwards from the package.
        load_dotenv(find_dotenv(usecwd=True)) or load_dotenv()
        env = os.environ

    data_dir = Path(env.get("DATA_DIR") or "data").expanduser().resolve()

    token = (env.get("DISCORD_TOKEN") or "").strip() or _legacy_token(data_dir)
    if not token:
        raise ConfigError(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and put your bot token in it."
        )

    subreddits = _str_list(env.get("SUBREDDITS")) or DEFAULT_SUBREDDITS

    channel = (env.get("YTDLP_CHANNEL") or "stable").strip().lower()
    if channel not in {"stable", "nightly"}:
        raise ConfigError("YTDLP_CHANNEL must be 'stable' or 'nightly'")

    return Settings(
        discord_token=token,
        data_dir=data_dir,
        command_prefix=env.get("COMMAND_PREFIX") or "$",
        log_level=(env.get("LOG_LEVEL") or "INFO").upper(),
        log_to_file=_bool(env.get("LOG_TO_FILE"), True),
        owner_ids=frozenset(_int_list(env.get("OWNER_IDS"), "OWNER_IDS")),
        guild_ids=_int_list(env.get("GUILD_IDS"), "GUILD_IDS"),
        sync_commands=_bool(env.get("SYNC_COMMANDS"), True),
        owner_log_channel_id=_optional_int(env.get("OWNER_LOG_CHANNEL_ID"), "OWNER_LOG_CHANNEL_ID"),
        subreddits=subreddits,
        reddit_client_id=env.get("REDDIT_CLIENT_ID") or None,
        reddit_client_secret=env.get("REDDIT_CLIENT_SECRET") or None,
        reddit_user_agent=env.get("REDDIT_USER_AGENT") or DEFAULT_USER_AGENT,
        meme_max_bytes=_int(env.get("MEME_MAX_BYTES"), 25 * 1024 * 1024, "MEME_MAX_BYTES"),
        mp3_max_duration_s=_int(env.get("MP3_MAX_DURATION_S"), 15 * 60, "MP3_MAX_DURATION_S"),
        mp3_max_concurrent=_int(env.get("MP3_MAX_CONCURRENT"), 2, "MP3_MAX_CONCURRENT"),
        mp3_job_timeout_s=_int(env.get("MP3_JOB_TIMEOUT_S"), 600, "MP3_JOB_TIMEOUT_S", minimum=30),
        ffmpeg_location=env.get("FFMPEG_LOCATION") or None,
        ytdlp_auto_update=_bool(env.get("YTDLP_AUTO_UPDATE"), True),
        ytdlp_update_interval_h=_int(
            env.get("YTDLP_UPDATE_INTERVAL_H"), 6, "YTDLP_UPDATE_INTERVAL_H"
        ),
        ytdlp_channel=channel,
        backup_keep=_int(env.get("BACKUP_KEEP"), 7, "BACKUP_KEEP"),
    )
