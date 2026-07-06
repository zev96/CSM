"""反馈/事实路由 —— /api/feedback/stats、/api/facts/changes、export 采集钩子。"""
from csm_core.feedback import storage as fb
from csm_sidecar.services import export_service, fact_service
from csm_sidecar.services import feedback_service as fbs


def test_feedback_stats_empty(client, monitor_db):
    r = client.get("/api/feedback/stats")
    assert r.status_code == 200
    assert r.json() == {"notes": [], "angles": []}


def test_facts_changes_empty(client, monitor_db):
    fact_service.reset_for_test()
    r = client.get("/api/facts/changes")
    assert r.status_code == 200
    assert r.json() == {"changes": []}


def test_export_route_records_feedback(client, monitor_db, monkeypatch):
    """POST /api/export/{fmt} 带 job_id → record_export 落一行；document_path 存 history 镜像。"""
    fbs.reset_for_test()
    monkeypatch.setattr(export_service, "export", lambda **k: {
        "document": "/out/a.md", "format": "markdown",
        "history_path": "/hist/a.md", "title": "A"})
    fbs.stash_request("jobR", {
        "mode": "normal", "keyword": "k", "template_id": "t", "title": "A",
        "angle_json": None, "skill_chain_json": None, "models_json": None, "contract_mode": None})
    r = client.post("/api/export/markdown",
                    json={"keyword": "k", "final_text": "成稿正文", "job_id": "jobR", "score": 80.0})
    assert r.status_code == 200
    row = fb.get_conn().execute(
        "SELECT document_path, score FROM creation_records WHERE job_id='jobR'").fetchone()
    assert row is not None
    assert row["document_path"] == "/hist/a.md"  # 优先存 history 镜像路径（供 list_recent join）
    assert row["score"] == 80.0


def test_export_route_without_job_id_no_record(client, monitor_db, monkeypatch):
    fbs.reset_for_test()
    monkeypatch.setattr(export_service, "export", lambda **k: {
        "document": "/out/b.md", "format": "markdown", "history_path": "/hist/b.md", "title": "B"})
    r = client.post("/api/export/markdown", json={"keyword": "k", "final_text": "成稿正文"})
    assert r.status_code == 200
    assert fb.get_conn().execute("SELECT COUNT(*) FROM creation_records").fetchone()[0] == 0
