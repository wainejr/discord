"""Tests for ``acelerado.state``.

The bot and YouTube module are both fully mocked. We never construct a
real ``discord.Client`` or make any HTTP calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from acelerado import state as state_mod
from acelerado import youtube as yt_mod


def _seed_published(path: Path, ids: list[str]) -> None:
    path.write_text("\n".join(ids))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_state_raises_when_channels_missing(chdir_tmp, fake_bot, monkeypatch):
    _seed_published(chdir_tmp / "published.txt", ["seed"])
    monkeypatch.setattr(yt_mod, "get_last_videos", lambda max_videos=20: [])

    fake_bot.get_channel.side_effect = lambda cid: None
    with pytest.raises(ValueError, match="Unable to get channels"):
        state_mod.AceleradoState(fake_bot)


def test_state_seeds_published_file_on_first_run(
    chdir_tmp, fake_bot, monkeypatch, make_playlist_item_fn
):
    items = [make_playlist_item_fn("a"), make_playlist_item_fn("b")]
    monkeypatch.setattr(yt_mod, "get_last_videos", lambda max_videos=20: items)

    state_mod.AceleradoState(fake_bot)
    assert (chdir_tmp / "published.txt").read_text().splitlines() == ["a", "b"]


# ---------------------------------------------------------------------------
# should_announce_video filtering
# ---------------------------------------------------------------------------


@pytest.fixture
def built_state(chdir_tmp, fake_bot, monkeypatch):
    _seed_published(chdir_tmp / "published.txt", ["seed"])
    monkeypatch.setattr(yt_mod, "get_last_videos", lambda max_videos=20: [])
    return state_mod.AceleradoState(fake_bot)


def test_announce_rules_public_processed_passes(built_state, make_video_fn):
    assert built_state.should_announce_video(make_video_fn()) is True


def test_announce_rules_skip_non_public(built_state, make_video_fn):
    assert built_state.should_announce_video(make_video_fn(privacy_status="unlisted")) is False


def test_announce_rules_skip_unprocessed_unless_live(built_state, make_video_fn):
    unprocessed = make_video_fn(upload_status="uploaded")
    assert built_state.should_announce_video(unprocessed) is False

    live = make_video_fn(upload_status="uploaded", livestream=True)
    assert built_state.should_announce_video(live) is True


def test_announce_rules_skip_vertical(built_state, make_video_fn):
    assert built_state.should_announce_video(make_video_fn(vertical=True)) is False


def test_video_state_returns_all_flags(built_state, make_video_fn):
    state_dict = built_state.get_video_state(make_video_fn(livestream=True))
    assert set(state_dict.keys()) == {
        "non-listed",
        "is-processed",
        "is-livestream",
        "is-vertical",
    }


# ---------------------------------------------------------------------------
# published.txt round-trip
# ---------------------------------------------------------------------------


def test_add_video_published_appends(built_state, chdir_tmp):
    built_state.add_video_published("new_id")
    assert "new_id" in (chdir_tmp / "published.txt").read_text().splitlines()


def test_check_videos_to_pub_filters_known_ids(built_state, monkeypatch, make_playlist_item_fn):
    items = [
        make_playlist_item_fn("seed"),  # already known
        make_playlist_item_fn("fresh"),
    ]
    monkeypatch.setattr(yt_mod, "get_last_videos", lambda max_videos=10: items)
    assert built_state.check_videos_to_pub() == ["fresh"]


# ---------------------------------------------------------------------------
# announce_video — message content + persistence
# ---------------------------------------------------------------------------


async def test_announce_video_regular(built_state, make_video_fn, fake_guild):
    video = make_video_fn(video_id="abc", title="Hello")
    await built_state.announce_video("abc", video)

    fake_guild._announce.send.assert_awaited_once()
    msg = fake_guild._announce.send.await_args.args[0]
    assert "@everyone" in msg
    assert "Vídeo novo no canal!" in msg
    assert "Hello" in msg
    assert "https://www.youtube.com/watch?v=abc" in msg


async def test_announce_video_livestream(built_state, make_video_fn, fake_guild):
    await built_state.announce_video("xyz", make_video_fn(video_id="xyz", livestream=True))
    msg = fake_guild._announce.send.await_args.args[0]
    assert "Estamos em live!" in msg


async def test_announce_video_members_only(built_state, make_video_fn, fake_guild):
    video = make_video_fn(video_id="m1", members_only=True)
    await built_state.announce_video("m1", video)
    msg = fake_guild._announce.send.await_args.args[0]
    assert "Vídeo novo pra membros!" in msg


# ---------------------------------------------------------------------------
# check_expiration — rate-limited warning
# ---------------------------------------------------------------------------


async def test_check_expiration_warns_when_under_24h(built_state, fake_guild, monkeypatch):
    monkeypatch.setattr(yt_mod, "get_token_time_to_expire", lambda: 3600)
    monkeypatch.setattr(yt_mod, "get_token_expiration_date", lambda: datetime.now(UTC))

    await built_state.check_expiration()
    fake_guild._log.send.assert_awaited_once()


async def test_check_expiration_silent_when_more_than_24h(built_state, fake_guild, monkeypatch):
    monkeypatch.setattr(yt_mod, "get_token_time_to_expire", lambda: 3600 * 48)
    await built_state.check_expiration()
    fake_guild._log.send.assert_not_awaited()


async def test_check_expiration_rate_limits_to_one_per_hour(built_state, fake_guild, monkeypatch):
    monkeypatch.setattr(yt_mod, "get_token_time_to_expire", lambda: 60)
    monkeypatch.setattr(yt_mod, "get_token_expiration_date", lambda: datetime.now(UTC))

    await built_state.check_expiration()
    await built_state.check_expiration()  # second call within the rate window
    assert fake_guild._log.send.await_count == 1

    # Force last_msg_expiry back in time; next call should warn again.
    built_state.last_msg_expiry = datetime.now() - timedelta(hours=2)
    await built_state.check_expiration()
    assert fake_guild._log.send.await_count == 2


# ---------------------------------------------------------------------------
# check_members_apoiadores — role sync
# ---------------------------------------------------------------------------


async def test_members_without_role_receive_it(built_state, fake_guild, monkeypatch):
    from unittest.mock import MagicMock

    apoiadores = fake_guild._apoiadores_role
    yt_role = fake_guild._yt_role

    def _make_member(name):
        m = MagicMock(name=f"Member({name})")
        m.name = name
        m.id = 9999
        m.roles = [yt_role]  # has YT role, missing apoiadores
        m.add_roles = AsyncMock()
        return m

    alice = _make_member("alice")
    yt_role.members = [alice]

    await built_state.check_members_apoiadores()

    alice.add_roles.assert_awaited_once_with(apoiadores)
    fake_guild._chat.send.assert_awaited_once()
    assert (
        "alice" in fake_guild._chat.send.await_args.args[0]
        or "<@9999>" in (fake_guild._chat.send.await_args.args[0])
    )


async def test_members_already_in_role_are_skipped(built_state, fake_guild):
    from unittest.mock import MagicMock

    apoiadores = fake_guild._apoiadores_role
    yt_role = fake_guild._yt_role

    already = MagicMock(name="Member(already)")
    already.name = "already"
    already.id = 42
    already.roles = [yt_role, apoiadores]
    already.add_roles = AsyncMock()
    yt_role.members = [already]

    await built_state.check_members_apoiadores()
    already.add_roles.assert_not_awaited()


async def test_members_special_case_eniaw_is_ignored(built_state, fake_guild):
    from unittest.mock import MagicMock

    yt_role = fake_guild._yt_role

    eniaw = MagicMock(name="Member(eniaw)")
    eniaw.name = "eniaw"
    eniaw.id = 7
    eniaw.roles = [yt_role]
    eniaw.add_roles = AsyncMock()
    yt_role.members = [eniaw]

    await built_state.check_members_apoiadores()
    eniaw.add_roles.assert_not_awaited()
    fake_guild._chat.send.assert_not_awaited()


async def test_members_missing_guild_is_logged_not_raised(built_state, fake_bot, caplog):
    fake_bot.get_guild.side_effect = lambda gid: None
    with caplog.at_level("ERROR", logger="acelerado.state"):
        await built_state.check_members_apoiadores()
    assert any("Guild not found" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# event_loop — isolates errors between steps
# ---------------------------------------------------------------------------


async def test_event_loop_isolates_step_errors(built_state, monkeypatch):
    async def raising():
        raise RuntimeError("boom")

    monkeypatch.setattr(built_state, "check_members_apoiadores", raising)

    async def ok_expiration():
        return None

    monkeypatch.setattr(built_state, "check_expiration", ok_expiration)
    monkeypatch.setattr(built_state, "check_videos_to_pub", lambda: [])

    # Should not raise even though check_members_apoiadores did.
    await built_state.event_loop()


async def test_event_loop_reports_failures_to_discord(built_state, fake_guild, monkeypatch):
    """Each failing step should fan out to ``report_error`` -> log channel."""

    async def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(built_state, "check_members_apoiadores", boom)
    monkeypatch.setattr(built_state, "check_expiration", boom)
    monkeypatch.setattr(built_state, "_pub_new_videos", boom)

    await built_state.event_loop()

    # First report goes through, the rest are rate-limited within the same tick.
    assert fake_guild._log.send.await_count == 1
    msg = fake_guild._log.send.await_args.args[0]
    assert "RuntimeError" in msg
    assert "kaboom" in msg


# ---------------------------------------------------------------------------
# Multi-tier YouTube Member sync
# ---------------------------------------------------------------------------


async def test_members_synced_across_multiple_tiers(built_state, fake_guild):
    from unittest.mock import MagicMock

    tier1 = fake_guild._yt_role  # already named "YouTube Member (Nível 1)"
    tier2 = MagicMock(name="Role(YouTube Member Nível 2)")
    tier2.name = "YouTube Member (Nível 2)"
    tier2.members = []
    fake_guild.roles.append(tier2)

    apoiadores = fake_guild._apoiadores_role

    def _member(name: str, member_id: int, roles):
        m = MagicMock(name=f"Member({name})")
        m.name = name
        m.id = member_id
        m.roles = roles
        m.add_roles = AsyncMock()
        return m

    only_t1 = _member("alice", 1, [tier1])
    only_t2 = _member("bob", 2, [tier2])
    in_both = _member("carol", 3, [tier1, tier2])

    tier1.members = [only_t1, in_both]
    tier2.members = [only_t2, in_both]

    await built_state.check_members_apoiadores()

    only_t1.add_roles.assert_awaited_once_with(apoiadores)
    only_t2.add_roles.assert_awaited_once_with(apoiadores)
    # Despite appearing in two tiers, ``carol`` is added exactly once.
    in_both.add_roles.assert_awaited_once_with(apoiadores)


async def test_members_missing_yt_roles_logs_and_returns(built_state, fake_guild, caplog):
    # Strip out the YouTube Member role entirely.
    fake_guild.roles = [r for r in fake_guild.roles if "YouTube Member" not in r.name]

    with caplog.at_level("ERROR", logger="acelerado.state"):
        await built_state.check_members_apoiadores()
    assert any("Missing roles" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# published.txt — robustness
# ---------------------------------------------------------------------------


def test_videos_pubs_strips_blank_and_whitespace_lines(built_state, chdir_tmp):
    (chdir_tmp / "published.txt").write_text("a\n\nb\n   \n\nc\n")
    assert built_state.videos_pubs == ["a", "b", "c"]


def test_videos_pubs_returns_empty_when_file_missing(built_state, chdir_tmp):
    (chdir_tmp / "published.txt").unlink()
    assert built_state.videos_pubs == []


def test_add_video_published_is_idempotent(built_state, chdir_tmp):
    built_state.add_video_published("xyz")
    built_state.add_video_published("xyz")  # no-op
    built_state.add_video_published("xyz")  # still no-op
    lines = (chdir_tmp / "published.txt").read_text().splitlines()
    assert [ln for ln in lines if ln.strip()].count("xyz") == 1


def test_add_video_published_creates_file_if_missing(built_state, chdir_tmp):
    (chdir_tmp / "published.txt").unlink()
    built_state.add_video_published("first")
    assert "first" in (chdir_tmp / "published.txt").read_text()


# ---------------------------------------------------------------------------
# report_error
# ---------------------------------------------------------------------------


async def test_report_error_posts_to_log_channel(built_state, fake_guild):
    exc = RuntimeError("everything is on fire")
    await built_state.report_error("step_name", exc)

    fake_guild._log.send.assert_awaited_once()
    msg = fake_guild._log.send.await_args.args[0]
    assert "step_name" in msg
    assert "RuntimeError" in msg
    assert "everything is on fire" in msg


async def test_report_error_rate_limited_within_cooldown(built_state, fake_guild):
    await built_state.report_error("a", RuntimeError("1"))
    await built_state.report_error("b", RuntimeError("2"))
    await built_state.report_error("c", RuntimeError("3"))
    assert fake_guild._log.send.await_count == 1


async def test_report_error_resumes_after_cooldown(built_state, fake_guild):
    from datetime import datetime, timedelta

    await built_state.report_error("first", RuntimeError("a"))
    # Force the cooldown to be in the past.
    built_state._last_error_report = datetime.now() - timedelta(hours=1)
    await built_state.report_error("second", RuntimeError("b"))
    assert fake_guild._log.send.await_count == 2


async def test_report_error_swallows_channel_send_failure(built_state, fake_guild):
    fake_guild._log.send.side_effect = RuntimeError("discord 500")
    # Must not propagate — the logger is the safety net.
    await built_state.report_error("ctx", RuntimeError("orig"))


async def test_report_error_truncates_long_messages(built_state, fake_guild):
    huge = RuntimeError("x" * 5000)
    await built_state.report_error("ctx", huge)
    msg = fake_guild._log.send.await_args.args[0]
    assert len(msg) <= 1901  # 1900 char limit + ellipsis


async def test_report_error_no_op_when_log_channel_missing(built_state, fake_bot):
    # Pretend the log channel disappeared from cache mid-run.
    fake_bot.get_channel.side_effect = lambda cid: None
    # Should not raise.
    await built_state.report_error("ctx", RuntimeError("boom"))
