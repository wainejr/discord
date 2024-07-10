from datetime import datetime, timedelta
from acelerado import youtube, log, env

from discord.ext import commands


class AceleradoState:
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.videos_pubs: set[str] = set()
        # Set last message as long time ago
        self.last_msg_expiry = datetime.now() - timedelta(days=7)

        self.initialize_videos_pubs()
        if(self.channel_log is None or self.channel_announce is None):
            raise ValueError(f"Unable to get channels log={self.channel_log} announce={self.channel_announce}")

    @property
    def channel_log(self):
        return self.bot.get_channel(env.get_env().DISCORD_LOG_CHANNEL_ID)

    @property
    def channel_announce(self):
        return self.bot.get_channel(env.get_env().DISCORD_ANNOUNCE_CHANNEL_ID)

    def initialize_videos_pubs(self):
        latest_videos = youtube.get_last_videos(max_videos=20)
        for video in latest_videos:
            video_id = youtube.get_video_id(video)
            self.videos_pubs.add(video_id)
        log.logger.info(f"Videos published on start: {list(self.videos_pubs)}")

    def check_videos_to_pub(self) -> list[dict]:
        latest_videos = youtube.get_last_videos(max_videos=10)
        return [
            v for v in latest_videos if youtube.get_video_id(v) not in self.videos_pubs
        ]

    def should_announce_video(self, video: dict) -> bool:
        if not youtube.is_non_listed(video) or not youtube.is_processed(video):
            return False
        return True

    def announce_video(self, video: dict):
        self.videos_pubs.add(youtube.get_video_id(video))
        msg = "Vídeo novo no canal!"
        if youtube.is_livestream(video):
            msg = "Estamos em live!"
        elif youtube.is_members_only(video):
            msg = "Vídeo novo pra membros!"
        msg_send = f"@everyone {msg} **{youtube.get_video_title(video)}**\n{youtube.get_video_url(video)}"
        self.channel_announce.send(msg_send)
        log.logger.info(f"Sent message: {msg_send}")

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
        log.logger.warn(f"Your token will expire in {int(expiration_time)} seconds. Renew it.")

    async def event_loop(self):
        try:
            await self.check_expiration()
        except BaseException as e:
            log.logger.error("Error cheking expiration", exc_info=True)

        try:
            for v in self.check_videos_to_pub():
                if(self.should_announce_video(v)):
                    self.announce_video(v)
        except BaseException as e:
            log.logger.error(f"Error on announcing videos. {e}", exc_info=True)
