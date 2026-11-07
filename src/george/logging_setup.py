"""Logging: always to stdout, optionally also to a rotating file in DATA_DIR/logs."""

from __future__ import annotations

import logging
import logging.handlers

import discord

from george.config import Settings


def setup_logging(settings: Settings) -> None:
    level = logging.getLevelNamesMapping().get(settings.log_level, logging.INFO)

    # Colourful stdout handler from discord.py, attached to the root logger.
    discord.utils.setup_logging(level=level, root=True)

    if settings.log_to_file:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            settings.log_dir / "george.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)

    # discord.http is very chatty at DEBUG.
    logging.getLogger("discord.http").setLevel(max(level, logging.INFO))
