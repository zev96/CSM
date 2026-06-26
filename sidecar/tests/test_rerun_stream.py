"""Part 2 Unit A: _rerun_job 异步 worker（流式 + 取消 + cost）。"""
from __future__ import annotations

from csm_sidecar.services import chain_service, generate_service


def _seed(job_id: str, client):
    chain_service.reset_for_test()
    steps = [
        chain_service.ChainStepInput(skill_id="p", role="persona", name="人设", body="P"),
        chain_service.ChainStepInput(skill_id="h", role="humanize", name="去AI味", body="H"),
    ]
    chain_service.run_chain(
        job_id, steps, draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model="deepseek-chat", client=client,
        checkpoint=lambda: None, on_pass=lambda p: None,
    )


class _Seq:
    def __init__(self, start=0): self.n = start
    def complete(self, *, system, user, temperature=None):
        self.n += 1; return f"R{self.n}"


def _wire_bus(monkeypatch):
    events: list = []
    finish: dict = {}
    fail: dict = {}
    monkeypatch.setattr(generate_service.bus, "publish", lambda j, kind, **d: events.append((kind, d)))
    monkeypatch.setattr(generate_service.bus, "finish", lambda j, **d: finish.update(d))
    monkeypatch.setattr(generate_service.bus, "fail", lambda j, **d: fail.update(d, error=d.get("error")))
    monkeypatch.setattr(generate_service.bus, "create_job", lambda j=None: j)
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: _Seq(start=50))
    return {"events": events, "finish": finish, "fail": fail}


def test_rerun_job_streams_and_finishes_with_cost(monkeypatch):
    _seed("job-rr", _Seq())
    cap = _wire_bus(monkeypatch)
    generate_service._rerun_job("job-rr", 0)
    pass_idx = [d["index"] for k, d in cap["events"] if k == "pass"]
    assert pass_idx == [0, 1]
    fin = cap["finish"]
    assert len(fin["passes"]) == 2
    assert fin["final_text"] == fin["passes"][-1]["output"]
    assert fin["cost"]["currency"] == "CNY" and fin["cost"]["cost"] is not None


def test_rerun_job_cancel(monkeypatch):
    _seed("job-rrc", _Seq())
    cap = _wire_bus(monkeypatch)
    with generate_service._state_lock:
        generate_service._cancelled.add("job-rrc")
    generate_service._rerun_job("job-rrc", 0)
    assert cap["fail"].get("cancelled") is True
    assert not cap["finish"]


def test_rerun_job_cache_miss(monkeypatch):
    chain_service.reset_for_test()
    cap = _wire_bus(monkeypatch)
    generate_service._rerun_job("nope", 0)
    assert cap["fail"].get("error")  # KeyError cache miss → fail
