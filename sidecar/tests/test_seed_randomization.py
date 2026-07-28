"""素材随机组合的种子契约测试。

根因回归：Tauri 前端单篇恒发 seed=0、批量不发 seed（后端默认 0 且批内所有
关键词共用），而素材抽样完全由 (seed, block.id) 决定 —— 于是不同关键词
生成的文章素材逐字节相同（「素材固定、按顺序往下组合」）。老 PyQt6 栈的
「每次随机滚种子」语义在 Tauri 重写时丢失。

修复后的契约：
- 请求不带 seed（None）→ 服务端滚一个随机种子（roll_seed），贯穿
  assemble_plan 与 reroll 用的 plan 缓存；
- 显式 seed → 原样生效（同种子复现语义保留，测试/调试可用）；
- 批量：每个关键词派生独立基准 seed = 批次基准 + (index-1)*1_000_000，
  候选 k 在其上加 (k-1)*1000（沿用既有候选间隔），version_seed = 该词
  基准 —— 同词 K 个候选仍落在同一结构版本（评分公平性不变），不同词
  各自随机抽版本。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from csm_core.assembler.constraints import roll_seed
from csm_core.assembler.plan import AssemblyPlan
from csm_sidecar.services import assembler_service, batch_service, generate_service


# ── helpers ────────────────────────────────────────────────────────────────
def _setup_minimal_world(client: TestClient, tmp_path: Path) -> dict[str, Path]:
    """最小可跑通 generate/batch 的 config + vault + 模板（同 batch 路由测试）。"""
    vault = tmp_path / "vault"
    out = tmp_path / "out"
    tpls = tmp_path / "tpls"
    vault.mkdir()
    out.mkdir()
    tpls.mkdir()
    (vault / "stub.md").write_text(
        "---\nmodule: any\n---\n# stub\n", encoding="utf-8"
    )
    template_body = {
        "id": "tpl1",
        "name": "演示",
        "product": "无线吸尘器",
        "template_type": "导购文",
        "default_skill_id": None,
        "blocks": [
            {"kind": "heading", "id": "h1", "level": 2, "text": "标题"},
        ],
    }
    (tpls / "tpl1.json").write_text(
        json.dumps(template_body, ensure_ascii=False), encoding="utf-8"
    )
    client.patch("/api/config", json={
        "vault_root": str(vault),
        "out_dir": str(out),
        "default_template": str(tpls / "tpl1.json"),
        "default_provider": "mock",
    })
    return {"vault": vault, "out": out, "tpls": tpls}


def _drain_sse(client: TestClient, url: str, *, deadline_seconds: float) -> str:
    """读 SSE 直到 error/done 的 data 行或超时（同 generate 路由测试的读法）。"""
    raw: list[str] = []
    deadline = time.monotonic() + deadline_seconds
    last_event: str | None = None
    with client.stream("GET", url) as r:
        for line in r.iter_lines():
            raw.append(line)
            if line.startswith("event: "):
                last_event = line.removeprefix("event: ").strip()
            if line == "" and last_event in ("error", "done"):
                break
            if time.monotonic() > deadline:
                break
    return "\n".join(raw)


def _wait_batch_finished(job_id: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = batch_service.get_state(job_id)
        if st is not None and st.finished_at is not None:
            return st.to_dict()
        time.sleep(0.05)
    return None


def _fake_plan(keyword: str, seed: int) -> AssemblyPlan:
    return AssemblyPlan(keyword=keyword, template_id="tpl1", seed=seed)


# ── roll_seed 本体 ─────────────────────────────────────────────────────────
def test_roll_seed_range_and_variety():
    """31-bit 非负整数；连滚多次必须出现不同值（全同概率 ~2^-31·n，视为不可能）。"""
    values = [roll_seed() for _ in range(64)]
    assert all(isinstance(v, int) and 0 <= v < 2**31 for v in values)
    assert len(set(values)) > 1


# ── 单篇 generate ──────────────────────────────────────────────────────────
def test_generate_omitted_seed_rolls_random(client: TestClient, tmp_path: Path, monkeypatch):
    """不带 seed 起飞 → 用 roll_seed() 的值采样，并写进 reroll 的 plan 缓存。"""
    _setup_minimal_world(client, tmp_path)
    monkeypatch.setattr(generate_service, "roll_seed", lambda: 424242)
    captured: list[int] = []

    def fake_assemble(**kw):
        captured.append(kw["seed"])
        return _fake_plan(kw["keyword"], kw["seed"])

    monkeypatch.setattr(generate_service, "assemble_plan", fake_assemble)

    body = {"keyword": "空气净化器哪个牌子好", "template_id": "tpl1", "draft_only": True}
    job_id = client.post("/api/generate", json=body).json()["job_id"]
    joined = _drain_sse(client, f"/api/events/{job_id}", deadline_seconds=5.0)
    assert "event: done" in joined

    assert captured == [424242]
    entry = assembler_service.get_plan(job_id)
    assert entry is not None and entry.seed == 424242


def test_generate_explicit_seed_honored(client: TestClient, tmp_path: Path, monkeypatch):
    """显式 seed=7 → 原样生效，绝不重滚（复现语义零回归）。"""
    _setup_minimal_world(client, tmp_path)

    def _boom():
        raise AssertionError("explicit seed must not trigger roll_seed")

    monkeypatch.setattr(generate_service, "roll_seed", _boom)
    captured: list[int] = []

    def fake_assemble(**kw):
        captured.append(kw["seed"])
        return _fake_plan(kw["keyword"], kw["seed"])

    monkeypatch.setattr(generate_service, "assemble_plan", fake_assemble)

    body = {
        "keyword": "空气净化器哪个牌子好", "template_id": "tpl1",
        "seed": 7, "draft_only": True,
    }
    job_id = client.post("/api/generate", json=body).json()["job_id"]
    joined = _drain_sse(client, f"/api/events/{job_id}", deadline_seconds=5.0)
    assert "event: done" in joined
    assert captured == [7]


def test_generate_explicit_seed_zero_honored(client: TestClient, tmp_path: Path, monkeypatch):
    """显式 seed=0 也必须原样生效 —— 判空必须是 ``is not None``，谁把它重构成
    真值判断（``req.seed or roll_seed()``），0 就会被静默重滚，而 0 恰是旧
    前端唯一发过的值。"""
    _setup_minimal_world(client, tmp_path)

    def _boom():
        raise AssertionError("explicit seed=0 must not trigger roll_seed")

    monkeypatch.setattr(generate_service, "roll_seed", _boom)
    captured: list[int] = []

    def fake_assemble(**kw):
        captured.append(kw["seed"])
        return _fake_plan(kw["keyword"], kw["seed"])

    monkeypatch.setattr(generate_service, "assemble_plan", fake_assemble)

    body = {"keyword": "净化器", "template_id": "tpl1", "seed": 0, "draft_only": True}
    job_id = client.post("/api/generate", json=body).json()["job_id"]
    joined = _drain_sse(client, f"/api/events/{job_id}", deadline_seconds=5.0)
    assert "event: done" in joined
    assert captured == [0]


def test_generate_two_omitted_seed_jobs_use_fresh_rolls(
    client: TestClient, tmp_path: Path, monkeypatch,
):
    """连续两次不带 seed 起飞 → 每次都重滚（素材组合不再固定）。"""
    _setup_minimal_world(client, tmp_path)
    rolls = iter([111, 222])
    monkeypatch.setattr(generate_service, "roll_seed", lambda: next(rolls))
    captured: list[int] = []

    def fake_assemble(**kw):
        captured.append(kw["seed"])
        return _fake_plan(kw["keyword"], kw["seed"])

    monkeypatch.setattr(generate_service, "assemble_plan", fake_assemble)

    for _ in range(2):
        body = {"keyword": "净化器", "template_id": "tpl1", "draft_only": True}
        job_id = client.post("/api/generate", json=body).json()["job_id"]
        joined = _drain_sse(client, f"/api/events/{job_id}", deadline_seconds=5.0)
        assert "event: done" in joined
    assert captured == [111, 222]


# ── 批量 batch ─────────────────────────────────────────────────────────────
def test_batch_per_keyword_seed_derivation(client: TestClient, tmp_path: Path, monkeypatch):
    """批量不带 seed：滚随机基准；批内每个关键词独立派生（这是本 bug 的主症状：
    过去所有关键词共用同一 seed，素材逐字节相同）。候选间隔 1000 保留；
    version_seed = 该词基准（同词候选同版本）。"""
    _setup_minimal_world(client, tmp_path)
    monkeypatch.setattr(batch_service, "roll_seed", lambda: 5_000_000)
    calls: list[tuple[str, int, int | None]] = []

    def fake_assemble(**kw):
        calls.append((kw["keyword"], kw["seed"], kw.get("version_seed")))
        return _fake_plan(kw["keyword"], kw["seed"])

    monkeypatch.setattr(batch_service, "assemble_plan", fake_assemble)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1", "kw2", "kw3"],
        "template_id": "tpl1",
        "candidates": 2,
    })
    assert resp.status_code == 202
    snap = _wait_batch_finished(resp.json()["job_id"], timeout=15.0)
    assert snap is not None

    by_kw: dict[str, list[tuple[int, int | None]]] = {}
    for kw, seed, vseed in calls:
        by_kw.setdefault(kw, []).append((seed, vseed))

    expected_bases = {"kw1": 5_000_000, "kw2": 6_000_000, "kw3": 7_000_000}
    for kw, base in expected_bases.items():
        assert by_kw[kw] == [(base, base), (base + 1000, base)], (
            f"{kw}: got {by_kw[kw]}"
        )
    # 三个关键词的素材种子互不相同 —— 修的就是这个。
    material_seeds = {s for _, s, _ in calls}
    assert len(material_seeds) == 6


def test_batch_explicit_seed_reproducible(client: TestClient, tmp_path: Path, monkeypatch):
    """显式 seed=1234 → 派生完全确定（1234 / 1_001_234），不滚随机。"""
    _setup_minimal_world(client, tmp_path)

    def _boom():
        raise AssertionError("explicit seed must not trigger roll_seed")

    monkeypatch.setattr(batch_service, "roll_seed", _boom)
    calls: list[tuple[str, int, int | None]] = []

    def fake_assemble(**kw):
        calls.append((kw["keyword"], kw["seed"], kw.get("version_seed")))
        return _fake_plan(kw["keyword"], kw["seed"])

    monkeypatch.setattr(batch_service, "assemble_plan", fake_assemble)

    resp = client.post("/api/batch", json={
        "keywords": ["kw1", "kw2"],
        "template_id": "tpl1",
        "seed": 1234,
    })
    assert resp.status_code == 202
    snap = _wait_batch_finished(resp.json()["job_id"], timeout=15.0)
    assert snap is not None
    assert calls == [
        ("kw1", 1234, 1234),
        ("kw2", 1_001_234, 1_001_234),
    ]
