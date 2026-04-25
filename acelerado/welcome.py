"""Welcome message handling for ``on_member_join``.

Pure helpers (load, render, pick) are easy to unit-test. ``handle_join``
is the only async piece — the bot's listener calls it and routes any
escape through ``state.report_error("welcome", exc)``.

Templates live in ``templates/welcome_messages.txt``: one line per
saudação, ``#`` lines are comments. Placeholders supported:

- ``{member}`` — mention (e.g. ``<@123>``)
- ``{guild}`` — guild name
- ``{channel_youtube}`` — canonical YouTube URL of the channel
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import discord
from discord.ext import commands

from acelerado.env import get_env

logger = logging.getLogger(__name__)

WELCOME_TEMPLATE_PATH = Path("templates/welcome_messages.txt")
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@waine_jr"

DEFAULT_WELCOME = (
    "Bem-vindo(a), {member}! Dá uma passada nas regras do servidor "
    "e fique à vontade para se apresentar."
)


def load_welcome_messages(path: Path | None = None) -> list[str]:
    """Read the template file, stripping blanks and ``#`` comments.

    Returns ``[DEFAULT_WELCOME]`` if the file is missing or contains no
    non-comment lines — callers never need to handle empty pools.
    """
    path = path or WELCOME_TEMPLATE_PATH
    if not path.exists():
        return [DEFAULT_WELCOME]

    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines or [DEFAULT_WELCOME]


def render_welcome(template: str, member: discord.Member, guild: discord.Guild | None) -> str:
    return template.format(
        member=member.mention,
        guild=guild.name if guild is not None else "servidor",
        channel_youtube=YOUTUBE_CHANNEL_URL,
    )


def pick_welcome(
    member: discord.Member,
    guild: discord.Guild | None,
    *,
    pool: list[str] | None = None,
    rng: random.Random | None = None,
) -> str:
    """Pick a random welcome and render it for ``member``.

    Pass ``rng=`` (a seeded ``random.Random``) for deterministic tests.
    """
    pool = pool if pool is not None else load_welcome_messages()
    chooser = rng or random
    template = chooser.choice(pool)
    return render_welcome(template, member, guild)


async def handle_join(bot: commands.Bot, member: discord.Member) -> None:
    """Send a welcome message: configured channel first, fall back to DM.

    Raises on unexpected failure; the caller (bot.on_member_join) wraps
    with ``state.report_error("welcome", exc)``. ``discord.Forbidden``
    on DM is treated as expected and silently logged — many users have
    DMs blocked and that's fine.
    """
    if member.bot:
        return  # don't welcome other bots

    msg = pick_welcome(member, member.guild)

    welcome_channel_id = get_env().DISCORD_WELCOME_CHANNEL_ID
    if welcome_channel_id:
        channel = bot.get_channel(welcome_channel_id)
        if isinstance(channel, discord.abc.Messageable):
            await channel.send(msg)
            return
        logger.warning(
            f"DISCORD_WELCOME_CHANNEL_ID={welcome_channel_id} "
            f"is not a sendable channel; falling back to DM"
        )

    # Fallback: DM. Forbidden = user blocked DMs — expected, not an error.
    try:
        await member.send(msg)
    except discord.Forbidden:
        logger.info(f"Cannot DM welcome to {member} — DMs blocked")
