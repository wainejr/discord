import asyncio
from acelerado.log import logger
from acelerado import state,env

import discord as disc
from discord.ext import commands

bot = commands.Bot(command_prefix="/", intents=disc.Intents.default())


@bot.event
async def on_ready():
    global latest_video
    logger.info(f"Logged on as {bot.user}!")
    await bot.change_presence(
        activity=disc.Activity(
            type=disc.ActivityType.watching, name="Waine - Dev do desemepenho"
        )
    )
    logger.info("Updated presence!")

    aero_state = state.AceleradoState(bot)

    while True:
        try:
            synced = await bot.tree.sync()
            synced = []
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Error Syncing commads: {e}")

        try:
            await aero_state.event_loop()
        except BaseException as e:
            logger.error(f"Error on event loop: {e}", exc_info=True)

        await asyncio.sleep(300)


async def amain():
    async with bot:
        await bot.start(env.get_env().DISCORD_TOKEN)


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
