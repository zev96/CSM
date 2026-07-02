import os
from pathlib import Path

import pytest

import csm_core.vault.index_cache as index_cache
from csm_core.vault.index_cache import IncrementalIndexer
from csm_core.vault.scanner import scan_vault

GOOD = "---\n素材类型: 科普\n---\n\n正文①\n"


def _write(p: Path, text: str, *, bump_ns: int | None = None) -> Path:
    p.write_text(text, encoding="utf-8")
    if bump_ns is not None:
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + bump_ns))
    return p


def _vault(root: Path) -> Path:
    _write(root / "a.md", GOOD)
    _write(root / "b.md", GOOD.replace("科普", "痛点"))
    (root / "sub").mkdir()
    _write(root / "sub" / "c.md", "没有 frontmatter\n")
    return root


def _assert_same(idx, full):
    assert [n.id for n in idx.notes] == [n.id for n in full.notes]
    assert set(idx.by_id) == set(full.by_id)
    assert idx.warnings == full.warnings
    assert idx.root == full.root


def _count_parses(monkeypatch):
    calls = []
    real = index_cache.parse_one

    def spy(path):
        calls.append(path.name)
        return real(path)

    monkeypatch.setattr(index_cache, "parse_one", spy)
    return calls


def test_first_refresh_equals_full_scan(tmp_path):
    root = _vault(tmp_path)
    idx = IncrementalIndexer().refresh(root)
    _assert_same(idx, scan_vault(root))


def test_unchanged_files_not_reparsed(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    ixr = IncrementalIndexer()
    ixr.refresh(root)
    calls = _count_parses(monkeypatch)
    ixr.refresh(root)
    assert calls == []          # 全部命中缓存


def test_modified_file_reparsed_alone(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    ixr = IncrementalIndexer()
    ixr.refresh(root)
    _write(root / "a.md", GOOD.replace("正文①", "改过的正文①"), bump_ns=2_000_000)
    calls = _count_parses(monkeypatch)
    idx = ixr.refresh(root)
    assert calls == ["a.md"]
    assert "改过的正文①" in idx.by_id["a"].variants[0]
    _assert_same(idx, scan_vault(root))


def test_same_size_mtime_only_change_detected(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    ixr = IncrementalIndexer()
    ixr.refresh(root)
    old_size = (root / "a.md").stat().st_size
    _write(root / "a.md", GOOD.replace("正文①", "正文②"), bump_ns=2_000_000)
    assert (root / "a.md").stat().st_size == old_size   # 同长度：只有 mtime 变
    calls = _count_parses(monkeypatch)
    idx = ixr.refresh(root)
    assert calls == ["a.md"]
    assert "正文②" in idx.by_id["a"].variants[0]


def test_added_and_deleted(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    ixr = IncrementalIndexer()
    ixr.refresh(root)
    (root / "b.md").unlink()
    _write(root / "d.md", GOOD)
    calls = _count_parses(monkeypatch)
    idx = ixr.refresh(root)
    assert calls == ["d.md"]
    assert "b" not in idx.by_id and "d" in idx.by_id
    _assert_same(idx, scan_vault(root))


def test_warning_files_cached_too(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    ixr = IncrementalIndexer()
    idx1 = ixr.refresh(root)
    assert idx1.warnings == ["c.md: 缺少 frontmatter"]
    calls = _count_parses(monkeypatch)
    idx2 = ixr.refresh(root)
    assert calls == []          # 警告文件也不重解析
    assert idx2.warnings == idx1.warnings


def test_root_change_full_rebuild(tmp_path):
    root1 = tmp_path / "v1"
    root1.mkdir()
    _vault(root1)
    root2 = tmp_path / "v2"
    root2.mkdir()
    _write(root2 / "z.md", GOOD)
    ixr = IncrementalIndexer()
    ixr.refresh(root1)
    idx = ixr.refresh(root2)
    assert list(idx.by_id) == ["z"]
    _assert_same(idx, scan_vault(root2))


def test_reset(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    ixr = IncrementalIndexer()
    ixr.refresh(root)
    ixr.reset()
    calls = _count_parses(monkeypatch)
    ixr.refresh(root)
    assert len(calls) == 3      # 全量重解析


REAL_VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


@pytest.mark.skipif(not REAL_VAULT.is_dir(), reason="真实库不可达（CI/无共享盘）")
def test_real_vault_incremental_equals_full_readonly():
    """真实库只读回归：增量首扫 == 全量扫（绝不写盘）。"""
    idx = IncrementalIndexer().refresh(REAL_VAULT)
    full = scan_vault(REAL_VAULT)
    assert [n.id for n in idx.notes] == [n.id for n in full.notes]
    assert idx.warnings == full.warnings
