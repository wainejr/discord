"""Tests for the monthly-challenge announcement step in ``AceleradoState``.

The GitHub helpers are patched so the step never makes real HTTP
calls; we only exercise the gating logic (feature flag, day-of-month,
hour-of-day, idempotency) and the channel routing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from acelerado import state as state_mod
from acelerado import youtube as yt_mod
from acelerado.challenges import github as challenge_github
from acelerado.challenges.spec import load_spec

SPEC_PAYLOAD = {
    "name": "deblur",
    "title": "arrumando autofoco",
    "month": "2026-05",
    "primary_metric": "psnr_mean_db",
    "direction": "max",
    "caps": {"time_ms_per_image": 200, "peak_rss_mb": 64},
}


@pytest.fixture
def challenges_channel():
    """Mock channel with a spec'd send method, like the announce/log channels."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "desafios"
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def state_with_challenges(chdir_tmp, fake_bot, fake_guild, monkeypatch, challenges_channel):
    """AceleradoState with the challenges channel wired in (id 444)."""
    monkeypatch.setattr(yt_mod, "get_last_videos", lambda max_videos=20: [])

    # Extend the bot's channel map to include the challenges channel.
    original_side_effect = fake_bot.get_channel.side_effect

    def get_channel(cid: int):
        if cid == 444:
            return challenges_channel
        return original_side_effect(cid)

    fake_bot.get_channel.side_effect = get_channel

    monkeypatch.setenv("DISCORD_CHALLENGES_CHANNEL_ID", "444")
    monkeypatch.setenv("ACELERADO_CHALLENGES_ENABLED", "true")
    monkeypatch.setenv("ACELERADO_CHALLENGES_ANNOUNCE_DAY", "1")
    monkeypatch.setenv("ACELERADO_CHALLENGES_ANNOUNCE_HOUR_UTC", "0")
    # The autouse ``clear_caches`` fixture already calls reload_settings,
    # but env was set after that ran — force a re-read.
    from acelerado.config import reload_settings

    reload_settings()

    return state_mod.AceleradoState(fake_bot)


def _patch_now(monkeypatch, when: datetime) -> None:
    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return when.replace(tzinfo=None)
            return when.astimezone(tz)

    monkeypatch.setattr(state_mod, "datetime", _FakeDateTime)


async def _patch_find(monkeypatch, spec):
    async def fake_find(repo, month, token=None):
        return spec

    monkeypatch.setattr(challenge_github, "find_current_spec", fake_find)


async def test_announce_skipped_when_disabled(
    state_with_challenges, monkeypatch, challenges_channel
):
    monkeypatch.setenv("ACELERADO_CHALLENGES_ENABLED", "false")
    from acelerado.config import reload_settings

    reload_settings()

    _patch_now(monkeypatch, datetime(2026, 5, 1, 12, tzinfo=UTC))
    await state_with_challenges._announce_new_challenge()

    challenges_channel.send.assert_not_awaited()


async def test_announce_skipped_when_not_announce_day(
    state_with_challenges, monkeypatch, challenges_channel
):
    _patch_now(monkeypatch, datetime(2026, 5, 15, 12, tzinfo=UTC))
    await state_with_challenges._announce_new_challenge()
    challenges_channel.send.assert_not_awaited()


async def test_announce_skipped_when_before_hour(
    state_with_challenges, monkeypatch, challenges_channel
):
    monkeypatch.setenv("ACELERADO_CHALLENGES_ANNOUNCE_HOUR_UTC", "12")
    from acelerado.config import reload_settings

    reload_settings()

    _patch_now(monkeypatch, datetime(2026, 5, 1, 11, tzinfo=UTC))
    await state_with_challenges._announce_new_challenge()
    challenges_channel.send.assert_not_awaited()


async def test_announce_posts_when_conditions_met(
    state_with_challenges, monkeypatch, challenges_channel
):
    _patch_now(monkeypatch, datetime(2026, 5, 1, 12, tzinfo=UTC))
    await _patch_find(monkeypatch, load_spec(SPEC_PAYLOAD))

    await state_with_challenges._announce_new_challenge()

    challenges_channel.send.assert_awaited_once()
    msg = challenges_channel.send.await_args.args[0]
    assert "arrumando autofoco" in msg
    assert "PSNR" in msg
    # Idempotency marker landed on disk.
    assert state_with_challenges.challenges.is_announced("2026-05-deblur")


async def test_announce_idempotent_within_same_month(
    state_with_challenges, monkeypatch, challenges_channel
):
    _patch_now(monkeypatch, datetime(2026, 5, 1, 12, tzinfo=UTC))
    await _patch_find(monkeypatch, load_spec(SPEC_PAYLOAD))

    await state_with_challenges._announce_new_challenge()
    await state_with_challenges._announce_new_challenge()

    assert challenges_channel.send.await_count == 1


async def test_announce_skipped_when_channel_unset(chdir_tmp, fake_bot, monkeypatch):
    monkeypatch.setattr(yt_mod, "get_last_videos", lambda max_videos=20: [])
    monkeypatch.setenv("ACELERADO_CHALLENGES_ENABLED", "true")
    monkeypatch.delenv("DISCORD_CHALLENGES_CHANNEL_ID", raising=False)
    from acelerado.config import reload_settings

    reload_settings()

    state = state_mod.AceleradoState(fake_bot)
    _patch_now(monkeypatch, datetime(2026, 5, 1, 12, tzinfo=UTC))
    # Should NOT call find_current_spec (the channel guard precedes it).
    called = False

    async def fake_find(repo, month, token=None):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(challenge_github, "find_current_spec", fake_find)

    await state._announce_new_challenge()
    assert called is False


async def test_announce_skipped_when_no_challenge_published(
    state_with_challenges, monkeypatch, challenges_channel
):
    _patch_now(monkeypatch, datetime(2026, 6, 1, 12, tzinfo=UTC))
    await _patch_find(monkeypatch, None)

    await state_with_challenges._announce_new_challenge()
    challenges_channel.send.assert_not_awaited()


async def test_announce_persists_across_state_instances(
    state_with_challenges, monkeypatch, challenges_channel, fake_bot, chdir_tmp: Path
):
    _patch_now(monkeypatch, datetime(2026, 5, 1, 12, tzinfo=UTC))
    await _patch_find(monkeypatch, load_spec(SPEC_PAYLOAD))

    await state_with_challenges._announce_new_challenge()
    assert challenges_channel.send.await_count == 1

    # New state instance reading the same disk file shouldn't re-announce.
    monkeypatch.setattr(yt_mod, "get_last_videos", lambda max_videos=20: [])
    fresh = state_mod.AceleradoState(fake_bot)
    await fresh._announce_new_challenge()
    assert challenges_channel.send.await_count == 1


# ---------------------------------------------------------------------------
# Phase 3 — _remind_pending_results
# ---------------------------------------------------------------------------


async def _patch_slugs(monkeypatch, slugs):
    async def fake_list(repo, token=None):
        return list(slugs)

    monkeypatch.setattr(challenge_github, "list_challenge_slugs", fake_list)


async def test_reminder_skipped_when_disabled(state_with_challenges, monkeypatch, fake_guild):
    monkeypatch.setenv("ACELERADO_CHALLENGES_ENABLED", "false")
    from acelerado.config import reload_settings

    reload_settings()

    _patch_now(monkeypatch, datetime(2026, 6, 5, 12, tzinfo=UTC))
    await _patch_slugs(monkeypatch, ["2026-05-deblur"])

    await state_with_challenges._remind_pending_results()
    fake_guild._log.send.assert_not_awaited()


async def test_reminder_posts_for_past_month_slug(state_with_challenges, monkeypatch, fake_guild):
    _patch_now(monkeypatch, datetime(2026, 6, 5, 12, tzinfo=UTC))
    await _patch_slugs(monkeypatch, ["2026-05-deblur", "2026-06-active"])

    await state_with_challenges._remind_pending_results()

    fake_guild._log.send.assert_awaited_once()
    msg = fake_guild._log.send.await_args.args[0]
    # Active month (2026-06) should NOT be nudged.
    assert "2026-05-deblur" in msg
    assert "2026-06-active" not in msg


async def test_reminder_skips_slugs_already_posted(state_with_challenges, monkeypatch, fake_guild):
    state_with_challenges.challenges.mark_results_posted("2026-05-deblur")
    _patch_now(monkeypatch, datetime(2026, 6, 5, 12, tzinfo=UTC))
    await _patch_slugs(monkeypatch, ["2026-05-deblur"])

    await state_with_challenges._remind_pending_results()
    fake_guild._log.send.assert_not_awaited()


async def test_reminder_skips_slugs_dismissed(state_with_challenges, monkeypatch, fake_guild):
    state_with_challenges.challenges.mark_results_dismissed("2026-05-deblur")
    _patch_now(monkeypatch, datetime(2026, 6, 5, 12, tzinfo=UTC))
    await _patch_slugs(monkeypatch, ["2026-05-deblur"])

    await state_with_challenges._remind_pending_results()
    fake_guild._log.send.assert_not_awaited()


async def test_reminder_rate_limited_to_24h(state_with_challenges, monkeypatch, fake_guild):
    _patch_now(monkeypatch, datetime(2026, 6, 5, 12, tzinfo=UTC))
    await _patch_slugs(monkeypatch, ["2026-05-deblur"])

    await state_with_challenges._remind_pending_results()
    await state_with_challenges._remind_pending_results()

    # Two ticks within the cooldown window — only one reminder.
    assert fake_guild._log.send.await_count == 1


async def test_reminder_swallows_github_errors(state_with_challenges, monkeypatch, fake_guild):
    _patch_now(monkeypatch, datetime(2026, 6, 5, 12, tzinfo=UTC))

    async def boom(repo, token=None):
        raise challenge_github.GitHubError("rate limited")

    monkeypatch.setattr(challenge_github, "list_challenge_slugs", boom)

    # Must NOT raise — the tick wraps each step in try/except, but we
    # still want this step to handle expected errors locally.
    await state_with_challenges._remind_pending_results()
    fake_guild._log.send.assert_not_awaited()
