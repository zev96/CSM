"""feedback/storage.py —— v9 迁移 + CRUD + 统计。全 tmp DB（fresh_db 装置）。"""
from csm_core.feedback import storage as fb
from csm_core.feedback.model import CreationRecord, FactSnapshot, NoteUsage

_ANGLE = '{"audience":"铲屎官","sellpoints":["防缠绕"],"tone":"口语"}'


def _rec(job_id="job-1", **kw) -> CreationRecord:
    base = dict(
        job_id=job_id, mode="normal", keyword="无线吸尘器", template_id="tpl", title="T",
        angle_json=_ANGLE, skill_chain_json='["人设"]', models_json=None,
        contract_mode="aggressive", document_path="/out/a.md", format="markdown",
        edit_ratio=0.1, lint_unresolved=0, factcheck_blocked=0,
        score=88.0, score_json='{"total":88}',
        created_at="2026-07-05T00:00:00Z", exported_at="2026-07-05T00:00:00Z",
    )
    base.update(kw)
    return CreationRecord(**base)


def test_v9_tables_exist(fresh_db):
    conn = fb.get_conn()
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"creation_records", "creation_note_usage",
            "fact_snapshots", "model_fingerprints"} <= names


def test_v9_schema_version(fresh_db):
    # schema_meta tracks the CURRENT global version stamp, not v9 specifically;
    # bumped to "11" by R2's v11 migration (monitor_run_progress), past geo's v10.
    conn = fb.get_conn()
    v = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[0]
    assert v == "11"


def test_record_creation_roundtrip(fresh_db):
    rid = fb.record_creation(
        _rec(),
        [NoteUsage("noteA", 0, "b1"), NoteUsage("noteB", 1, "b2")],
        [FactSnapshot("戴森V12", "fp1", '{"specs":[]}')],
    )
    conn = fb.get_conn()
    assert conn.execute(
        "SELECT COUNT(*) FROM creation_note_usage WHERE record_id=?", (rid,)).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM fact_snapshots WHERE record_id=?", (rid,)).fetchone()[0] == 1
    rec = fb.find_creation_by_document("/out/a.md")
    assert rec is not None
    assert rec.contract_mode == "aggressive" and rec.score == 88.0 and rec.id == rid


def test_record_creation_overwrites_same_job(fresh_db):
    fb.record_creation(_rec(edit_ratio=0.5), [NoteUsage("noteA")], [])
    fb.record_creation(_rec(edit_ratio=0.2), [NoteUsage("noteB")], [])  # 同 job_id → 覆盖
    conn = fb.get_conn()
    assert conn.execute("SELECT COUNT(*) FROM creation_records").fetchone()[0] == 1
    rows = conn.execute("SELECT note_id FROM creation_note_usage").fetchall()
    assert [r[0] for r in rows] == ["noteB"]  # 旧 noteA 级联删，不累加
    assert fb.find_creation_by_document("/out/a.md").edit_ratio == 0.2


def test_fk_cascade_on_delete(fresh_db):
    rid = fb.record_creation(_rec(), [NoteUsage("noteA")], [FactSnapshot("M", "fp", "{}")])
    conn = fb.get_conn()
    conn.execute("DELETE FROM creation_records WHERE id=?", (rid,))
    assert conn.execute("SELECT COUNT(*) FROM creation_note_usage").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM fact_snapshots").fetchone()[0] == 0


def test_baseline_upsert_and_read(fresh_db):
    fb.upsert_model_fingerprints(
        [("戴森V12", "fp1", '{"specs":[["吸力","150AW"]]}')], now="2026-07-05T00:00:00Z")
    fb.upsert_model_fingerprints(
        [("戴森V12", "fp2", '{"specs":[["吸力","230AW"]]}')], now="2026-07-05T01:00:00Z")
    bl = fb.get_model_fingerprints()
    assert bl["戴森V12"][0] == "fp2" and "230AW" in bl["戴森V12"][1]


def test_fact_snapshots_for_record(fresh_db):
    rid = fb.record_creation(
        _rec(), [], [FactSnapshot("A", "fpA", "{}"), FactSnapshot("B", "fpB", "{}")])
    snaps = fb.get_fact_snapshots_for_record(rid)
    assert {s.model for s in snaps} == {"A", "B"}


def test_stats_empty(fresh_db):
    assert fb.get_feedback_stats() == {"notes": [], "angles": []}


def test_stats_shape(fresh_db):
    fb.record_creation(_rec(job_id="j1"), [NoteUsage("noteA")], [])
    fb.record_creation(_rec(job_id="j2", document_path="/out/b.md"), [NoteUsage("noteA")], [])
    s = fb.get_feedback_stats()
    assert s["notes"][0]["note_id"] == "noteA" and s["notes"][0]["uses"] == 2
    assert len(s["angles"]) == 1 and s["angles"][0]["uses"] == 2
    assert s["angles"][0]["audience"] == "铲屎官" and s["angles"][0]["tone"] == "口语"
