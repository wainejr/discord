# CLAUDE.md

## Overview

This repo hosts **Acelerado**, a Discord bot that manages the community server for the YouTube channel [Waine - Dev do Desempenho](https://www.youtube.com/@waine_jr). It announces new YouTube uploads/livestreams in the Discord guild and keeps YouTube channel members synced to a Discord role.

The codebase is small, single-bot, Python 3.11+, and is meant to run inside a `tmux`/`screen` session (systemd was removed — the user manages the process by hand).

## Stack

- **Language:** Python >=3.11
- **Discord:** `discord.py` 2.x — `commands.Bot` subclass (`AceleradoBot`) using `setup_hook` and `discord.ext.tasks.loop` for periodic work; `members` intent enabled
- **YouTube:** `google-api-python-client` via OAuth2 (`google-auth-oauthlib`); a token-based client is used so members-only / unlisted videos are visible
- **Config:** `pydantic-settings` (`BaseSettings` in `env.py`) wrapped by a runtime `Settings` overlay in `config.py` (issue #30). Resolution: `config.json` (overlay, gitignored, atomic-written) → `.env` / process env → defaults. Edited via `acelerado config` CLI and `/config` slash group; secrets (`DISCORD_TOKEN`, `YOUTUBE_API_KEY`) are guarded — only `.env`. `get_env()` is now a thin proxy over `get_settings().cfg`; tests still call `get_env.cache_clear()` (delegates to `reload_settings()`).
- **CLI:** `typer` — single `acelerado` entrypoint with subcommands (`run`, `audit-members`, `refresh-token`, `status`, `monitor`)
- **TUI:** `textual` — used for the `monitor` command (live token expiry + recent announcements)
- **Packaging:** `pyproject.toml` (hatchling), managed with `uv`
- **Lint/format:** `ruff` (replaces `black` + `isort`)
- **Logging:** stdlib `logging` + `rich.logging.RichHandler`; each module does `logger = logging.getLogger(__name__)`; configured once via `acelerado.log.setup_logging()` from the typer root callback (`--log-level` / `ACELERADO_LOG_LEVEL`, default `INFO`). Third-party loggers (`discord`, `googleapiclient`, `urllib3`) are pinned to `WARNING` unless `DEBUG` is requested.
- **Tests:** `pytest` + `pytest-asyncio` (asyncio_mode=auto) + `pytest-cov`. Discord and the Google YouTube client are fully mocked — the suite runs offline and never opens a gateway connection or triggers OAuth.
- **Type-check:** `mypy` with the `pydantic.mypy` plugin (`uv run mypy acelerado`). Pragmatic posture: `ignore_missing_imports`, but `check_untyped_defs` and `strict_equality` are on.
- **CI:** GitHub Actions (`.github/workflows/ci.yml`) runs ruff + mypy + pytest with coverage on every push/PR to `main`.
- **Process:** run by hand inside `tmux` (or wrap in a `while true` loop). Bot is fail-proof: per-step exceptions are caught, reported to the Discord log channel (10-min cooldown), and the loop keeps ticking. Crashes of the whole process trigger a non-zero exit so the wrapper can restart.

## Layout

```
acelerado/
  __init__.py     # marks the package (mypy needs this)
  __main__.py     # thin wrapper -> cli.app (so `python -m acelerado` works)
  cli.py          # typer app, subcommands defined here
  bot.py          # AceleradoBot — setup_hook, tasks.loop, on_error,
                  # error-restart hook, run_bot()
  state.py        # AceleradoState — per-tick orchestration + report_error
  youtube.py      # OAuth + YouTube Data API helpers (lazy lru_cache)
  tui.py          # textual MonitorApp
  env.py          # EnvCfg pydantic schema (incl. ACELERADO_TICK_SECONDS)
  config.py       # Settings overlay — config.json on top of EnvCfg
                  # (atomic write, set/unset/reload, secret-key guard)
  log.py          # setup_logging() with RichHandler
  challenges/     # monthly performance-challenge integration (issue #37)
    spec.py       #   pydantic Spec for spec.json (extra="allow")
    github.py     #   async httpx client for the desafios repo + history cache
    state.py      #   challenges_state.json — announce + results posted/dismissed/last_remind
    announce.py   #   metric-aware announcement copy renderer
    results.py    #   pydantic Results + metric-aware results post renderer (Phase 3)
scripts/
  send_token.sh   # SCP token.pickle to a remote host
.github/workflows/
  ci.yml          # ruff check + ruff format --check + mypy + pytest --cov
tests/
  conftest.py     # autouse fixtures: tmp cwd, lru_cache resets, env vars,
                  # YouTube payload builders, fake_bot/fake_guild MagicMocks,
                  # write_token helper
  test_youtube.py # pure helpers + mocked google-client responses
  test_state.py   # AceleradoState with mocked bot/channels/youtube
  test_env.py     # pydantic-settings loading / validation
  test_log.py     # setup_logging idempotence & level gating
  test_cli.py     # typer CliRunner smoke tests
examples/         # sample YouTube API payloads
published.txt     # persisted list of already-announced video IDs
credentials.json  # Google OAuth client secrets (gitignored variant: .example.json)
token.pickle      # cached OAuth user token
.env              # runtime config (see .example.env)
```

## Runtime behavior

`AceleradoBot.setup_hook` calls `event_loop_task.change_interval(seconds=ACELERADO_TICK_SECONDS)` (default 300) and starts the loop. Its `before_loop` waits for the gateway-ready signal, then constructs `AceleradoState` once. Each tick calls `state.event_loop()`, which iterates a `[(name, step), …]` list and wraps each step in try/except → `state.report_error(name, exc)` (logs locally + posts to Discord log channel, 10-min cooldown).

1. **`check_members_apoiadores`** — for **every** role whose name contains `"YouTube Member"` (so all tiers, not just the first match), ensure each member also has the `Registradores` role; if added, post a welcome in the `chat-registradores` channel. Members appearing in multiple tiers are deduped via a `seen` id set.
2. **`check_expiration`** — if the YouTube OAuth token expires in <24h, post a renewal reminder to the log channel (rate-limited to once/hour).
3. **Video announcing** — fetch the latest 10 uploads, diff against `published.txt`, and announce new ones in the announce channel with `@everyone`. Filtering rules (`should_announce_video`):
   - Skip if non-public (unlisted/private).
   - Skip if not yet processed (unless it's a livestream).
   - Skip vertical videos (Shorts).
   - Message wording differs for livestream / members-only / regular video.
4. **Monthly challenges** (issue #37) — gated by `ACELERADO_CHALLENGES_ENABLED`. Two tick steps:
   - `_announce_new_challenge` (Phase 1): on the configured day/hour, query the `wainejr/acelerado-desafios` repo via the GitHub REST API, locate the `YYYY-MM-*` folder for the current month, fetch its `spec.json`, and post a metric-aware announcement in `DISCORD_CHALLENGES_CHANNEL_ID`. Idempotency lives in `challenges_state.json` (slug-keyed, not month-keyed).
   - `_remind_pending_results` (Phase 3): for every challenge folder whose `YYYY-MM` is in the past and which is neither posted nor dismissed in state, post a 1×/24h reminder in the **log channel** so the operator gets nudged to run `/desafio resultados <slug>` (or `/desafio resultados-skip <slug>` to mute).

   `/desafio` is a slash group: `status` (current challenge + open-PR count, public), `resultados <slug>` (admin — fetches `results.json`, renders metric-aware draft, posts to `DISCORD_REVIEW_CHANNEL_ID` with the editorial `EditableDraftView`), `resultados-skip <slug>` (admin — silences reminders), `historico` (top-3 of past challenges, 6h cache, footer shows last fetch).

## Required env (`.env`)

Required: `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_ANNOUNCE_CHANNEL_ID`, `DISCORD_LOG_CHANNEL_ID`, `YOUTUBE_CHANNEL_ID`, `YOUTUBE_API_KEY`.

Optional: `ACELERADO_TICK_SECONDS` (loop period, default `300`), `ACELERADO_LOG_LEVEL` (`DEBUG`/`INFO`/…, default `INFO`).

Plus `credentials.json` (Google OAuth client). First run opens a browser for consent; the resulting token is cached to `token.pickle`.

## CLI

```sh
uv sync
uv run acelerado --help
```

| Subcommand            | Purpose                                                         |
|-----------------------|-----------------------------------------------------------------|
| `acelerado run`       | Start the Discord bot (long-running). Wrap in tmux + `while true; do …; sleep 5; done` for resilience. |
| `acelerado status`    | Print token expiry + count of tracked announcements.            |
| `acelerado monitor`   | Open the textual TUI: live token countdown + recent video list. |
| `acelerado audit-members` | Print members in `Registradores` missing the YouTube role. |
| `acelerado refresh-token` | Backup `token.pickle` and re-run the OAuth consent flow.   |

**Deployment:** `tmux new -s acelerado 'while true; do uv run acelerado run; sleep 5; done'`. The bot itself is fail-proof at the per-step level; the outer `while` covers full-process crashes (e.g. login failure with stale token).

## Tests

```sh
uv run pytest
```

The suite is fully offline:
- **`conftest.py`** auto-chdirs each test into a fresh `tmp_path`, clears the `@lru_cache`d `get_env`/`_youtube`/`get_upload_playlist_id` singletons, and sets placeholder env vars — so importing `acelerado.env` or `acelerado.youtube` never blocks on real credentials.
- The **Google YouTube client** is replaced with a chainable `MagicMock` (`_fake_youtube_client` in `test_youtube.py`) that mimics `.channels()/.playlistItems()/.videos().list(...).execute()` shapes from `examples/video.json`. Payloads are built by the `make_video` / `make_playlist_item` fixtures.
- **Discord** is never instantiated. `fake_bot`/`fake_guild` are `MagicMock`s shaped to match only what `AceleradoState` touches (`get_channel`, `get_guild`, `roles`, `channels`, `members`). Channel `.send` and member `.add_roles` are `AsyncMock`s so coroutines can be awaited and asserted.
- **Token files** are written as synthetic `token.pickle` blobs by the `write_token` / `token_future` fixtures. This exercises the naive-UTC → aware-UTC normalization added to `youtube.get_token_expiration_date()`.

### API accuracy note

The token-expiry math used `datetime.now()` (naive local) against `Credentials.expiry` (naive UTC), which silently drifted by the host's timezone offset. `get_token_expiration_date()` now returns an aware UTC datetime and `get_token_time_to_expire()` compares against `datetime.now(UTC)`. Covered by `test_youtube.py::test_expiration_reads_token_file_and_returns_aware_utc` and siblings.

## Conventions / gotchas

- User-facing strings (Discord messages, role names) are in **Portuguese** — keep that when editing.
- Hardcoded role/channel names live in `state.py` (`ROLE_NAME_APOIADORES = "Registradores"`, `CHAT_MSG_ADD = "chat-registradores"`); the YouTube member role is matched by substring `"YouTube Member"`.
- `published.txt` is the source of truth for "already announced". It's seeded on first run from the latest 20 uploads if missing — don't delete it on a live deployment or you'll re-announce.
- The OAuth token must be refreshed periodically; the bot itself only *warns* about expiry, it does not auto-renew the consent flow.
- The YouTube client and upload-playlist ID are lazy-initialized via `@lru_cache` in `youtube.py` — first call triggers OAuth and the channel lookup.
- Slash commands live in `acelerado/slash.py`. `register_commands(tree, guild=...)` is called from `bot.setup_hook` and pushed via `tree.sync(guild=...)` — guild-scoped so changes propagate instantly. To add a new slash command: define it with `@app_commands.command(...)` in `slash.py`, add `tree.add_command(new_cmd, guild=guild)` inside `register_commands`, add a registration test in `tests/test_slash.py`. The bot is otherwise event-driven (no message-prefixed commands).

## Fail-proof contract

Every public coroutine that the tick fans out to **must not raise** — it should either succeed or surface its error through `state.report_error(context, exc)`. The outer `bot.event_loop_task` body has a try/except as a final net, plus a `@event_loop_task.error` hook that restarts the loop if anything still escapes. The `commands.Bot.on_error` override pipes gateway-event errors through the same `report_error` path. CLI's `run` command catches `KeyboardInterrupt` (clean shutdown) and any other `Exception` (logged + non-zero exit).

When you add new logic that runs inside a tick, follow the same pattern: handle expected errors locally, let unexpected ones bubble up to the dispatcher's try/except — never wrap the whole thing in a bare `except` that swallows silently.

## Coverage shape

`acelerado/__init__.py`, `env.py`, `log.py`, `state.py`, and `youtube.py` are at 77–100% (the YouTube OAuth flow is the only meaningful gap). `bot.py` and `tui.py` are at 0% — they're glue against the live Discord runtime / a TTY-bound textual app, neither worth the rigging cost. Coverage goal: keep `state.py` and `youtube.py` above 90%; the rest is best-effort.
