# sidecar/tests/test_generate_cancel.py
"""Cooperative-cancel wiring for /api/generate jobs.

完整 happy-path（真 vault + LLM）太重；这里测线路：
request_cancel 的 live 语义、checkpoint 抛取消、路由返回值。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from csm_sidecar.services import generate_service


@pytest.fixture(autouse=True)
def _clean_cancel_state():
    yield
    with generate_service._state_lock:
        generate_service._live.clear()
        generate_service._cancelled.clear()


def test_cancel_unknown_job_returns_ok_false(client: TestClient):
    resp = client.post("/api/generate/no-such-job/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "no-such-job", "ok": False}


def test_request_cancel_lifecycle():
    jid = "job-under-test"
    assert generate_service.request_cancel(jid) is False  # not live
    with generate_service._state_lock:
        generate_service._live.add(jid)
    assert generate_service.request_cancel(jid) is True   # newly marked
    assert generate_service.request_cancel(jid) is False  # already marked


def test_checkpoint_raises_only_when_cancelled():
    jid = "job-checkpoint"
    with generate_service._state_lock:
        generate_service._live.add(jid)
    generate_service._checkpoint(jid)  # 未取消 → 不抛
    generate_service.request_cancel(jid)
    with pytest.raises(generate_service._CancelledGenerate):
        generate_service._checkpoint(jid)
