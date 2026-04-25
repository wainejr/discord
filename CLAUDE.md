# CLAUDE.md

## Overview

This repo hosts **Acelerado**, a Discord bot that manages the community server for the YouTube channel [Waine - Dev do Desempenho](https://www.youtube.com/@waine_jr). It announces new YouTube uploads/livestreams in the Discord guild and keeps YouTube channel members synced to a Discord role.

The codebase is small, single-bot, Python 3.10+, and runs as a long-lived service (systemd unit provided).

## Stack

- **Language:** Python >=3.11
- **Discord:** `discord.py` 2.x — `commands.Bot` subclass (`AceleradoBot`) using `setup_hook` and `discord.ext.tasks.loop` for periodic work; `members` intent enabled
- **YouTube:** `google-api-python-client` via OAuth2 (`google-auth-oauthlib`); a token-based client is used so members-only / unlisted videos are visible
- **Config:** `pydantic-settings` (`BaseSettings` reading `.env`)
- **CLI:** `typer` — single `acelerado` entrypoint with subcommands (`run`, `audit-members`, `refresh-token`, `status`, `monitor`)
- **TUI:** `textual` — used for the `monitor` command (live token expiry + recent announcements)
- **Packaging:** `pyproject.toml` (hatchling), managed with `uv`
- **Lint/format:** `ruff` (replaces `black` + `isort`)
- **Logging:** stdlib `logging` + `rich.logging.RichHandler`; each module does `logger = logging.getLogger(__name__)`; configured once via `acelerado.log.setup_logging()` from the typer root callback (`--log-level` / `ACELERADO_LOG_LEVEL`, default `INFO`). Third-party loggers (`discord`, `googleapiclient`, `urllib3`) are pinned to `WARNING` unless `DEBUG` is requested.
- **Process:** `scripts/acelerado.service` (systemd, user unit) → `scripts/run_service.sh` → `acelerado run`

## Layout

```
acelerado/
  __main__.py     # thin wrapper -> cli.app (so `python -m acelerado` works)
  cli.py          # typer app, subcommands defined here
  bot.py          # AceleradoBot (commands.Bot subclass) + run_bot()
  state.py        # AceleradoState — orchestrates checks each tick
  youtube.py      # OAuth + YouTube Data API helpers
  tui.py          # textual MonitorApp
  env.py          # pydantic-settings env config
  log.py          # logger setup
scripts/
  acelerado.service        # systemd unit
  run_service.sh           # invoked by systemd; calls `acelerado run`
  copy_systemd.sh / send_token.sh
examples/         # sample YouTube API payloads
published.txt     # persisted list of already-announced video IDs
credentials.json  # Google OAuth client secrets (gitignored variant: .example.json)
token.pickle      # cached OAuth user token
.env              # runtime config (see .example.env)
```

## Runtime behavior

`AceleradoBot.setup_hook` starts a `tasks.loop(seconds=300)`. Its `before_loop` waits for the gateway-ready signal, then constructs `AceleradoState` once. Each tick calls `state.event_loop()`:

1. **`check_members_apoiadores`** — for every member with a role whose name contains `"YouTube Member"`, ensure they also have the `Registradores` role; if added, post a welcome in the `chat-registradores` channel.
2. **`check_expiration`** — if the YouTube OAuth token expires in <24h, post a renewal reminder to the log channel (rate-limited to once/hour).
3. **Video announcing** — fetch the latest 10 uploads, diff against `published.txt`, and announce new ones in the announce channel with `@everyone`. Filtering rules (`should_announce_video`):
   - Skip if non-public (unlisted/private).
   - Skip if not yet processed (unless it's a livestream).
   - Skip vertical videos (Shorts).
   - Message wording differs for livestream / members-only / regular video.

## Required env (`.env`)

`DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_ANNOUNCE_CHANNEL_ID`, `DISCORD_LOG_CHANNEL_ID`, `YOUTUBE_CHANNEL_ID`, `YOUTUBE_API_KEY`. Plus `credentials.json` (Google OAuth client). First run opens a browser for consent; the resulting token is cached to `token.pickle`.

## CLI

```sh
uv sync
uv run acelerado --help
```

| Subcommand            | Purpose                                                         |
|-----------------------|-----------------------------------------------------------------|
| `acelerado run`       | Start the Discord bot (long-running; what systemd invokes).     |
| `acelerado status`    | Print token expiry + count of tracked announcements.            |
| `acelerado monitor`   | Open the textual TUI: live token countdown + recent video list. |
| `acelerado audit-members` | Print members in `Registradores` missing the YouTube role. |
| `acelerado refresh-token` | Backup `token.pickle` and re-run the OAuth consent flow.   |

For deployment, install the systemd user unit via `scripts/copy_systemd.sh`. The unit shells out to `scripts/run_service.sh`, which now calls `acelerado run`.

## Conventions / gotchas

- User-facing strings (Discord messages, role names) are in **Portuguese** — keep that when editing.
- Hardcoded role/channel names live in `state.py` (`ROLE_NAME_APOIADORES = "Registradores"`, `CHAT_MSG_ADD = "chat-registradores"`); the YouTube member role is matched by substring `"YouTube Member"`.
- `published.txt` is the source of truth for "already announced". It's seeded on first run from the latest 20 uploads if missing — don't delete it on a live deployment or you'll re-announce.
- The OAuth token must be refreshed periodically; the bot itself only *warns* about expiry, it does not auto-renew the consent flow.
- The YouTube client and upload-playlist ID are lazy-initialized via `@lru_cache` in `youtube.py` — first call triggers OAuth and the channel lookup.
- The bot is event-driven, not command-driven; no slash commands are registered, so `bot.tree.sync()` is intentionally not called.
