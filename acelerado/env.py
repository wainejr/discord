"""Schema for all bot configuration.

``EnvCfg`` is the single pydantic-settings model — it reads ``.env`` /
process env. The runtime layering (``config.json`` overrides on top of
this) lives in :mod:`acelerado.config`. Most callers should keep using
:func:`get_env`, which proxies through to the merged ``Settings.cfg``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvCfg(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DISCORD_ANNOUNCE_CHANNEL_ID: int
    DISCORD_LOG_CHANNEL_ID: int
    DISCORD_TOKEN: str
    YOUTUBE_CHANNEL_ID: str
    YOUTUBE_API_KEY: str
    DISCORD_GUILD_ID: int

    # Discord user ID allowed to run sensitive owner-only slash commands
    # (`/token renew-start` etc.). 0 disables them — they refuse with a
    # warning instead of going through. Kept separate from
    # `default_permissions(administrator=True)` because token rotation
    # is a stricter gate than "anyone with Manage Server".
    DISCORD_OWNER_ID: int = 0

    # How often the periodic job runs. 300s is the production default; dropping
    # this in dev lets you exercise the loop faster.
    ACELERADO_TICK_SECONDS: int = 300

    # Whether new-video announcements automatically open a discussion thread.
    ACELERADO_AUTO_THREAD: bool = True

    # Channel ID for ``on_member_join`` welcome messages. If 0/unset, the bot
    # tries to DM the new member (which silently no-ops if DMs are blocked).
    DISCORD_WELCOME_CHANNEL_ID: int = 0

    # Channel ID where /report deliveries go. If 0/unset, /report responds
    # with an "admin not configured" warning.
    DISCORD_MODS_CHANNEL_ID: int = 0

    # Minutes-before-start to send a "live em N min" reminder for scheduled
    # YouTube lives. The reminder fires once per video.
    ACELERADO_LIVE_REMINDER_MINUTES: int = 15

    # How often to poll YouTube for *upcoming* livestreams. This step uses
    # ``search.list`` which costs 100 quota units per call (vs. 1 for the
    # other endpoints we hit), so it's gated independently from the main
    # tick. Default of 3600s = 24 calls/day = 2400 units/day, well within
    # the 10k daily quota even after everything else.
    ACELERADO_UPCOMING_LIVES_INTERVAL_SECONDS: int = 3600

    # Channel ID where weekly summary drafts await human approval before
    # being posted publicly. Same channel works for stale-apoiadores reports
    # if you don't want a separate one.
    DISCORD_REVIEW_CHANNEL_ID: int = 0

    # Whitelist of Discord usernames (NOT IDs — for human-edit convenience)
    # that are exempt from the "stale apoiadores" report. Comma-separated.
    ACELERADO_APOIADORES_WHITELIST: str = "eniaw"

    # ------------------------------------------------------------------
    # Anti-spam (cross-channel) — issue #31
    # Default disabled: opt-in once an admin has watched the alerts and
    # is comfortable with the thresholds.
    # ------------------------------------------------------------------
    ACELERADO_ANTISPAM_ENABLED: bool = False
    # Sliding window in seconds for the cross-channel detector.
    ACELERADO_ANTISPAM_WINDOW_SECONDS: int = 30
    # Number of distinct channels (within the window) that triggers a signal.
    ACELERADO_ANTISPAM_CROSS_CHANNEL_THRESHOLD: int = 3
    # Reaction when a signal fires. ``alert`` only logs; ``delete`` removes
    # cross-posted duplicates; ``timeout`` mutes the user.
    ACELERADO_ANTISPAM_ACTION: str = "alert"
    # Minutes to apply when ``ACELERADO_ANTISPAM_ACTION == "timeout"``.
    ACELERADO_ANTISPAM_TIMEOUT_MINUTES: int = 10
    # Comma-separated channel IDs exempt from cross-channel detection
    # (e.g. cross-post hubs that legitimately mirror announcements).
    ACELERADO_ANTISPAM_CHANNEL_WHITELIST: str = ""
    # Per-user notification cooldown (seconds) so the bot doesn't flood
    # the mods channel with repeated alerts for the same user.
    ACELERADO_ANTISPAM_ALERT_COOLDOWN_SECONDS: int = 600


def get_env() -> EnvCfg:
    """Return the merged :class:`EnvCfg`, with ``config.json`` applied on top.

    Thin wrapper over :func:`acelerado.config.get_settings` kept for
    backward compatibility — every call site does ``get_env().FOO`` and
    we don't want to thrash that whole graph just to add a new layer.
    """
    from acelerado.config import get_settings

    return get_settings().cfg


def _cache_clear() -> None:
    """Compatibility shim for tests that used to call ``get_env.cache_clear()``.

    Delegates to :func:`acelerado.config.reload_settings` so monkeypatched
    env vars or freshly-written ``config.json`` files take effect on the
    next access.
    """
    from acelerado.config import reload_settings

    reload_settings()


# Tests call ``env_mod.get_env.cache_clear()`` to reset state between cases.
# Preserve that surface by attaching a callable attribute to the function
# (mirrors the ``functools.lru_cache`` API the previous version exposed).
get_env.cache_clear = _cache_clear  # type: ignore[attr-defined]
