from dotenv import dotenv_values
from pydantic import BaseModel

_config = dotenv_values(".env")

REQUIRED_KEYS = (
    "DISCORD_ANNOUNCE_CHANNEL_ID",
    "DISCORD_LOG_CHANNEL_ID",
    "DISCORD_TOKEN",
    "YOUTUBE_CHANNEL_ID",
    "YOUTUBE_API_KEY",
    "DISCORD_GUILD_ID",
)
if not all(s in _config for s in REQUIRED_KEYS):
    raise KeyError(
        f"Not all required keys in .env. Keys found {list(_config.keys())}. Keys required {REQUIRED_KEYS}"
    )


class EnvCfg(BaseModel):
    DISCORD_ANNOUNCE_CHANNEL_ID: int
    DISCORD_LOG_CHANNEL_ID: int
    DISCORD_TOKEN: str
    YOUTUBE_CHANNEL_ID: str
    YOUTUBE_API_KEY: str
    DISCORD_GUILD_ID: int


def get_env() -> EnvCfg:
    global _config
    return EnvCfg(
        DISCORD_ANNOUNCE_CHANNEL_ID=_config["DISCORD_ANNOUNCE_CHANNEL_ID"],
        DISCORD_LOG_CHANNEL_ID=_config["DISCORD_LOG_CHANNEL_ID"],
        DISCORD_TOKEN=_config["DISCORD_TOKEN"],
        YOUTUBE_CHANNEL_ID=_config["YOUTUBE_CHANNEL_ID"],
        YOUTUBE_API_KEY=_config["YOUTUBE_API_KEY"],
        DISCORD_GUILD_ID=_config["DISCORD_GUILD_ID"],
    )
