"""Tests for the async GitHub client.

Network calls are mocked at the httpx transport layer via ``respx``,
so we exercise the real ``httpx.AsyncClient`` code path (headers,
timeouts, error handling) without hitting api.github.com.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from acelerado.challenges import github as gh

REPO = "wainejr/acelerado-desafios"
SPEC_PAYLOAD = {
    "name": "deblur",
    "title": "arrumando autofoco",
    "month": "2026-05",
    "primary_metric": "psnr_mean_db",
    "direction": "max",
    "caps": {"time_ms_per_image": 200, "peak_rss_mb": 64},
}


def _contents_payload() -> list[dict[str, str]]:
    return [
        {"name": "README.md", "type": "file"},
        {"name": "LICENSE", "type": "file"},
        {"name": "2026-05-deblur", "type": "dir"},
        {"name": "2026-04-mandelbrot", "type": "dir"},
        {"name": "scripts", "type": "dir"},  # not YYYY-MM-prefixed
    ]


@respx.mock
async def test_list_challenge_slugs_filters_to_dated_dirs():
    respx.get(f"{gh.API_BASE}/repos/{REPO}/contents").mock(
        return_value=httpx.Response(200, json=_contents_payload())
    )
    slugs = await gh.list_challenge_slugs(REPO)
    assert slugs == ["2026-04-mandelbrot", "2026-05-deblur"]


@respx.mock
async def test_list_challenge_slugs_raises_on_http_error():
    respx.get(f"{gh.API_BASE}/repos/{REPO}/contents").mock(
        return_value=httpx.Response(404, text="not found")
    )
    with pytest.raises(gh.GitHubError, match="404"):
        await gh.list_challenge_slugs(REPO)


@respx.mock
async def test_list_challenge_slugs_raises_on_non_list_payload():
    respx.get(f"{gh.API_BASE}/repos/{REPO}/contents").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    with pytest.raises(gh.GitHubError, match="expected list"):
        await gh.list_challenge_slugs(REPO)


@respx.mock
async def test_fetch_spec_loads_from_raw_endpoint():
    url = f"https://raw.githubusercontent.com/{REPO}/HEAD/2026-05-deblur/spec.json"
    respx.get(url).mock(return_value=httpx.Response(200, json=SPEC_PAYLOAD))

    spec = await gh.fetch_spec(REPO, "2026-05-deblur")
    assert spec.name == "deblur"
    assert spec.primary_metric == "psnr_mean_db"


@respx.mock
async def test_fetch_spec_propagates_http_errors():
    url = f"https://raw.githubusercontent.com/{REPO}/HEAD/2026-05-deblur/spec.json"
    respx.get(url).mock(return_value=httpx.Response(500, text="internal"))
    with pytest.raises(gh.GitHubError, match="500"):
        await gh.fetch_spec(REPO, "2026-05-deblur")


@respx.mock
async def test_find_current_spec_picks_matching_month():
    respx.get(f"{gh.API_BASE}/repos/{REPO}/contents").mock(
        return_value=httpx.Response(200, json=_contents_payload())
    )
    respx.get(f"https://raw.githubusercontent.com/{REPO}/HEAD/2026-05-deblur/spec.json").mock(
        return_value=httpx.Response(200, json=SPEC_PAYLOAD)
    )

    spec = await gh.find_current_spec(REPO, "2026-05")
    assert spec is not None
    assert spec.slug == "2026-05-deblur"


@respx.mock
async def test_find_current_spec_returns_none_when_no_match():
    respx.get(f"{gh.API_BASE}/repos/{REPO}/contents").mock(
        return_value=httpx.Response(200, json=_contents_payload())
    )
    spec = await gh.find_current_spec(REPO, "2026-06")
    assert spec is None


@respx.mock
async def test_token_added_as_authorization_header(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    route = respx.get(f"{gh.API_BASE}/repos/{REPO}/contents").mock(
        return_value=httpx.Response(200, json=[])
    )
    await gh.list_challenge_slugs(REPO)
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer secret-token"


@respx.mock
async def test_no_token_means_no_authorization_header(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    route = respx.get(f"{gh.API_BASE}/repos/{REPO}/contents").mock(
        return_value=httpx.Response(200, json=[])
    )
    await gh.list_challenge_slugs(REPO)
    assert "Authorization" not in route.calls.last.request.headers


def test_slug_month_extracts_prefix():
    assert gh.slug_month("2026-05-deblur") == "2026-05"
    assert gh.slug_month("2026-12-foo-bar") == "2026-12"


def test_slug_month_returns_none_for_invalid():
    assert gh.slug_month("scripts") is None
    assert gh.slug_month("2026-13-bad-month") is None
