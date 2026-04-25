"""Slash commands registered on the bot's command tree.

All slash commands live here so adding new ones is a one-stop change. The
bot's ``setup_hook`` calls :func:`register_commands` and then
``tree.sync(guild=...)`` (guild-scoped) so changes propagate instantly
during development.

To add a new command:
1. Define it with ``@app_commands.command(...)`` here.
2. Add ``tree.add_command(your_cmd, guild=guild)`` inside
   :func:`register_commands`.
3. Add a registration test in ``tests/test_slash.py``.
"""

import logging
import re

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


# Edit this dict to add/remove links. Keys are display names, values are URLs.
LINKS: dict[str, str] = {
    "YouTube": "https://www.youtube.com/@waine_jr",
    "Discord": "https://discord.gg/RHuhFcfzyV",
    "Instagram": "https://instagram.com/waine_jr",
    "GitHub do Waine": "https://github.com/wainejr",
}


@app_commands.command(
    name="links",
    description="Mostra os links importantes da Comunidade do Desempenho",
)
async def cmd_links(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="🔗 Links do Waine",
        description="Confira os canais oficiais:",
        color=discord.Color.blurple(),
    )
    for name, url in LINKS.items():
        embed.add_field(name=name, value=url, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app_commands.command(
    name="sync",
    description="(admin) Força a sincronização de membros agora",
)
@app_commands.default_permissions(administrator=True)
async def cmd_sync(interaction: discord.Interaction) -> None:
    # Local import to avoid a circular dep with bot.py at module load.
    from acelerado.bot import AceleradoBot

    bot = interaction.client
    if not isinstance(bot, AceleradoBot) or bot.state_handler is None:
        await interaction.response.send_message(
            "⚠️ Bot ainda não terminou o setup; tente novamente em alguns segundos.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        added = await bot.state_handler.check_members_apoiadores()
    except Exception as exc:
        await bot.state_handler.report_error("slash:sync", exc)
        await interaction.followup.send(
            f"❌ Sync falhou: `{type(exc).__name__}: {exc}`",
            ephemeral=True,
        )
        return

    if added == 0:
        msg = "✅ Sync concluído — nenhum membro pendente."
    elif added == 1:
        msg = "✅ Sync concluído — 1 membro adicionado a Registradores."
    else:
        msg = f"✅ Sync concluído — {added} membros adicionados a Registradores."
    await interaction.followup.send(msg, ephemeral=True)


@app_commands.command(
    name="update",
    description="(admin) Pull do código + uv sync; reinicia o bot via wrapper",
)
@app_commands.default_permissions(administrator=True)
async def cmd_update(interaction: discord.Interaction) -> None:
    import asyncio

    from acelerado.updater import EXIT_RESTART, apply_updates

    await interaction.response.defer(ephemeral=True, thinking=True)
    # apply_updates is sync (subprocess), run off the event loop.
    result = await asyncio.to_thread(apply_updates)

    if result.status == "clean":
        await interaction.followup.send("⏸️ Nada pra atualizar.", ephemeral=True)
        return
    if result.status == "conflict":
        await interaction.followup.send(
            f"❌ Conflito impede o pull:\n```\n{result.message[:500]}\n```",
            ephemeral=True,
        )
        return
    if result.status == "error":
        await interaction.followup.send(
            f"❌ Erro: `{result.message[:500]}`",
            ephemeral=True,
        )
        return

    # status == "ok" — schedule restart after the response delivers.
    commits_text = "\n".join(f"• {c}" for c in result.commits[:10])
    if len(result.commits) > 10:
        commits_text += f"\n• … (+{len(result.commits) - 10})"
    await interaction.followup.send(
        f"✅ Atualizado pra `{result.short_head}` ({len(result.commits)} commits)\n"
        f"{commits_text}\n\n"
        f"⚠️ Encerrando com exit {EXIT_RESTART} em 3s — wrapper deve restartar.",
        ephemeral=True,
    )
    asyncio.create_task(_delayed_exit(EXIT_RESTART))


async def _delayed_exit(code: int, delay_seconds: float = 3.0) -> None:
    """Sleep briefly so the followup message ships, then exit hard."""
    import asyncio
    import os

    await asyncio.sleep(delay_seconds)
    logger.warning(f"Exiting with code {code} for wrapper-driven restart")
    os._exit(code)


_MESSAGE_LINK_RE = re.compile(r"https?://(?:\w+\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)")


@app_commands.command(name="report", description="Reportar uma mensagem aos mods")
@app_commands.describe(
    message_link="Link da mensagem (clique-direito → Copy Message Link)",
    reason="Por que essa mensagem é problemática",
)
async def cmd_report(
    interaction: discord.Interaction,
    message_link: str,
    reason: str,
) -> None:
    from typing import cast

    from discord.ext import commands

    from acelerado import moderation

    bot = cast(commands.Bot, interaction.client)

    match = _MESSAGE_LINK_RE.search(message_link.strip())
    if match is None:
        await interaction.response.send_message(
            "⚠️ Link inválido. Clique-direito numa mensagem → 'Copy Message Link'.",
            ephemeral=True,
        )
        return

    _, channel_id, message_id = (int(g) for g in match.groups())

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send("⚠️ Canal não acessível.", ephemeral=True)
            return
        target = await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        await interaction.followup.send(
            f"⚠️ Não foi possível buscar a mensagem: `{type(exc).__name__}`",
            ephemeral=True,
        )
        return

    try:
        result_msg = await moderation.deliver_report(bot, interaction.user, target, reason)
    except moderation.ReportRateLimited:
        result_msg = (
            f"⏸️ Você já usou o limite de {moderation._REPORT_RATE_MAX} reports nos "
            f"últimos {int(moderation._REPORT_RATE_WINDOW / 60)} minutos. Aguarde."
        )
    await interaction.followup.send(result_msg, ephemeral=True)


def register_commands(
    tree: app_commands.CommandTree,
    guild: discord.abc.Snowflake | None = None,
) -> None:
    """Register all slash commands on ``tree``.

    Pass ``guild=`` to scope commands to a single guild (instant sync,
    great for dev). Pass ``None`` to register globally (~1h propagation).
    """
    from acelerado.review import cmd_preview_stale, cmd_preview_summary

    tree.add_command(cmd_links, guild=guild)
    tree.add_command(cmd_sync, guild=guild)
    tree.add_command(cmd_update, guild=guild)
    tree.add_command(cmd_report, guild=guild)
    tree.add_command(cmd_preview_summary, guild=guild)
    tree.add_command(cmd_preview_stale, guild=guild)
