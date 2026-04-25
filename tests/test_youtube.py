"""Tests for ``acelerado.youtube``.

Pure helpers go through the fixture builders; anything that touches the
actual YouTube API is stubbed via ``monkeypatch`` on ``youtube._youtube``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from acelerado import youtube

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_is_livestream_toggles_on_streaming_details(make_video_fn):
    assert youtube.is_livestream(make_video_fn(livestream=True)) is True
    assert youtube.is_livestream(make_video_fn(livestream=False)) is False


@pytest.mark.parametrize(
    "privacy,expected",
    [("public", False), ("unlisted", True), ("private", True)],
)
def test_is_non_listed(make_video_fn, privacy, expected):
    assert youtube.is_non_listed(make_video_fn(privacy_status=privacy)) is expected


@pytest.mark.parametrize(
    "status,expected",
    [("processed", True), ("uploaded", False), ("failed", False)],
)
def test_is_processed(make_video_fn, status, expected):
    assert youtube.is_processed(make_video_fn(upload_status=status)) is expected


def test_is_members_only_detects_tag(make_video_fn):
    assert youtube.is_members_only(make_video_fn(members_only=True)) is True
    assert youtube.is_members_only(make_video_fn(members_only=False)) is False


def test_is_members_only_without_tags_key(make_video_fn):
    video = make_video_fn()
    del video["snippet"]["tags"]
    assert youtube.is_members_only(video) is False


def test_is_vertical(make_video_fn):
    assert youtube.is_vertical(make_video_fn(vertical=True)) is True
    assert youtube.is_vertical(make_video_fn(vertical=False)) is False


def test_is_vertical_missing_file_details_is_false(make_video_fn):
    video = make_video_fn()
    video.pop("fileDetails", None)
    assert youtube.is_vertical(video) is False


def test_is_vertical_empty_streams_is_false(make_video_fn):
    video = make_video_fn()
    video["fileDetails"]["videoStreams"] = []
    assert youtube.is_vertical(video) is False


def test_get_video_id_url_title(sample_video):
    vid = youtube.get_video_id(sample_video)
    assert vid == "vid123"
    assert youtube.get_video_url(vid) == "https://www.youtube.com/watch?v=vid123"
    assert youtube.get_video_title(sample_video) == "Example video"


# ---------------------------------------------------------------------------
# API-touching functions — the google client is fully mocked
# ---------------------------------------------------------------------------


def _fake_youtube_client(*, channels=None, playlist_items=None, videos=None):
    """Build a chainable MagicMock that mimics the google-api-python-client shape.

    Only the methods we actually call end up being exercised: .list(...).execute().
    """
    client = MagicMock(name="youtube-client")

    client.channels.return_value.list.return_value.execute.return_value = channels or {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test_uploads"}}}]
    }
    client.playlistItems.return_value.list.return_value.execute.return_value = playlist_items or {
        "items": []
    }
    client.videos.return_value.list.return_value.execute.return_value = videos or {"items": []}
    return client


def test_get_upload_playlist_id(monkeypatch):
    client = _fake_youtube_client()
    monkeypatch.setattr(youtube, "_youtube", lambda: client)
    youtube.get_upload_playlist_id.cache_clear()

    assert youtube.get_upload_playlist_id() == "UU_test_uploads"


def test_get_last_videos(monkeypatch, make_playlist_item_fn):
    items = [make_playlist_item_fn("a"), make_playlist_item_fn("b")]
    client = _fake_youtube_client(playlist_items={"items": items})
    monkeypatch.setattr(youtube, "_youtube", lambda: client)
    youtube.get_upload_playlist_id.cache_clear()

    assert youtube.get_last_videos(max_videos=2) == items
    # Sanity: pagination argument propagated to the API call
    client.playlistItems.return_value.list.assert_called_once()
    _, kwargs = client.playlistItems.return_value.list.call_args
    assert kwargs["maxResults"] == 2
    assert kwargs["playlistId"] == "UU_test_uploads"


def test_get_video_info_returns_single_item(monkeypatch, make_video_fn):
    video = make_video_fn(video_id="abc")
    client = _fake_youtube_client(videos={"items": [video]})
    monkeypatch.setattr(youtube, "_youtube", lambda: client)

    assert youtube.get_video_info("abc") == video


def test_get_video_info_raises_on_empty(monkeypatch):
    client = _fake_youtube_client(videos={"items": []})
    monkeypatch.setattr(youtube, "_youtube", lambda: client)

    with pytest.raises(ValueError, match="Video with ID zzz not found"):
        youtube.get_video_info("zzz")


# ---------------------------------------------------------------------------
# Token expiry — the UTC/naive-local fix
# ---------------------------------------------------------------------------


def test_expiration_returns_none_when_missing(monkeypatch):
    # token.pickle doesn't exist in this tmp cwd
    assert youtube.get_token_expiration_date() is None
    assert youtube.get_token_time_to_expire() is None


def test_expiration_reads_token_file_and_returns_aware_utc(token_future):
    expiry = youtube.get_token_expiration_date()
    assert expiry is not None
    assert expiry.tzinfo is not None, "expiry must be timezone-aware"
    # Should be close to the 30-day future we wrote
    delta = expiry - datetime.now(UTC)
    assert timedelta(days=29) < delta < timedelta(days=31)


def test_time_to_expire_is_positive_for_future_token(token_future):
    seconds = youtube.get_token_time_to_expire()
    assert seconds is not None
    # ~30 days in seconds, give a wide tolerance for wall-clock drift
    assert 29 * 86400 < seconds < 31 * 86400


# ---------------------------------------------------------------------------
# Upcoming livestreams
# ---------------------------------------------------------------------------


def test_is_live_now_distinguishes_scheduled_from_actual(make_video_fn):
    scheduled = make_video_fn(livestream=True)
    # default fixture sets actualStartTime; remove to simulate "scheduled"
    scheduled["liveStreamingDetails"] = {"scheduledStartTime": "2026-04-25T19:00:00Z"}
    assert youtube.is_livestream(scheduled) is True
    assert youtube.is_live_now(scheduled) is False

    live = make_video_fn(livestream=True)
    live["liveStreamingDetails"] = {
        "actualStartTime": "2026-04-25T19:00:00Z",
        "scheduledStartTime": "2026-04-25T19:00:00Z",
    }
    assert youtube.is_live_now(live) is True


def test_is_live_now_false_when_ended(make_video_fn):
    video = make_video_fn(livestream=True)
    video["liveStreamingDetails"] = {
        "actualStartTime": "2026-04-25T19:00:00Z",
        "actualEndTime": "2026-04-25T20:00:00Z",
    }
    assert youtube.is_live_now(video) is False


def test_get_scheduled_start_time_parses_z_suffix(make_video_fn):
    video = make_video_fn(livestream=True)
    video["liveStreamingDetails"] = {"scheduledStartTime": "2026-04-25T19:00:00Z"}
    parsed = youtube.get_scheduled_start_time(video)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.month == 4 and parsed.day == 25


def test_get_scheduled_start_time_returns_none_when_missing(make_video_fn):
    assert youtube.get_scheduled_start_time(make_video_fn()) is None


def test_get_upcoming_livestream_ids(monkeypatch):
    client = _fake_youtube_client()
    client.search.return_value.list.return_value.execute.return_value = {
        "items": [
            {"id": {"videoId": "live1", "kind": "youtube#video"}},
            {"id": {"videoId": "live2", "kind": "youtube#video"}},
            {"id": {"kind": "youtube#channel"}},  # malformed entry — skipped
        ]
    }
    monkeypatch.setattr(youtube, "_youtube", lambda: client)

    ids = youtube.get_upcoming_livestream_ids()
    assert ids == ["live1", "live2"]


def test_time_to_expire_negative_for_past_token(write_token):
    write_token(datetime.now(UTC) - timedelta(days=1))
    seconds = youtube.get_token_time_to_expire()
    assert seconds is not None
    assert seconds < 0
