import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import discord
from discord.ext import commands

from acelerado import youtube
from acelerado.env import get_env

logger = logging.getLogger(__name__)

CHAT_MSG_ADD = "chat-registradores"
ROLE_NAME_APOIADORES = "Registradores"
ROLE_NAME_YT_MEMBER_SUBSTRING = "YouTube Member"
FILENAME_PUBLISHED = Path("published.txt")

# How often we're willing to post a "something blew up" report to Discord.
# Local logs are always emitted; this only throttles the remote notification
# so a broken tick doesn't spam the log channel every 5 minutes.
ERROR_REPORT_COOLDOWN = timedelta(minutes=10)


class AceleradoState:
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # "Long enough ago that the first warning isn't rate-limited."
        long_ago = datetime.now() - timedelta(days=7)
        self.last_msg_expiry = long_ago
        self._last_error_report = long_ago

        self._initialize_videos_pubs()
        if self.channel_log is None or self.channel_announce is None:
            raise ValueError(
                f"Unable to get channels log={self.channel_log} announce={self.channel_announce}"
            )

    # ------------------------------------------------------------------
    # Channel lookups (go through the bot cache, so they may return None
    # briefly during startup).
    # ------------------------------------------------------------------

    @property
    def channel_log(self) -> discord.abc.Messageable | None:
        # bot.get_channel returns a broad union; we configure these IDs to
        # always point at sendable channels.
        return cast(
            "discord.abc.Messageable | None",
            self.bot.get_channel(get_env().DISCORD_LOG_CHANNEL_ID),
        )

    @property
    def channel_announce(self) -> discord.abc.Messageable | None:
        return cast(
            "discord.abc.Messageable | None",
            self.bot.get_channel(get_env().DISCORD_ANNOUNCE_CHANNEL_ID),
        )

    # ------------------------------------------------------------------
    # published.txt — source of truth for "already announced".
    # ------------------------------------------------------------------

    @property
    def videos_pubs(self) -> list[str]:
        """Non-empty, stripped IDs from ``published.txt``. Missing file -> []."""
        if not FILENAME_PUBLISHED.exists():
            return []
        return [
            line.strip() for line in FILENAME_PUBLISHED.read_text().splitlines() if line.strip()
        ]

    def _initialize_videos_pubs(self) -> None:
        if not FILENAME_PUBLISHED.exists():
            latest_videos = youtube.get_last_videos(max_videos=20)
            video_ids = [youtube.get_video_id(v) for v in latest_videos]
            FILENAME_PUBLISHED.write_text("\n".join(video_ids))

        logger.info(f"Videos published on start: {self.videos_pubs}")

    def add_video_published(self, video_id: str) -> None:
        """Append ``video_id`` to ``published.txt``. No-op if already present."""
        existing = set(self.videos_pubs)
        if video_id in existing:
            logger.debug(f"Video {video_id} already in published.txt, skipping append")
            return
        # Ensure the file exists — callers shouldn't have to care.
        if not FILENAME_PUBLISHED.exists():
            FILENAME_PUBLISHED.write_text("")
        # Use a leading newline only when the file isn't empty/missing-trailing-nl.
        current = FILENAME_PUBLISHED.read_text()
        prefix = "" if not current or current.endswith("\n") else "\n"
        with FILENAME_PUBLISHED.open("a") as f:
            f.write(f"{prefix}{video_id}\n")

    def check_videos_to_pub(self) -> list[str]:
        published = set(self.videos_pubs)
        return [
            youtube.get_video_id(v)
            for v in youtube.get_last_videos(max_videos=10)
            if youtube.get_video_id(v) not in published
        ]

    # ------------------------------------------------------------------
    # Announcement filtering
    # ------------------------------------------------------------------

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
        channel = self.channel_announce
        if channel is None:
            logger.error("Announce channel disappeared from cache; cannot send")
            return
        await channel.send(msg_send)

    # ------------------------------------------------------------------
    # Token expiry warning (rate-limited, once/hour)
    # ------------------------------------------------------------------

    async def check_expiration(self) -> None:
        expiration_time = youtube.get_token_time_to_expire()
        if expiration_time is None or expiration_time >= (3600 * 24):
            return

        diff_last_msg = (datetime.now() - self.last_msg_expiry).total_seconds()
        if diff_last_msg < 3600:
            return

        self.last_msg_expiry = datetime.now()
        expiry_date = youtube.get_token_expiration_date()
        channel = self.channel_log
        if channel is None:
            logger.warning("Log channel disappeared from cache; skipping warning")
        else:
            await channel.send(
                f"Renew your Token! It will expire in {int(expiration_time)} seconds "
                f"(at {expiry_date})."
            )
        logger.warning(f"Your token will expire in {int(expiration_time)} seconds. Renew it.")

    # ------------------------------------------------------------------
    # YouTube Member role sync — walks *all* tiers, not just the first.
    # ------------------------------------------------------------------

    async def check_members_apoiadores(self) -> None:
        guild = self.bot.get_guild(get_env().DISCORD_GUILD_ID)
        if guild is None:
            logger.error("Guild not found in cache")
            return

        yt_roles = [r for r in guild.roles if ROLE_NAME_YT_MEMBER_SUBSTRING in r.name]
        apoiadores_role = discord.utils.get(guild.roles, name=ROLE_NAME_APOIADORES)
        if not yt_roles or apoiadores_role is None:
            logger.error(
                f"Missing roles: yt_roles={[r.name for r in yt_roles]} "
                f"apoiadores_role={apoiadores_role}"
            )
            return

        chat_channel = discord.utils.get(guild.channels, name=CHAT_MSG_ADD)

        # A member may appear in several YT-tier roles; dedupe before iterating.
        seen: set[int] = set()
        for yt_role in yt_roles:
            for member in yt_role.members:
                if member.id in seen:
                    continue
                seen.add(member.id)

                if apoiadores_role in member.roles:
                    continue
                if member.name == "eniaw":
                    continue
                await member.add_roles(apoiadores_role)
                if isinstance(chat_channel, discord.abc.Messageable):
                    await chat_channel.send(
                        f"Seja bem vindo aos {ROLE_NAME_APOIADORES}, <@{member.id}>!"
                    )
                logger.info(
                    f"Adding member {member} to {ROLE_NAME_APOIADORES} "
                    f"(source tier: {yt_role.name})!"
                )

    # ------------------------------------------------------------------
    # Error reporting — local log + rate-limited Discord notification.
    # ------------------------------------------------------------------

    async def report_error(self, context: str, exc: BaseException) -> None:
        """Log an error locally and, if not rate-limited, post to the log channel.

        ``context`` is a short label for where the error came from so the
        Discord message is readable at a glance.
        """
        logger.exception(f"[{context}] {type(exc).__name__}: {exc}", exc_info=exc)

        now = datetime.now()
        if now - self._last_error_report < ERROR_REPORT_COOLDOWN:
            return
        self._last_error_report = now

        channel = self.channel_log
        if channel is None:
            return

        summary = f"⚠️ Erro em `{context}`: `{type(exc).__name__}: {exc}`"
        # Discord caps messages at 2000 chars; leave headroom.
        if len(summary) > 1900:
            summary = summary[:1900] + "…"
        try:
            await channel.send(summary)
        except Exception:
            # A failing notifier must never bubble up — we already logged locally.
            logger.exception("Failed to deliver error report to Discord log channel")

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _pub_new_videos(self) -> None:
        """Inner video-announcement step — pulled out so event_loop reads linearly."""
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

    async def event_loop(self) -> None:
        logger.info("Started event loop...")

        steps = [
            ("apoiadores", self.check_members_apoiadores),
            ("expiration", self.check_expiration),
            ("videos", self._pub_new_videos),
        ]
        for name, step in steps:
            try:
                await step()
            except Exception as exc:
                await self.report_error(name, exc)

        logger.info("Finished event loop!")
