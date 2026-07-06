"""feedback_service —— stash + record_export（fail-open）+ weights。tmp DB + config 隔离。"""
from types import SimpleNamespace

import pytest

from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.config import AppConfig
from csm_core.feedback import storage as fb
from csm_core.feedback.model import FactSnapshot
from csm_sidecar.services import assembler_service, chain_service, config_service
from csm_sidecar.services import feedback_service as fbs


@pytest.fixture(autouse=True)
def _reset():
    fbs.reset_for_test()
    yield
    fbs.reset_for_test()


def _snap(mode="normal"):
    return {
        "mode": mode, "keyword": "无线吸尘器", "template_id": "tpl", "title": "T",
        "angle_json": '{"audience":"铲屎官","sellpoints":["防缠绕"],"tone":"口语"}',
        "skill_chain_json": '["人设"]', "models_json": None, "contract_mode": "aggressive",
    }


def _fake_plan(job, monkeypatch, note_id="noteA"):
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0, results=[
        BlockResult(block_id="b1", kind="paragraph", picks=[
            PickedVariant(note_id=note_id, variant_index=0, text="x")])])
    monkeypatch.setattr(assembler_service, "get_plan", lambda jid: SimpleNamespace(plan=plan))


def test_record_export_full_chain(monitor_db, settings_path, monkeypatch):
    job = "jobX"
    fbs.stash_request(job, _snap())
    fbs.stash_scopes(job, [FactSnapshot("戴森V12", "fp1", '{"specs":[]}')])
    _fake_plan(job, monkeypatch)
    monkeypatch.setattr(chain_service, "get_state", lambda jid: SimpleNamespace(final_text="链成稿正文"))
    fbs.record_export(job, document_path="/h/a.md", fmt="markdown",
                      final_text="链成稿正文，改了一点点", score=88.0,
                      score_json='{"total":88}', lint_unresolved=1)
    conn = fb.get_conn()
    row = conn.execute("SELECT * FROM creation_records WHERE job_id=?", (job,)).fetchone()
    assert row is not None
    assert row["contract_mode"] == "aggressive" and row["score"] == 88.0
    assert row["document_path"] == "/h/a.md" and row["lint_unresolved"] == 1
    assert row["edit_ratio"] is not None and row["edit_ratio"] > 0  # 改过 → 非 0
    rid = row["id"]
    assert conn.execute(
        "SELECT note_id FROM creation_note_usage WHERE record_id=?", (rid,)).fetchone()["note_id"] == "noteA"
    assert conn.execute(
        "SELECT model FROM fact_snapshots WHERE record_id=?", (rid,)).fetchone()["model"] == "戴森V12"


def test_record_export_fail_open(monitor_db, settings_path, monkeypatch):
    fbs.stash_request("jobF", _snap())

    def _boom(*a, **k):
        raise RuntimeError("storage boom")

    monkeypatch.setattr(fb, "record_creation", _boom)
    # 不得抛 —— 反馈失败绝不影响导出。
    fbs.record_export("jobF", document_path="/h/a.md", fmt="markdown", final_text="x")


def test_record_export_no_job_id_skips(monitor_db, settings_path):
    fbs.record_export(None, document_path="/h/a.md", fmt="markdown", final_text="x")
    assert fb.get_conn().execute("SELECT COUNT(*) FROM creation_records").fetchone()[0] == 0


def test_record_export_snapshot_miss_skips(monitor_db, settings_path):
    fbs.record_export("ghost", document_path="/h/a.md", fmt="markdown", final_text="x")
    assert fb.get_conn().execute("SELECT COUNT(*) FROM creation_records").fetchone()[0] == 0


def test_record_export_record_off(monitor_db, monkeypatch):
    cfg = AppConfig()
    cfg.feedback.record = False
    monkeypatch.setattr(config_service, "load", lambda: cfg)
    fbs.stash_request("jobOff", _snap())
    fbs.record_export("jobOff", document_path="/h/a.md", fmt="markdown", final_text="x")
    assert fb.get_conn().execute("SELECT COUNT(*) FROM creation_records").fetchone()[0] == 0


def test_edit_ratio_none_when_chain_miss(monitor_db, settings_path, monkeypatch):
    fbs.stash_request("jobNM", _snap())
    _fake_plan("jobNM", monkeypatch)
    monkeypatch.setattr(chain_service, "get_state", lambda jid: None)  # 链缓存 miss
    fbs.record_export("jobNM", document_path="/h/a.md", fmt="markdown", final_text="x")
    row = fb.get_conn().execute("SELECT edit_ratio FROM creation_records WHERE job_id='jobNM'").fetchone()
    assert row is not None and row["edit_ratio"] is None


def test_get_note_weights_rank_gate(monitor_db, monkeypatch):
    cfg = AppConfig()
    monkeypatch.setattr(config_service, "load", lambda: cfg)
    cfg.feedback.rank = False
    assert fbs.get_note_weights() == {}          # rank 关 → {}
    cfg.feedback.rank = True
    # rank 开 → 走 storage（空库返回 {}，但路径不同——至少不抛）
    assert isinstance(fbs.get_note_weights(), dict)


def test_stash_lru_eviction():
    for i in range(fbs.MAX + 5):
        fbs.stash_request(f"j{i}", _snap())
    with fbs._lock:
        assert len(fbs._request_cache) == fbs.MAX
        assert "j0" not in fbs._request_cache  # 最旧被淘汰
        assert f"j{fbs.MAX + 4}" in fbs._request_cache


def test_get_note_weights_fail_open(monitor_db, monkeypatch):
    # 红线：rank 开 + storage 抛 → 退回 {}（不抛），生成热路径不受反馈层拖垮。
    cfg = AppConfig()
    cfg.feedback.rank = True
    monkeypatch.setattr(config_service, "load", lambda: cfg)

    def _boom(*a, **k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(fb, "get_note_weights", _boom)
    assert fbs.get_note_weights() == {}  # fail-open → 均匀采样（零回归）
