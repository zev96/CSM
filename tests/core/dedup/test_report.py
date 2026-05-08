"""Dedup report dataclasses: ensure construction + serialization shape."""
from datetime import datetime
from csm_core.dedup.report import DuplicateReport, TopMatch, SegmentHit


def test_segment_hit_construction():
    h = SegmentHit(
        start=10, end=23,
        text="今天天气真好",
        source_path="/tmp/note.md",
        source_title="天气笔记",
        source_excerpt="...今天天气真好，适合...",
    )
    assert h.start == 10
    assert h.end == 23
    assert h.text == "今天天气真好"


def test_top_match_construction():
    m = TopMatch(
        source_path="/tmp/a.md",
        source_title="A 文章",
        overlap_chars=156,
        overlap_ratio=0.049,
    )
    assert m.overlap_chars == 156
    assert 0.04 < m.overlap_ratio < 0.05


def test_duplicate_report_construction_and_ratio():
    now = datetime.now()
    r = DuplicateReport(
        corpus_kind="history",
        text_length=3200,
        duplicate_chars=384,
        duplicate_ratio=0.12,
        top_matches=[],
        hits=[],
        computed_at=now,
    )
    assert r.corpus_kind == "history"
    assert r.duplicate_ratio == 0.12
    assert r.top_matches == []
    assert r.hits == []
    assert r.computed_at is now


def test_duplicate_report_empty_when_no_index():
    """Helper: report.empty(kind) returns a 0%-coverage report for UI display."""
    r = DuplicateReport.empty("history")
    assert r.corpus_kind == "history"
    assert r.text_length == 0
    assert r.duplicate_chars == 0
    assert r.duplicate_ratio == 0.0
    assert r.top_matches == []
    assert r.hits == []
