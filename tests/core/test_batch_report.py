from pathlib import Path
from csm_core.batch.report import BatchItem, BatchReport, write_report, read_report


def _mk_report(items=None):
    return BatchReport(
        batch_id="batch-20260420-120000",
        batch_dir="/tmp/batch-20260420-120000",
        started_at="2026-04-20T12:00:00",
        finished_at=None,
        template_path="/t/template.json",
        vault_root="/v",
        seed=0,
        total=2,
        items=items or [],
    )


def test_batch_item_frozen():
    item = BatchItem(index=1, keyword="k", status="success")
    try:
        item.index = 2  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("BatchItem should be frozen")


def test_write_and_read_round_trip(tmp_path):
    item = BatchItem(
        index=1, keyword="k", status="success",
        markdown_path="/p.md", assembly_json_path="/p.json",
        duration_seconds=1.5,
    )
    report = _mk_report(items=[item])
    path = tmp_path / "batch-report.json"
    write_report(report, path)
    loaded = read_report(path)
    assert loaded.batch_id == "batch-20260420-120000"
    assert loaded.total == 2
    assert len(loaded.items) == 1
    assert loaded.items[0].keyword == "k"
    assert loaded.items[0].status == "success"
    assert loaded.items[0].duration_seconds == 1.5


def test_write_is_atomic(tmp_path, monkeypatch):
    """Simulate a crash mid-write: temp file exists, target unchanged or absent."""
    report = _mk_report()
    path = tmp_path / "batch-report.json"
    write_report(report, path)
    import json
    def boom(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr("csm_core.batch.report.json.dumps", boom)
    try:
        write_report(report, path)
    except RuntimeError:
        pass
    loaded = read_report(path)
    assert loaded.batch_id == "batch-20260420-120000"


def test_failed_item_fields():
    item = BatchItem(
        index=2, keyword="bad", status="failed",
        error_type="EmptyPoolError",
        error_message="slot 'x': empty pool",
    )
    report = _mk_report(items=[item])
    from dataclasses import asdict
    data = asdict(report)
    assert data["items"][0]["error_type"] == "EmptyPoolError"
