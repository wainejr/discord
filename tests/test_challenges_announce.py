"""Tests for the announcement renderer."""

from __future__ import annotations

from acelerado.challenges.announce import (
    format_cap,
    render_announcement,
    render_short_status,
)
from acelerado.challenges.spec import load_spec


def _spec(**overrides):
    base = {
        "name": "deblur",
        "title": "arrumando autofoco",
        "month": "2026-05",
        "primary_metric": "psnr_mean_db",
        "direction": "max",
        "caps": {"time_ms_per_image": 200, "peak_rss_mb": 64},
    }
    base.update(overrides)
    return load_spec(base)


def test_render_psnr_max_uses_metric_specific_copy():
    msg = render_announcement(_spec())
    assert "Maximizar **PSNR médio**" in msg
    assert "@everyone" in msg
    assert "2026-05" in msg
    assert "arrumando autofoco" in msg
    assert "https://wainejr.github.io/acelerado-desafios/desafios/2026-05-deblur/" in msg


def test_render_includes_caps_section():
    msg = render_announcement(_spec())
    assert "Limites:" in msg
    assert "200 ms" in msg
    assert "64 MB" in msg


def test_render_unknown_metric_falls_back_to_generic_copy():
    spec = _spec(primary_metric="weirdness", direction="min", caps={})
    msg = render_announcement(spec)
    assert "Minimizar" in msg
    assert "weirdness" in msg
    # No caps line when caps dict is empty.
    assert "Limites:" not in msg


def test_render_time_min_metric():
    spec = _spec(primary_metric="time_ms", direction="min", caps={"time_ms": 1000})
    msg = render_announcement(spec)
    assert "tempo de execução" in msg
    # ``time_ms`` cap should NOT carry the per-imagem suffix.
    assert "1000 ms\n" in msg or "1000 ms\n" in msg + "\n"
    assert "1000 ms por imagem" not in msg


def test_format_cap_known_keys():
    assert format_cap("time_ms", 100) == "⏱ 100 ms"
    assert format_cap("time_ms_per_image", 200) == "⏱ 200 ms por imagem"
    assert format_cap("peak_rss_mb", 64) == "💾 64 MB de RAM"
    assert format_cap("disk_write_mb", 10) == "📝 10 MB de escrita em disco"
    assert format_cap("binary_size_bytes", 2048) == "📦 2048 bytes (binário)"
    assert format_cap("code_size_bytes", 512) == "📜 512 bytes (código-fonte)"


def test_format_cap_unknown_key_falls_back():
    assert format_cap("custom_metric", 42) == "custom_metric: 42"


def test_render_short_status_one_liner():
    line = render_short_status(_spec())
    assert line.startswith("**2026-05 — arrumando autofoco**")
    assert "PSNR" in line
