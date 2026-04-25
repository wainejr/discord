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


@lru_cache(maxsize=1)
def get_env() -> EnvCfg:
    return EnvCfg()
