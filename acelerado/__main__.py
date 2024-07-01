import asyncio
from acelerado.log import logger
import os
import pickle
import json

from dotenv import dotenv_values
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import discord as disc
from discord.ext import commands

config = dotenv_values(".env")
required_keys = (
    "DISCORD_CHANNEL_ID",
    "YOUTUBE_CHANNEL_ID",
    "DISCORD_TOKEN",
)
if not all(s in config for s in required_keys):
    raise KeyError(
        f"Not all required keys in .env. Keys found {list(config.keys())}. Keys required {required_keys}"
    )

bot = commands.Bot(command_prefix="/", intents=disc.Intents.default())

# Configurações do bot
DISCORD_CHANNEL_ID = int(config["DISCORD_CHANNEL_ID"])


# OAuth 2.0 scopes
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def get_authenticated_service():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            cred_json = pickle.load(token)
        creds = Credentials.from_authorized_user_info(json.loads(cred_json), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "w") as token:
            pickle.dump(creds.to_json(), token)
    return build("youtube", "v3", credentials=creds)


# Configuração da API do YouTube
youtube = get_authenticated_service()


def get_upload_playlist_id() -> int:
    response = (
        youtube.channels()
        .list(
            part="contentDetails",
            id=config["YOUTUBE_CHANNEL_ID"],
        )
        .execute()
    )

    uploads_playlist_id = response["items"][0]["contentDetails"]["relatedPlaylists"][
        "uploads"
    ]
    return uploads_playlist_id


upload_playlist_id = get_upload_playlist_id()


def get_latest_video() -> dict[str, int]:
    global upload_playlist_id

    # Get the latest video from the uploads playlist
    playlist_items_response = (
        youtube.playlistItems()
        .list(
            part="snippet",
            playlistId=upload_playlist_id,
            maxResults=5,
        )
        .execute()
    )

    latest_video = playlist_items_response["items"][0]
    video_id = latest_video["snippet"]["resourceId"]["videoId"]
    video_title = latest_video["snippet"]["title"]

    return {"id": video_id, "title": video_title}


latest_video = None


async def send_msg(channel, msg: str):
    logger.info(f"Sending msg: {msg!r}\t")
    await channel.send(msg)


async def check_new_videos():
    global latest_video
    video = get_latest_video()

    if video:
        video_id = video["id"]

        if video["id"] != latest_video["id"]:
            latest_video = video
            video_title = video["title"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            channel = bot.get_channel(DISCORD_CHANNEL_ID)
            await send_msg(
                channel, f"@everyone Novo vídeo: **{video_title}**\n{video_url}"
            )


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

    # Update latest video, to not post this one
    latest_video = get_latest_video()
    logger.info(f"latest video on start is {latest_video}")
    # Uncomment to add latest video on startup
    # latest_video = {"id": "", "title": ""}

    while True:
        try:
            # synced = await bot.tree.sync()
            synced = []
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Error Syncing commads: {e}")

        try:
            await check_new_videos()
        except BaseException as e:
            logger.error(f"Error Checking new videos: {e}")

        await asyncio.sleep(300)


async def amain():
    async with bot:
        await bot.start(config["DISCORD_TOKEN"])


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
