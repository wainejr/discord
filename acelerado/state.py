import logging
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord.ext import commands

from acelerado import youtube
from acelerado.env import get_env

logger = logging.getLogger(__name__)

CHAT_MSG_ADD = "chat-registradores"
ROLE_NAME_APOIADORES = "Registradores"
FILENAME_PUBLISHED = Path("published.txt")


class AceleradoState:
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.last_msg_expiry = datetime.now() - timedelta(days=7)

        self._initialize_videos_pubs()
        if self.channel_log is None or self.channel_announce is None:
            raise ValueError(
                f"Unable to get channels log={self.channel_log} announce={self.channel_announce}"
            )

    @property
    def channel_log(self) -> discord.abc.Messageable | None:
        return self.bot.get_channel(get_env().DISCORD_LOG_CHANNEL_ID)

    @property
    def channel_announce(self) -> discord.abc.Messageable | None:
        return self.bot.get_channel(get_env().DISCORD_ANNOUNCE_CHANNEL_ID)

    @property
    def videos_pubs(self) -> list[str]:
        if not FILENAME_PUBLISHED.exists():
            raise FileNotFoundError(f"File {FILENAME_PUBLISHED} not found")
        return FILENAME_PUBLISHED.read_text().split("\n")

    def _initialize_videos_pubs(self) -> None:
        if not FILENAME_PUBLISHED.exists():
            latest_videos = youtube.get_last_videos(max_videos=20)
            video_ids = [youtube.get_video_id(v) for v in latest_videos]
            FILENAME_PUBLISHED.write_text("\n".join(video_ids))

        logger.info(f"Videos published on start: {self.videos_pubs}")

    def add_video_published(self, video_id: str) -> None:
        if not FILENAME_PUBLISHED.exists():
            raise FileNotFoundError(f"File {FILENAME_PUBLISHED} not found")
        with FILENAME_PUBLISHED.open("a") as f:
            f.write(f"\n{video_id}")

    def check_videos_to_pub(self) -> list[str]:
        published = set(self.videos_pubs)
        return [
            youtube.get_video_id(v)
            for v in youtube.get_last_videos(max_videos=10)
            if youtube.get_video_id(v) not in published
        ]

    def should_announce_video(self, video: dict) -> bool:
        if youtube.is_non_listed(video):
            return False
        if not youtube.is_processed(video) and not youtube.is_livestream(video):
            return False
        if youtube.is_vertical(video):
            return False
        return True

    def get_video_state(self, video: dict) -> dict:
        return {
            "non-listed": youtube.is_non_listed(video),
            "is-processed": youtube.is_processed(video),
            "is-livestream": youtube.is_livestream(video),
            "is-vertical": youtube.is_vertical(video),
        }

    async def announce_video(self, video_id: str, video: dict) -> None:
        self.add_video_published(video_id)
        if youtube.is_livestream(video):
            msg = "Estamos em live!"
        elif youtube.is_members_only(video):
            msg = "Vídeo novo pra membros!"
        else:
            msg = "Vídeo novo no canal!"
        title = youtube.get_video_title(video)
        url = youtube.get_video_url(video_id)
        msg_send = f"@everyone {msg} **{title}**\n{url}"
        logger.info(f"Sending message: {msg_send}")
        await self.channel_announce.send(msg_send)

    async def check_expiration(self) -> None:
        expiration_time = youtube.get_token_time_to_expire()
        # Only warn when under 1 day remaining
        if expiration_time is None or expiration_time >= (3600 * 24):
            return

        # Rate-limit warnings to once per hour
        diff_last_msg = (datetime.now() - self.last_msg_expiry).total_seconds()
        if diff_last_msg < 3600:
            return

        self.last_msg_expiry = datetime.now()
        expiry_date = youtube.get_token_expiration_date()
        await self.channel_log.send(
            f"Renew your Token! It will expire in {int(expiration_time)} seconds "
            f"(at {expiry_date})."
        )
        logger.warning(f"Your token will expire in {int(expiration_time)} seconds. Renew it.")

    async def check_members_apoiadores(self) -> None:
        guild = self.bot.get_guild(get_env().DISCORD_GUILD_ID)
        if guild is None:
            logger.error("Guild not found in cache")
            return

        yt_role = discord.utils.find(lambda r: "YouTube Member" in r.name, guild.roles)
        apoiadores_role = discord.utils.get(guild.roles, name=ROLE_NAME_APOIADORES)
        if yt_role is None or apoiadores_role is None:
            logger.error(f"Missing roles: yt_role={yt_role} apoiadores_role={apoiadores_role}")
            return

        chat_channel = discord.utils.get(guild.channels, name=CHAT_MSG_ADD)

        for member in yt_role.members:
            if apoiadores_role in member.roles:
                continue
            if member.name == "eniaw":
                continue
            await member.add_roles(apoiadores_role)
            if chat_channel is not None:
                await chat_channel.send(
                    f"Seja bem vindo aos {ROLE_NAME_APOIADORES}, <@{member.id}>!"
                )
            logger.info(f"Adding member {member} to {ROLE_NAME_APOIADORES}!")

    async def event_loop(self) -> None:
        logger.info("Started event loop...")
        try:
            await self.check_members_apoiadores()
        except Exception:
            logger.exception("Error checking apoiadores")

        try:
            await self.check_expiration()
        except Exception:
            logger.exception("Error checking expiration")

        try:
            for video_id in self.check_videos_to_pub():
                video = youtube.get_video_info(video_id)
                title = youtube.get_video_title(video)
                if self.should_announce_video(video):
                    logger.info(f"Announcing video {video_id} - '{title}'!")
                    await self.announce_video(video_id, video)
                else:
                    logger.info(
                        f"Not announcing video {video_id} - '{title}' yet "
                        f"({self.get_video_state(video)})"
                    )
        except Exception:
            logger.exception("Error on announcing videos")
        logger.info("Finished event loop!")
