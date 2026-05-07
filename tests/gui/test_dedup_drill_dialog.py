"""DedupDrillDialog: shows top 3 matches + segment hit list."""
from datetime import datetime
from csm_gui.widgets.dedup_drill_dialog import DedupDrillDialog
from csm_core.dedup.report import DuplicateReport, TopMatch, SegmentHit


def _make_report():
    return DuplicateReport(
        corpus_kind="history",
        text_length=3200,
        duplicate_chars=384,
        duplicate_ratio=0.12,
        top_matches=[
            TopMatch(source_path="/tmp/a.md", source_title="A 文章",
                     overlap_chars=156, overlap_ratio=0.049),
            TopMatch(source_path="/tmp/b.md", source_title="B 文章",
                     overlap_chars=98, overlap_ratio=0.031),
        ],
        hits=[
            SegmentHit(start=10, end=26, text="片段一" * 5,
                       source_path="/tmp/a.md", source_title="A 文章",
                       source_excerpt="...上下文..."),
        ],
        computed_at=datetime.now(),
    )


def test_dialog_renders_summary(qtbot):
    dialog = DedupDrillDialog(_make_report())
    qtbot.addWidget(dialog)
    summary = dialog.summary_label.text()
    assert "3200" in summary or "3,200" in summary
    assert "384" in summary


def test_dialog_renders_top_matches(qtbot):
    dialog = DedupDrillDialog(_make_report())
    qtbot.addWidget(dialog)
    assert dialog.top_matches_list.count() == 2


def test_dialog_renders_hits(qtbot):
    dialog = DedupDrillDialog(_make_report())
    qtbot.addWidget(dialog)
    assert dialog.hits_list.count() == 1


def test_dialog_with_empty_report(qtbot):
    """Empty report should not crash."""
    empty = DuplicateReport.empty("history")
    dialog = DedupDrillDialog(empty)
    qtbot.addWidget(dialog)
    assert dialog.top_matches_list.count() == 0
    assert dialog.hits_list.count() == 0


def test_dialog_open_source_emits_signal(qtbot):
    """Double-clicking a top-match row emits open_source_requested."""
    dialog = DedupDrillDialog(_make_report())
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog.open_source_requested, timeout=1000) as blocker:
        item = dialog.top_matches_list.item(0)
        dialog.top_matches_list.itemDoubleClicked.emit(item)
    assert blocker.args[0] == "/tmp/a.md"
