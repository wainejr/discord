"""Tests for ``acelerado.youtube``.

Pure helpers go through the fixture builders; anything that touches the
actual YouTube API is stubbed via ``monkeypatch`` on ``youtube._youtube``.
"""

from __future__ import annotations

import time
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


# ---------------------------------------------------------------------------
# Discord-initiated OAuth renewal flow
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_pending_flows():
    youtube._PENDING_FLOWS.clear()
    yield
    youtube._PENDING_FLOWS.clear()


@pytest.fixture
def fake_credentials_file(tmp_path):
    """Write a minimal installed-app credentials.json into the test cwd."""
    payload = {
        "installed": {
            "client_id": "fake-client-id.apps.googleusercontent.com",
            "client_secret": "fake-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    path = tmp_path / "credentials.json"
    path.write_text(__import__("json").dumps(payload))
    return path


def test_start_oauth_flow_missing_credentials_raises():
    with pytest.raises(FileNotFoundError):
        youtube.start_oauth_flow(user_id=42)


def test_start_oauth_flow_returns_url_and_parks_flow(monkeypatch, fake_credentials_file):
    fake_flow = MagicMock(name="Flow")
    fake_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?state=abc123",
        "abc123",
    )
    monkeypatch.setattr(
        youtube.Flow,
        "from_client_secrets_file",
        classmethod(lambda cls, *a, **kw: fake_flow),
    )

    url = youtube.start_oauth_flow(user_id=42)
    assert "state=abc123" in url
    assert 42 in youtube._PENDING_FLOWS
    parked_flow, state, _ = youtube._PENDING_FLOWS[42]
    assert parked_flow is fake_flow
    assert state == "abc123"


def test_complete_oauth_flow_no_pending_raises():
    with pytest.raises(LookupError):
        youtube.complete_oauth_flow(user_id=42, redirect_url="http://localhost/?code=x&state=y")


def test_complete_oauth_flow_state_mismatch_rejects(monkeypatch):
    youtube._PENDING_FLOWS[42] = (MagicMock(name="Flow"), "expected-state", time.time() + 600)
    with pytest.raises(ValueError, match="State mismatch"):
        youtube.complete_oauth_flow(
            user_id=42,
            redirect_url="http://localhost/?code=abc&state=evil-state",
        )
    # Flow consumed even on mismatch — user must restart
    assert 42 not in youtube._PENDING_FLOWS


def test_complete_oauth_flow_missing_code_rejects():
    youtube._PENDING_FLOWS[42] = (MagicMock(name="Flow"), "s1", time.time() + 600)
    with pytest.raises(ValueError, match="no `code=` parameter"):
        youtube.complete_oauth_flow(
            user_id=42,
            redirect_url="http://localhost/?state=s1",
        )


def test_complete_oauth_flow_writes_token_and_busts_cache(monkeypatch, tmp_path):
    fake_creds = MagicMock(name="Credentials")
    fake_creds.to_json.return_value = '{"token": "fresh"}'
    fake_flow = MagicMock(name="Flow")
    fake_flow.credentials = fake_creds
    youtube._PENDING_FLOWS[42] = (fake_flow, "stateXYZ", time.time() + 600)

    # Pre-existing token must be backed up, not silently overwritten.
    youtube.TOKEN_PATH.write_bytes(b"old-token-bytes")

    youtube.complete_oauth_flow(
        user_id=42,
        redirect_url="http://localhost/?code=abc&state=stateXYZ",
    )

    fake_flow.fetch_token.assert_called_once()
    assert youtube.TOKEN_PATH.exists()
    backup = youtube.TOKEN_PATH.with_name(youtube.TOKEN_PATH.name + ".old")
    assert backup.exists() and backup.read_bytes() == b"old-token-bytes"
    # Pending entry consumed
    assert 42 not in youtube._PENDING_FLOWS


def test_pending_flows_expire_after_ttl(monkeypatch):
    fake_flow = MagicMock(name="Flow")
    youtube._PENDING_FLOWS[42] = (fake_flow, "s1", time.time() - 1)  # already expired
    youtube._prune_expired_pending_flows()
    assert 42 not in youtube._PENDING_FLOWS


# ---------------------------------------------------------------------------
# Refresh-token issuance tracking (the actual 7-day countdown)
# ---------------------------------------------------------------------------


def test_record_refresh_issuance_writes_iso_timestamp():
    youtube._record_refresh_issuance()
    assert youtube.REFRESH_ISSUED_PATH.exists()
    raw = youtube.REFRESH_ISSUED_PATH.read_text()
    parsed = datetime.fromisoformat(raw)
    assert parsed.tzinfo is not None
    assert abs((parsed - datetime.now(UTC)).total_seconds()) < 5


def test_get_refresh_token_issued_at_returns_none_when_missing():
    assert youtube.get_refresh_token_issued_at() is None


def test_get_refresh_token_issued_at_normalizes_naive_iso():
    """Legacy file written by an earlier bot version may lack tz suffix."""
    youtube.REFRESH_ISSUED_PATH.write_text("2026-05-01T00:00:00")
    parsed = youtube.get_refresh_token_issued_at()
    assert parsed is not None and parsed.tzinfo is not None


def test_get_refresh_token_issued_at_returns_none_on_garbage():
    youtube.REFRESH_ISSUED_PATH.write_text("not a timestamp")
    assert youtube.get_refresh_token_issued_at() is None


def test_refresh_token_time_to_expire_none_when_no_token():
    assert youtube.get_refresh_token_time_to_expire(7) is None


def test_refresh_token_time_to_expire_bootstraps_missing_sidecar(token_future):
    """Existing install upgraded — no sidecar yet. Bootstrap with `now` and
    return ttl_days * 86400 (within tolerance)."""
    seconds = youtube.get_refresh_token_time_to_expire(7)
    assert seconds is not None
    assert 7 * 86400 - 5 < seconds <= 7 * 86400
    assert youtube.REFRESH_ISSUED_PATH.exists()


def test_refresh_token_time_to_expire_negative_when_past_deadline(token_future):
    """Sidecar 8 days old + 7-day TTL → expired."""
    youtube._record_refresh_issuance(now=datetime.now(UTC) - timedelta(days=8))
    seconds = youtube.get_refresh_token_time_to_expire(7)
    assert seconds is not None and seconds < 0


def test_refresh_token_time_to_expire_honors_custom_ttl(token_future):
    youtube._record_refresh_issuance(now=datetime.now(UTC) - timedelta(days=10))
    # 30-day TTL means we still have ~20 days left, even though the
    # default 7-day TTL would say "expired".
    seconds = youtube.get_refresh_token_time_to_expire(30)
    assert seconds is not None and seconds > 19 * 86400


def test_complete_oauth_flow_records_refresh_issuance(monkeypatch):
    fake_creds = MagicMock(name="Credentials")
    fake_creds.to_json.return_value = '{"token": "fresh"}'
    fake_flow = MagicMock(name="Flow")
    fake_flow.credentials = fake_creds
    youtube._PENDING_FLOWS[42] = (fake_flow, "s1", time.time() + 600)

    youtube.complete_oauth_flow(
        user_id=42,
        redirect_url="http://localhost/?code=abc&state=s1",
    )

    assert youtube.REFRESH_ISSUED_PATH.exists()
    parsed = youtube.get_refresh_token_issued_at()
    assert parsed is not None
    assert abs((parsed - datetime.now(UTC)).total_seconds()) < 5
