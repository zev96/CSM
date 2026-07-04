"""横评元数据 LRU 缓存单测（镜像 assembler_service 的 plan 缓存范式）。"""
from __future__ import annotations

from csm_sidecar.services import comparison_cache as cc


def test_cache_put_get_roundtrip():
    cc.reset_for_test()
    cc.cache_comparison("job1", models=["A", "B"], category="吸尘器",
                        keyword="k", title="t", tone="口语",
                        skill_chain=["s1"], contract_mode="conservative")
    e = cc.get_comparison("job1")
    assert e is not None
    assert e.models == ["A", "B"]
    assert e.category == "吸尘器"
    assert e.keyword == "k"
    assert e.tone == "口语"
    assert e.skill_chain == ["s1"]
    assert e.contract_mode == "conservative"


def test_cache_miss_returns_none():
    cc.reset_for_test()
    assert cc.get_comparison("nope") is None


def test_cache_lru_evicts_oldest_over_capacity():
    cc.reset_for_test()
    for i in range(cc.MAX_CACHE + 5):
        cc.cache_comparison(f"j{i}", models=["A", "B"], category="吸尘器",
                            keyword="k", title=None, tone=None,
                            skill_chain=None, contract_mode=None)
    assert cc.get_comparison("j0") is None            # 最旧被淘汰
    assert cc.get_comparison(f"j{cc.MAX_CACHE + 4}") is not None
