import json
import logging
import pickle
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from acelerado.env import get_env

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
TOKEN_PATH = Path("token.pickle")
CREDENTIALS_PATH = Path("credentials.json")


def get_creds() -> Credentials:
    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        with TOKEN_PATH.open("rb") as token:
            cred_json = pickle.load(token)
        creds = Credentials.from_authorized_user_info(json.loads(cred_json), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        with TOKEN_PATH.open("wb") as token:
            pickle.dump(creds.to_json(), token)
    return creds


def get_token_expiration_date() -> datetime | None:
    """Return the cached token's expiry as a timezone-aware UTC datetime.

    google-auth stores ``Credentials.expiry`` as a naive UTC datetime; we
    normalize to aware UTC so downstream arithmetic doesn't silently drift
    on non-UTC hosts.
    """
    if not TOKEN_PATH.exists():
        return None
    with TOKEN_PATH.open("rb") as token:
        cred_json = pickle.load(token)
    expiry = Credentials.from_authorized_user_info(json.loads(cred_json), SCOPES).expiry
    if expiry is None:
        return None
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry


def get_token_time_to_expire() -> float | None:
    expire = get_token_expiration_date()
    if expire is None:
        return None
    return (expire - datetime.now(UTC)).total_seconds()


@lru_cache(maxsize=1)
def _youtube():
    """OAuth-backed YouTube client — sees members-only and unpublished videos."""
    return build("youtube", "v3", credentials=get_creds(), cache_discovery=False)


@lru_cache(maxsize=1)
def get_upload_playlist_id() -> str:
    response = (
        _youtube().channels().list(part="contentDetails", id=get_env().YOUTUBE_CHANNEL_ID).execute()
    )
    return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_last_videos(max_videos: int = 20) -> list[dict]:
    response = (
        _youtube()
        .playlistItems()
        .list(
            part="snippet",
            playlistId=get_upload_playlist_id(),
            maxResults=max_videos,
        )
        .execute()
    )
    return response["items"]


def get_video_info(video_id: str) -> dict:
    response = (
        _youtube()
        .videos()
        .list(
            part=(
                "contentDetails,fileDetails,id,liveStreamingDetails,localizations,"
                "player,processingDetails,recordingDetails,snippet,statistics,"
                "status,suggestions,topicDetails"
            ),
            id=video_id,
        )
        .execute()
    )
    if not response["items"]:
        raise ValueError(f"Video with ID {video_id} not found.")
    return response["items"][0]


def get_video_id(video: dict) -> str:
    return video["snippet"]["resourceId"]["videoId"]


def get_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def get_video_title(video: dict) -> str:
    return video["snippet"]["title"]


def is_livestream(video: dict) -> bool:
    return "liveStreamingDetails" in video


def is_non_listed(video: dict) -> bool:
    return video["status"]["privacyStatus"] != "public"


def is_processed(video: dict) -> bool:
    return video["status"]["uploadStatus"] == "processed"


def is_members_only(video: dict) -> bool:
    tags = video["snippet"].get("tags", [])
    return "membros" in tags


def is_vertical(video: dict) -> bool:
    streams = video.get("fileDetails", {}).get("videoStreams", [])
    if not streams:
        logger.debug("Could not determine vertical orientation — no videoStreams available")
        return False
    stream = streams[0]
    width = stream.get("widthPixels", 0)
    height = stream.get("heightPixels", 0)
    return height > width
