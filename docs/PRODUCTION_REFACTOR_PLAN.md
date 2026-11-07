# BotGeorge – Production Readiness Refactor Plan

**Scope:** Make the bot *as it is today* (same features, same commands) safe, stable and deployable.
The two future goals, **better multi-user support** and **automatic YouTube library (yt-dlp) updates**,
are out of scope here. The plan does set up the architecture for them (see §6).

---

## 1. Current state at a glance

| Area | Today |
|---|---|
| Entry point | `George.py` (268 lines): config loading, JSON storage, QR, file helpers, and one large `on_message` handler |
| Commands | `$`-prefix text commands, matched with `startswith` in a chain of independent `if`s |
| Storage | `data/Data.json`, tracked in git. The bot reads and rewrites it on every request |
| External | Reddit (unauthenticated JSON), YouTube via `yt-dlp` + system `ffmpeg`, QR via `segno` |
| Concurrency | Blocking work goes to `asyncio.to_thread`, but every output file has a **fixed shared name** |
| Config | `data/token.json` (gitignored); subreddit list hard-coded |
| Ops | No logging, tests, CI, container, process supervision or pinned dependencies |
| Dead code | `modules/localLLM.py` (unused, broken), `prototyping/`, `chatlog.csv`, committed `__pycache__/*.pyc` |

---

## 2. Findings, ordered by severity

### 🔴 Critical (fix before the bot runs anywhere else)

1. **The Discord bot token is in git history.** Commit `9f4af6b` added a real `token.json` at the repo root.
   Commit `f479b66` deleted the file, but the token can still be read from history by anyone who can clone the repo.
   - **Action:** Reset the token in the Discord Developer Portal (Bot → Reset Token) **now**. After that the leaked value is worthless.
   - Optional: remove the file from history with `git filter-repo --path token.json --invert-paths` and force-push.
     Rotating the token is the fix that matters; rewriting history only cleans up.
2. **Data loss in `write_to_json` (`George.py:87-108`).** If `Data.json` fails to parse for any reason (for example a half-written file after a crash), the `except` branch swaps in an empty skeleton and writes it back. That deletes every stored entry and also the `help` list.
   The write is not atomic (`open(..., 'w')` truncates first), so a crash or power loss mid-write produces exactly that corrupt file.
3. **`@everyone` / mention injection.** Users can store any text with `$addSwear`/`$addCompliment`/…, and the bot repeats it later.
   An entry like `@everyone` or `<@&role_id>` makes the bot ping the whole server. Nothing sets `allowed_mentions`.
4. **NSFW content in SFW channels.** `memeRequest.py` never checks `post["over_18"]`. Subreddits like `me_irl` regularly have NSFW posts, and posting them in a non-NSFW channel breaks Discord's rules and can get the bot reported.
5. **Playlist / huge-download abuse in `$Mp3` (`youtube.py:7-38`).** There is no `noplaylist`, so a `watch?v=…&list=…` link downloads the **whole playlist**. There is also no duration or file-size limit, so one 10-hour video can fill the disk and tie up a worker thread for a long time.

### 🟠 High (wrong results or crashes when used normally, especially with several users)

6. **Race conditions from fixed filenames.** These come straight from "multiple users at once":
   - QR (`George.py:111-116, 235`): every request writes `./qr.png`. If two users run `$CreateQR` at the same time, one of them can get the other's QR code.
   - Meme (`memeRequest.py:22,38`, `George.py:220-222`): always `media/leMeme.<ext>`. `find_file` returns the *first* `leMeme*` file in the folder, so a leftover `.mp4` from an earlier failed run gets sent in place of the new `.jpg`. Concurrent requests overwrite and delete each other's files.
   - MP3 (`youtube.py:45-46`): output goes to the current directory, named after the video title. Two users converting the same video share one file, and whoever finishes first deletes it while the other is still uploading it.
7. **Inconsistent paths.** `Data.json` and the token are found relative to `baseDir`, but `qr.png` and `./media` are relative to the **current working directory**. Start the bot from another folder (systemd, cron, Docker) and memes and QR codes break.
8. **Unhandled errors in storage reads (`George.py:63-85`).**
   - If the file is missing or corrupt, `coollist` is never assigned and the next line raises `UnboundLocalError`.
   - `random.choice([])` on an empty list raises `IndexError`.
   - An unknown list returns `None`, and `channel.send(None)` raises an error.
9. **Unbounded recursion and no timeouts in `memeRequest.py`.**
   - Line 47 calls itself recursively with no depth limit, and throws away the result.
   - `requests.get` (lines 7, 17, 33) has no `timeout`, so a stalled connection blocks a worker thread forever.
   - Media is fully loaded into RAM with no size check.
10. **The Reddit integration is fragile.** It makes unauthenticated `old.reddit.com/.../random.json` calls with a placeholder User-Agent (`/u/your_username`). Reddit rate-limits or blocks unauthenticated clients aggressively, and the `random` endpoint is unreliable. Reddit `fallback_url` videos also have **no audio track**.
11. **Upload-size failures are reported wrongly.** Discord's free upload limit is lower than many MP3s or Reddit videos. `George.py:253` reports *every* exception as "file too big", which hides the real cause.
12. **No rate limiting or concurrency cap.** Anyone can spam `$Mp3` or `$Meme`. Each call takes a thread from the default pool (≈ CPU+4 threads) and may start an `ffmpeg` process.
13. **`get_token` swallows errors (`George.py:14-21`).** It uses a bare `except` and returns `None`, so `client.run(None)` later fails with a confusing message. The bot should fail fast with a clear error.

### 🟡 Medium (maintainability, correctness at the edges)

14. **One large `on_message` with `startswith` matching.**
    - `$promptXYZ`, `$helpme`, `$hello123` all trigger commands.
    - Arguments are taken with `content[len('$addPrompt '):]`, which cuts off a character when there's no space.
    - Command casing is mixed (`$Meme`, `$Mp3`, `$CreateQR` vs `$hello`).
15. **No real command framework.** Moving to `discord.ext.commands` and slash commands gives argument parsing, built-in help, cooldowns, permission checks, and central error handling. It also removes the need for the privileged **Message Content** intent. That intent requires Discord's approval once the bot is in 100+ servers.
16. **Runtime data lives in git.** `data/Data.json` is both seed content and live state.
    - Every `git pull` on the server conflicts with or overwrites what users added.
    - The `help` text lives in the data file and drifts from the real commands.
    - Duplicates are not prevented (`"You have beautiful retinas"` is stored 3×).
17. **No record of who added what.** Entries store no author, guild or timestamp, so a moderator can't find or remove an abusive entry. All content is global, so text added in one server shows up in every server. Input length isn't limited, so messages over 2000 characters fail to send.
18. **Logging is only `print`.** There are no log levels or tracebacks, and nothing can be inspected after a crash.
19. **Dependencies are unpinned** (`>=` only, no lockfile). `ffmpeg` is a required system dependency but is not documented. Recent `yt-dlp` releases also expect an external JavaScript runtime (Deno) for full YouTube support.
20. **The process runs on import.** `client.run(token)` and `get_token()` run at import time with no `if __name__ == "__main__":` guard, so the module can't be imported for tests.

### 🟢 Low / housekeeping

21. `modules/__pycache__/*.pyc` is tracked even though it is gitignored (it was committed before the ignore rule). `chatlog.csv` (chat logs) is committed at the root.
22. `modules/localLLM.py`: `messageToModel` never returns `answer`, there's a cp1252 Windows-console workaround, and `ollama` is not in the requirements. It's unused, so it should be removed or moved to `prototyping/`.
23. `prototyping/` pulls in `pandas`, `PyPDF2`, `tkinter`, `ollama`. These aren't in the requirements, and `weather.py` runs network calls on import.
24. The README repeats the install steps twice and gives the wrong paths (`config/token.json`, `example_token.json`).
25. `intents.messages = True` is redundant, because it's already in `Intents.default()`.

---

## 3. Target architecture

```
BotGeorge/
├── pyproject.toml              # deps + tool config (ruff, pytest); lockfile via uv or pip-tools
├── Dockerfile                  # python:3.12-slim + ffmpeg (+ deno for yt-dlp)
├── compose.yaml                # bot service + named volume for /data
├── .env.example                # DISCORD_TOKEN=..., LOG_LEVEL=INFO, ...
├── seed/
│   └── content.json            # former Data.json (read-only seed, imported once)
├── src/george/
│   ├── __main__.py             # `python -m george` → asyncio.run(main())
│   ├── bot.py                  # GeorgeBot(commands.Bot): setup_hook loads cogs, opens DB, creates HTTP session
│   ├── config.py               # typed settings from env (pydantic-settings or dataclass)
│   ├── logging_setup.py
│   ├── errors.py               # user-facing error types + global error handler
│   ├── storage/
│   │   ├── db.py               # aiosqlite connection, migrations
│   │   └── content_repo.py     # add/random/list/delete entries (category, guild, author)
│   ├── services/
│   │   ├── reddit.py           # async (aiohttp/asyncpraw), NSFW filter, retries, size checks
│   │   ├── youtube.py          # yt-dlp wrapper: per-job temp dir, limits, semaphore
│   │   └── qr.py               # in-memory PNG (BytesIO)
│   └── cogs/
│       ├── basic.py            # hello, name, help
│       ├── content.py          # prompt/swear/compliment/random + add*
│       ├── meme.py
│       ├── qr.py
│       └── mp3.py
└── tests/
    ├── fixtures/               # recorded Reddit JSON, yt-dlp info dicts
    └── test_*.py
```

**Key design rules**
- **Cogs only handle Discord I/O.** Logic lives in `services/` and `storage/` and has no `discord` imports, so it can be unit-tested.
- **No shared mutable files.** Every job gets its own `tempfile.TemporaryDirectory()` or an in-memory `BytesIO`, cleaned up in `finally`/`async with`.
- **All runtime state goes in one place** (`/data` volume, SQLite). The repo becomes read-only at runtime.
- **Every external call has a timeout, a size cap and a clear failure message.**

---

## 4. Phased plan

Each phase leaves the bot working and can ship on its own.

### Phase 0: Emergency (≈ 30 min)
- [ ] Reset the Discord token in the Developer Portal and update the local secret.
- [ ] Set `allowed_mentions=discord.AllowedMentions.none()` on the client (one line). This closes finding #3 right away.
- [ ] Add `'noplaylist': True` and a `match_filter` duration limit to the yt-dlp options. This closes the worst part of #5.
- [ ] Skip Reddit posts with `post.get("over_18")` (#4).
- [ ] Back up the current `data/Data.json`.

**Done when:** the old token is rejected, `@everyone` entries no longer ping, and a playlist link only downloads one video.

### Phase 1: Repository hygiene & tooling (≈ ½ day)
- [ ] `git rm --cached -r modules/__pycache__ chatlog.csv`. Extend `.gitignore` with `media/`, `*.mp3`, `qr.png`, `.env`, `data/*.db`, `.venv/`.
- [ ] Move `modules/localLLM.py` to `prototyping/` (or delete it). Keep `prototyping/` out of the package and lint scope.
- [ ] Add `pyproject.toml` with pinned dependency ranges (`discord.py~=2.6`, `yt-dlp`, `segno`, `aiohttp`, `aiosqlite`), dev extras (`pytest`, `pytest-asyncio`, `ruff`), and a lockfile (`uv lock` or `pip-compile`).
- [ ] Add `ruff` (lint + format) and a pre-commit config.
- [ ] Rewrite the README: one install path, the correct file names, system requirements (`ffmpeg`, Python ≥ 3.11, Deno for yt-dlp), the required intents, and how to run it in Docker.

**Done when:** a fresh clone installs from the lockfile and `ruff check` passes.

### Phase 2: Skeleton: config, logging, bot class, cogs (≈ 1 day)
- [ ] `config.py` reads settings from the environment or `.env`:
  `DISCORD_TOKEN` (required, fail fast with a clear message), `DATA_DIR`, `LOG_LEVEL`, `COMMAND_PREFIX` (default `$`), `SUBREDDITS`, `MP3_MAX_DURATION_S`, `MP3_MAX_CONCURRENT`, `MEME_MAX_BYTES`.
  Keep reading `data/token.json` as a deprecated fallback for one release.
- [ ] `logging_setup.py`: use `discord.utils.setup_logging()` plus a `george` logger, logging to stdout in Docker and optionally to a rotating file. Replace every `print`.
- [ ] `GeorgeBot(commands.Bot)`, where `setup_hook()` opens the DB, creates one shared `aiohttp.ClientSession`, and loads the cogs. `close()` disposes of them.
- [ ] `__main__.py` uses `asyncio.run(main())` with `async with bot: await bot.start(token)` and handles SIGTERM for a clean Docker stop.
- [ ] Port every command into cogs as **hybrid commands** (`@commands.hybrid_command`). They work as `$hello` **and** `/hello`, so existing users aren't broken. Add case-insensitive aliases for the old names (`$Meme` → `meme`, `$Mp3` → `mp3`, `$CreateQR` → `qr` with alias `CreateQR`).
- [ ] Global `on_command_error` / `tree.on_error`: send a friendly message, log the full traceback, and handle `CommandOnCooldown`, `MaxConcurrencyReached` and `MissingPermissions` explicitly.
- [ ] Generate help from the registered commands (the built-in help or a custom embed), and remove `help` from the data file.

**Done when:** every current command behaves the same, `python -m george` starts from any working directory, and an exception in one command is logged and doesn't affect other commands.

### Phase 3: Fix each feature for correctness & concurrency (≈ 1–2 days)

**QR (`services/qr.py`)**
- [ ] `segno.make_qr(text).save(buf, kind="png", scale=10)` into `io.BytesIO`, then send `discord.File(buf, "qr.png")`. No files on disk at all.
- [ ] Limit the input length (QR capacity is about 2.9 KB of bytes at the lowest error correction). Catch `segno.DataOverflowError` and send a user message.

**Memes (`services/reddit.py`)**
- [ ] Use async HTTP through the shared `aiohttp` session with an explicit timeout (e.g. 10 s), or `asyncpraw` with a registered Reddit app (OAuth). OAuth is much more reliable than anonymous JSON.
- [ ] Replace the `random.json` call: fetch `hot`/`top?t=week` (limit ≈ 50), cache the listing per subreddit for a few minutes, and pick randomly from posts that pass the filters. This also removes the recursion.
- [ ] Filters: skip `over_18` (unless `channel.is_nsfw()`), skip `stickied`, accept `post_hint == "image"` / `i.redd.it` / gallery first image. For `is_video`, either skip it or merge audio with yt-dlp, because `fallback_url` has no sound.
- [ ] Check `Content-Length` before downloading and stream with a byte cap equal to `ctx.guild.filesize_limit` (falling back to 10 MiB in DMs). Keep the data in memory (`BytesIO`) or in a per-request temp dir.
- [ ] Set a real User-Agent: `"python:botgeorge:v<version> (by /u/<real_account>)"`.
- [ ] Use a bounded number of attempts (e.g. 3 subreddits / 3 posts) before replying "no meme found, try again".

**MP3 (`services/youtube.py`)**
- [ ] Validate URLs with `urllib.parse`. Accept `youtube.com`, `www.`, `m.`, `music.` (`/watch?v=`, `/shorts/`) and `youtu.be`. Strip the `list` parameter.
- [ ] Per-job `TemporaryDirectory`, with `outtmpl = "<tmp>/%(id)s.%(ext)s"`. The tempdir is removed in `finally`, so partial `.part`/`.webm` files go away too.
- [ ] Options: `noplaylist`, `match_filter=match_filter_func("duration <= 900")`, `max_filesize`, `socket_timeout`, `retries`. Keep the existing thumbnail and metadata postprocessors. Use `restrictfilenames` and set the upload name to a sanitized title.
- [ ] Choose a bitrate so the result usually fits the guild upload limit, e.g. `preferredquality: "192"` or derived from the duration. Check `os.path.getsize` against `ctx.guild.filesize_limit` **before** sending, and give the real reason if it's too large.
- [ ] Concurrency: a global `asyncio.Semaphore(MP3_MAX_CONCURRENT)` (e.g. 2) plus `@commands.max_concurrency(1, per=BucketType.user)` and a cooldown. Tell the user when their job is queued.
- [ ] Use `ctx.defer()` / `ctx.typing()` while working. Slash-command interactions time out after 3 s without a defer.
- [ ] Map `yt_dlp.utils.DownloadError` messages to user text (private video, age-restricted, region-blocked, too long).

**Content lists (`cogs/content.py`)**: covered by Phase 4.

**Global**
- [ ] Cooldowns on every command (e.g. `@commands.cooldown(1, 5, BucketType.user)` for media, lighter limits for text).
- [ ] Truncate any outgoing message to 2000 characters.

**Done when:** 10 parallel `$CreateQR`, `$Meme` and `$Mp3` calls from different users each return the correct, separate result, and the working directory is unchanged afterwards.

### Phase 4: Persistence: SQLite instead of Data.json (≈ 1 day)
- [ ] Schema (migration `001_init.sql`):
  ```sql
  CREATE TABLE entries (
      id          INTEGER PRIMARY KEY,
      guild_id    INTEGER,              -- NULL = global seed content
      category    TEXT NOT NULL CHECK (category IN ('prompt','swear','compliment','random')),
      text        TEXT NOT NULL,
      author_id   INTEGER,              -- NULL for seed data
      created_at  TEXT NOT NULL DEFAULT (datetime('now')),
      UNIQUE (guild_id, category, text)
  );
  CREATE INDEX idx_entries_lookup ON entries (category, guild_id);
  CREATE TABLE schema_version (version INTEGER NOT NULL);
  ```
- [ ] `aiosqlite`, with WAL mode and one connection owned by the bot. SQLite handles atomic writes, so no more corruption or races.
- [ ] Random pick: `SELECT text FROM entries WHERE category=? AND (guild_id IS NULL OR guild_id=?) ORDER BY random() LIMIT 1`. This is fine at this data size. If the list is empty, reply "I don't know any yet, teach me with /add…".
- [ ] One-time import: copy `seed/content.json` (today's `Data.json`, de-duplicated, without `help`) as global entries **plus** a migration of the live server's current `Data.json`, so nothing users have added is lost.
- [ ] Input rules: strip whitespace, 1–300 characters, reject duplicates with a friendly message, no mention parsing (already covered by the global `allowed_mentions`).
- [ ] New moderator commands (`manage_messages` permission): `/content list <category>`, `/content remove <id>`. Moderators need these to clean up abusive entries.
- [ ] Back up `/data/george.db` with SQLite `.backup` from a cron/systemd timer or a small in-bot `tasks.loop`, and keep N copies.

**Done when:** killing the process during `$addPrompt` never corrupts data, entries record author and guild, and a moderator can remove an entry.

### Phase 5: Testing & CI (≈ 1 day, can run alongside Phases 3–4)
- [ ] Unit tests (no network):
  - URL validator: valid and invalid YouTube URLs, playlist stripping.
  - Reddit post filtering, with recorded JSON fixtures covering image, gallery, video, NSFW, text post.
  - yt-dlp options builder and the error mapping.
  - `content_repo` against an in-memory SQLite DB: add, duplicate, random from an empty list, guild scoping.
  - QR generation, including the overflow case.
  - Config: a missing token fails fast with a clear error.
- [ ] Cog smoke tests with mocked `ctx` (or `dpytest`).
- [ ] GitHub Actions: `ruff check`, `ruff format --check`, `pytest` on push/PR. Docker build on main.
- [ ] Dependabot (or Renovate) for pip and GitHub Actions. This is also the first step toward automatic yt-dlp updates (§6).

### Phase 6: Portable packaging, deployment & operations (≈ 1 day)

**Goal: the bot runs the same way on any machine** (Windows PC, Linux server, Raspberry Pi, Mac, cloud VPS). Moving it means copying two things: the `.env` file and the `data/` folder.

**Portability rules (apply from Phase 2 onward)**
- [ ] All paths come from `config.DATA_DIR` and `pathlib.Path`. No hard-coded `./`, no `os.getcwd()` assumptions, no Windows-only code (e.g. the cp1252 console workaround).
- [ ] **All state goes in one folder:** `DATA_DIR/` holds `george.db`, `backups/` and `logs/`, and temporary files go to the OS temp dir. Backup or move = copy that folder.
- [ ] **All config goes in `.env`**, with `.env.example` committed. Nothing machine-specific lives in the code or the repo.

**Option A: Docker (recommended; identical on every OS)**
- [ ] **Dockerfile:** `python:3.12-slim`, `apt-get install ffmpeg`, install Deno (the JS runtime yt-dlp uses for YouTube), install from the lockfile, run as a non-root user, `WORKDIR /app`, `VOLUME /data`, `CMD ["python", "-m", "george"]`.
  ffmpeg and Deno are inside the image, so the host only needs Docker.
- [ ] **Multi-arch image** (`linux/amd64` + `linux/arm64`) built by GitHub Actions with `docker buildx` and pushed to GitHub Container Registry (GHCR, `ghcr.io/adrianprok/botgeorge`), so a Raspberry Pi, a normal PC or a VPS can pull the same tag.
- [ ] **compose.yaml:** `image: ghcr.io/…:latest` (with `build: .` as fallback), `restart: unless-stopped`, `env_file: .env`, `./data:/data` bind mount (easy to find and copy), memory/CPU limits (ffmpeg can spike), log rotation (`logging.options.max-size`).
- [ ] Deploy on any host: `git clone` (or just download `compose.yaml` + `.env.example`), fill in `.env`, `docker compose up -d`.

**Option B: Plain Python (no Docker)**
- [ ] Run with `uv run python -m george` (or `pip install .`) on Windows, macOS and Linux.
- [ ] At startup the bot checks for `ffmpeg` and `deno` on `PATH` (`shutil.which`) and exits with a clear install hint if one is missing. The README lists the install command per OS (`winget`, `brew`, `apt`).
- [ ] Optional service files in `deploy/`: a systemd unit for Linux (`Restart=on-failure`, `EnvironmentFile=`) and a short Windows Task Scheduler / NSSM note.

**Operations (both options)**
- [ ] **Health:** log `on_ready`, `on_disconnect` and `on_resumed`. Add a heartbeat file for the Docker `HEALTHCHECK`. Optionally send errors to a private Discord channel or webhook.
- [ ] **Graceful shutdown:** on SIGTERM/Ctrl+C, stop accepting new MP3 jobs, let running ones finish (with a timeout), then close the DB and HTTP session.
- [ ] **Discord application settings:** enable the Message Content intent. A private bot in fewer than 100 servers needs no verification for it, so `$` prefix commands can stay long-term alongside slash commands. Register slash commands to your server (`tree.copy_global_to(guild)` + `sync(guild=…)`) so changes appear instantly. Invite the bot with: Send Messages, Attach Files, Embed Links, Use Application Commands. In the Developer Portal, turn off "Public Bot" so only you can add it to servers.
- [ ] **Release process:** semantic version in `pyproject.toml`, git tags, and a CHANGELOG.

**Done when:** on a machine that has never run the bot, `.env` + `data/` + `docker compose up -d` (or `uv run python -m george`) brings it up with all content intact, it restarts by itself after a crash, and the same image runs on x86 and ARM.

---

## 5. Suggested order & effort

| # | Phase | Effort | Depends on |
|---|---|---|---|
| 0 | Emergency fixes | 30 min | – |
| 1 | Hygiene & tooling | ½ day | 0 |
| 2 | Skeleton (config, logging, cogs) | 1 day | 1 |
| 3 | Feature correctness & concurrency | 1–2 days | 2 |
| 4 | SQLite persistence | 1 day | 2 |
| 5 | Tests & CI | 1 day | 2 (alongside 3/4) |
| 6 | Portable packaging (Docker multi-arch + plain Python) / ops | 1 day | 2 |

Total: about **5–7 focused days**. Phases 3, 4 and 5 can be split into one PR per feature.

---

## 6. How this sets up the next goals

**Better multi-user support**
- Per-job temp dirs, semaphores, per-user cooldowns and `max_concurrency` (Phase 3) already remove the race conditions that hit concurrent users.
- `guild_id` and `author_id` on every entry (Phase 4) enable per-server libraries, "my entries", per-user favourites and moderation without another migration.
- Slash commands (Phase 2) allow ephemeral replies, autocomplete, and per-command permissions set by server admins.
- Later options: a job queue with position feedback for MP3s, and per-guild settings (enabled commands, subreddit list, NSFW policy) in a `guild_settings` table.

**Keeping yt-dlp up to date automatically** (confirmed goal)

yt-dlp needs frequent updates because YouTube keeps changing. When it's outdated, `$Mp3` breaks with "Sign in to confirm…", "nsig extraction failed" or HTTP 403 errors. Phases 1, 5 and 6 make updates *safe*: a lockfile, tests around the wrapper, and a portable image. `services/youtube.py` is the only module that imports `yt_dlp`, so an update can't break anything else.

Recommended pipeline, which fits the portable Docker setup:
1. **Dependabot** checks `yt-dlp` **daily** and opens a PR that bumps the lockfile.
2. **CI** runs the unit tests and a **canary job** that converts one short, known-good public video with the new version.
3. If CI is green, the PR **auto-merges** (GitHub auto-merge, limited to `yt-dlp` patch/minor bumps).
4. The merge triggers the **multi-arch image build** and pushes `ghcr.io/…:latest` plus a dated tag.
5. On the host, a **scheduled job pulls the new image and restarts** the bot: `docker compose pull && docker compose up -d`, run from cron, a systemd timer or Windows Task Scheduler (`deploy/update.sh` / `update.ps1`). This keeps the host side portable.
6. **Rollback:** pin the previous dated tag in `compose.yaml`.

Safety nets inside the bot:
- Map the typical "outdated extractor" errors to a clear message ("YouTube changed something, an update is on its way") and alert the owner channel.
- A `$version` command shows the bot, yt-dlp and ffmpeg versions, so you can see whether an update has landed.
- Ship Deno in the image, because newer yt-dlp versions need a JS runtime for YouTube.

Simpler fallback for **Option B (no Docker)**: a scheduled `uv lock --upgrade-package yt-dlp && uv sync`, then a restart. Or upgrade yt-dlp in the start script before launching. It's less reproducible, but fine for a private bot.

*(Avoid:* `pip install -U` and reloading the module while the bot is running. It's fragile and can't be rolled back.)

---

## 7. Decisions & open questions

**Decided**
| Topic | Decision | Effect on the plan |
|---|---|---|
| "YouTube library" | Means keeping **yt-dlp** up to date | §6 pipeline: Dependabot → CI canary → auto-merge → image build → scheduled pull |
| Audience | **Private** server | Message Content intent needs no verification, so `$` commands stay. "Public Bot" turned off. ToS risk of `$Mp3` is accepted. Reddit OAuth is recommended but not required. |
| Hosting | **Portable** | Phase 6: Docker multi-arch image (Option A) plus plain-Python fallback (Option B). All state in `data/`, all config in `.env`. |
| `$` prefix | Keep, alongside slash commands (hybrid) | Phase 2 as written |

**Still open**
1. **Is the bot in one server or several?** If it's only ever in your one server, content scope doesn't matter: keep today's behaviour (everything shared). The `guild_id` column is still stored so it can be switched later. If it's in several servers, decide between `CONTENT_SCOPE=global` (today: added text appears everywhere) and `CONTENT_SCOPE=guild` (each server sees the shared seed list plus only its own additions).
