"""DedupIndex: MinHashLSH wrapper + persistence + incremental updates."""
from pathlib import Path
import pytest
from csm_core.dedup.index import DedupIndex


def test_empty_index_query_returns_empty():
    idx = DedupIndex()
    assert idx.query("任何文本内容都行" * 5) == []


def test_add_doc_and_query_finds_self():
    """Adding a doc and querying its own text should find it as candidate."""
    idx = DedupIndex()
    idx.add_doc(
        doc_id="doc1",
        text="今天天气真好，适合出门散步去公园看花",
        meta={"path": "/tmp/a.md", "title": "A", "mtime": 1.0},
    )
    candidates = idx.query("今天天气真好，适合出门散步去公园看花")
    assert "doc1" in candidates


def test_add_doc_idempotent_for_same_id():
    """Adding the same doc_id twice updates rather than duplicates."""
    idx = DedupIndex()
    idx.add_doc("doc1", "abc" * 30, meta={"path": "x", "title": "x", "mtime": 1.0})
    idx.add_doc("doc1", "xyz" * 30, meta={"path": "x", "title": "x", "mtime": 2.0})
    # Old "abc" content should NOT find doc1
    assert "doc1" not in idx.query("abc" * 30)
    # New "xyz" content should
    assert "doc1" in idx.query("xyz" * 30)


def test_remove_doc():
    idx = DedupIndex()
    idx.add_doc("doc1", "今天天气真好" * 5, meta={"path": "x", "title": "x", "mtime": 1.0})
    assert "doc1" in idx.query("今天天气真好" * 5)
    idx.remove_doc("doc1")
    assert "doc1" not in idx.query("今天天气真好" * 5)


def test_get_meta():
    idx = DedupIndex()
    meta = {"path": "/tmp/a.md", "title": "A", "mtime": 12345.0}
    idx.add_doc("doc1", "abc" * 30, meta=meta)
    assert idx.get_meta("doc1") == meta


def test_persist_and_load_roundtrip(tmp_path: Path):
    """Save to disk, load back — query results should be identical."""
    idx = DedupIndex()
    idx.add_doc("doc1", "今天天气真好" * 5, meta={"path": "/a", "title": "A", "mtime": 1.0})
    idx.add_doc("doc2", "明天可能下雨" * 5, meta={"path": "/b", "title": "B", "mtime": 2.0})

    save_dir = tmp_path / "dedup_idx"
    idx.save(save_dir, name="history")
    assert (save_dir / "history.lsh").exists()
    assert (save_dir / "history.meta.json").exists()

    loaded = DedupIndex.load(save_dir, name="history")
    assert "doc1" in loaded.query("今天天气真好" * 5)
    assert "doc2" in loaded.query("明天可能下雨" * 5)
    assert loaded.get_meta("doc1")["path"] == "/a"


def test_load_missing_returns_empty_index(tmp_path: Path):
    """Loading from a nonexistent dir returns an empty (but valid) index."""
    idx = DedupIndex.load(tmp_path / "nonexistent", name="history")
    assert idx.query("anything" * 10) == []


def test_load_corrupt_pickle_returns_empty(tmp_path: Path):
    """Corrupt .lsh file → empty index, not crash. Caller should rebuild."""
    save_dir = tmp_path / "idx"
    save_dir.mkdir()
    (save_dir / "history.lsh").write_bytes(b"not a pickle")
    (save_dir / "history.meta.json").write_text("{}", encoding="utf-8")
    idx = DedupIndex.load(save_dir, name="history")
    assert idx.query("anything" * 10) == []


def test_doc_count():
    idx = DedupIndex()
    assert idx.doc_count() == 0
    idx.add_doc("d1", "abc" * 30, meta={"path": "x", "title": "x", "mtime": 1.0})
    idx.add_doc("d2", "xyz" * 30, meta={"path": "y", "title": "y", "mtime": 1.0})
    assert idx.doc_count() == 2
    idx.remove_doc("d1")
    assert idx.doc_count() == 1
