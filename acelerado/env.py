from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvCfg(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DISCORD_ANNOUNCE_CHANNEL_ID: int
    DISCORD_LOG_CHANNEL_ID: int
    DISCORD_TOKEN: str
    YOUTUBE_CHANNEL_ID: str
    YOUTUBE_API_KEY: str
    DISCORD_GUILD_ID: int

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

    # Channel ID where weekly summary drafts await human approval before
    # being posted publicly. Same channel works for stale-apoiadores reports
    # if you don't want a separate one.
    DISCORD_REVIEW_CHANNEL_ID: int = 0

    # Whitelist of Discord usernames (NOT IDs — for human-edit convenience)
    # that are exempt from the "stale apoiadores" report. Comma-separated.
    ACELERADO_APOIADORES_WHITELIST: str = "eniaw"


@lru_cache(maxsize=1)
def get_env() -> EnvCfg:
    return EnvCfg()
