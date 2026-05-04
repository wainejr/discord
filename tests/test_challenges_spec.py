"""Tests for ``acelerado.challenges.spec``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from acelerado.challenges.spec import load_spec, load_spec_file

SAMPLE = {
    "name": "deblur",
    "title": "arrumando autofoco",
    "month": "2026-05",
    "primary_metric": "psnr_mean_db",
    "direction": "max",
    "caps": {"time_ms_per_image": 200, "peak_rss_mb": 64},
    "image": {"format": "bmp24", "width": 512},
}


def test_load_spec_parses_known_fields():
    spec = load_spec(SAMPLE)
    assert spec.name == "deblur"
    assert spec.title == "arrumando autofoco"
    assert spec.month == "2026-05"
    assert spec.primary_metric == "psnr_mean_db"
    assert spec.direction == "max"
    assert spec.caps == {"time_ms_per_image": 200, "peak_rss_mb": 64}


def test_load_spec_preserves_unknown_fields_in_extras():
    spec = load_spec(SAMPLE)
    # ``image`` isn't a Spec field — extra="allow" puts it in model_extra.
    assert spec.model_extra is not None
    assert spec.model_extra.get("image") == {"format": "bmp24", "width": 512}


def test_slug_combines_month_and_name():
    spec = load_spec(SAMPLE)
    assert spec.slug == "2026-05-deblur"


def test_site_url_points_at_github_pages():
    spec = load_spec(SAMPLE)
    assert spec.site_url == "https://wainejr.github.io/acelerado-desafios/desafios/2026-05-deblur/"


def test_load_spec_rejects_malformed_month():
    bad = dict(SAMPLE, month="2026-13")
    with pytest.raises(ValidationError):
        load_spec(bad)


def test_load_spec_rejects_missing_required_fields():
    bad = {k: v for k, v in SAMPLE.items() if k != "primary_metric"}
    with pytest.raises(ValidationError):
        load_spec(bad)


def test_load_spec_caps_optional():
    minimal = {k: v for k, v in SAMPLE.items() if k != "caps"}
    spec = load_spec(minimal)
    assert spec.caps == {}


def test_load_spec_file(tmp_path: Path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(SAMPLE))
    spec = load_spec_file(path)
    assert spec.name == "deblur"
