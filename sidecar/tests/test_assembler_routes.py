"""Tests for /api/assembler/reroll.

The csm_core reroll_pick logic is exercised by tests/core/assembler/* —
here we just verify the sidecar wrapper:

  * cache miss → 404
  * NoCandidatesError → 409
  * happy path → updated plan + new draft text returned
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.assembler.reroll import NoCandidatesError
from csm_sidecar.services import assembler_service


@pytest.fixture(autouse=True)
def reset_cache():
    assembler_service.reset_for_test()
    yield
    assembler_service.reset_for_test()


def _seed_plan() -> AssemblyPlan:
    return AssemblyPlan(
        keyword="测试关键词",
        template_id="t1",
        seed=42,
        results=[
            BlockResult(
                block_id="p1",
                kind="paragraph",
                picks=[
                    PickedVariant(note_id="n1", variant_index=0, text="原文"),
                ],
                text="原文",
            ),
        ],
    )


def test_unknown_job_id_returns_404(client: TestClient):
    resp = client.post("/api/assembler/reroll", json={
        "job_id": "no-such-job", "block_id": "p1", "pick_index": 0,
    })
    assert resp.status_code == 404
    assert "unknown job_id" in resp.json()["detail"]


def test_invalid_body_422(client: TestClient):
    # Missing pick_index, negative pick_index — Pydantic rejects.
    resp = client.post("/api/assembler/reroll", json={
        "job_id": "x", "block_id": "p1", "pick_index": -1,
    })
    assert resp.status_code == 422


def test_no_candidates_returns_409(client: TestClient, monkeypatch, tmp_path):
    # Pre-populate the cache so the route gets past the lookup, then
    # patch reroll_pick to raise NoCandidatesError.
    plan = _seed_plan()
    assembler_service.cache_plan(
        "job-x", plan, template_id="t1", seed=42,
    )

    # Provide a vault_root + a template file so the route gets to the
    # reroll_pick call (we patch it before it actually runs).
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "stub.md").write_text("---\nx: 1\n---\nx", encoding="utf-8")
    tdir = tmp_path / "tpls"
    tdir.mkdir()
    (tdir / "t1.json").write_text(
        '{"id":"t1","name":"t","product":"p","blocks":'
        '[{"kind":"heading","id":"h","level":2,"text":"x"}]}',
        encoding="utf-8",
    )
    client.patch("/api/config", json={
        "vault_root": str(vault),
        "default_template": str(tdir / "t1.json"),
    })

    def boom(*a, **kw):
        raise NoCandidatesError("source pool exhausted")

    monkeypatch.setattr(
        "csm_sidecar.services.assembler_service.reroll_pick", boom,
    )
    resp = client.post("/api/assembler/reroll", json={
        "job_id": "job-x", "block_id": "p1", "pick_index": 0,
    })
    assert resp.status_code == 409
    assert "exhausted" in resp.json()["detail"]


def test_happy_path_returns_updated_plan_and_draft(
    client: TestClient, monkeypatch, tmp_path: Path,
):
    plan = _seed_plan()
    assembler_service.cache_plan(
        "job-y", plan, template_id="t1", seed=42,
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "stub.md").write_text("---\nx: 1\n---\nx", encoding="utf-8")
    tdir = tmp_path / "tpls"
    tdir.mkdir()
    (tdir / "t1.json").write_text(
        '{"id":"t1","name":"t","product":"p","blocks":'
        '[{"kind":"heading","id":"h","level":2,"text":"x"}]}',
        encoding="utf-8",
    )
    client.patch("/api/config", json={
        "vault_root": str(vault),
        "default_template": str(tdir / "t1.json"),
    })

    # Fake reroll_pick: swap the pick text to "新文本".
    def fake_reroll(plan_in, block_id, pick_index, *_args, **_kw):
        new_plan = plan_in.model_copy(deep=True)
        result = new_plan.get_result(block_id)
        assert result is not None
        result.picks[pick_index] = PickedVariant(
            note_id="n2", variant_index=0, text="新文本",
        )
        result.text = "新文本"
        return new_plan

    monkeypatch.setattr(
        "csm_sidecar.services.assembler_service.reroll_pick", fake_reroll,
    )
    monkeypatch.setattr(
        "csm_sidecar.services.assembler_service.compose_draft",
        lambda p: "draft after reroll",
    )

    resp = client.post("/api/assembler/reroll", json={
        "job_id": "job-y", "block_id": "p1", "pick_index": 0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["draft"] == "draft after reroll"
    # Plan was serialized via model_dump.
    assert data["plan"]["keyword"] == "测试关键词"
    p1 = next(r for r in data["plan"]["results"] if r["block_id"] == "p1")
    assert p1["picks"][0]["text"] == "新文本"

    # Cache was updated — second reroll uses the *new* plan as input.
    captured: dict[str, Any] = {}

    def capture(plan_in, block_id, pick_index, *_a, **_kw):
        captured["text"] = plan_in.get_result(block_id).picks[pick_index].text
        raise NoCandidatesError("done")

    monkeypatch.setattr(
        "csm_sidecar.services.assembler_service.reroll_pick", capture,
    )
    client.post("/api/assembler/reroll", json={
        "job_id": "job-y", "block_id": "p1", "pick_index": 0,
    })
    assert captured["text"] == "新文本"


def test_lru_eviction(client: TestClient):
    """The cache caps at MAX_CACHE entries; oldest entry is evicted."""
    cap = assembler_service.MAX_CACHE
    plan = _seed_plan()
    # Push cap + 3 jobs; the first 3 should be gone afterwards.
    for i in range(cap + 3):
        assembler_service.cache_plan(
            f"job-{i}", plan, template_id="t1", seed=i,
        )
    assert assembler_service.get_plan("job-0") is None
    assert assembler_service.get_plan("job-1") is None
    assert assembler_service.get_plan("job-2") is None
    assert assembler_service.get_plan(f"job-{cap + 2}") is not None
