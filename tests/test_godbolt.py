"""Tests for ``acelerado.godbolt`` URL builder."""

from __future__ import annotations

import pytest

from acelerado import godbolt


def test_supported_keys_includes_known_languages():
    keys = godbolt.supported_keys()
    assert {"c", "c++", "rust", "zig", "go"} <= set(keys)


@pytest.mark.parametrize("lang", ["c", "c++", "rust", "zig", "go"])
def test_build_url_returns_clientstate(lang):
    url = godbolt.build_clientstate_url(lang, "hello")
    assert url.startswith(godbolt.GODBOLT_BASE)


def test_build_url_round_trip_preserves_source():
    code = "int main() { return 42; }"
    url = godbolt.build_clientstate_url("c", code)
    state = godbolt.decode_clientstate_url(url)
    assert state["sessions"][0]["source"] == code
    assert state["sessions"][0]["language"] == "c"
    assert state["sessions"][0]["compilers"][0]["id"] == godbolt.LANGUAGES["c"].compiler


def test_build_url_handles_unicode_source():
    code = 'fn main() { println!("olá, açaí 🥭"); }'
    url = godbolt.build_clientstate_url("rust", code)
    state = godbolt.decode_clientstate_url(url)
    assert state["sessions"][0]["source"] == code


def test_build_url_unknown_language_raises():
    with pytest.raises(ValueError, match="não suportada"):
        godbolt.build_clientstate_url("brainfuck", "+++.")


def test_alias_cpp_maps_to_cpp():
    url = godbolt.build_clientstate_url("cpp", "int x;")
    state = godbolt.decode_clientstate_url(url)
    assert state["sessions"][0]["language"] == "c++"


def test_language_case_insensitive():
    a = godbolt.build_clientstate_url("RUST", "x")
    b = godbolt.build_clientstate_url("rust", "x")
    assert a == b
