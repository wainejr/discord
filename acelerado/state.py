import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import discord
from discord.ext import commands

from acelerado import metrics, youtube
from acelerado.env import get_env
from acelerado.error_reporter import ErrorReporter
from acelerado.review import parse_username_whitelist
from acelerado.store import LineSetStore

logger = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    """Render a non-negative seconds count as the largest sensible unit (d/h/m)."""
    seconds = abs(int(seconds))
    if seconds >= 86400:
        return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


CHAT_MSG_ADD = "chat-registradores"
ROLE_NAME_APOIADORES = "Registradores"
ROLE_NAME_YT_MEMBER_SUBSTRING = "YouTube Member"
FILENAME_PUBLISHED = Path("published.txt")
LAST_TICK_PATH = Path("last_tick.txt")
LIVE_REMINDERS_PATH = Path("live_reminders.txt")


class AceleradoState:
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.published = LineSetStore(FILENAME_PUBLISHED)
        self.live_reminders = LineSetStore(LIVE_REMINDERS_PATH)
        # "Long enough ago that the first warning isn't rate-limited."
        self.last_msg_expiry = datetime.now(UTC) - timedelta(days=7)
        # Independent throttle for the upcoming-lives poll: search.list
        # costs 100 quota units, so we don't run it on every 5-min tick.
        # ``None`` means "never run" — first tick will fire it.
        self.last_upcoming_lives_check: datetime | None = None
        self.error_reporter = ErrorReporter(lambda: self.channel_log)

        # Channel validation only — cheap cache lookup, no I/O. Network /
        # OAuth-triggering work happens in `warm_up`.
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
        return self.published.read_all()

    async def warm_up(self) -> None:
        """First-run seeding. Called from the bot once the gateway is ready.

        Kept out of ``__init__`` because it makes a YouTube API call (and
        on a fresh deployment will trigger the OAuth browser flow), which
        would otherwise block the gateway-ready callback.
        """
        if not FILENAME_PUBLISHED.exists():
            try:
                latest = youtube.get_last_videos(max_videos=20)
                ids = [youtube.get_video_id(v) for v in latest]
                FILENAME_PUBLISHED.write_text("\n".join(ids))
            except Exception as exc:
                await self.error_reporter.report("warm_up", exc)
                return
        logger.info(f"Videos published on start: {self.videos_pubs}")

    def add_video_published(self, video_id: str) -> None:
        """Append ``video_id`` to ``published.txt``. No-op if already present."""
        self.published.add(video_id)

    def check_videos_to_pub(self) -> list[str]:
        published = self.published.as_set()
        out: list[str] = []
        for v in youtube.get_last_videos(max_videos=10):
            vid = youtube.get_video_id(v)
            if vid not in published:
                out.append(vid)
        return out

    # ------------------------------------------------------------------
    # Announcement
    # ------------------------------------------------------------------

    async def announce_video(self, video_id: str, video: dict) -> None:
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
        # Send first, then record. Recording before send risks marking a
        # video "announced" when Discord rejected the message — the next
        # tick would then skip it forever. The reverse failure (double-post
        # if Discord accepted but we crash before recording) is louder and
        # rarer.
        sent = await channel.send(msg_send)
        self.add_video_published(video_id)
        metrics.increment("videos_announced", context=video_id)

        if get_env().ACELERADO_AUTO_THREAD:
            await self._open_discussion_thread(sent, title)

    async def _open_discussion_thread(self, message: discord.Message, title: str) -> None:
        """Open a thread on the announcement message for discussion.

        Discord caps thread names at 100 chars; we truncate at 90 + "…" to
        leave room for variability. Failures here must NOT prevent the
        announcement itself — they're reported but swallowed.
        """
        thread_name = title if len(title) <= 90 else title[:90] + "…"
        try:
            await message.create_thread(name=thread_name)
        except discord.HTTPException as exc:
            # Forbidden (no perm), NotFound (msg gone), or other HTTP errors
            # are expected and shouldn't bubble. Anything else (programmer
            # error like AttributeError) deliberately escapes — the outer
            # event_loop guard reports it.
            await self.report_error("auto_thread", exc)

    # ------------------------------------------------------------------
    # Token expiry warning (rate-limited, once/hour)
    # ------------------------------------------------------------------

    async def check_expiration(self) -> None:
        # The 1h "access token" expiry is auto-refreshed by google-auth on
        # every call — warning about it is meaningless. The thing that
        # actually requires operator action is the *refresh token*, which
        # Google caps at 7 days for "Testing"-mode OAuth apps. Issuance
        # time is tracked in REFRESH_ISSUED_PATH; TTL comes from config.
        ttl_days = get_env().ACELERADO_REFRESH_TOKEN_TTL_DAYS
        seconds_left = youtube.get_refresh_token_time_to_expire(ttl_days)
        if seconds_left is None or seconds_left >= (3600 * 24):
            return

        diff_last_msg = (datetime.now(UTC) - self.last_msg_expiry).total_seconds()
        if diff_last_msg < 3600:
            return

        self.last_msg_expiry = datetime.now(UTC)
        issued_at = youtube.get_refresh_token_issued_at()
        deadline = issued_at + timedelta(days=ttl_days) if issued_at else None
        deadline_str = deadline.strftime("%Y-%m-%d %H:%M UTC") if deadline else "?"
        if seconds_left < 0:
            head = (
                f"⚠️ Refresh token YouTube **expirou** há "
                f"{_format_duration(-seconds_left)} (em {deadline_str}). "
                "Bot vai falhar na próxima chamada à API."
            )
            log_msg = f"Refresh token expired {int(-seconds_left)}s ago. Renew it."
        else:
            head = (
                f"⚠️ Refresh token YouTube expira em {_format_duration(seconds_left)} "
                f"(em {deadline_str})."
            )
            log_msg = f"Refresh token expires in {int(seconds_left)}s. Renew it."
        hint = "Renove com `/token renew-start` (DM com o link do Google)."
        channel = self.channel_log
        if channel is None:
            logger.warning("Log channel disappeared from cache; skipping warning")
        else:
            await channel.send(f"{head}\n{hint}")
        logger.warning(log_msg)

    # ------------------------------------------------------------------
    # YouTube Member role sync — walks *all* tiers, not just the first.
    # ------------------------------------------------------------------

    async def check_members_apoiadores(self) -> int:
        """Sync YouTube Members → Registradores. Returns count of additions."""
        guild = self.bot.get_guild(get_env().DISCORD_GUILD_ID)
        if guild is None:
            logger.error("Guild not found in cache")
            return 0

        yt_roles = [r for r in guild.roles if ROLE_NAME_YT_MEMBER_SUBSTRING in r.name]
        apoiadores_role = discord.utils.get(guild.roles, name=ROLE_NAME_APOIADORES)
        if not yt_roles or apoiadores_role is None:
            logger.error(
                f"Missing roles: yt_roles={[r.name for r in yt_roles]} "
                f"apoiadores_role={apoiadores_role}"
            )
            return 0

        chat_channel = discord.utils.get(guild.channels, name=CHAT_MSG_ADD)
        whitelist = parse_username_whitelist(get_env().ACELERADO_APOIADORES_WHITELIST)

        # A member may appear in several YT-tier roles; dedupe before iterating.
        seen: set[int] = set()
        added = 0
        for yt_role in yt_roles:
            for member in yt_role.members:
                if member.id in seen:
                    continue
                seen.add(member.id)

                if apoiadores_role in member.roles:
                    continue
                if member.name in whitelist:
                    continue
                await member.add_roles(apoiadores_role)
                added += 1
                if isinstance(chat_channel, discord.abc.Messageable):
                    await chat_channel.send(
                        f"Seja bem vindo aos {ROLE_NAME_APOIADORES}, <@{member.id}>!"
                    )
                logger.info(
                    f"Adding member {member} to {ROLE_NAME_APOIADORES} "
                    f"(source tier: {yt_role.name})!"
                )
        if added > 0:
            metrics.increment("members_synced", value=added)
        return added

    # ------------------------------------------------------------------
    # Error reporting — thin wrapper around ErrorReporter to keep the
    # public API stable for callers (welcome, slash commands, bot.py).
    # ------------------------------------------------------------------

    async def report_error(self, context: str, exc: BaseException) -> None:
        await self.error_reporter.report(context, exc)

    # ------------------------------------------------------------------
    # Upcoming livestream reminders
    # ------------------------------------------------------------------

    @property
    def live_reminders_sent(self) -> set[str]:
        """Already-reminded video IDs from ``live_reminders.txt``."""
        return self.live_reminders.as_set()

    async def _check_upcoming_lives(self) -> None:
        """Send a "live em N min" reminder for any scheduled live within window.

        ``youtube.get_upcoming_livestream_ids`` calls ``search.list``, which
        costs 100 YouTube quota units per request — running it every 5-min
        tick blows past the 10k/day default quota by ~3x. Gate the poll
        behind ``ACELERADO_UPCOMING_LIVES_INTERVAL_SECONDS`` (default 1h)
        so the cheap steps still run on every tick.
        """
        now = datetime.now(UTC)
        interval = timedelta(seconds=get_env().ACELERADO_UPCOMING_LIVES_INTERVAL_SECONDS)
        if (
            self.last_upcoming_lives_check is not None
            and now - self.last_upcoming_lives_check < interval
        ):
            return
        self.last_upcoming_lives_check = now

        window = timedelta(minutes=get_env().ACELERADO_LIVE_REMINDER_MINUTES)
        sent = self.live_reminders.as_set()

        for vid in youtube.get_upcoming_livestream_ids():
            if vid in sent:
                continue
            video = youtube.get_video_info(vid)
            scheduled = youtube.get_scheduled_start_time(video)
            if scheduled is None:
                continue
            time_until = scheduled - now
            if time_until < timedelta(0) or time_until > window:
                continue

            title = youtube.get_video_title(video)
            url = youtube.get_video_url(vid)
            minutes = max(1, int(time_until.total_seconds() / 60))
            msg = f"@everyone 🔔 Live em ~{minutes} min: **{title}**\n{url}"

            channel = self.channel_announce
            if channel is None:
                logger.error("Announce channel disappeared; can't send live reminder")
                return
            await channel.send(msg)
            self.live_reminders.add(vid)
            logger.info(f"Posted live reminder for {vid} ({title})")

    async def _pub_new_videos(self) -> None:
        """Inner video-announcement step — pulled out so event_loop reads linearly."""
        for video_id in self.check_videos_to_pub():
            video = youtube.get_video_info(video_id)
            title = youtube.get_video_title(video)
            if youtube.should_announce_video(video):
                logger.info(f"Announcing video {video_id} - '{title}'!")
                await self.announce_video(video_id, video)
            else:
                logger.info(
                    f"Not announcing video {video_id} - '{title}' yet "
                    f"({youtube.video_state_flags(video)})"
                )

    async def event_loop(self) -> None:
        logger.info("Started event loop...")

        steps = [
            ("apoiadores", self.check_members_apoiadores),
            ("expiration", self.check_expiration),
            ("upcoming_lives", self._check_upcoming_lives),
            ("videos", self._pub_new_videos),
        ]
        for name, step in steps:
            try:
                await step()
            except Exception as exc:
                await self.report_error(name, exc)

        # Mark a successful tick — used by external healthcheck.
        try:
            LAST_TICK_PATH.write_text(datetime.now(UTC).isoformat())
            metrics.mark_tick()
        except Exception:
            logger.exception("Failed to write last_tick / metrics")

        logger.info("Finished event loop!")
