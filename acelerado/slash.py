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
    description="Mostra os links importantes da comunidade do Waine",
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


def register_commands(
    tree: app_commands.CommandTree,
    guild: discord.abc.Snowflake | None = None,
) -> None:
    """Register all slash commands on ``tree``.

    Pass ``guild=`` to scope commands to a single guild (instant sync,
    great for dev). Pass ``None`` to register globally (~1h propagation).
    """
    tree.add_command(cmd_links, guild=guild)
