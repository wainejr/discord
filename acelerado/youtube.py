from acelerado.log import logger
import os
from datetime import datetime, timezone
import pickle
import json

from dotenv import dotenv_values
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


config = dotenv_values(".env")
required_keys = (
    "YOUTUBE_CHANNEL_ID",
    "YOUTUBE_API_KEY",
)
if not all(s in config for s in required_keys):
    raise KeyError(
        f"Not all required keys in .env for {__file__}. Keys found {list(config.keys())}. Keys required {required_keys}"
    )

# OAuth 2.0 scopes
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def get_creds():
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
        content_write = creds.to_json()
        with open("token.pickle", "wb") as token:
            pickle.dump(content_write, token)
    return creds


def get_authenticated_youtube_token():
    """Using YouTube via token, we get ALL the videos, even the ones that were not published yet"""
    creds = get_creds()
    return build("youtube", "v3", credentials=creds)


def get_token_expiration_date() -> None | datetime:
    creds = get_creds()

    with open("token.pickle", "rb") as token:
        cred_json = pickle.load(token)
    creds = Credentials.from_authorized_user_info(json.loads(cred_json), SCOPES)
    expiry = creds.expiry

    return expiry


def get_token_time_to_expire() -> None | float:
    expire = get_token_expiration_date()
    if expire is None:
        return None

    return (expire - datetime.now()).total_seconds()


# This one doesn't fetch members and private videos, neither expires
def get_authenticated_youtube_key():
    """Using YouTube via key, we don't get members only and private videos."""
    return build("youtube", "v3", developerKey=config["YOUTUBE_API_KEY"])


# Configuração da API do YouTube
youtube = get_authenticated_youtube_token()


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


def get_last_videos(max_videos: int = 20) -> list[dict]:
    global upload_playlist_id

    # Get the latest video from the uploads playlist
    playlist_items_response = (
        youtube.playlistItems()
        .list(
            part="snippet",
            playlistId=upload_playlist_id,
            maxResults=max_videos,
        )
        .execute()
    )
    return playlist_items_response["items"]


def get_latest_video() -> dict:
    videos = get_last_videos(max_videos=1)
    return videos[0]


def get_video_info(id: str) -> dict:
    video = (
        youtube.videos()
        .list(
            part="contentDetails,fileDetails,id,liveStreamingDetails,localizations,player,processingDetails,recordingDetails,snippet,statistics,status,suggestions,topicDetails",
            id=id,
        )
        .execute()
    )
    if len(video["items"]) == 0:
        raise ValueError(f"Video with ID {id} not found.")
    return video["items"][0]


def get_video_id(video: dict) -> str:
    return video["snippet"]["resourceId"]["videoId"]


def get_video_url(video: dict) -> str:
    return f"https://www.youtube.com/watch?v={get_video_id(video)}"


def get_video_title(video: dict) -> str:
    return video["snippet"]["title"]


def is_livestream(video: dict) -> bool:
    return "liveStreamingDetails" in video


def is_non_listed(video: dict) -> bool:
    # Both members and public videos are listed as public.
    # For private and non listed this is different
    return video["status"]["privacyStatus"] != "public"


def is_processed(video: dict) -> bool:
    # Both members and public videos are listed as public.
    # For private and non listed this is different
    return video["status"]["uploadStatus"] == "processed"


def is_members_only(video: dict) -> bool:
    if "tags" not in video["snippet"]:
        return False
    tags = video["snippet"]["tags"]
    return "membros" in tags
