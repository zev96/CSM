"""DedupWorker: QThread that runs analyze / build_index off the UI thread."""
from pathlib import Path
from PyQt6.QtCore import QObject
from csm_gui.workers.dedup_worker import DedupAnalyzeWorker, DedupBuildWorker
from csm_core.dedup.analyzer import DedupAnalyzer


def test_analyze_worker_emits_finished(qtbot, tmp_path: Path):
    (tmp_path / "a.md").write_text("内容文字" * 30, encoding="utf-8")
    analyzer = DedupAnalyzer()
    analyzer.build_index(tmp_path, kind="history")

    text = "另外一些不重叠的内容文字" * 10
    worker = DedupAnalyzeWorker(analyzer=analyzer, text=text, kind="history")
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start()
    report = blocker.args[0]
    assert report.corpus_kind == "history"


def test_analyze_worker_handles_no_index(qtbot):
    """No index built — worker still emits finished with empty report."""
    analyzer = DedupAnalyzer()
    worker = DedupAnalyzeWorker(analyzer=analyzer, text="some text" * 20, kind="history")
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start()
    report = blocker.args[0]
    assert report.duplicate_ratio == 0.0


def test_build_worker_emits_progress_then_finished(qtbot, tmp_path: Path):
    for i in range(5):
        (tmp_path / f"f{i}.md").write_text(f"文章 {i} 内容" * 30, encoding="utf-8")

    analyzer = DedupAnalyzer()
    worker = DedupBuildWorker(analyzer=analyzer, root=tmp_path, kind="history")

    progress_calls = []
    worker.progress.connect(lambda done, total: progress_calls.append((done, total)))

    with qtbot.waitSignal(worker.finished, timeout=10000):
        worker.start()

    assert analyzer.index_doc_count("history") == 5
    assert progress_calls
    assert progress_calls[-1][0] == progress_calls[-1][1]
