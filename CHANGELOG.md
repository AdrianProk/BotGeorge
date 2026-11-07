# Changelog

## 1.0.0 – production-ready refactor

### Changed
- The bot is now the `george` package in `src/george` (start with `uv run george`,
  `python -m george`, `python George.py` or Docker).
- Every command is also a slash command. Old `$` spellings keep working (case-insensitive).
- `$CreateQR` is now `$qr` (the old name still works as an alias).
- Content is stored in SQLite (`data/george.db`) instead of `data/Data.json`; an old
  `Data.json` placed in `data/` is imported automatically on start.
- Configuration moved to environment variables / `.env` (`data/token.json` still works for now).
- Help text is generated from the commands instead of being stored in the data file.

### Added
- `$content list` / `$content remove` for moderation, `$version`.
- Author and origin server are recorded for every new entry; duplicates are rejected.
- Optional owner log channel, daily database backups, Docker health check.
- Docker image for amd64/arm64, compose file, update scripts, systemd unit.
- Tests, ruff, GitHub Actions CI, Dependabot (daily yt-dlp checks).

### Fixed
- Users could make George ping `@everyone` or roles through stored text.
- Concurrent `$qr`, `$meme` and `$mp3` requests could send someone else's file.
- A corrupt `Data.json` could wipe all stored content.
- `$mp3` downloaded entire playlists and had no length/size limit.
- NSFW Reddit posts could be posted in normal channels.
- Meme downloads had no timeout or size limit and could recurse endlessly.
- Paths depended on the folder the bot was started from.
