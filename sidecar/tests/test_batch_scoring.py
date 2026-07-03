"""批量链路升级 —— 注入/链/核对计数/评分/多候选选优/total_cost。

复用 test_batch_routes.py 的 tmp-vault + template + mock LLM 装置风格：走
真实 client fixture（settings_path + vault_cache_reset），只 monkeypatch
LLM client（llm_factory.build_client）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from csm_sidecar.services import batch_service


# ── Helpers ──────────────────────────────────────────────────────────────
def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


VAULT_MODULE = "营销资料库/产品模块/吸尘器"


def _brand_vault(root: Path) -> None:
    """真实型号笔记（镜像 test_brand_memory_service.py 的装置）——
    CEWEYDS18: 吸力(AW)=220, 转速=12万转, 认证 CE、FCC。own_brands 默认
    含 CEWEY，故 role=主推。"""
    _w(root / VAULT_MODULE / "产品参数/CEWEYDS18-产品参数.md",
       "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
       "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 220 |\n"
       "| 电机转速 | 12万转 |\n\n"
       "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 认证检测 | CE、FCC |\n")


def _hero_template(tpls: Path, tpl_id: str = "tpl-hero") -> None:
    """含 hero_brand(title=CEWEYDS18) 的模板 —— HeroBrandBlock 只需静态
    title，不需要 notes_query（sampler.py 直接把 title 渲进 text），
    resolve_scopes 靠 _model_candidates 抓 hero_brand.text 命中 registry。"""
    body = {
        "id": tpl_id,
        "name": "hero 测试模板",
        "product": "吸尘器",
        "template_type": "导购文",
        "default_skill_id": None,
        "blocks": [
            {"kind": "heading", "id": "h1", "level": 2, "text": "标题"},
            {"kind": "hero_brand", "id": "hero1", "title": "CEWEYDS18"},
        ],
    }
    (tpls / f"{tpl_id}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def _plain_template(tpls: Path, tpl_id: str = "tpl-plain") -> None:
    """无 hero_brand 的最简模板（镜像 test_batch_routes._setup_minimal_world）。"""
    body = {
        "id": tpl_id,
        "name": "演示",
        "product": "无线吸尘器",
        "template_type": "导购文",
        "default_skill_id": None,
        "blocks": [
            {"kind": "heading", "id": "h1", "level": 2, "text": "标题"},
        ],
    }
    (tpls / f"{tpl_id}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def _setup_world(
    client: TestClient, tmp_path: Path, *, with_brand_vault: bool = False,
    template_id: str = "tpl-plain", extra_config: dict | None = None,
) -> dict[str, Path]:
    vault = tmp_path / "vault"
    out = tmp_path / "out"
    tpls = tmp_path / "tpls"
    vault.mkdir()
    out.mkdir()
    tpls.mkdir()
    (vault / "stub.md").write_text("---\nmodule: any\n---\n# stub\n", encoding="utf-8")
    if with_brand_vault:
        _brand_vault(vault)
    _plain_template(tpls)
    _hero_template(tpls)

    cfg_patch: dict[str, Any] = {
        "vault_root": str(vault),
        "out_dir": str(out),
        "default_template": str(tpls / f"{template_id}.json"),
        "default_provider": "mock",
    }
    if extra_config:
        cfg_patch.update(extra_config)
    client.patch("/api/config", json=cfg_patch)
    return {"vault": vault, "out": out, "tpls": tpls}


def _wait_for_finished(job_id: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = batch_service.get_state(job_id)
        if st is not None and st.finished_at is not None:
            return st.to_dict()
        time.sleep(0.05)
    return None


class _SeqClient:
    """按调用顺序循环吐出固定文本列表（每次 complete 前进一格）。"""

    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        idx = len(self.calls) % len(self.outputs)
        self.calls.append((system, user))
        return self.outputs[idx]


AI_HEAVY = (
    "首先，吸力是选购吸尘器的核心指标。其次，续航能力同样值得关注。最后，噪音水平不容忽视。\n\n"
    "总的来说，这款产品表现出色。值得一提的是，它不是简单的清洁工具，而是智能家居的入口。"
    "不仅性能强劲，更在细节处体现匠心。众所周知，除螨需要强吸力。\n\n"
    "总之，综合来看这是一款值得推荐的产品。"
)
CLEAN_HUMAN = (
    "上周把家里那台老吸尘器换掉了。原因说来好笑：猫毛缠进滚刷，拆了半小时。\n\n"
    "新机器用了十天，地毯上的猫毛一遍过。楼下邻居问我是不是换了保洁阿姨。\n\n"
    "要说缺点也有，尘杯小了点，倒得勤。但对我这种懒人，能少拆一次刷头就是胜利。"
)


def _patch_client(monkeypatch, client_obj) -> None:
    from csm_sidecar.services import chain_service
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: client_obj)


# ── 1) candidates=2：高分候选导出 + 落选稿落盘 + 事件字段 ──────────────────
def test_candidates_two_picks_higher_score_and_saves_loser(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    _setup_world(client, tmp_path, template_id="tpl-plain")
    seq = _SeqClient([AI_HEAVY, CLEAN_HUMAN])  # 候选1差、候选2好
    _patch_client(monkeypatch, seq)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1"], "template_id": "tpl-plain", "candidates": 2,
    })
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    item = snap["items"][0]
    assert item["status"] == "success"
    assert item["score"] is not None
    assert len(item["candidate_scores"]) == 2
    assert len(item["score_parts"]) <= 3
    # 候选2（CLEAN_HUMAN）AI 味更低 → 分更高 → 应为导出胜者
    assert seq.calls == 2 * seq.calls[:1] + seq.calls[1:] or len(seq.calls) == 2
    assert item["candidate_scores"][1] > item["candidate_scores"][0]
    doc_path = Path(item["document"])
    assert doc_path.exists()
    exported = doc_path.read_text(encoding="utf-8")
    assert "猫毛缠进滚刷" in exported  # 高分候选（CLEAN_HUMAN）内容
    assert "首先，吸力是选购吸尘器的核心指标" not in exported

    # 落选稿存在 candidates/ 目录，文件名含分数
    cand_dir = tmp_path / "out" / f"batch-{job_id[:8]}" / "candidates"
    assert cand_dir.is_dir()
    saved = list(cand_dir.glob("*.md"))
    assert len(saved) == 1
    assert any(c.isdigit() for c in saved[0].stem.split("-")[-1])


# ── 2) candidates=1（默认）零回归 ──────────────────────────────────────────
def test_candidates_default_one_zero_regression(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    _setup_world(client, tmp_path, template_id="tpl-plain")
    seq = _SeqClient([CLEAN_HUMAN])
    _patch_client(monkeypatch, seq)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1", "kw2"], "template_id": "tpl-plain",
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    # candidates=1 默认 → 每关键词恰 1 次 complete（N=2 keywords → 2 calls）
    assert len(seq.calls) == 2
    for item in snap["items"]:
        assert item["status"] == "success"
        assert item["score"] is not None  # 免费评分仍带
        assert item["candidate_scores"] == [item["score"]]
    cand_dir = tmp_path / "out" / f"batch-{job_id[:8]}" / "candidates"
    assert not cand_dir.exists()  # 不建 candidates/ 目录


# ── 3) inject 开：user prompt 含品牌型号事实 ───────────────────────────────
def test_inject_on_prompt_carries_brand_facts(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    _setup_world(
        client, tmp_path, with_brand_vault=True, template_id="tpl-hero",
        extra_config={"brand_memory": {"inject": True}},
    )
    seq = _SeqClient([CLEAN_HUMAN])
    _patch_client(monkeypatch, seq)

    resp = client.post("/api/batch", json={
        "keywords": ["无线吸尘器"], "template_id": "tpl-hero",
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    assert snap["items"][0]["status"] == "success"
    assert len(seq.calls) == 1
    user_prompt = seq.calls[0][1]
    assert "CEWEY" in user_prompt and "220" in user_prompt


# ── 4) factcheck 开 + 越界数字：计数不拦 ───────────────────────────────────
def test_factcheck_on_violation_counts_not_blocks(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    _setup_world(
        client, tmp_path, with_brand_vault=True, template_id="tpl-hero",
        extra_config={"brand_memory": {"factcheck": True}},
    )
    # 成稿编造一个不在白名单里的数字（999AW），触发越界。
    seq = _SeqClient(["测评发现吸力高达999AW，表现优异。"])
    _patch_client(monkeypatch, seq)

    resp = client.post("/api/batch", json={
        "keywords": ["无线吸尘器"], "template_id": "tpl-hero",
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    item = snap["items"][0]
    assert item["status"] == "success"  # 绝不是 blocked/failed
    assert item["factcheck_violations"] > 0
    assert item["score"] is not None
    assert item["score"] < 100.0  # 因核对违规被扣分


# ── 5) done 事件带 total_cost ───────────────────────────────────────────
def test_done_carries_total_cost(client: TestClient, tmp_path: Path, monkeypatch):
    _setup_world(client, tmp_path, template_id="tpl-plain")
    seq = _SeqClient([CLEAN_HUMAN])
    _patch_client(monkeypatch, seq)

    resp = client.post("/api/batch", json={"keywords": ["kw1"], "template_id": "tpl-plain"})
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    st = batch_service.get_state(job_id)
    assert st is not None
    summary = batch_service._summary(st)
    assert "total_cost" not in summary  # _summary 本身不带；由 _run_job 追加进 bus.finish

    # 通过 bus.finish 落地验证：monkeypatch 截获
    calls: dict = {}
    monkeypatch.setattr(batch_service.bus, "finish", lambda job_id, **d: calls.update(d))
    resp2 = client.post("/api/batch", json={"keywords": ["kw2"], "template_id": "tpl-plain"})
    job_id2 = resp2.json()["job_id"]
    _wait_for_finished(job_id2, timeout=10.0)
    assert "total_cost" in calls
    tc = calls["total_cost"]
    assert set(tc.keys()) == {"input_tokens", "output_tokens", "cost", "currency"}
    assert tc["input_tokens"] > 0


# ── 6) skill_chain=[两个合成 skill]：每候选 2 次 complete ─────────────────
def test_skill_chain_two_skills_two_passes_per_candidate(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    world = _setup_world(client, tmp_path, template_id="tpl-plain")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _w(skills_dir / "人设.md", "---\nname: 克制理性\nrole: persona\n---\n人设BODY")
    _w(skills_dir / "去味.md", "---\nname: 去AI味\nrole: humanize\n---\n去味BODY")
    client.patch("/api/config", json={"skill_dir": str(skills_dir)})

    seq = _SeqClient([CLEAN_HUMAN])
    _patch_client(monkeypatch, seq)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1"], "template_id": "tpl-plain",
        "skill_chain": ["人设", "去味"],
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    assert snap["items"][0]["status"] == "success"
    # candidates=1（默认）× 2 pass/candidate = 2 次 complete
    assert len(seq.calls) == 2


# ── 7) 候选级故障隔离：后败不弃先胜 ───────────────────────────────────────
class _FlakyClient:
    """第 1 次 complete 成功、之后全 raise —— 模拟候选 2 的 LLM 故障。"""

    def __init__(self, first_out: str):
        self.first_out = first_out
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.calls.append((system, user))
        if len(self.calls) == 1:
            return self.first_out
        raise ValueError("boom-LLM")


def test_candidate_failure_keeps_earlier_winner(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    """候选 2 抛异常不拖垮整词：候选 1 优胜稿照常导出、item=success。"""
    _setup_world(client, tmp_path, template_id="tpl-plain")
    flaky = _FlakyClient(CLEAN_HUMAN)
    _patch_client(monkeypatch, flaky)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1"], "template_id": "tpl-plain", "candidates": 2,
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    item = snap["items"][0]
    assert item["status"] == "success"          # 候选2失败不弃候选1优胜
    assert item["error_type"] is None
    assert item["candidate_scores"] is not None and len(item["candidate_scores"]) == 1
    assert item["document"] is not None
    assert "猫毛缠进滚刷" in Path(item["document"]).read_text(encoding="utf-8")
    assert len(flaky.calls) == 2                # 两个候选都真的尝试过
    # 失败候选没有产出 → 不该有 candidates/ 落选稿残留
    cand_dir = tmp_path / "out" / f"batch-{job_id[:8]}" / "candidates"
    assert not cand_dir.exists()


# ── 8a) 取消打断（k=1 已成）→ 该词 success 只带 1 个候选、后续词 cancelled ──
class _CancelAfterFirstClient:
    """k=1 的 complete 成功并顺手标记取消 → 内层在 k=2 前退出。"""

    def __init__(self, out: str):
        self.out = out
        self.calls = 0

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.calls += 1
        with batch_service._lock:
            for st in batch_service._states.values():
                if st.finished_at is None:
                    st.cancel_requested = True
        return self.out


def test_cancel_after_first_candidate_keeps_winner_and_cancels_rest(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    """取消落在 k=1 成功之后：该词以候选1成稿 success；第二个词 cancelled 非 failed。"""
    _setup_world(client, tmp_path, template_id="tpl-plain")
    cac = _CancelAfterFirstClient(CLEAN_HUMAN)
    _patch_client(monkeypatch, cac)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1", "kw2"], "template_id": "tpl-plain", "candidates": 2,
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    it1, it2 = snap["items"]
    assert it1["status"] == "success"           # 已花钱的候选1保住
    assert len(it1["candidate_scores"]) == 1    # k=2 没跑
    assert cac.calls == 1                       # 只有 1 次 complete
    assert it2["status"] == "cancelled"         # 第二个词是取消，不是失败
    assert it2["error_type"] is None


# ── 8b) 取消打断且零成稿 → cancelled 不是 failed ───────────────────────────
class _FailAndCancelClient:
    """complete 即标记取消并 raise —— 候选1败 + 取消打断候选2 → 零成稿。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.calls += 1
        with batch_service._lock:
            for st in batch_service._states.values():
                if st.finished_at is None:
                    st.cancel_requested = True
        raise ValueError("boom-then-cancel")


def test_cancel_with_no_candidate_marks_cancelled_not_failed(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    """取消打断且一个成稿都没有 → item 标 cancelled（不误报 failed）。"""
    _setup_world(client, tmp_path, template_id="tpl-plain")
    fc = _FailAndCancelClient()
    _patch_client(monkeypatch, fc)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1"], "template_id": "tpl-plain", "candidates": 2,
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    item = snap["items"][0]
    assert item["status"] == "cancelled"        # 用户取消，不是失败
    assert item["error_type"] is None
    assert item["document"] is None
    assert fc.calls == 1                        # 候选2被取消打断，没有再调


# ── 9) 全候选失败 → failed 且带真实错误（非内部 RuntimeError 文案）─────────
class _AlwaysBoomClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.calls += 1
        raise ValueError("boom-LLM-always")


def test_all_candidates_fail_marks_failed_with_real_error(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    """所有候选都失败 → item=failed，error_* 是真实底层异常，且每个候选都尝试过。"""
    _setup_world(client, tmp_path, template_id="tpl-plain")
    boom = _AlwaysBoomClient()
    _patch_client(monkeypatch, boom)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1"], "template_id": "tpl-plain", "candidates": 2,
    })
    job_id = resp.json()["job_id"]
    snap = _wait_for_finished(job_id, timeout=10.0)
    assert snap is not None
    item = snap["items"][0]
    assert item["status"] == "failed"
    assert item["error_type"] == "ValueError"
    assert "boom-LLM-always" in (item["error_message"] or "")
    assert boom.calls == 2                      # 候选级隔离：两个候选都尝试过
    assert snap["finished_at"] is not None      # 批任务整体正常收尾
