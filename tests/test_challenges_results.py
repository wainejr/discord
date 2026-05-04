"""Tests for ``acelerado.challenges.results`` — model + renderer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acelerado.challenges.results import (
    format_metric_value,
    load_results,
    render_results_post,
)

PSNR_PAYLOAD = {
    "slug": "2026-05-deblur",
    "primary_metric": "psnr_mean_db",
    "direction": "max",
    "ranking": [
        {
            "rank": 1,
            "user": "alice",
            "language": "rust",
            "metrics": {"psnr_mean_db": 41.2, "time_ms_per_image": 87, "peak_rss_mb": 38},
        },
        {
            "rank": 2,
            "user": "bob",
            "language": "c",
            "metrics": {"psnr_mean_db": 39.8, "time_ms_per_image": 102, "peak_rss_mb": 42},
        },
        {
            "rank": 3,
            "user": "carol",
            "language": "python",
            "metrics": {"psnr_mean_db": 35.5, "time_ms_per_image": 1500, "peak_rss_mb": 60},
        },
        {
            "rank": 4,
            "user": "dave",
            "language": "go",
            "metrics": {"psnr_mean_db": 30.1, "time_ms_per_image": 90, "peak_rss_mb": 45},
        },
    ],
    "disqualified": [{"user": "eve", "reason": "estourou peak_rss_mb cap"}],
}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_load_results_parses_full_payload():
    results = load_results(PSNR_PAYLOAD)
    assert results.slug == "2026-05-deblur"
    assert results.primary_metric == "psnr_mean_db"
    assert len(results.ranking) == 4
    assert results.ranking[0].user == "alice"
    assert results.ranking[0].metrics["psnr_mean_db"] == 41.2
    assert len(results.disqualified) == 1


def test_load_results_preserves_unknown_fields():
    payload = dict(PSNR_PAYLOAD, hardware="ryzen 9 5950x")
    results = load_results(payload)
    assert results.model_extra is not None
    assert results.model_extra.get("hardware") == "ryzen 9 5950x"


def test_load_results_rejects_missing_required():
    bad = {k: v for k, v in PSNR_PAYLOAD.items() if k != "primary_metric"}
    with pytest.raises(ValidationError):
        load_results(bad)


def test_load_results_empty_ranking_ok():
    minimal = {"slug": "2026-06-foo", "primary_metric": "time_ms", "direction": "min"}
    results = load_results(minimal)
    assert results.ranking == []
    assert results.disqualified == []


# ---------------------------------------------------------------------------
# format_metric_value
# ---------------------------------------------------------------------------


def test_format_time_ms_under_one_second():
    assert format_metric_value("time_ms", 87) == "87 ms"


def test_format_time_ms_seconds():
    assert format_metric_value("time_ms", 1500) == "1.50 s"


def test_format_time_ms_per_image_appends_per_img():
    assert format_metric_value("time_ms_per_image", 87) == "87 ms/img"
    assert format_metric_value("time_ms_per_image", 1500) == "1.50 s/img"


def test_format_memory_mb():
    assert format_metric_value("peak_rss_mb", 142) == "142 MB"
    assert format_metric_value("disk_write_mb", 15) == "15 MB"


def test_format_bytes_humanizes():
    assert format_metric_value("binary_size_bytes", 312) == "312 B"
    assert format_metric_value("binary_size_bytes", 2048) == "2.0 KB"
    assert format_metric_value("binary_size_bytes", 2_400_000) == "2.40 MB"
    assert format_metric_value("code_size_bytes", 312) == "312 B"


def test_format_psnr_db():
    assert format_metric_value("psnr_mean_db", 41.2) == "41.20 dB"


def test_format_unknown_metric_falls_back_to_str():
    assert format_metric_value("custom_metric", "weird-value") == "weird-value"


def test_format_handles_non_numeric_gracefully():
    # If results.json has a buggy value, we degrade to str() rather than raise.
    assert format_metric_value("time_ms", "not-a-number") == "not-a-number"


# ---------------------------------------------------------------------------
# render_results_post
# ---------------------------------------------------------------------------


def test_render_includes_top3_with_podium():
    results = load_results(PSNR_PAYLOAD)
    post = render_results_post(results)
    assert "🥇" in post
    assert "🥈" in post
    assert "🥉" in post
    assert "@alice" in post
    assert "41.20 dB" in post


def test_render_top3_has_secondary_line_with_lang_and_metrics():
    results = load_results(PSNR_PAYLOAD)
    post = render_results_post(results)
    # alice's secondary: time + memory + language
    assert "87 ms/img" in post
    assert "38 MB" in post
    assert "rust" in post


def test_render_collapses_ranks_4plus_into_short_list():
    results = load_results(PSNR_PAYLOAD)
    post = render_results_post(results)
    assert "Demais participantes" in post
    assert "@dave" in post


def test_render_lists_disqualified_at_end():
    results = load_results(PSNR_PAYLOAD)
    post = render_results_post(results)
    assert "Desclassificados" in post
    assert "@eve" in post
    assert "estourou peak_rss_mb cap" in post


def test_render_handles_empty_ranking():
    results = load_results({"slug": "2026-06-foo", "primary_metric": "time_ms", "direction": "min"})
    post = render_results_post(results)
    assert "Sem submissões válidas" in post
    assert "Desclassificados" not in post  # no DQ section when empty


def test_render_handles_missing_secondary_metrics():
    """Entry with only the primary metric — no secondary line should appear."""
    payload = {
        "slug": "2026-07-bar",
        "primary_metric": "time_ms",
        "direction": "min",
        "ranking": [{"rank": 1, "user": "alice", "metrics": {"time_ms": 500}}],
    }
    results = load_results(payload)
    post = render_results_post(results)
    assert "@alice" in post
    assert "500 ms" in post


def test_render_includes_slug_in_header():
    results = load_results(PSNR_PAYLOAD)
    post = render_results_post(results)
    assert "2026-05-deblur" in post
