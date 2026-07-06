"""get_note_weights —— 聚合/门槛/去重/钳位。全 tmp DB。"""
from csm_core.feedback import storage as fb
from csm_core.feedback.model import CreationRecord, NoteUsage


def _rec(job_id, edit_ratio) -> CreationRecord:
    return CreationRecord(
        job_id=job_id, mode="normal", keyword="k", template_id="t", title=None,
        angle_json=None, skill_chain_json=None, models_json=None, contract_mode=None,
        document_path=f"/out/{job_id}.md", format="markdown", edit_ratio=edit_ratio,
        lint_unresolved=0, factcheck_blocked=0, score=None, score_json=None,
        created_at="2026-07-05T00:00:00Z", exported_at="2026-07-05T00:00:00Z",
    )


def test_weight_high_keep_clamps_upper(fresh_db):
    for i in range(6):
        fb.record_creation(_rec(f"j{i}", 0.0), [NoteUsage("noteHi")], [])  # edit=0 → keep=1
    w = fb.get_note_weights(min_samples=5, alpha=0.5)
    assert w["noteHi"] == 1.5  # 1 + 0.5*(1-0.5)*2 = 1.5（钳位上界）


def test_weight_low_keep_clamps_lower(fresh_db):
    for i in range(6):
        fb.record_creation(_rec(f"j{i}", 1.0), [NoteUsage("noteBad")], [])  # edit=1 → keep=0
    w = fb.get_note_weights(min_samples=5, alpha=0.5)
    assert w["noteBad"] == 0.5  # 1 + 0.5*(0-0.5)*2 = 0.5（钳位下界）


def test_weight_below_threshold_absent(fresh_db):
    for i in range(4):
        fb.record_creation(_rec(f"j{i}", 0.0), [NoteUsage("noteLo")], [])
    assert "noteLo" not in fb.get_note_weights(min_samples=5, alpha=0.5)


def test_weight_null_edit_ratio_excluded(fresh_db):
    for i in range(6):
        fb.record_creation(_rec(f"j{i}", None), [NoteUsage("noteN")], [])  # edit_ratio NULL 不计样本
    assert "noteN" not in fb.get_note_weights(min_samples=5, alpha=0.5)


def test_weight_dedup_same_record(fresh_db):
    # 同一条 record 里 noteZ 出现两次 → 只算 1 样本（3 record < 门槛 5，尽管 6 usage 行）
    for i in range(3):
        fb.record_creation(
            _rec(f"j{i}", 0.0), [NoteUsage("noteZ", 0), NoteUsage("noteZ", 1)], [])
    assert "noteZ" not in fb.get_note_weights(min_samples=5, alpha=0.5)


def test_weight_mid_keep(fresh_db):
    for i in range(5):
        fb.record_creation(_rec(f"j{i}", 0.5), [NoteUsage("noteMid")], [])  # keep=0.5 → w=1.0
    w = fb.get_note_weights(min_samples=5, alpha=0.5)
    assert abs(w["noteMid"] - 1.0) < 1e-9
