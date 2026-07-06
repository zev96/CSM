"""list_recent §7.3 增强 —— facts_stale/stale_models/record + 形状兼容。tmp DB。"""
from csm_core.feedback import storage as fb
from csm_core.feedback.model import CreationRecord, FactSnapshot
from csm_sidecar.services import aggregation_service as agg


def _rec(doc="/h/a.md") -> CreationRecord:
    return CreationRecord(
        job_id="j", mode="normal", keyword="无线吸尘器", template_id="tpl", title="A",
        angle_json='{"tone":"口语"}', skill_chain_json='["人设"]', models_json=None,
        contract_mode="aggressive", document_path=doc, format="markdown", edit_ratio=0.1,
        lint_unresolved=0, factcheck_blocked=0, score=None, score_json=None,
        created_at="t", exported_at="t")


def test_enrich_stale_flags_and_record(monitor_db):
    fb.record_creation(_rec(), [], [FactSnapshot("M", "OLDFP", '{"specs":[["吸力","150AW"]]}')])
    fb.upsert_model_fingerprints([("M", "NEWFP", '{"specs":[["吸力","230AW"]]}')], now="t")  # 基线变了
    items = [{"path": "/h/a.md", "title": "A"}]
    agg._enrich_stale(items)
    assert items[0]["facts_stale"] is True
    assert items[0]["stale_models"] == ["M"]
    assert items[0]["record"]["keyword"] == "无线吸尘器"
    assert items[0]["record"]["contract_mode"] == "aggressive"
    assert items[0]["record"]["mode"] == "normal"


def test_enrich_not_stale_when_fp_matches(monitor_db):
    fb.record_creation(_rec("/h/b.md"), [], [FactSnapshot("M", "SAME", '{"specs":[]}')])
    fb.upsert_model_fingerprints([("M", "SAME", '{"specs":[]}')], now="t")  # 基线与快照同
    items = [{"path": "/h/b.md"}]
    agg._enrich_stale(items)
    assert items[0]["facts_stale"] is False
    assert items[0]["stale_models"] == []
    assert items[0]["record"] is not None  # 有记录但不过期


def test_enrich_no_record_shape(monitor_db):
    items = [{"path": "/h/none.md", "title": "X"}]
    agg._enrich_stale(items)
    # 无 creation_record → 三字段仍在（形状兼容），facts_stale=False、record=None。
    assert items[0]["facts_stale"] is False
    assert items[0]["stale_models"] == []
    assert items[0]["record"] is None
    assert items[0]["title"] == "X"  # 原字段不动


def test_enrich_empty_items():
    items = []
    agg._enrich_stale(items)  # 不抛
    assert items == []
