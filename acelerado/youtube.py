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


def is_live_now(video: dict) -> bool:
    """True only when the live has actually started (and not yet ended).

    A merely *scheduled* live also has ``liveStreamingDetails`` but no
    ``actualStartTime``. Use this to distinguish "live right now" from
    "live coming soon".
    """
    details = video.get("liveStreamingDetails", {})
    return "actualStartTime" in details and "actualEndTime" not in details


def parse_iso8601_z(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (incl. trailing ``Z``) to aware UTC.

    Returns None for empty input or unparseable values; logs a warning for
    the latter so silent format drift in YouTube payloads is visible.
    """
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning(f"Invalid ISO-8601 timestamp: {raw!r}")
        return None


def get_scheduled_start_time(video: dict) -> datetime | None:
    """Return ``scheduledStartTime`` as aware UTC datetime, or None."""
    raw = video.get("liveStreamingDetails", {}).get("scheduledStartTime")
    return parse_iso8601_z(raw)


def get_upcoming_livestream_ids(max_results: int = 5) -> list[str]:
    """Return video IDs for scheduled (not-yet-started) lives on the configured channel."""
    response = (
        _youtube()
        .search()
        .list(
            part="snippet",
            channelId=get_env().YOUTUBE_CHANNEL_ID,
            type="video",
            eventType="upcoming",
            maxResults=max_results,
        )
        .execute()
    )
    items = response.get("items", [])
    return [item["id"]["videoId"] for item in items if "videoId" in item.get("id", {})]


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


def should_announce_video(video: dict) -> bool:
    """True if the video passes every filter we apply before announcing.

    Pure function — operates only on the YouTube payload shape.
    """
    if is_non_listed(video):
        return False
    # Scheduled-but-not-yet-live: handled by the live-reminder step, not
    # here. Avoid announcing "Estamos em live!" before the live actually
    # starts.
    if is_livestream(video) and not is_live_now(video):
        return False
    if not is_processed(video) and not is_livestream(video):
        return False
    if is_vertical(video):
        return False
    return True


def video_state_flags(video: dict) -> dict[str, bool]:
    """Snapshot of the boolean flags consulted by :func:`should_announce_video`."""
    return {
        "non-listed": is_non_listed(video),
        "is-processed": is_processed(video),
        "is-livestream": is_livestream(video),
        "is-vertical": is_vertical(video),
    }
