"""Analyzer: orchestrates corpus scan → MinHash index → analyze + segment locate."""
from pathlib import Path
from csm_core.dedup.analyzer import DedupAnalyzer, build_doc_id


def test_build_doc_id_stable():
    """Same path → same id (used as deduplication key)."""
    a = build_doc_id(Path("/tmp/a.md"))
    b = build_doc_id(Path("/tmp/a.md"))
    assert a == b
    assert build_doc_id(Path("/tmp/b.md")) != a


def test_build_index_from_dir(tmp_path: Path):
    (tmp_path / "a.md").write_text("# A\n\n" + "今天天气真好，适合出门散步" * 10,
                                   encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\n" + "明天有可能下雨注意带伞" * 10,
                                   encoding="utf-8")
    analyzer = DedupAnalyzer()
    progress_calls = []
    analyzer.build_index(tmp_path, kind="history",
                         progress_cb=lambda done, total: progress_calls.append((done, total)))
    assert analyzer.index_doc_count("history") == 2
    assert len(progress_calls) >= 1
    assert progress_calls[-1] == (2, 2)


def test_analyze_finds_overlap(tmp_path: Path):
    """A draft directly quoting a corpus doc should yield non-zero duplicate_ratio."""
    corpus_text = "今天天气真好，适合出门散步去公园看花。" * 5
    (tmp_path / "a.md").write_text(corpus_text, encoding="utf-8")

    analyzer = DedupAnalyzer()
    analyzer.build_index(tmp_path, kind="history")

    current = (
        "前缀文字相关内容描述无关的填充。"
        + "今天天气真好，适合出门散步去公园看花。" * 3
        + "后缀继续写无关的内容拉长整段文本以满足最小长度要求。"
    )
    report = analyzer.analyze(current, kind="history")

    assert report.corpus_kind == "history"
    assert report.text_length == len(current)
    assert report.duplicate_chars > 0
    assert report.duplicate_ratio > 0.0
    assert len(report.top_matches) >= 1
    assert report.top_matches[0].source_path.endswith("a.md")
    assert len(report.hits) >= 1


def test_analyze_no_overlap_returns_zero(tmp_path: Path):
    (tmp_path / "a.md").write_text("完全无关的内容ABCDEFGHIJ" * 10,
                                   encoding="utf-8")
    analyzer = DedupAnalyzer()
    analyzer.build_index(tmp_path, kind="history")

    report = analyzer.analyze("另一段毫不相关的文字内容XYZ" * 10, kind="history")
    assert report.duplicate_ratio < 0.05


def test_analyze_short_text_returns_empty_report(tmp_path: Path):
    """Text shorter than MIN_ANALYZABLE_CHARS returns an empty report."""
    (tmp_path / "a.md").write_text("文章内容" * 30, encoding="utf-8")
    analyzer = DedupAnalyzer()
    analyzer.build_index(tmp_path, kind="history")

    report = analyzer.analyze("太短", kind="history")
    assert report.text_length == 0
    assert report.duplicate_ratio == 0.0


def test_analyze_unknown_kind_returns_empty():
    analyzer = DedupAnalyzer()
    report = analyzer.analyze("一些足够长的文本内容" * 10, kind="vault")
    assert report.duplicate_ratio == 0.0


def test_persist_and_reload(tmp_path: Path):
    """Build → save → new analyzer → load → analyze should still find overlap."""
    (tmp_path / "a.md").write_text("具体内容文字" * 30, encoding="utf-8")
    save_dir = tmp_path / "idx"

    a = DedupAnalyzer()
    a.build_index(tmp_path, kind="history")
    a.save(save_dir)

    b = DedupAnalyzer()
    b.load(save_dir)
    report = b.analyze("具体内容文字" * 30, kind="history")
    assert report.duplicate_ratio > 0.0
