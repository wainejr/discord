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


def register_commands(
    tree: app_commands.CommandTree,
    guild: discord.abc.Snowflake | None = None,
) -> None:
    """Register all slash commands on ``tree``.

    Pass ``guild=`` to scope commands to a single guild (instant sync,
    great for dev). Pass ``None`` to register globally (~1h propagation).
    """
    tree.add_command(cmd_links, guild=guild)
    tree.add_command(cmd_sync, guild=guild)
