import asyncio

from dotenv import dotenv_values
from googleapiclient.discovery import build

import discord as disc
from discord.ext import commands

config = dotenv_values(".env")
required_keys = (
    "DISCORD_CHANNEL_ID",
    "YOUTUBE_CHANNEL_ID",
    "DISCORD_TOKEN",
    "YOUTUBE_API_KEY",
)
if not all(s in config for s in required_keys):
    raise KeyError(
        f"Not all required keys in .env. Keys found {list(config.keys())}. Keys required {required_keys}"
    )

bot = commands.Bot(command_prefix="/", intents=disc.Intents.default())

# Configurações do bot
DISCORD_CHANNEL_ID = config["DISCORD_CHANNEL_ID"]

# Configuração da API do YouTube
youtube = build("youtube", "v3", developerKey=config["YOUTUBE_API_KEY"])


# Função para obter o último vídeo do canal do YouTube
async def get_latest_video():
    request = youtube.search().list(
        part="snippet",
        channelId=config["YOUTUBE_CHANNEL_ID"],
        maxResults=1,
        order="date",
    )
    response = request.execute()
    if "items" in response and response["items"]:
        return response["items"][0]
    return None


@bot.event
async def on_ready():
    print(f"Logged on as {bot.user}!")
    await bot.change_presence(
        activity=disc.Activity(
            type=disc.ActivityType.watching, name="Waine - Dev do desemepenho"
        )
    )

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        await check_new_videos()

    except Exception as e:
        print(f"Error Syncing commads: {e}")


async def check_new_videos():
    latest_video_id = None
    while True:
        video = await get_latest_video()
        if video:
            video_id = video["id"]["videoId"]
            # Trecho Abaixo usado para testar
            # if(latest_video_id == None):
            #    latest_video_id = video_id
            #    video_title = video['snippet']['title']
            #    video_url = f'https://www.youtube.com/watch?v={video_id}'
            #    channel = bot.get_channel(DISCORD_CHANNEL_ID)
            #    await channel.send(f'Novo vídeo: **{video_title}**\n{video_url}')
            #
            if video_id != latest_video_id:
                latest_video_id = video_id
                video_title = video["snippet"]["title"]
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                channel = bot.get_channel(DISCORD_CHANNEL_ID)
                await channel.send(f"Novo vídeo: **{video_title}**\n{video_url}")
        await asyncio.sleep(300)


async def amain():
    async with bot:
        await bot.start(config["DISCORD_TOKEN"])


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()