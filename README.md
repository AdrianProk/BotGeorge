# BotGeorge

George, the creepy gargoyle: a private Discord bot written in Python with
[discord.py](https://discordpy.readthedocs.io/). He posts memes, makes QR codes,
turns YouTube links into MP3s, and remembers prompts, compliments and swears that
people teach him.

It runs the same way on Windows, macOS, Linux and a Raspberry Pi, either in Docker
(recommended) or with plain Python.

---

## Commands

Every command works with the `$` prefix **and** as a slash command (`/meme`).
Prefix commands ignore upper/lower case, so the old spellings (`$Meme`, `$Mp3`,
`$CreateQR`, `$addPrompt`, …) still work.

| Command | What it does |
|---|---|
| `$hello` | Says hello |
| `$name` | George introduces himself |
| `$help` | Lists all commands |
| `$meme` | A random meme from Reddit (NSFW posts only in NSFW channels) |
| `$qr <text>` | QR code from text or a link (alias: `$createqr`) |
| `$mp3 <YouTube link>` | MP3 of a single YouTube video (max 15 min by default) |
| `$prompt` / `$compliment` / `$random` / `$fuckyou` | A random art prompt / compliment / random line / swear |
| `$addprompt <text>` / `$addcompliment` / `$addrandom` / `$addswear` | Teach George something new |
| `$content list <category> [page]` | Show what George has learned, with `#id`s |
| `$content remove <id>` | Remove an entry (see [Moderation](#moderation)) |
| `$version` | Bot, yt-dlp and ffmpeg versions |

What people teach George is **shared between all servers** he's in.

---

## 1. Create the Discord application (once)

1. Open the [Discord Developer Portal](https://discord.com/developers/applications), click **New Application**, then go to **Bot**.
2. Click **Reset Token** and copy the token. You'll need it for `.env`.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**. The `$` commands need it.
4. Turn **Public Bot** off, so only you can add George to servers.
5. Invite the bot. Replace `YOUR_APP_ID` with the *Application ID* from **General Information**:
   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=2147535872
   ```
   (permissions: View Channels, Send Messages, Embed Links, Attach Files, Use Application Commands)

## 2. Configure

```bash
git clone https://github.com/AdrianProk/BotGeorge.git
cd BotGeorge
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and set at least `DISCORD_TOKEN`. Recommended extras:

| Variable | Why |
|---|---|
| `OWNER_IDS` | Your Discord user ID. Owners can remove any entry. |
| `GUILD_IDS` | Your server IDs. Slash commands then show up instantly. |
| `OWNER_LOG_CHANNEL_ID` | A private channel where George reports new entries, removals and errors. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Optional. More reliable memes ([create a "script" app](https://www.reddit.com/prefs/apps)). |

All options with explanations are in [`.env.example`](.env.example).
(To copy IDs, enable *Developer Mode* in Discord: Settings → Advanced.)

## 3a. Run with Docker (recommended)

You only need [Docker](https://docs.docker.com/get-docker/). ffmpeg and Deno are inside the image.

```bash
docker compose up -d --build   # first start (builds the image locally)
docker compose logs -f         # watch the logs, Ctrl+C to stop watching
docker compose down            # stop the bot
```

When GitHub Actions has published the image (`ghcr.io/adrianprok/botgeorge`),
`docker compose up -d` pulls it instead of building. If the repository is
private, run `docker login ghcr.io` first, or keep using `--build`. The image
works on x86 PCs/servers and on ARM (Raspberry Pi 4/5).

## 3b. Run without Docker

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), **ffmpeg** and **[Deno](https://deno.com)** (yt-dlp needs Deno for YouTube):
   - Windows: `winget install astral-sh.uv Gyan.FFmpeg DenoLand.Deno`
   - macOS: `brew install uv ffmpeg deno`
   - Debian/Ubuntu: `sudo apt install ffmpeg`, then install uv and Deno with their install scripts
2. In the project folder:
   ```bash
   uv sync --no-dev
   uv run george          # or: python George.py (inside the uv environment)
   ```

George tells you at startup if ffmpeg or Deno is missing. Without ffmpeg, only
`$mp3` is turned off. For an always-on Linux service there's a systemd unit in
[`deploy/george.service`](deploy/george.service).

---

## Data, backups and moving to another machine

Everything George stores lives in the **`data/`** folder:

```
data/
├── george.db        # all learned content (SQLite)
├── backups/         # daily copies of the database (last 7 kept)
├── logs/            # log files (when not running in Docker)
└── heartbeat        # used by the Docker health check
```

To move George to another computer, copy **`.env`** and **`data/`**, then start it there.
To restore a backup, stop the bot and copy a file from `data/backups/` over `data/george.db`.

## Updating (including yt-dlp)

YouTube changes often, so yt-dlp needs regular updates. When `$mp3` starts
failing with "YouTube changed something", update the bot:

- **Docker:** `deploy/update.sh` (Linux/macOS) or `deploy/update.ps1` (Windows).
  It pulls the newest image and restarts George. You can schedule it daily (instructions inside the scripts).
- **Without Docker:** `git pull`, then `uv sync --no-dev --upgrade-package yt-dlp`, then restart.

Dependabot checks for new yt-dlp versions every day and opens a pull request.
Each merge to `main` builds a new image.

## Upgrading from the old version (George.py + Data.json)

The old `data/Data.json` and `data/token.json` are no longer in the repository.
Before you `git pull`:

1. **Copy `data/Data.json` somewhere safe.** It contains everything people taught George.
2. `git pull` (if git complains about local changes to `data/Data.json`, run `git checkout -- data/Data.json` *after* making the copy).
3. Put your copy back into `data/Data.json`. On the next start George imports it into the
   database and renames it to `Data.json.imported`.
4. Move the token from `data/token.json` into `DISCORD_TOKEN` in `.env`
   (`data/token.json` still works for now, with a warning).

---

## Moderation

Because content is shared between servers, removing an entry removes it everywhere.
`$content remove <id>` is allowed for:

- **bot owners** (`OWNER_IDS`): any entry
- **the person who added it**: their own entries
- **server moderators** (*Manage Messages*): entries that were added from their server

Mentions in stored text never ping anyone (`@everyone` is harmless).

## Development

```bash
uv sync                      # installs dev tools too
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format
```

```
src/george/
├── __main__.py      # entry point (signals, startup checks)
├── bot.py           # GeorgeBot: setup, error handling, backups, heartbeat
├── config.py        # settings from environment / .env
├── cogs/            # Discord commands (basic, content, meme, qr, mp3)
├── services/        # Reddit, YouTube (only place that imports yt-dlp), QR
├── storage/         # SQLite database + content repository
└── seed/content.json  # starting content for a fresh database
```

The refactor plan behind this structure is in [`docs/PRODUCTION_REFACTOR_PLAN.md`](docs/PRODUCTION_REFACTOR_PLAN.md).

## Security notice

- Never commit `.env`. It's in `.gitignore`.
- If a token ever ends up in git, **reset it** in the Developer Portal right away.
  Deleting the file is not enough, because it stays in the git history.

## License

MIT
