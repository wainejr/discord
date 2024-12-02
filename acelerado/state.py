import pathlib
from datetime import datetime, timedelta

from acelerado import env, log, youtube
from discord.ext import commands


class AceleradoState:
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Set last message as long time ago
        self.last_msg_expiry = datetime.now() - timedelta(days=7)

        self.initialize_videos_pubs()
        if self.channel_log is None or self.channel_announce is None:
            raise ValueError(
                f"Unable to get channels log={self.channel_log} announce={self.channel_announce}"
            )

    @property
    def channel_log(self):
        return self.bot.get_channel(env.get_env().DISCORD_LOG_CHANNEL_ID)

    @property
    def channel_announce(self):
        return self.bot.get_channel(env.get_env().DISCORD_ANNOUNCE_CHANNEL_ID)

    @property
    def videos_pubs(self) -> list[str]:
        filename = pathlib.Path("published.txt")
        if not filename.exists():
            raise FileNotFoundError(f"File {filename} not found")
        with open(filename, "r") as f:
            return f.read().split("\n")

    def initialize_videos_pubs(self):
        filename = pathlib.Path("published.txt")
        if not filename.exists():
            latest_videos = youtube.get_last_videos(max_videos=20)
            videos_pubs = list()
            for video in latest_videos:
                video_id = youtube.get_video_id(video)
                videos_pubs.append(video_id)
            with open(filename, "w") as f:
                f.write("\n".join(list(videos_pubs)))

        log.logger.info(f"Videos published on start: {list(self.videos_pubs)}")

    def add_video_published(self, v_id: str):
        filename = pathlib.Path("published.txt")
        if not filename.exists():
            raise FileNotFoundError(f"File {filename} not found")
        with open(filename, "a") as f:
            f.write(f"\n{v_id}")

    def check_videos_to_pub(self) -> list[str]:
        latest_videos = youtube.get_last_videos(max_videos=10)
        return [
            youtube.get_video_id(v)
            for v in latest_videos
            if youtube.get_video_id(v) not in self.videos_pubs
        ]

    def should_announce_video(self, video: dict) -> bool:
        if (
            youtube.is_non_listed(video)
            or (not youtube.is_processed(video) and not youtube.is_livestream(video))
            or youtube.is_vertical(video)
        ):
            return False
        return True

    def get_video_state(self, video: dict) -> dict:
        return {
            "non-listed": youtube.is_non_listed(video),
            "is-processed": youtube.is_processed(video),
            "is-livestream": youtube.is_livestream(video),
            "is-vertical": youtube.is_vertical(video),
        }

    async def announce_video(self, v_id: str, video: dict):
        self.add_video_published(v_id)
        msg = "Vídeo novo no canal!"
        if youtube.is_livestream(video):
            msg = "Estamos em live!"
        elif youtube.is_members_only(video):
            msg = "Vídeo novo pra membros!"
        msg_send = f"@everyone {msg} **{youtube.get_video_title(video)}**\n{youtube.get_video_url(v_id)}"
        log.logger.info(f"Sending message: {msg_send}")
        return
        await self.channel_announce.send(msg_send)

    async def check_expiration(self):
        expiration_time = youtube.get_token_time_to_expire()
        # More than 1 day to expiry
        if expiration_time is not None and expiration_time < (3600 * 24):
            return

        diff_last_msg = (datetime.now() - self.last_msg_expiry).total_seconds()
        if diff_last_msg < 3600:
            return

        self.last_msg_expiry = datetime.now()
        await self.channel_log.send(
            f"Renew your Token! It will expire in {int(expiration_time)} seconds (at {youtube.get_token_expiration_date()})."
        )
        log.logger.warn(
            f"Your token will expire in {int(expiration_time)} seconds. Renew it."
        )

    async def check_members_apoiadores(self):
        guild = self.bot.get_guild(env.get_env().DISCORD_GUILD_ID)
        roles = guild.roles
        yt_role = next(r for r in roles if r.name == "YouTube Member")
        apoiadores_role = next(r for r in roles if r.name == "Apoiadores")

        for member in yt_role.members:
            if apoiadores_role not in member.roles:
                channel = next(c for c in guild.channels if c.name == "chat-exclusivo")
                if member.name == "eniaw":
                    continue
                await member.add_roles(apoiadores_role)
                await channel.send(f"Seja bem vindo aos apoiadores, <@{member.id}>!")
                log.logger.info(f"Adding member {member} to Apoiadores!")

    async def event_loop(self):
        log.logger.info("Started event loop...")
        try:
            await self.check_members_apoiadores()
        except BaseException as e:
            log.logger.error("Error checking apoiadores", exc_info=True)

        try:
            await self.check_expiration()
        except BaseException as e:
            log.logger.error("Error cheking expiration", exc_info=True)

        try:
            for video_id in self.check_videos_to_pub():
                video = youtube.get_video_info(video_id)
                if self.should_announce_video(video):
                    log.logger.info(
                        f"Announcing video {video_id} - '{youtube.get_video_title(video)}'!"
                    )
                    await self.announce_video(video_id, video)
                else:
                    log.logger.info(
                        f"Not announcing video {video_id} - '{youtube.get_video_title(video)}' yet ({self.get_video_state(video)})"
                    )
        except BaseException as e:
            log.logger.error(f"Error on announcing videos. {e}", exc_info=True)
        log.logger.info("Finished event loop!")
