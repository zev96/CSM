"""Tests for the vendored MediaCrawler WBI signer.

The vendored class lives at
``csm_core/mining/platforms/_vendor/mc_bilibili_sign.py`` — see the
``_vendor/README.md`` for source and NCL 1.1 license attribution.

We don't verify against live B 站 here (keys rotate). We just verify the
algorithm is deterministic and the output format matches B 站's
expectations (32-char md5 hex w_rid, int wts).
"""
from __future__ import annotations

from csm_core.mining.platforms._vendor.mc_bilibili_sign import BilibiliSign


def test_sign_adds_wts_and_w_rid():
    signer = BilibiliSign("a" * 32, "b" * 32)
    out = signer.sign({"keyword": "test", "page": 1})

    # All values come out as strings — upstream canonicalizes everything
    # through ``str(v)`` before urlencode so that md5 sees the same bytes
    # the server will reconstruct. We just verify the keys + format.
    assert "wts" in out
    assert "w_rid" in out
    assert int(out["wts"]) > 0       # roundtrip as int, sanity
    assert isinstance(out["w_rid"], str)
    assert len(out["w_rid"]) == 32
    assert all(c in "0123456789abcdef" for c in out["w_rid"])


def test_sign_filters_special_chars_in_signing():
    """B 站 signer skips ``!'()*`` when canonicalizing values.

    We just verify signing doesn't crash and produces a w_rid; the
    upstream algorithm strips those characters from values before md5.
    """
    signer = BilibiliSign("a" * 32, "b" * 32)
    out = signer.sign({"keyword": "hello!world(2024)*"})

    assert "w_rid" in out
    assert len(out["w_rid"]) == 32


def test_get_salt_is_deterministic_and_32_chars():
    """``get_salt`` mixes img_key + sub_key through MAP_TABLE → 32 chars."""
    signer = BilibiliSign("0123456789abcdef" * 2, "fedcba9876543210" * 2)
    s1 = signer.get_salt()
    s2 = signer.get_salt()

    assert s1 == s2
    assert len(s1) == 32


def test_map_table_indexes_within_64_byte_key_space():
    """All MAP_TABLE indices must fall inside a 64-char (img_key+sub_key) string."""
    assert max(BilibiliSign.MAP_TABLE) < 64
    assert min(BilibiliSign.MAP_TABLE) >= 0
    assert len(BilibiliSign.MAP_TABLE) == 64
