"""Weekly summary + apoiadores-stale report — both posted to a private
review channel for human approval before any public action.

Design split:
- **Builders** (``build_weekly_summary_text``, ``find_stale_apoiadores``)
  are pure / easy to test offline. They take data and return strings or
  member lists.
- **Posters** (``post_weekly_summary_draft``, ``post_stale_report``)
  are the async coroutines the bot's scheduled tasks call. They build,
  post, and (for the weekly summary) attach a ``WeeklySummaryView`` for
  human approval.

The ``WeeklySummaryView`` is non-persistent (24h timeout); if the bot
restarts mid-review, the buttons go dead — admins can re-trigger via
``/preview-summary``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import cast

import discord
from discord import app_commands, ui
from discord.ext import commands

from acelerado import youtube
from acelerado.env import get_env

logger = logging.getLogger(__name__)

# How far back the weekly summary looks. 7 days, give or take.
SUMMARY_WINDOW = timedelta(days=7)


# ---------------------------------------------------------------------------
# Builders (pure)
# ---------------------------------------------------------------------------


def build_weekly_summary_text(videos: list[dict], window: timedelta = SUMMARY_WINDOW) -> str:
    """Render a Markdown summary of videos published in the last ``window``.

    ``videos`` is a list of YouTube ``videos().list``-shaped dicts
    (snippet + statistics expected). The function is pure — pass real
    data or fixtures.
    """
    cutoff = datetime.now(UTC) - window

    def _parse_published(video: dict) -> datetime | None:
        raw = video.get("snippet", {}).get("publishedAt")
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    in_window: list[tuple[datetime, dict]] = []
    for v in videos:
        when = _parse_published(v)
        if when is not None and when >= cutoff:
            in_window.append((when, v))
    in_window.sort(key=lambda pair: pair[0], reverse=True)

    if not in_window:
        return "## 📅 Resumo da semana\n_Nenhum vídeo novo publicado nos últimos 7 dias._\n"

    lines = ["## 📅 Resumo da semana", f"**{len(in_window)} vídeos novos:**", ""]
    for when, video in in_window:
        title = video.get("snippet", {}).get("title", "<sem título>")
        vid_id = video.get("id") or video.get("snippet", {}).get("resourceId", {}).get("videoId")
        url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""
        lines.append(f"- **{title}** ({when.strftime('%a %d/%m')}) — {url}")

    # Top by views (only if statistics are present)
    with_stats = [(v, int(v.get("statistics", {}).get("viewCount", 0))) for _, v in in_window]
    with_stats = [(v, n) for v, n in with_stats if n > 0]
    if with_stats:
        with_stats.sort(key=lambda pair: pair[1], reverse=True)
        top_video, top_views = with_stats[0]
        top_title = top_video.get("snippet", {}).get("title", "<sem título>")
        lines.append("")
        lines.append(f"**🏆 Top da semana:** {top_title} ({top_views:,} views)")

    return "\n".join(lines)


def parse_username_whitelist(value: str) -> set[str]:
    """Parse ``ACELERADO_APOIADORES_WHITELIST`` (comma-separated names) → set."""
    return {item.strip() for item in value.split(",") if item.strip()}


def find_stale_apoiadores(guild: discord.Guild) -> list[discord.Member]:
    """Members holding ``Registradores`` but no role containing 'YouTube Member'.

    Whitelisted usernames (env: ``ACELERADO_APOIADORES_WHITELIST``) are
    excluded.
    """
    apoiadores = discord.utils.get(guild.roles, name="Registradores")
    if apoiadores is None:
        return []

    whitelist = parse_username_whitelist(get_env().ACELERADO_APOIADORES_WHITELIST)

    def _has_yt_role(member: discord.Member) -> bool:
        return any("YouTube Member" in r.name for r in member.roles)

    return [m for m in apoiadores.members if not _has_yt_role(m) and m.name not in whitelist]


def format_stale_report(members: list[discord.Member]) -> str:
    """Render the stale-apoiadores list for posting to mods."""
    if not members:
        return "✅ Nenhum apoiador stale essa semana."

    lines = [
        f"## 🩹 Apoiadores stale ({len(members)})",
        "Membros com cargo `Registradores` mas sem cargo `YouTube Member`:",
        "",
    ]
    for m in members:
        lines.append(f"- {m.mention} (`{m.name}`, id `{m.id}`)")
    lines.append("")
    lines.append("_Decisão de remover o cargo permanece manual._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Approval View
# ---------------------------------------------------------------------------


class _EditModal(ui.Modal, title="Editar resumo"):
    new_text: ui.TextInput = ui.TextInput(
        label="Texto",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=3500,
    )

    def __init__(self, parent: WeeklySummaryView) -> None:
        super().__init__()
        self.parent = parent
        self.new_text.default = parent.draft_text

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.parent.draft_text = self.new_text.value
        # Update the original message to show the edited draft.
        if interaction.message is not None:
            await interaction.message.edit(content=self.new_text.value, view=self.parent)
        await interaction.response.defer()


class WeeklySummaryView(ui.View):
    """Three-button view shown alongside the draft summary."""

    def __init__(self, draft_text: str, announce_channel_id: int) -> None:
        super().__init__(timeout=24 * 60 * 60)  # 24h
        self.draft_text = draft_text
        self.announce_channel_id = announce_channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only mods (manage_messages) can act. discord.py auto-replies if False.
        if isinstance(interaction.user, discord.Member):
            if interaction.user.guild_permissions.manage_messages:
                return True
        await interaction.response.send_message(
            "⚠️ Apenas mods podem decidir sobre essa proposta.",
            ephemeral=True,
        )
        return False

    @ui.button(label="✅ Aprovar e postar", style=discord.ButtonStyle.success)
    async def approve(
        self,
        interaction: discord.Interaction,
        _button: ui.Button,
    ) -> None:
        bot = cast(commands.Bot, interaction.client)
        announce_channel = bot.get_channel(self.announce_channel_id)
        if not isinstance(announce_channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "⚠️ Canal de anúncios não acessível.", ephemeral=True
            )
            return
        await announce_channel.send(self.draft_text)
        if interaction.message is not None:
            await interaction.message.edit(content=f"✅ APROVADO\n\n{self.draft_text}", view=None)
        await interaction.response.send_message("Postado!", ephemeral=True)
        self.stop()

    @ui.button(label="✏️ Editar", style=discord.ButtonStyle.primary)
    async def edit(
        self,
        interaction: discord.Interaction,
        _button: ui.Button,
    ) -> None:
        await interaction.response.send_modal(_EditModal(self))

    @ui.button(label="🚫 Descartar", style=discord.ButtonStyle.danger)
    async def discard(
        self,
        interaction: discord.Interaction,
        _button: ui.Button,
    ) -> None:
        if interaction.message is not None:
            await interaction.message.edit(content=f"🚫 DESCARTADO\n\n{self.draft_text}", view=None)
        await interaction.response.send_message("Descartado.", ephemeral=True)
        self.stop()


# ---------------------------------------------------------------------------
# Async posters (called from scheduled tasks + admin slashes)
# ---------------------------------------------------------------------------


async def post_weekly_summary_draft(bot: commands.Bot) -> str:
    """Post the weekly summary draft to ``DISCORD_REVIEW_CHANNEL_ID``.

    Returns a short status string for ephemeral feedback.
    """
    cfg = get_env()
    if not cfg.DISCORD_REVIEW_CHANNEL_ID:
        return "⚠️ DISCORD_REVIEW_CHANNEL_ID não configurado."
    review_channel = bot.get_channel(cfg.DISCORD_REVIEW_CHANNEL_ID)
    if not isinstance(review_channel, discord.abc.Messageable):
        return "⚠️ Canal de review não acessível."

    items = youtube.get_last_videos(max_videos=20)
    # Convert playlistItem-shaped dicts into video-shaped (we need the videoId
    # to fetch the full info incl. statistics).
    full_videos: list[dict] = []
    for item in items:
        vid = youtube.get_video_id(item)
        try:
            full_videos.append(youtube.get_video_info(vid))
        except Exception as exc:
            logger.warning(f"Could not fetch video {vid} for summary: {exc}")

    draft = build_weekly_summary_text(full_videos)
    view = WeeklySummaryView(draft, cfg.DISCORD_ANNOUNCE_CHANNEL_ID)
    await review_channel.send(content=draft, view=view)
    return "✅ Rascunho postado no canal de review."


async def post_stale_report(bot: commands.Bot) -> str:
    """Post the stale-apoiadores list to ``DISCORD_MODS_CHANNEL_ID``."""
    cfg = get_env()
    target_id = cfg.DISCORD_MODS_CHANNEL_ID or cfg.DISCORD_REVIEW_CHANNEL_ID
    if not target_id:
        return "⚠️ Sem canal de mods/review configurado."

    target = bot.get_channel(target_id)
    if not isinstance(target, discord.abc.Messageable):
        return "⚠️ Canal de mods não acessível."

    guild = bot.get_guild(cfg.DISCORD_GUILD_ID)
    if guild is None:
        return "⚠️ Guild não encontrada no cache."

    stale = find_stale_apoiadores(guild)
    await target.send(format_stale_report(stale))
    return f"✅ Relatório postado: {len(stale)} stale."


# ---------------------------------------------------------------------------
# Admin slash commands — manual trigger
# ---------------------------------------------------------------------------


@app_commands.command(
    name="preview-summary",
    description="(admin) Posta o rascunho do resumo semanal no canal de review",
)
@app_commands.default_permissions(administrator=True)
async def cmd_preview_summary(interaction: discord.Interaction) -> None:
    bot = cast(commands.Bot, interaction.client)
    await interaction.response.defer(ephemeral=True, thinking=True)
    msg = await post_weekly_summary_draft(bot)
    await interaction.followup.send(msg, ephemeral=True)


@app_commands.command(
    name="preview-stale",
    description="(admin) Posta o relatório de apoiadores stale agora",
)
@app_commands.default_permissions(administrator=True)
async def cmd_preview_stale(interaction: discord.Interaction) -> None:
    bot = cast(commands.Bot, interaction.client)
    await interaction.response.defer(ephemeral=True, thinking=True)
    msg = await post_stale_report(bot)
    await interaction.followup.send(msg, ephemeral=True)
