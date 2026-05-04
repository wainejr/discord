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


@app_commands.command(
    name="godbolt",
    description="Gera link do Compiler Explorer com seu código",
)
@app_commands.describe(
    language="Linguagem do código",
    code="Código (até ~3000 chars)",
)
@app_commands.choices(
    language=[
        app_commands.Choice(name="C", value="c"),
        app_commands.Choice(name="C++", value="c++"),
        app_commands.Choice(name="Rust", value="rust"),
        app_commands.Choice(name="Zig", value="zig"),
        app_commands.Choice(name="Go", value="go"),
        app_commands.Choice(name="Python", value="python"),
        app_commands.Choice(name="JavaScript", value="javascript"),
        app_commands.Choice(name="Java", value="java"),
        app_commands.Choice(name="Haskell", value="haskell"),
        app_commands.Choice(name="Odin", value="odin"),
    ]
)
async def cmd_godbolt(
    interaction: discord.Interaction,
    language: app_commands.Choice[str],
    code: str,
) -> None:
    from acelerado import godbolt

    try:
        url = godbolt.build_clientstate_url(language.value, code)
    except ValueError as exc:
        await interaction.response.send_message(
            f"⚠️ {exc}. Suportadas: {', '.join(godbolt.supported_keys())}",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"🔗 Compiler Explorer — {language.name}",
        description=f"[Abrir no godbolt.org]({url})",
        color=discord.Color.dark_orange(),
    )
    embed.add_field(name="Snippet", value=f"```{language.value}\n{code[:500]}\n```", inline=False)
    if len(code) > 500:
        embed.set_footer(text=f"(snippet truncado — {len(code)} chars no link)")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app_commands.command(
    name="desafio",
    description="Mostra o desafio de performance ativo do mês",
)
async def cmd_desafio(interaction: discord.Interaction) -> None:
    from datetime import UTC, datetime

    from acelerado.challenges import announce as challenge_announce
    from acelerado.challenges import github as challenge_github
    from acelerado.env import get_env

    cfg = get_env()
    if not cfg.ACELERADO_CHALLENGES_ENABLED:
        await interaction.response.send_message(
            "⚠️ Desafios mensais ainda não estão habilitados neste servidor.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    month = datetime.now(UTC).strftime("%Y-%m")
    try:
        spec = await challenge_github.find_current_spec(
            cfg.ACELERADO_CHALLENGES_REPO,
            month,
        )
    except challenge_github.GitHubError as exc:
        await interaction.followup.send(
            f"⚠️ Não consegui falar com o GitHub: `{exc}`",
            ephemeral=True,
        )
        return

    if spec is None:
        await interaction.followup.send(
            f"📭 Nenhum desafio publicado para **{month}** ainda — fica de olho.",
            ephemeral=True,
        )
        return

    # Submission count is best-effort — a flaky GitHub call shouldn't
    # tank the whole reply. We surface "indisponível" inline instead.
    try:
        open_prs = await challenge_github.count_open_submissions(
            cfg.ACELERADO_CHALLENGES_REPO,
        )
        submissions_line = f"📊 **{open_prs}** submissões abertas"
    except challenge_github.GitHubError:
        submissions_line = "📊 Submissões: indisponível no momento"

    pr_url = f"https://github.com/{cfg.ACELERADO_CHALLENGES_REPO}/pulls"

    embed = discord.Embed(
        title=f"🏁 Desafio de {spec.month} — {spec.title}",
        description=challenge_announce.render_short_status(spec),
        url=spec.site_url,
        color=discord.Color.green(),
    )
    if spec.caps:
        embed.add_field(
            name="Limites",
            value="\n".join(
                f"• {challenge_announce.format_cap(k, v)}" for k, v in spec.caps.items()
            ),
            inline=False,
        )
    embed.add_field(name="Enunciado", value=spec.site_url, inline=False)
    embed.add_field(
        name="Submissões",
        value=f"{submissions_line} — [ver PRs]({pr_url})",
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


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


# ---------------------------------------------------------------------------
# /config — runtime configuration overlay (issue #30)
# ---------------------------------------------------------------------------
#
# Built as an ``app_commands.Group`` so the surface is ``/config list``,
# ``/config set-channel``, etc., instead of ``cmd_config_list`` style. The
# group instance must be re-created per registration call (discord.py
# binds it to a tree at add time and barfs on re-registration), so it
# lives inside :func:`_build_config_group` rather than at module scope.

_CHANNEL_KEY_CHOICES = [
    app_commands.Choice(name="announce", value="DISCORD_ANNOUNCE_CHANNEL_ID"),
    app_commands.Choice(name="log", value="DISCORD_LOG_CHANNEL_ID"),
    app_commands.Choice(name="welcome", value="DISCORD_WELCOME_CHANNEL_ID"),
    app_commands.Choice(name="mods", value="DISCORD_MODS_CHANNEL_ID"),
    app_commands.Choice(name="review", value="DISCORD_REVIEW_CHANNEL_ID"),
    app_commands.Choice(name="challenges", value="DISCORD_CHALLENGES_CHANNEL_ID"),
]

# Non-channel, non-secret editable keys exposed via /config set + unset.
_PLAIN_KEY_CHOICES = [
    app_commands.Choice(name="tick-seconds", value="ACELERADO_TICK_SECONDS"),
    app_commands.Choice(name="auto-thread", value="ACELERADO_AUTO_THREAD"),
    app_commands.Choice(name="live-reminder-min", value="ACELERADO_LIVE_REMINDER_MINUTES"),
    app_commands.Choice(name="apoiadores-whitelist", value="ACELERADO_APOIADORES_WHITELIST"),
    app_commands.Choice(name="challenges-enabled", value="ACELERADO_CHALLENGES_ENABLED"),
    app_commands.Choice(name="challenges-repo", value="ACELERADO_CHALLENGES_REPO"),
]

# Union for /config unset (covers every editable key).
_UNSET_KEY_CHOICES = _CHANNEL_KEY_CHOICES + _PLAIN_KEY_CHOICES


def _build_config_group() -> app_commands.Group:
    """Build a fresh ``/config`` group bound to a single tree."""
    from acelerado.config import get_settings

    group = app_commands.Group(
        name="config",
        description="Inspecionar/editar config runtime do bot",
        default_permissions=discord.Permissions(administrator=True),
    )

    @group.command(name="list", description="Mostra config atual + origem")
    async def cmd_config_list(interaction: discord.Interaction) -> None:
        from acelerado.config import CHANNEL_KEYS

        settings = get_settings()
        embed = discord.Embed(
            title="⚙️ Config atual",
            color=discord.Color.blurple(),
        )
        for key in settings.all_keys():
            # Channel-typed keys: render as <#id> so the ID resolves to a
            # clickable mention; bare ints aren't actionable.
            if key in CHANNEL_KEYS:
                cid = getattr(settings.cfg, key)
                rendered = f"<#{cid}>" if cid else "*(não configurado)*"
            else:
                rendered = f"`{settings.display_value(key)}`"
            embed.add_field(
                name=key,
                value=f"{rendered} *(de {settings.origin(key)})*",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(
        name="set-channel",
        description="Aponta uma config-canal pro canal escolhido (resolve ID automaticamente)",
    )
    @app_commands.describe(key="Qual canal configurar", channel="Canal alvo")
    @app_commands.choices(key=_CHANNEL_KEY_CHOICES)
    async def cmd_config_set_channel(
        interaction: discord.Interaction,
        key: app_commands.Choice[str],
        channel: discord.TextChannel,
    ) -> None:
        try:
            get_settings().set(key.value, channel.id)
        except (KeyError, PermissionError, ValueError) as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ `{key.value}` = <#{channel.id}>", ephemeral=True
        )

    @group.command(
        name="set",
        description="Define uma config não-canal (int, bool, string)",
    )
    @app_commands.describe(key="Qual config", value="Valor (será coerced via pydantic)")
    @app_commands.choices(key=_PLAIN_KEY_CHOICES)
    async def cmd_config_set(
        interaction: discord.Interaction,
        key: app_commands.Choice[str],
        value: str,
    ) -> None:
        try:
            coerced = get_settings().set(key.value, value)
        except (KeyError, PermissionError) as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return
        except ValueError as exc:
            await interaction.response.send_message(
                f"⚠️ Valor inválido para `{key.value}`:\n```\n{str(exc)[:500]}\n```",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"✅ `{key.value}` = `{coerced!r}`", ephemeral=True)

    @group.command(
        name="unset",
        description="Remove um override (volta pro fallback .env / default)",
    )
    @app_commands.choices(key=_UNSET_KEY_CHOICES)
    async def cmd_config_unset(
        interaction: discord.Interaction,
        key: app_commands.Choice[str],
    ) -> None:
        settings = get_settings()
        try:
            settings.unset(key.value)
        except KeyError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ `{key.value}` removido — agora vem de `{settings.origin(key.value)}`",
            ephemeral=True,
        )

    return group


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
    tree.add_command(cmd_godbolt, guild=guild)
    tree.add_command(cmd_desafio, guild=guild)
    tree.add_command(_build_config_group(), guild=guild)
