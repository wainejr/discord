import discord as disc
from acelerado import env, state
from acelerado.log import logger
from discord.ext import commands

intents = disc.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}.")

    guild = bot.get_guild(env.get_env().DISCORD_GUILD_ID)
    if guild is None:
        print("Server not found. Check your server ID.")
        return

    # Fetch roles
    apoiadores_role = disc.utils.get(guild.roles, name="Registradores")
    youtube_members_role = disc.utils.get(guild.roles, name="YouTube Member")

    if not apoiadores_role or not youtube_members_role:
        print("Roles not found. Check role names.")
        return

    # Find members who are in "Regsitradores" but not in "YouTube Members"
    members_only_in_registradores = [
        member
        for member in guild.members
        if apoiadores_role in member.roles and youtube_members_role not in member.roles
    ]

    print("Members in 'Apoiadores' but not in 'YouTube Members':")
    for member in members_only_in_registradores:
        print(f"{member.name}#{member.discriminator}")

    await bot.close()


bot.run(env.get_env().DISCORD_TOKEN)
