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


@app.command(name="channels")
def channels(
    text_only: Annotated[
        bool,
        typer.Option(
            "--text-only/--all",
            help="Mostra só canais de texto (default) ou todos os tipos.",
        ),
    ] = True,
) -> None:
    """List Discord channels in the configured guild — id + name + category.

    Useful when prepping a `config set` from the CLI (e.g. via SSH) and you
    don't have Discord open. Connects to the gateway, dumps the table, and
    closes — no long-running bot.
    """
    import discord
    from discord.ext import commands

    from acelerado.config import CHANNEL_KEYS, get_settings
    from acelerado.env import get_env

    settings = get_settings()
    bound: dict[int, list[str]] = {}
    for key in CHANNEL_KEYS:
        value = getattr(settings.cfg, key)
        if value:
            bound.setdefault(value, []).append(key)

    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="/", intents=intents)

    @bot.event
    async def on_ready() -> None:
        try:
            guild = bot.get_guild(get_env().DISCORD_GUILD_ID)
            if guild is None:
                logger.error("Guild not found. Check DISCORD_GUILD_ID.")
                return

            table = Table(title=f"Canais em '{guild.name}'")
            table.add_column("Tipo")
            table.add_column("Nome")
            table.add_column("ID", style="dim")
            table.add_column("Categoria", style="dim")
            table.add_column("Bound to", style="cyan")

            channels_iter = sorted(
                guild.channels,
                key=lambda c: (
                    (c.category.position if c.category else -1),
                    getattr(c, "position", 0),
                ),
            )
            for chan in channels_iter:
                if text_only and not isinstance(chan, discord.TextChannel):
                    continue
                bound_keys = ", ".join(bound.get(chan.id, [])) or "—"
                category = chan.category.name if chan.category else "—"
                table.add_row(
                    type(chan).__name__.removesuffix("Channel").lower(),
                    chan.name,
                    str(chan.id),
                    category,
                    bound_keys,
                )
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


@app.command()
def healthcheck(
    max_age: Annotated[
        int | None,
        typer.Option(
            "--max-age",
            help="Idade máxima do último tick em segundos (default: 2× ACELERADO_TICK_SECONDS).",
        ),
    ] = None,
) -> None:
    """Reporta saúde do bot via ``last_tick.txt``. Exit 0 se OK, 1 se stale/missing."""
    from datetime import UTC, datetime

    from acelerado.env import get_env
    from acelerado.state import LAST_TICK_PATH

    if max_age is None:
        max_age = 2 * get_env().ACELERADO_TICK_SECONDS

    if not LAST_TICK_PATH.exists():
        console.print("[red]❌ stale:[/] last_tick.txt não existe (bot nunca rodou um tick)")
        raise typer.Exit(code=1)

    raw = LAST_TICK_PATH.read_text(encoding="utf-8").strip()
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        console.print(f"[red]❌ stale:[/] last_tick.txt corrompido: {raw!r}")
        raise typer.Exit(code=1) from None

    now = datetime.now(last.tzinfo or UTC)
    age = (now - last).total_seconds()
    if age > max_age:
        console.print(f"[red]❌ stale:[/] último tick há [bold]{int(age)}s[/] (limite {max_age}s)")
        raise typer.Exit(code=1)
    console.print(f"[green]✅ ok:[/] último tick há [bold]{int(age)}s[/] (limite {max_age}s)")


config_app = typer.Typer(
    name="config",
    help="Inspect and edit runtime configuration (config.json overlay).",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


@config_app.command("list")
def config_list() -> None:
    """Show every config key with its effective value and origin."""
    from acelerado.config import get_settings

    settings = get_settings()
    table = Table(title="Acelerado config")
    table.add_column("Key")
    table.add_column("Value")
    table.add_column("Origin", style="dim")
    for key in settings.all_keys():
        table.add_row(key, settings.display_value(key), settings.origin(key))
    console.print(table)


@config_app.command("get")
def config_get(key: str) -> None:
    """Print one key's value + origin."""
    from acelerado.config import get_settings
    from acelerado.env import EnvCfg

    if key not in EnvCfg.model_fields:
        console.print(f"[red]Unknown key:[/] {key}")
        raise typer.Exit(code=1)
    settings = get_settings()
    console.print(
        f"[bold]{key}[/] = {settings.display_value(key)} [dim](from {settings.origin(key)})[/]"
    )


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Persist ``key=value`` to config.json (validates type via pydantic)."""
    from acelerado.config import get_settings

    settings = get_settings()
    try:
        coerced = settings.set(key, value)
    except KeyError:
        console.print(f"[red]Unknown key:[/] {key}")
        raise typer.Exit(code=1) from None
    except PermissionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        console.print(f"[red]Validation error:[/]\n{exc}")
        raise typer.Exit(code=1) from None
    console.print(f"[green]✅[/] {key} = {coerced!r} [dim](written to config.json)[/]")


@config_app.command("unset")
def config_unset(key: str) -> None:
    """Remove a key from config.json (falls back to .env / default)."""
    from acelerado.config import get_settings

    settings = get_settings()
    try:
        settings.unset(key)
    except KeyError:
        console.print(f"[red]Unknown key:[/] {key}")
        raise typer.Exit(code=1) from None
    console.print(f"[green]✅[/] {key} unset — now reads from [bold]{settings.origin(key)}[/]")


@config_app.command("edit")
def config_edit() -> None:
    """Open config.json in $EDITOR (defaults to vi); reload after exit."""
    import os
    import subprocess

    from acelerado.config import CONFIG_PATH, reload_settings

    editor = os.environ.get("EDITOR", "vi")
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text("{}\n", encoding="utf-8")
    subprocess.call([editor, str(CONFIG_PATH)])
    reload_settings()
    console.print(f"[green]✅[/] reloaded from {CONFIG_PATH}")


@app.command()
def update() -> None:
    """Pull latest commits and re-sync deps. Exit code 75 on success → wrapper restarts."""
    from acelerado.updater import EXIT_RESTART, apply_updates

    result = apply_updates()

    if result.status == "clean":
        console.print("[yellow]⏸️  Nada pra atualizar[/]")
        return
    if result.status == "ok":
        console.print(
            f"[green]✅ Atualizado pra [bold]{result.short_head}[/bold] "
            f"({len(result.commits)} commits)[/]"
        )
        for line in result.commits[:20]:
            console.print(f"  • {line}")
        console.print(
            f"\n[bold]Saindo com exit {EXIT_RESTART}[/] — wrapper externo deve restartar."
        )
        raise typer.Exit(code=EXIT_RESTART)
    if result.status == "conflict":
        console.print(f"[red]❌ Conflito (working tree não fast-forwardável):[/]\n{result.message}")
        raise typer.Exit(code=1)
    # error
    console.print(f"[red]❌ Falhou:[/] {result.message}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
