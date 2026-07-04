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


import csm_sidecar.services.generate_service as gs


def test_finalize_draft_scopes_bypass_skips_resolve(monkeypatch):
    """传入 scopes 时不再调 resolve_scopes（横评路径的关键旁路）。"""
    called = {"resolve": 0, "chain_directive": None}

    def fake_resolve(*a, **k):
        called["resolve"] += 1
        return []
    monkeypatch.setattr(gs, "resolve_scopes", fake_resolve)

    class _State:
        final_text = "X"
        passes = []
    def fake_run_chain(job_id, steps, **kw):
        called["chain_directive"] = kw.get("angle_directive")
        return _State()
    monkeypatch.setattr(gs.chain_service, "run_chain", fake_run_chain)
    monkeypatch.setattr(gs, "render_brand_facts", lambda *a, **k: "facts")
    monkeypatch.setattr(gs.pricing, "chain_cost", lambda *a, **k: {})
    monkeypatch.setattr(gs, "_maybe_block_for_factcheck", lambda *a, **k: False)
    monkeypatch.setattr(gs.bus, "publish", lambda *a, **k: None)

    class _Cfg:
        # _effective_model(model=None, provider=None) 会读 cfg.default_provider；
        # 置 None 使其早退 None，交给已 patch 的 pricing.chain_cost（plan 的 mock
        # 漏了这项 —— 与本旁路无关，补全 fixture 不动断言）。
        default_provider = None
        class brand_memory:
            inject = True; factcheck = False; own_brands = []
            inject_variant_cap = 3; inject_endorsement_cap = 5
        class contract: mode = "conservative"
        class pricing: pass
    prebuilt = [object()]
    gs.finalize_draft(
        "job1", chain_steps=[], draft="d", plan=None, index=None, registry=None,
        category="吸尘器", keyword="k", title=None, angle=None,
        provider=None, model=None, cfg=_Cfg, out_dir=__import__("pathlib").Path("."),
        checkpoint=lambda: None, on_pass=lambda p: None,
        stage_index=0, stage_total=1, contract_mode="conservative",
        scopes=prebuilt, angle_directive="横评指令",
    )
    assert called["resolve"] == 0                 # 旁路：未调 resolve_scopes
    assert called["chain_directive"] == "横评指令" # 旁路：directive 覆盖生效
