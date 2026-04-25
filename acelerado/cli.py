"""Acelerado command-line interface."""

import logging
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from acelerado.log import setup_logging

app = typer.Typer(
    name="acelerado",
    help="Acelerado — Discord bot for the Waine - Dev do Desempenho community.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
logger = logging.getLogger(__name__)

LogLevel = Annotated[
    str,
    typer.Option(
        "--log-level",
        "-l",
        help="Log level for the `acelerado` logger (DEBUG, INFO, WARNING, ERROR).",
        case_sensitive=False,
        envvar="ACELERADO_LOG_LEVEL",
    ),
]


@app.callback()
def _root(log_level: LogLevel = "INFO") -> None:
    setup_logging(log_level)


@app.command()
def run() -> None:
    """Start the Discord bot (long-running)."""
    from acelerado.bot import run_bot

    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested (Ctrl+C)")
    except Exception:
        logger.exception("Bot crashed during startup or runtime")
        raise typer.Exit(code=1) from None


@app.command(name="audit-members")
def audit_members() -> None:
    """List members in 'Registradores' but not in any 'YouTube Member' role."""
    import discord
    from discord.ext import commands

    from acelerado.env import get_env

    ROLE_APOIADORES = "Registradores"
    ROLE_YOUTUBE_MEMBER = "YouTube Member"

    intents = discord.Intents.default()
    intents.members = True
    bot = commands.Bot(command_prefix="/", intents=intents)

    @bot.event
    async def on_ready() -> None:
        try:
            guild = bot.get_guild(get_env().DISCORD_GUILD_ID)
            if guild is None:
                logger.error("Server not found. Check your server ID.")
                return

            apoiadores = discord.utils.get(guild.roles, name=ROLE_APOIADORES)
            yt_members = discord.utils.find(lambda r: ROLE_YOUTUBE_MEMBER in r.name, guild.roles)
            if not apoiadores or not yt_members:
                logger.error("Roles not found. Check role names.")
                return

            offenders = [
                m for m in guild.members if apoiadores in m.roles and yt_members not in m.roles
            ]
            table = Table(title=f"In '{ROLE_APOIADORES}' but not in '{ROLE_YOUTUBE_MEMBER}'")
            table.add_column("Name")
            table.add_column("ID", style="dim")
            for member in offenders:
                table.add_row(member.name, str(member.id))
            console.print(table)
        finally:
            await bot.close()

    bot.run(get_env().DISCORD_TOKEN, log_handler=None)


@app.command(name="refresh-token")
def refresh_token() -> None:
    """Force a fresh YouTube OAuth flow (backs up the existing token)."""
    from acelerado import youtube

    if youtube.TOKEN_PATH.exists():
        backup = Path(f"{youtube.TOKEN_PATH}.old")
        shutil.move(str(youtube.TOKEN_PATH), str(backup))
        console.print(f"Moved existing token to [cyan]{backup}[/]")

    youtube._youtube.cache_clear()
    youtube.get_upload_playlist_id.cache_clear()
    youtube._youtube()
    console.print("[green]Token refreshed.[/]")


@app.command()
def status() -> None:
    """Print YouTube token expiry and published-video count."""
    from acelerado import youtube
    from acelerado.state import FILENAME_PUBLISHED

    expiry = youtube.get_token_expiration_date()
    seconds = youtube.get_token_time_to_expire()
    if expiry is None or seconds is None:
        token_line = "[yellow]No cached token[/]"
    elif seconds <= 0:
        token_line = f"[red bold]EXPIRED[/] at {expiry:%Y-%m-%d %H:%M:%S}"
    else:
        days = int(seconds // 86400)
        token_line = f"[green]expires in {days}d[/] (at {expiry:%Y-%m-%d %H:%M:%S})"

    if FILENAME_PUBLISHED.exists():
        ids = [line for line in FILENAME_PUBLISHED.read_text().splitlines() if line.strip()]
        published_line = f"{len(ids)} published video(s) tracked"
    else:
        published_line = "[yellow]published.txt not initialized[/]"

    console.print(f"YouTube token: {token_line}")
    console.print(f"Announcements: {published_line}")


@app.command()
def monitor() -> None:
    """Launch the live Textual monitor TUI."""
    from acelerado.tui import run_monitor

    run_monitor()


if __name__ == "__main__":
    app()
