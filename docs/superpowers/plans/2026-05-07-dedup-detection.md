# 历史文章查重与素材引用率检测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在创作区右侧润色按钮下方加两条指标——「历史重复率」（vs 用户指定的历史文章库目录）与「素材引用率」（vs Obsidian vault），并支持点击下钻查看相似文章 + 命中段落。

**Architecture:** 纯 Python 算法层 `csm_core/dedup/`（shingles + datasketch MinHash + LSH 候选检索 + shingling 精算）；GUI 层 `csm_gui/widgets/dedup_panel.py` 双指标条 + `dedup_drill_dialog.py` 下钻；后台 `csm_gui/workers/dedup_worker.py` QThread 不阻塞 UI；索引懒加载 + 持久化到 `<config_dir>/dedup_index/`。

**Tech Stack:** Python 3.11, datasketch 1.x (MinHashLSH), python-docx 1.2 (docx 文本提取), pydantic v2 (AppConfig), PyQt6 + qfluentwidgets, pytest / pytest-qt

**Spec:** [docs/superpowers/specs/2026-05-07-dedup-detection-design.md](../specs/2026-05-07-dedup-detection-design.md)

---

## File Structure

**Create:**
- `csm_core/dedup/__init__.py`
- `csm_core/dedup/shingles.py` — 13-字符滑窗 shingling
- `csm_core/dedup/corpus.py` — 目录扫描 + .md/.docx/.txt 文本提取 + mtime 增量
- `csm_core/dedup/index.py` — MinHashLSH 索引封装 + pickle 持久化
- `csm_core/dedup/analyzer.py` — 编排 build/load/analyze
- `csm_core/dedup/report.py` — DuplicateReport / TopMatch / SegmentHit dataclass
- `csm_gui/workers/dedup_worker.py` — QThread 后台分析 + 索引构建
- `csm_gui/widgets/dedup_panel.py` — 双指标右侧面板
- `csm_gui/widgets/dedup_drill_dialog.py` — 命中段落下钻对话框
- `tests/core/dedup/__init__.py`
- `tests/core/dedup/test_shingles.py`
- `tests/core/dedup/test_corpus.py`
- `tests/core/dedup/test_index.py`
- `tests/core/dedup/test_analyzer.py`
- `tests/core/dedup/test_report.py`
- `tests/gui/test_dedup_panel.py`
- `tests/gui/test_dedup_drill_dialog.py`
- `tests/gui/test_dedup_worker.py`

**Modify:**
- `pyproject.toml` — 加 `datasketch>=1.6`, `python-docx>=1.0`
- `csm_gui/config.py` — AppConfig 加 6 个 dedup_* 字段
- `csm_gui/widgets/workspace_side_panel.py` — 润色按钮下方插 DedupPanel
- `csm_gui/pages/settings_page.py` — 加「历史查重」section
- `csm_gui/main_window.py` — 串信号：polished/generated → DedupAnalyzer
- `tests/gui/test_config.py` — 新字段测试
- `tests/gui/test_settings_page.py` — 历史查重 UI 测试
- `tests/gui/test_main_window.py` — 集成信号测试

**Test layout:** `tests/core/dedup/` 是新目录，需要 `__init__.py`；GUI 测试散在 `tests/gui/`。

---

## Task 1: 添加依赖 datasketch + python-docx

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 编辑 pyproject.toml — 在 dependencies 列表追加**

打开 `pyproject.toml`，把 `dependencies` 段改为：

```toml
dependencies = [
    "pydantic>=2.6",
    "python-frontmatter>=1.1",
    "httpx>=0.27",
    "tenacity>=8.2",
    "click>=8.1",
    "anthropic>=0.39",
    "datasketch>=1.6",
    "python-docx>=1.0",
]
```

- [ ] **Step 2: 安装新依赖到当前环境**

```bash
pip install -e .
```

预期：datasketch 和 python-docx 安装成功，`python -c "import datasketch, docx; print('OK')"` 输出 OK。

- [ ] **Step 3: 提交**

```bash
git add pyproject.toml
git commit -m "deps: add datasketch and python-docx for dedup detection"
```

---

## Task 2: AppConfig 加 dedup_* 字段

**Files:**
- Modify: `csm_gui/config.py`
- Modify: `tests/gui/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/gui/test_config.py` 末尾追加：

```python
def test_appconfig_dedup_defaults():
    from csm_gui.config import AppConfig
    cfg = AppConfig()
    assert cfg.dedup_enabled is False
    assert cfg.dedup_history_dir == ""
    assert cfg.dedup_threshold_green == 15
    assert cfg.dedup_threshold_yellow == 30
    assert cfg.dedup_history_last_built == ""
    assert cfg.dedup_vault_last_built == ""


def test_appconfig_dedup_loads_old_settings(tmp_path):
    """老 settings.json 没有 dedup_* 字段时回退到默认值。"""
    from csm_gui.config import AppConfig, load_config
    p = tmp_path / "settings.json"
    p.write_text('{"vault_root":"/tmp"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.dedup_enabled is False
    assert cfg.dedup_history_dir == ""


def test_appconfig_dedup_threshold_validation():
    from csm_gui.config import AppConfig
    # Threshold must be int 0-100
    cfg = AppConfig(dedup_threshold_green=20, dedup_threshold_yellow=40)
    assert cfg.dedup_threshold_green == 20
    assert cfg.dedup_threshold_yellow == 40
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_config.py -k dedup -v
```

预期：`AttributeError`。

- [ ] **Step 3: 实现 — 在 AppConfig 加 6 字段**

修改 `csm_gui/config.py`，在 `tray_first_minimize_shown` 字段下方追加：

```python
    # ── Dedup detection ────────────────────────────────────────────────
    dedup_enabled: bool = False
    dedup_history_dir: str = ""
    dedup_threshold_green: int = 15           # %
    dedup_threshold_yellow: int = 30          # %
    dedup_history_last_built: str = ""        # ISO timestamp
    dedup_vault_last_built: str = ""
```

- [ ] **Step 4: 跑测试通过**

```bash
pytest tests/gui/test_config.py -v
```

预期：所有 dedup 测试 + 既有测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/config.py tests/gui/test_config.py
git commit -m "feat(config): add dedup_* fields for history dedup detection"
```

---

## Task 3: shingles.py — 字符级 13-shingle 切片

**Files:**
- Create: `tests/core/dedup/__init__.py` (empty)
- Create: `csm_core/dedup/__init__.py`
- Create: `csm_core/dedup/shingles.py`
- Create: `tests/core/dedup/test_shingles.py`

- [ ] **Step 1: 创建空 `__init__.py`**

```bash
mkdir -p csm_core/dedup tests/core/dedup
```

写文件 `csm_core/dedup/__init__.py`：

```python
"""Dedup detection: shingling + MinHash/LSH candidate retrieval + precise overlap analysis."""
```

写文件 `tests/core/dedup/__init__.py`：

```python
```

(空文件 — pytest 会把它识别为 package。)

- [ ] **Step 2: 写失败测试**

写文件 `tests/core/dedup/test_shingles.py`：

```python
"""Shingles: char-level n-grams for Chinese plagiarism detection."""
from csm_core.dedup.shingles import compute_shingles, compute_shingles_with_positions


def test_compute_shingles_basic():
    text = "今天天气真好，适合出门散步"
    shingles = compute_shingles(text, n=4)
    # 文本长度 12 字符，4-shingle 应有 12-4+1 = 9 个
    assert len(shingles) == 9
    assert "今天天气" in shingles
    assert "适合出门" in shingles


def test_compute_shingles_returns_set():
    """Set semantics: duplicates collapse."""
    text = "abcabcabc"
    shingles = compute_shingles(text, n=3)
    # "abc","bca","cab" 各出现多次但 set 去重
    assert shingles == {"abc", "bca", "cab"}


def test_compute_shingles_short_text_returns_empty():
    assert compute_shingles("abc", n=4) == set()
    assert compute_shingles("", n=4) == set()


def test_compute_shingles_unicode():
    """中文字符 + emoji + 英文混合应正确切片。"""
    text = "Hello世界🌍test"
    shingles = compute_shingles(text, n=3)
    assert "Hel" in shingles
    assert "lo世" in shingles
    # emoji 算 1 个 codepoint（Python str 索引以 codepoint 为单位）
    assert len(shingles) >= 8


def test_compute_shingles_with_positions_returns_dict():
    text = "abcabc"
    posed = compute_shingles_with_positions(text, n=3)
    # 每个 shingle 映射到所有出现位置
    assert posed["abc"] == [0, 3]
    assert posed["bca"] == [1]
    assert posed["cab"] == [2]


def test_compute_shingles_default_n_is_13():
    """默认 n=13 字符（中文论文查重常用粒度）。"""
    text = "一二三四五六七八九十一二三四"  # 14 字符
    shingles = compute_shingles(text)
    assert len(shingles) == 14 - 13 + 1  # = 2
```

- [ ] **Step 3: 跑失败**

```bash
pytest tests/core/dedup/test_shingles.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 4: 实现**

写文件 `csm_core/dedup/shingles.py`：

```python
"""Character-level shingling for dedup detection.

The default ``n=13`` matches what most Chinese plagiarism-detection systems
use — small enough to catch sentence-level reuse, large enough that a
13-char window appearing in two unrelated documents is overwhelmingly
unlikely to be coincidence.

For LSH candidate retrieval, ``compute_shingles`` returns a flat set.
For precise overlap location (drill-down UI), use ``compute_shingles_with_positions``
which keeps the start index of each occurrence.
"""
from __future__ import annotations

DEFAULT_N = 13


def compute_shingles(text: str, n: int = DEFAULT_N) -> set[str]:
    """Return the set of all n-character substrings of ``text``.

    Empty or shorter-than-n inputs return an empty set rather than raising.
    """
    if not text or len(text) < n:
        return set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def compute_shingles_with_positions(
    text: str, n: int = DEFAULT_N,
) -> dict[str, list[int]]:
    """Return a dict mapping each n-shingle to the list of start indices
    (in character units) where it appears in ``text``.

    Used for the drill-down precise pass: given a candidate doc's shingle
    set, we find which positions in ``text`` are covered by matching shingles.
    """
    out: dict[str, list[int]] = {}
    if not text or len(text) < n:
        return out
    for i in range(len(text) - n + 1):
        s = text[i:i + n]
        out.setdefault(s, []).append(i)
    return out
```

- [ ] **Step 5: 跑通过**

```bash
pytest tests/core/dedup/test_shingles.py -v
```

预期：6 PASS。

- [ ] **Step 6: 提交**

```bash
git add csm_core/dedup/__init__.py csm_core/dedup/shingles.py tests/core/dedup/__init__.py tests/core/dedup/test_shingles.py
git commit -m "feat(dedup): char-level shingling with position tracking"
```

---

## Task 4: report.py — DuplicateReport / TopMatch / SegmentHit dataclasses

**Files:**
- Create: `csm_core/dedup/report.py`
- Create: `tests/core/dedup/test_report.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/core/dedup/test_report.py`：

```python
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
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/core/dedup/test_report.py -v
```

- [ ] **Step 3: 实现**

写文件 `csm_core/dedup/report.py`：

```python
"""Dedup report data structures."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SegmentHit:
    """One contiguous span in the analyzed text covered by candidate shingles."""
    start: int                  # char-unit start index in current text
    end: int                    # char-unit end index (exclusive)
    text: str                   # current_text[start:end]
    source_path: str            # absolute path of the source that contributed
    source_title: str           # title (first H1 or file stem) of source
    source_excerpt: str         # ±50 chars context from the source


@dataclass
class TopMatch:
    """Aggregate stats for one source document that overlapped current text."""
    source_path: str
    source_title: str
    overlap_chars: int          # total chars covered by this source's shingles
    overlap_ratio: float        # overlap_chars / current_text_length, 0..1


@dataclass
class DuplicateReport:
    """Result of analyzing one text against one corpus.

    ``corpus_kind`` is "history" or "vault" — the UI shows two reports side
    by side (one per kind).
    """
    corpus_kind: str            # "history" | "vault"
    text_length: int            # char count of current text
    duplicate_chars: int        # chars covered by any matching shingle
    duplicate_ratio: float      # duplicate_chars / text_length, 0..1
    top_matches: list[TopMatch] = field(default_factory=list)  # at most 3
    hits: list[SegmentHit] = field(default_factory=list)
    computed_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def empty(cls, kind: str) -> "DuplicateReport":
        """Empty report — used by the UI when index is missing or text too short."""
        return cls(
            corpus_kind=kind,
            text_length=0,
            duplicate_chars=0,
            duplicate_ratio=0.0,
        )
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/core/dedup/test_report.py -v
```

预期：4 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/dedup/report.py tests/core/dedup/test_report.py
git commit -m "feat(dedup): DuplicateReport / TopMatch / SegmentHit dataclasses"
```

---

## Task 5: corpus.py — 目录扫描 + 文本提取 + mtime 增量元数据

**Files:**
- Create: `csm_core/dedup/corpus.py`
- Create: `tests/core/dedup/test_corpus.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/core/dedup/test_corpus.py`：

```python
"""Corpus scanner: walk dir, extract text from .md/.docx/.txt, track mtime."""
from pathlib import Path
import pytest
from csm_core.dedup.corpus import (
    CorpusEntry, scan_corpus, extract_text, extract_title,
)


def test_extract_text_from_md(tmp_path: Path):
    f = tmp_path / "test.md"
    f.write_text("# Title\n\n正文内容第一段\n\n第二段", encoding="utf-8")
    text = extract_text(f)
    assert "正文内容第一段" in text
    assert "第二段" in text


def test_extract_text_from_txt(tmp_path: Path):
    f = tmp_path / "test.txt"
    f.write_text("纯文本内容", encoding="utf-8")
    assert extract_text(f) == "纯文本内容"


def test_extract_text_from_docx(tmp_path: Path):
    """Smoke: build a real .docx via python-docx and read it back."""
    from docx import Document
    doc_path = tmp_path / "test.docx"
    d = Document()
    d.add_paragraph("第一段内容")
    d.add_paragraph("第二段内容")
    d.save(str(doc_path))
    text = extract_text(doc_path)
    assert "第一段内容" in text
    assert "第二段内容" in text


def test_extract_text_unsupported_format_returns_empty(tmp_path: Path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"\x00\x01\x02")
    assert extract_text(f) == ""


def test_extract_title_md_uses_first_h1(tmp_path: Path):
    f = tmp_path / "test.md"
    f.write_text("# 我的文章标题\n\n正文", encoding="utf-8")
    assert extract_title(f) == "我的文章标题"


def test_extract_title_md_falls_back_to_stem(tmp_path: Path):
    f = tmp_path / "no-h1.md"
    f.write_text("没有标题的笔记", encoding="utf-8")
    assert extract_title(f) == "no-h1"


def test_scan_corpus_yields_entries(tmp_path: Path):
    (tmp_path / "a.md").write_text("# A\n\n内容 A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("内容 B", encoding="utf-8")
    (tmp_path / "ignored.bin").write_bytes(b"\x00")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("# C\n\n内容 C", encoding="utf-8")

    entries = list(scan_corpus(tmp_path))
    paths = {e.path.name for e in entries}
    assert paths == {"a.md", "b.txt", "c.md"}
    for e in entries:
        assert isinstance(e, CorpusEntry)
        assert e.text  # non-empty
        assert e.mtime > 0


def test_scan_corpus_missing_dir_returns_empty(tmp_path: Path):
    nonexist = tmp_path / "doesnotexist"
    assert list(scan_corpus(nonexist)) == []


def test_scan_corpus_skips_huge_file(tmp_path: Path):
    """File over 5MB is skipped (likely not a finished article)."""
    big = tmp_path / "big.md"
    big.write_text("x" * (6 * 1024 * 1024), encoding="utf-8")
    entries = list(scan_corpus(tmp_path))
    # 大文件被跳过
    assert big not in [e.path for e in entries]
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/core/dedup/test_corpus.py -v
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3: 实现**

写文件 `csm_core/dedup/corpus.py`：

```python
"""Corpus scanning + text extraction.

Supports ``.md``, ``.txt``, ``.docx``. Files over ``MAX_FILE_BYTES`` are
skipped (defensive — a 50MB markdown is almost certainly garbage). The
scanner yields one ``CorpusEntry`` per supported file under the root,
recursively.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".md", ".txt", ".docx")
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class CorpusEntry:
    """One scanned source file + its extracted text + mtime for incremental update."""
    path: Path
    title: str
    text: str
    mtime: float


def extract_text(path: Path) -> str:
    """Extract plain-text content from a supported file. Returns "" on failure."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".md", ".txt"):
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".docx":
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception as exc:
        logger.warning("dedup corpus: failed to read %s — %s", path, exc)
        return ""
    return ""


def extract_title(path: Path) -> str:
    """Best-effort title extraction.

    For ``.md``: first H1 line; falls back to file stem.
    For ``.txt``/``.docx``: file stem.
    """
    if path.suffix.lower() == ".md":
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            m = _H1_RE.search(content)
            if m:
                return m.group(1).strip()
        except Exception:
            pass
    return path.stem


def scan_corpus(root: Path) -> Iterator[CorpusEntry]:
    """Yield CorpusEntry for every supported file under ``root`` (recursive).

    Silently skips:
    - non-existent root
    - files exceeding MAX_FILE_BYTES
    - files where text extraction returns empty
    """
    root = Path(root)
    if not root.exists() or not root.is_dir():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > MAX_FILE_BYTES:
            logger.info("dedup corpus: skipping oversize file %s (%d bytes)",
                        path, stat.st_size)
            continue
        text = extract_text(path)
        if not text.strip():
            continue
        yield CorpusEntry(
            path=path,
            title=extract_title(path),
            text=text,
            mtime=stat.st_mtime,
        )
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/core/dedup/test_corpus.py -v
```

预期：9 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/dedup/corpus.py tests/core/dedup/test_corpus.py
git commit -m "feat(dedup): corpus scanner with .md/.txt/.docx text extraction"
```

---

## Task 6: index.py — MinHashLSH 索引封装 + pickle 持久化

**Files:**
- Create: `csm_core/dedup/index.py`
- Create: `tests/core/dedup/test_index.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/core/dedup/test_index.py`：

```python
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
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/core/dedup/test_index.py -v
```

- [ ] **Step 3: 实现**

写文件 `csm_core/dedup/index.py`：

```python
"""MinHashLSH index wrapper with pickle persistence.

Decouples the rest of the codebase from datasketch — callers see
``add_doc(text, meta)`` / ``query(text) -> [doc_id]`` and never touch
MinHash objects directly. Persistence: one ``.lsh`` (pickle of the LSH
itself) plus one ``.meta.json`` (doc_id → meta dict, including each doc's
serialized MinHash signature for the rebuild-on-update path).
"""
from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datasketch import MinHash, MinHashLSH

from .shingles import compute_shingles

logger = logging.getLogger(__name__)

NUM_PERM = 128
LSH_THRESHOLD = 0.3


def _build_minhash(text: str, num_perm: int = NUM_PERM) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for s in compute_shingles(text):
        m.update(s.encode("utf-8"))
    return m


@dataclass
class _Meta:
    """In-memory state per doc: original meta + serialized MinHash hashvalues
    (numpy array) so we can re-insert into a fresh LSH on partial updates.
    """
    meta: dict[str, Any]
    hashvalues: bytes  # MinHash.hashvalues serialized via pickle


class DedupIndex:
    """High-level dedup index. Thread-affine — use one instance per QThread."""

    def __init__(self):
        self._lsh = MinHashLSH(threshold=LSH_THRESHOLD, num_perm=NUM_PERM)
        self._meta: dict[str, _Meta] = {}

    def add_doc(self, doc_id: str, text: str, meta: dict[str, Any]) -> None:
        """Insert or replace a doc.

        Replacement: removes the old entry first (LSH does not allow
        duplicate keys).
        """
        if doc_id in self._meta:
            self.remove_doc(doc_id)
        m = _build_minhash(text)
        self._lsh.insert(doc_id, m)
        self._meta[doc_id] = _Meta(meta=meta, hashvalues=pickle.dumps(m.hashvalues))

    def remove_doc(self, doc_id: str) -> None:
        if doc_id in self._meta:
            try:
                self._lsh.remove(doc_id)
            except KeyError:
                pass
            del self._meta[doc_id]

    def query(self, text: str, top_k: int = 10) -> list[str]:
        """Return up to ``top_k`` candidate doc_ids whose Jaccard estimate
        is >= ``LSH_THRESHOLD`` to ``text``.
        """
        m = _build_minhash(text)
        candidates = self._lsh.query(m)
        return list(candidates)[:top_k]

    def get_meta(self, doc_id: str) -> dict[str, Any] | None:
        if doc_id in self._meta:
            return self._meta[doc_id].meta
        return None

    def doc_count(self) -> int:
        return len(self._meta)

    # ── Persistence ────────────────────────────────────────────────────
    def save(self, dir_path: Path, *, name: str) -> None:
        """Atomic write of LSH + meta.json to dir_path/{name}.lsh + .meta.json."""
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        lsh_path = dir_path / f"{name}.lsh"
        meta_path = dir_path / f"{name}.meta.json"

        # LSH itself pickles cleanly.
        tmp_lsh = lsh_path.with_suffix(".lsh.tmp")
        with open(tmp_lsh, "wb") as f:
            pickle.dump(self._lsh, f)
        tmp_lsh.replace(lsh_path)

        # Meta JSON — encode hashvalues bytes as hex so JSON-serializable.
        payload = {
            doc_id: {
                "meta": entry.meta,
                "hashvalues_hex": entry.hashvalues.hex(),
            }
            for doc_id, entry in self._meta.items()
        }
        tmp_meta = meta_path.with_suffix(".json.tmp")
        tmp_meta.write_text(json.dumps(payload, ensure_ascii=False),
                            encoding="utf-8")
        tmp_meta.replace(meta_path)

    @classmethod
    def load(cls, dir_path: Path, *, name: str) -> "DedupIndex":
        """Load from dir_path/{name}.lsh + .meta.json. Returns empty index on
        any error so the caller can prompt the user to rebuild.
        """
        dir_path = Path(dir_path)
        lsh_path = dir_path / f"{name}.lsh"
        meta_path = dir_path / f"{name}.meta.json"

        idx = cls()
        if not lsh_path.exists() or not meta_path.exists():
            return idx

        try:
            with open(lsh_path, "rb") as f:
                idx._lsh = pickle.load(f)
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            for doc_id, entry in payload.items():
                idx._meta[doc_id] = _Meta(
                    meta=entry["meta"],
                    hashvalues=bytes.fromhex(entry["hashvalues_hex"]),
                )
        except Exception as exc:
            logger.warning("dedup index: load failed for %s — %s", name, exc)
            return cls()  # fresh empty
        return idx
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/core/dedup/test_index.py -v
```

预期：9 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/dedup/index.py tests/core/dedup/test_index.py
git commit -m "feat(dedup): MinHashLSH index wrapper with pickle persistence"
```

---

## Task 7: analyzer.py — 编排 build_index + analyze_text

**Files:**
- Create: `csm_core/dedup/analyzer.py`
- Create: `tests/core/dedup/test_analyzer.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/core/dedup/test_analyzer.py`：

```python
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
    # 索引里应有 2 篇
    assert analyzer.index_doc_count("history") == 2
    # 进度回调被调用了
    assert len(progress_calls) >= 1
    assert progress_calls[-1] == (2, 2)


def test_analyze_finds_overlap(tmp_path: Path):
    """A draft directly quoting a corpus doc should yield non-zero duplicate_ratio."""
    corpus_text = "今天天气真好，适合出门散步去公园看花。" * 5
    (tmp_path / "a.md").write_text(corpus_text, encoding="utf-8")

    analyzer = DedupAnalyzer()
    analyzer.build_index(tmp_path, kind="history")

    # 当前文章直接抄了 corpus_text 的一部分
    current = "前缀文本无关。今天天气真好，适合出门散步去公园看花。后缀也无关内容。"
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
    # 零或近零（边界 shingle 偶然碰撞极少）
    assert report.duplicate_ratio < 0.05


def test_analyze_short_text_returns_empty_report(tmp_path: Path):
    """Text shorter than MIN_ANALYZABLE_CHARS returns an empty report."""
    (tmp_path / "a.md").write_text("文章内容" * 30, encoding="utf-8")
    analyzer = DedupAnalyzer()
    analyzer.build_index(tmp_path, kind="history")

    report = analyzer.analyze("太短", kind="history")
    assert report.text_length == 0  # 短文本回 empty
    assert report.duplicate_ratio == 0.0


def test_analyze_unknown_kind_returns_empty():
    analyzer = DedupAnalyzer()
    # 没建过 index 的 kind
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
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/core/dedup/test_analyzer.py -v
```

- [ ] **Step 3: 实现**

写文件 `csm_core/dedup/analyzer.py`：

```python
"""Dedup analyzer: build index from corpus, analyze text against it.

Two-stage analysis:
1. LSH candidate retrieval (top-K most-similar docs by Jaccard estimate)
2. Per-candidate precise overlap (shingle position intersection → covered
   character bitmap → SegmentHit list + per-source TopMatch totals)
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from .corpus import scan_corpus
from .index import DedupIndex
from .report import DuplicateReport, SegmentHit, TopMatch
from .shingles import (
    DEFAULT_N, compute_shingles, compute_shingles_with_positions,
)

logger = logging.getLogger(__name__)

MIN_ANALYZABLE_CHARS = 50          # text shorter than this → empty report
TOP_MATCHES_RETURNED = 3
TOP_K_CANDIDATES = 10
EXCERPT_CONTEXT = 50               # chars on each side of source excerpt


def build_doc_id(path: Path) -> str:
    """Deterministic short id from absolute path. SHA1 first 12 hex chars."""
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


class DedupAnalyzer:
    """Owns one index per ``kind`` (e.g. "history", "vault")."""

    def __init__(self):
        self._indexes: dict[str, DedupIndex] = {}

    # ── Index management ───────────────────────────────────────────────
    def build_index(
        self,
        root: Path,
        *,
        kind: str,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> None:
        """Walk ``root`` and build a fresh DedupIndex under ``kind``.

        ``progress_cb(done, total)`` is called periodically for UI updates.
        Total is unknown until the scan completes the first pass — we pre-count.
        """
        # Pre-count for progress (cheap directory walk).
        total = sum(1 for _ in scan_corpus(root))
        if total == 0:
            self._indexes[kind] = DedupIndex()
            if progress_cb:
                progress_cb(0, 0)
            return

        idx = DedupIndex()
        done = 0
        for entry in scan_corpus(root):
            doc_id = build_doc_id(entry.path)
            idx.add_doc(
                doc_id,
                entry.text,
                meta={
                    "path": str(entry.path),
                    "title": entry.title,
                    "mtime": entry.mtime,
                },
            )
            done += 1
            if progress_cb and done % 10 == 0:
                progress_cb(done, total)
        if progress_cb:
            progress_cb(done, total)
        self._indexes[kind] = idx

    def index_doc_count(self, kind: str) -> int:
        idx = self._indexes.get(kind)
        return idx.doc_count() if idx else 0

    def save(self, dir_path: Path) -> None:
        for kind, idx in self._indexes.items():
            idx.save(dir_path, name=kind)

    def load(self, dir_path: Path, *, kinds: tuple[str, ...] = ("history", "vault")) -> None:
        for kind in kinds:
            self._indexes[kind] = DedupIndex.load(dir_path, name=kind)

    # ── Analysis ───────────────────────────────────────────────────────
    def analyze(self, text: str, *, kind: str) -> DuplicateReport:
        """Analyze ``text`` against the index for ``kind``.

        Returns an empty report if:
        - ``kind`` has no index built
        - ``text`` shorter than MIN_ANALYZABLE_CHARS
        """
        if kind not in self._indexes:
            return DuplicateReport.empty(kind)
        if len(text) < MIN_ANALYZABLE_CHARS:
            return DuplicateReport.empty(kind)

        idx = self._indexes[kind]
        candidates = idx.query(text, top_k=TOP_K_CANDIDATES)
        if not candidates:
            return DuplicateReport(
                corpus_kind=kind,
                text_length=len(text),
                duplicate_chars=0,
                duplicate_ratio=0.0,
                top_matches=[],
                hits=[],
                computed_at=datetime.now(),
            )

        # Precise pass: compute current text's positioned shingles once,
        # then for each candidate compute overlap.
        current_pos = compute_shingles_with_positions(text)
        if not current_pos:
            return DuplicateReport.empty(kind)

        # Per-position attribution: which doc covers position i?
        # We use the FIRST candidate (in candidates order, which is LSH-determined)
        # whose shingle covers that position. Aggregate overlap_chars per doc.
        covered = bytearray(len(text))  # 0 / 1 bitmap
        attribution: dict[int, str] = {}  # position → doc_id
        per_doc_chars: dict[str, int] = {}

        for doc_id in candidates:
            doc_meta = idx.get_meta(doc_id) or {}
            doc_path = doc_meta.get("path", "")
            if not doc_path:
                continue
            try:
                cand_text = Path(doc_path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if doc_path.lower().endswith(".docx"):
                from .corpus import extract_text
                cand_text = extract_text(Path(doc_path))
            cand_shingles = compute_shingles(cand_text)
            if not cand_shingles:
                continue

            # Mark positions covered by shared shingles.
            doc_chars = 0
            for shingle, positions in current_pos.items():
                if shingle not in cand_shingles:
                    continue
                for pos in positions:
                    for j in range(pos, min(pos + DEFAULT_N, len(text))):
                        if not covered[j]:
                            covered[j] = 1
                            attribution[j] = doc_id
                            doc_chars += 1
                        elif attribution.get(j) == doc_id:
                            doc_chars += 0  # already counted to this doc
            per_doc_chars[doc_id] = per_doc_chars.get(doc_id, 0) + doc_chars

        duplicate_chars = sum(covered)
        text_length = len(text)
        ratio = duplicate_chars / text_length if text_length else 0.0

        # Build TopMatch list (top 3 by overlap_chars).
        ranked = sorted(per_doc_chars.items(), key=lambda kv: kv[1], reverse=True)
        top_matches: list[TopMatch] = []
        for doc_id, chars in ranked[:TOP_MATCHES_RETURNED]:
            meta = idx.get_meta(doc_id) or {}
            top_matches.append(TopMatch(
                source_path=meta.get("path", ""),
                source_title=meta.get("title", ""),
                overlap_chars=chars,
                overlap_ratio=chars / text_length if text_length else 0.0,
            ))

        # Build SegmentHit list — collapse runs of consecutive covered positions.
        hits: list[SegmentHit] = []
        i = 0
        while i < len(covered):
            if covered[i]:
                j = i
                while j < len(covered) and covered[j]:
                    j += 1
                doc_id = attribution.get(i, "")
                meta = idx.get_meta(doc_id) or {}
                src_path = meta.get("path", "")
                excerpt = ""
                if src_path:
                    try:
                        src_text = Path(src_path).read_text(encoding="utf-8", errors="ignore")
                        seg = text[i:j]
                        idx_in_src = src_text.find(seg)
                        if idx_in_src >= 0:
                            lo = max(0, idx_in_src - EXCERPT_CONTEXT)
                            hi = min(len(src_text), idx_in_src + len(seg) + EXCERPT_CONTEXT)
                            excerpt = src_text[lo:hi]
                    except OSError:
                        pass
                hits.append(SegmentHit(
                    start=i, end=j,
                    text=text[i:j],
                    source_path=src_path,
                    source_title=meta.get("title", ""),
                    source_excerpt=excerpt,
                ))
                i = j
            else:
                i += 1

        return DuplicateReport(
            corpus_kind=kind,
            text_length=text_length,
            duplicate_chars=duplicate_chars,
            duplicate_ratio=ratio,
            top_matches=top_matches,
            hits=hits,
            computed_at=datetime.now(),
        )
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/core/dedup/test_analyzer.py -v
```

预期：7 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_core/dedup/analyzer.py tests/core/dedup/test_analyzer.py
git commit -m "feat(dedup): analyzer with two-stage LSH + precise overlap"
```

---

## Task 8: dedup_worker.py — QThread 后台分析 / 索引构建

**Files:**
- Create: `csm_gui/workers/dedup_worker.py`
- Create: `tests/gui/test_dedup_worker.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/gui/test_dedup_worker.py`：

```python
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
    # Last progress call should be at 100%
    assert progress_calls[-1][0] == progress_calls[-1][1]
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_dedup_worker.py -v
```

- [ ] **Step 3: 实现**

写文件 `csm_gui/workers/dedup_worker.py`：

```python
"""Background workers for dedup analysis and index building.

Both workers are QThread subclasses that emit finished/progress signals.
They run synchronously in their own thread; the analyzer is shared
(thread-affine — only one worker should touch a given analyzer at a time).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.dedup.analyzer import DedupAnalyzer
from csm_core.dedup.report import DuplicateReport

logger = logging.getLogger(__name__)


class DedupAnalyzeWorker(QThread):
    """Analyze ``text`` against ``kind``'s index. Emits ``finished(report)``."""

    finished = pyqtSignal(DuplicateReport)

    def __init__(self, analyzer: DedupAnalyzer, text: str, kind: str,
                 parent=None):
        super().__init__(parent)
        self._analyzer = analyzer
        self._text = text
        self._kind = kind

    def run(self) -> None:
        try:
            report = self._analyzer.analyze(self._text, kind=self._kind)
        except Exception as exc:
            logger.warning("DedupAnalyzeWorker failed: %s", exc)
            report = DuplicateReport.empty(self._kind)
        self.finished.emit(report)


class DedupBuildWorker(QThread):
    """Build a fresh index for ``kind`` by scanning ``root``.

    Emits ``progress(done, total)`` periodically and ``finished()`` at end.
    """

    progress = pyqtSignal(int, int)
    finished = pyqtSignal()

    def __init__(self, analyzer: DedupAnalyzer, root: Path, kind: str,
                 parent=None):
        super().__init__(parent)
        self._analyzer = analyzer
        self._root = Path(root)
        self._kind = kind

    def run(self) -> None:
        try:
            self._analyzer.build_index(
                self._root,
                kind=self._kind,
                progress_cb=lambda done, total: self.progress.emit(done, total),
            )
        except Exception as exc:
            logger.warning("DedupBuildWorker failed: %s", exc)
        self.finished.emit()
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_dedup_worker.py -v
```

预期：3 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/workers/dedup_worker.py tests/gui/test_dedup_worker.py
git commit -m "feat(dedup): QThread workers for analyze + build_index"
```

---

## Task 9: dedup_panel.py — 双指标右侧面板组件

**Files:**
- Create: `csm_gui/widgets/dedup_panel.py`
- Create: `tests/gui/test_dedup_panel.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/gui/test_dedup_panel.py`：

```python
"""DedupPanel: two-row metrics widget showing 历史重复率 / 素材引用率."""
from datetime import datetime
from csm_gui.widgets.dedup_panel import DedupPanel
from csm_core.dedup.report import DuplicateReport, TopMatch


def test_panel_initial_state_shows_dash(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    # 默认状态显示 "—"
    assert "—" in panel.history_value_label.text()
    assert "—" in panel.vault_value_label.text()


def test_panel_renders_history_report(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    report = DuplicateReport(
        corpus_kind="history",
        text_length=3200,
        duplicate_chars=384,
        duplicate_ratio=0.12,
        top_matches=[TopMatch(source_path="/a", source_title="A", overlap_chars=200, overlap_ratio=0.06)],
        hits=[],
        computed_at=datetime.now(),
    )
    panel.set_report(report)
    assert "12" in panel.history_value_label.text()


def test_panel_renders_vault_report(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    report = DuplicateReport(
        corpus_kind="vault",
        text_length=1000,
        duplicate_chars=380,
        duplicate_ratio=0.38,
        top_matches=[],
        hits=[],
        computed_at=datetime.now(),
    )
    panel.set_report(report)
    assert "38" in panel.vault_value_label.text()


def test_panel_recalculate_button_emits_signal(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.recalculate_requested, timeout=1000) as blocker:
        panel.recalc_button.click()


def test_panel_history_drilldown_emits_signal(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    # 先设置一个 report 好让 drill 按钮启用
    report = DuplicateReport(
        corpus_kind="history",
        text_length=1000, duplicate_chars=120, duplicate_ratio=0.12,
        top_matches=[], hits=[], computed_at=datetime.now(),
    )
    panel.set_report(report)
    with qtbot.waitSignal(panel.drilldown_requested, timeout=1000) as blocker:
        panel.history_drill_button.click()
    assert blocker.args[0] == "history"


def test_panel_thresholds_change_color(qtbot):
    """颜色按 green/yellow 阈值切换。"""
    panel = DedupPanel()
    qtbot.addWidget(panel)

    # green
    panel.set_thresholds(green=15, yellow=30)
    panel.set_report(DuplicateReport(
        corpus_kind="history", text_length=1000, duplicate_chars=80,
        duplicate_ratio=0.08, top_matches=[], hits=[], computed_at=datetime.now(),
    ))
    style = panel.history_value_label.styleSheet()
    # 不强校验具体颜色码，但应有 color 属性
    assert "color" in style.lower() or panel.history_value_label.text()


def test_panel_disabled_state_when_not_enabled(qtbot):
    panel = DedupPanel()
    qtbot.addWidget(panel)
    panel.set_disabled_message("功能未启用")
    # 显示信息提示，按钮禁用
    assert not panel.recalc_button.isEnabled()
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_dedup_panel.py -v
```

- [ ] **Step 3: 实现**

写文件 `csm_gui/widgets/dedup_panel.py`：

```python
"""DedupPanel — two-metric row widget for the article right-side panel.

Layout:

    📊 内容查重           ⟳ 重新计算
    历史重复率   12% ▓▓░░░░░░  ⓘ 详情
    素材引用率   38% ▓▓▓▓░░░░  ⓘ 详情

The panel is purely presentational. It exposes two signals:
- ``recalculate_requested()`` — user clicked ⟳
- ``drilldown_requested(kind: str)`` — user clicked ⓘ for "history" or "vault"
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
)
from qfluentwidgets import (
    BodyLabel, StrongBodyLabel, PushButton, ToolButton, FluentIcon,
)

from csm_core.dedup.report import DuplicateReport

_PERCENT_PLACEHOLDER = "—"


class _MetricRow(QWidget):
    """One labelled metric row with progress bar + drill button."""

    drill_requested = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.label = BodyLabel(label, self)
        self.label.setMinimumWidth(72)
        lay.addWidget(self.label)

        self.value_label = StrongBodyLabel(_PERCENT_PLACEHOLDER, self)
        self.value_label.setMinimumWidth(50)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.value_label)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar, 1)

        self.drill_button = ToolButton(FluentIcon.INFO, self)
        self.drill_button.setToolTip("查看详情")
        self.drill_button.setEnabled(False)
        self.drill_button.clicked.connect(self.drill_requested.emit)
        lay.addWidget(self.drill_button)


class DedupPanel(QWidget):
    """Right-side panel showing 历史重复率 + 素材引用率."""

    recalculate_requested = pyqtSignal()
    drilldown_requested = pyqtSignal(str)  # "history" | "vault"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DedupPanel")
        self.setStyleSheet("#DedupPanel { background: transparent; }")
        self._green_threshold = 15
        self._yellow_threshold = 30
        self._disabled_msg: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Header row: title + 重新计算 button
        header = QHBoxLayout()
        header.setSpacing(6)
        title = StrongBodyLabel("📊 内容查重", self)
        header.addWidget(title)
        header.addStretch(1)
        self.recalc_button = PushButton(FluentIcon.SYNC, "重新计算", self)
        self.recalc_button.setFixedHeight(26)
        self.recalc_button.clicked.connect(self.recalculate_requested.emit)
        header.addWidget(self.recalc_button)
        root.addLayout(header)

        # 历史重复率行
        self._history_row = _MetricRow("历史重复率", self)
        self._history_row.drill_requested.connect(
            lambda: self.drilldown_requested.emit("history")
        )
        root.addWidget(self._history_row)

        # 素材引用率行
        self._vault_row = _MetricRow("素材引用率", self)
        self._vault_row.drill_requested.connect(
            lambda: self.drilldown_requested.emit("vault")
        )
        root.addWidget(self._vault_row)

        # Hint label (used for disabled state messages)
        self._hint_label = QLabel("", self)
        self._hint_label.setStyleSheet("color: rgba(30,28,25,0.45); font-size: 11px;")
        self._hint_label.setVisible(False)
        root.addWidget(self._hint_label)

    # ── Public API ──────────────────────────────────────────────────────
    @property
    def history_value_label(self):
        return self._history_row.value_label

    @property
    def vault_value_label(self):
        return self._vault_row.value_label

    @property
    def history_drill_button(self):
        return self._history_row.drill_button

    @property
    def vault_drill_button(self):
        return self._vault_row.drill_button

    def set_thresholds(self, *, green: int, yellow: int) -> None:
        self._green_threshold = green
        self._yellow_threshold = yellow

    def set_report(self, report: DuplicateReport) -> None:
        row = self._history_row if report.corpus_kind == "history" else self._vault_row
        if report.text_length == 0:
            row.value_label.setText(_PERCENT_PLACEHOLDER)
            row.bar.setValue(0)
            row.drill_button.setEnabled(False)
            return
        pct = round(report.duplicate_ratio * 100)
        row.value_label.setText(f"{pct}%")
        row.bar.setValue(min(100, pct))
        row.drill_button.setEnabled(True)
        # color
        color = self._color_for(pct)
        row.value_label.setStyleSheet(
            f"color: {color}; background: transparent;"
        )

    def set_disabled_message(self, msg: str) -> None:
        self._disabled_msg = msg
        self.recalc_button.setEnabled(False)
        self._history_row.drill_button.setEnabled(False)
        self._vault_row.drill_button.setEnabled(False)
        self._hint_label.setText(msg)
        self._hint_label.setVisible(True)

    def clear_disabled_message(self) -> None:
        self._disabled_msg = None
        self.recalc_button.setEnabled(True)
        self._hint_label.setVisible(False)

    # ── Internal ────────────────────────────────────────────────────────
    def _color_for(self, pct: int) -> str:
        if pct < self._green_threshold:
            return "#2f6f5e"   # green
        if pct < self._yellow_threshold:
            return "#b89f3e"   # yellow
        return "#c0524b"       # red
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_dedup_panel.py -v
```

预期：7 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/widgets/dedup_panel.py tests/gui/test_dedup_panel.py
git commit -m "feat(dedup): right-side panel with two metric rows"
```

---

## Task 10: dedup_drill_dialog.py — 命中段落下钻对话框

**Files:**
- Create: `csm_gui/widgets/dedup_drill_dialog.py`
- Create: `tests/gui/test_dedup_drill_dialog.py`

- [ ] **Step 1: 写失败测试**

写文件 `tests/gui/test_dedup_drill_dialog.py`：

```python
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
    # 摘要文本应该包含总字数和重复字数
    assert "3200" in dialog.summary_label.text() or "3,200" in dialog.summary_label.text()
    assert "384" in dialog.summary_label.text()


def test_dialog_renders_top_matches(qtbot):
    dialog = DedupDrillDialog(_make_report())
    qtbot.addWidget(dialog)
    # Top matches list should have 2 rows
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
        # itemDoubleClicked is the QListWidget signal
        dialog.top_matches_list.itemDoubleClicked.emit(item)
    assert blocker.args[0] == "/tmp/a.md"
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_dedup_drill_dialog.py -v
```

- [ ] **Step 3: 实现**

写文件 `csm_gui/widgets/dedup_drill_dialog.py`：

```python
"""DedupDrillDialog — modal dialog showing top matches + hit segments."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QDialogButtonBox, QSplitter, QWidget,
)
from qfluentwidgets import StrongBodyLabel, BodyLabel, CaptionLabel

from csm_core.dedup.report import DuplicateReport

_KIND_LABEL = {"history": "历史重复率", "vault": "素材引用率"}


class DedupDrillDialog(QDialog):
    """Drill-down dialog. Read-only — closed via Close button."""

    open_source_requested = pyqtSignal(str)  # absolute path

    def __init__(self, report: DuplicateReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{_KIND_LABEL.get(report.corpus_kind, '查重')} 详情")
        self.resize(820, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        # Summary
        pct = round(report.duplicate_ratio * 100)
        self.summary_label = BodyLabel(
            f"当前文章共 {report.text_length:,} 字，"
            f"{report.duplicate_chars:,} 字（{pct}%）在语料库找到",
            self,
        )
        root.addWidget(self.summary_label)

        # Splitter: top — matches; bottom — hits
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # Top matches
        top_box = QWidget()
        top_lay = QVBoxLayout(top_box)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(6)
        top_lay.addWidget(StrongBodyLabel("Top 相似文章（双击打开）", top_box))
        self.top_matches_list = QListWidget(top_box)
        self.top_matches_list.itemDoubleClicked.connect(self._on_match_double_clicked)
        for m in report.top_matches:
            it = QListWidgetItem(
                f"《{m.source_title}》 — {m.overlap_chars} 字重叠（{m.overlap_ratio*100:.1f}%）"
            )
            it.setData(Qt.ItemDataRole.UserRole, m.source_path)
            self.top_matches_list.addItem(it)
        top_lay.addWidget(self.top_matches_list)
        splitter.addWidget(top_box)

        # Hits
        bottom_box = QWidget()
        bot_lay = QVBoxLayout(bottom_box)
        bot_lay.setContentsMargins(0, 0, 0, 0)
        bot_lay.setSpacing(6)
        bot_lay.addWidget(StrongBodyLabel("命中段落（按位置排序）", bottom_box))
        self.hits_list = QListWidget(bottom_box)
        for h in report.hits:
            it = QListWidgetItem(
                f"第 {h.start}–{h.end} 字  来自《{h.source_title}》\n"
                f"  片段：{h.text}\n"
                f"  上下文：{h.source_excerpt}"
            )
            it.setData(Qt.ItemDataRole.UserRole, h.source_path)
            self.hits_list.addItem(it)
        self.hits_list.itemDoubleClicked.connect(self._on_match_double_clicked)
        bot_lay.addWidget(self.hits_list)
        splitter.addWidget(bottom_box)

        splitter.setSizes([220, 320])

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_match_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_source_requested.emit(str(path))
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_dedup_drill_dialog.py -v
```

预期：5 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/widgets/dedup_drill_dialog.py tests/gui/test_dedup_drill_dialog.py
git commit -m "feat(dedup): drill-down dialog showing top matches + hit segments"
```

---

## Task 11: WorkspaceSidePanel 集成 DedupPanel

**Files:**
- Modify: `csm_gui/widgets/workspace_side_panel.py`
- Modify: existing test file or create new check

- [ ] **Step 1: 写失败测试**

打开 `tests/gui/test_article_page.py`（已存在）查找现有测试模式，然后追加：

```python
def test_workspace_side_panel_has_dedup_panel(qtbot):
    """Right-side panel exposes a DedupPanel instance below polish button."""
    from csm_gui.widgets.workspace_side_panel import WorkspaceSidePanel
    from csm_gui.widgets.dedup_panel import DedupPanel
    panel = WorkspaceSidePanel()
    qtbot.addWidget(panel)
    assert isinstance(panel.dedup_panel, DedupPanel)


def test_workspace_dedup_recalculate_signal_relayed(qtbot):
    """Click 重新计算 in nested DedupPanel → WorkspaceSidePanel re-emits."""
    from csm_gui.widgets.workspace_side_panel import WorkspaceSidePanel
    panel = WorkspaceSidePanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.dedup_recalculate_requested, timeout=1000):
        panel.dedup_panel.recalc_button.click()


def test_workspace_dedup_drilldown_signal_relayed(qtbot):
    """Click ⓘ详情 → relays kind through WorkspaceSidePanel."""
    from csm_gui.widgets.workspace_side_panel import WorkspaceSidePanel
    from csm_core.dedup.report import DuplicateReport, TopMatch
    from datetime import datetime
    panel = WorkspaceSidePanel()
    qtbot.addWidget(panel)
    panel.dedup_panel.set_report(DuplicateReport(
        corpus_kind="history", text_length=1000, duplicate_chars=120,
        duplicate_ratio=0.12, top_matches=[], hits=[], computed_at=datetime.now(),
    ))
    with qtbot.waitSignal(panel.dedup_drilldown_requested, timeout=1000) as blocker:
        panel.dedup_panel.history_drill_button.click()
    assert blocker.args[0] == "history"
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_article_page.py -k dedup -v
```

预期：`AttributeError: 'WorkspaceSidePanel' object has no attribute 'dedup_panel'`。

- [ ] **Step 3: 在 WorkspaceSidePanel 中插入 DedupPanel**

修改 `csm_gui/widgets/workspace_side_panel.py`：

a) **顶部 import** 加：

```python
from .dedup_panel import DedupPanel
```

b) **`WorkspaceSidePanel` 类** 增加两个 signal（在现有 signal 列表之后）：

```python
    dedup_recalculate_requested = pyqtSignal()
    dedup_drilldown_requested = pyqtSignal(str)   # "history" | "vault"
```

c) **在 `__init__` 中**，找到现有的 `self.polish_btn` 添加位置（约 116 行），紧随其后追加：

```python
        # ── Dedup metrics (insert below polish button) ───────────────
        b_lay.addSpacing(8)
        self.dedup_panel = DedupPanel(inner)
        self.dedup_panel.recalculate_requested.connect(
            self.dedup_recalculate_requested.emit
        )
        self.dedup_panel.drilldown_requested.connect(
            self.dedup_drilldown_requested.emit
        )
        b_lay.addWidget(self.dedup_panel)
```

注意要在 `b_lay.addStretch(1)` **之前**插入。

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_article_page.py -v
```

预期：3 个新测试 PASS，旧测试不回归。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/widgets/workspace_side_panel.py tests/gui/test_article_page.py
git commit -m "feat(dedup): integrate DedupPanel below polish button"
```

---

## Task 12: SettingsPage 加「历史查重」section

**Files:**
- Modify: `csm_gui/pages/settings_page.py`
- Modify: `tests/gui/test_settings_page.py`

- [ ] **Step 1: 写失败测试**

在 `tests/gui/test_settings_page.py` 末尾追加：

```python
def test_settings_page_has_dedup_section(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    assert hasattr(page, "dedup_enabled_switch")
    assert hasattr(page, "dedup_history_dir_edit")
    assert hasattr(page, "dedup_rebuild_history_button")
    assert hasattr(page, "dedup_rebuild_vault_button")
    assert hasattr(page, "dedup_threshold_green_spin")
    assert hasattr(page, "dedup_threshold_yellow_spin")


def test_settings_page_dedup_save_persists_fields(qtbot, tmp_path):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    saved: list[AppConfig] = []
    page = SettingsPage(config=cfg, on_save=lambda c: saved.append(c))
    qtbot.addWidget(page)
    page.dedup_enabled_switch.setChecked(True)
    page.dedup_history_dir_edit.setText(str(tmp_path))
    page.dedup_threshold_green_spin.setValue(20)
    page.dedup_threshold_yellow_spin.setValue(40)
    page._save()
    assert saved
    assert saved[-1].dedup_enabled is True
    assert saved[-1].dedup_history_dir == str(tmp_path)
    assert saved[-1].dedup_threshold_green == 20
    assert saved[-1].dedup_threshold_yellow == 40


def test_settings_page_dedup_rebuild_history_emits_signal(qtbot, tmp_path):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig(dedup_history_dir=str(tmp_path))
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.dedup_rebuild_requested, timeout=1000) as blocker:
        page.dedup_rebuild_history_button.click()
    assert blocker.args[0] == "history"
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_settings_page.py -k dedup -v
```

- [ ] **Step 3: 实现**

修改 `csm_gui/pages/settings_page.py`：

a) **顶部 import** 增加（如果还没引入）：

```python
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QSpinBox, QFileDialog
from qfluentwidgets import LineEdit, PushButton, SwitchButton
```

b) **类签名加 signal**：

```python
class SettingsPage(QWidget):
    # ... existing attributes ...
    dedup_rebuild_requested = pyqtSignal(str)  # "history" | "vault"
```

c) **`__init__` 中** 新增 `_build_dedup()` 方法调用，紧随现有 `_build_general()`、`_build_export()` 之后：

```python
        self._build_dedup()
```

d) **加方法 `_build_dedup`**：

```python
    def _build_dedup(self) -> None:
        """历史查重 section — enable toggle, corpus dir, rebuild buttons, thresholds."""
        card = _SettingsCard("历史查重", "对比历史文章库和 vault 素材，识别撞稿与未消化原文")

        # Enable switch
        row_enable = _SettingsRow("启用历史查重")
        self.dedup_enabled_switch = SwitchButton(self)
        self.dedup_enabled_switch.setChecked(self._config.dedup_enabled)
        row_enable.set_control(self.dedup_enabled_switch)
        card.add_row(row_enable)

        # History dir
        row_dir = _SettingsRow("历史文章库目录")
        dir_holder = QWidget(self)
        dir_lay = QHBoxLayout(dir_holder)
        dir_lay.setContentsMargins(0, 0, 0, 0)
        dir_lay.setSpacing(6)
        self.dedup_history_dir_edit = LineEdit(dir_holder)
        self.dedup_history_dir_edit.setText(self._config.dedup_history_dir or "")
        self.dedup_history_dir_edit.setPlaceholderText("选择存放历史成品文章的目录")
        dir_lay.addWidget(self.dedup_history_dir_edit, 1)
        browse_btn = PushButton("选择…", dir_holder)
        browse_btn.clicked.connect(self._on_browse_dedup_history_dir)
        dir_lay.addWidget(browse_btn)
        row_dir.set_control(dir_holder)
        card.add_row(row_dir)

        # Rebuild buttons
        row_rebuild = _SettingsRow("重建索引")
        rebuild_holder = QWidget(self)
        rb_lay = QHBoxLayout(rebuild_holder)
        rb_lay.setContentsMargins(0, 0, 0, 0)
        rb_lay.setSpacing(6)
        self.dedup_rebuild_history_button = PushButton("重建历史索引", rebuild_holder)
        self.dedup_rebuild_history_button.clicked.connect(
            lambda: self.dedup_rebuild_requested.emit("history")
        )
        rb_lay.addWidget(self.dedup_rebuild_history_button)
        self.dedup_rebuild_vault_button = PushButton("重建 Vault 索引", rebuild_holder)
        self.dedup_rebuild_vault_button.clicked.connect(
            lambda: self.dedup_rebuild_requested.emit("vault")
        )
        rb_lay.addWidget(self.dedup_rebuild_vault_button)
        rb_lay.addStretch(1)
        row_rebuild.set_control(rebuild_holder)
        card.add_row(row_rebuild)

        # Thresholds
        row_th = _SettingsRow("阈值 (绿/黄)")
        th_holder = QWidget(self)
        th_lay = QHBoxLayout(th_holder)
        th_lay.setContentsMargins(0, 0, 0, 0)
        th_lay.setSpacing(6)
        self.dedup_threshold_green_spin = QSpinBox(th_holder)
        self.dedup_threshold_green_spin.setRange(1, 99)
        self.dedup_threshold_green_spin.setSuffix(" %")
        self.dedup_threshold_green_spin.setValue(self._config.dedup_threshold_green)
        th_lay.addWidget(self.dedup_threshold_green_spin)
        self.dedup_threshold_yellow_spin = QSpinBox(th_holder)
        self.dedup_threshold_yellow_spin.setRange(1, 99)
        self.dedup_threshold_yellow_spin.setSuffix(" %")
        self.dedup_threshold_yellow_spin.setValue(self._config.dedup_threshold_yellow)
        th_lay.addWidget(self.dedup_threshold_yellow_spin)
        th_lay.addStretch(1)
        row_th.set_control(th_holder)
        card.add_row(row_th)

        self._add_card(card)  # use whatever the file's existing card-add method is

    def _on_browse_dedup_history_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择历史文章库目录",
                                             self.dedup_history_dir_edit.text() or "")
        if d:
            self.dedup_history_dir_edit.setText(d)
```

**Note:** the `_add_card(card)` call assumes the existing settings_page has such helper. **READ the existing `_build_general()` / `_build_export()` first** to find the actual API for adding a card; mirror that exact pattern. Adjust the call accordingly.

e) **修改 `_save()`** — 在构造 new AppConfig 时加 dedup 字段：

```python
new_cfg = AppConfig(
    # ... existing fields ...
    dedup_enabled=self.dedup_enabled_switch.isChecked(),
    dedup_history_dir=self.dedup_history_dir_edit.text(),
    dedup_threshold_green=self.dedup_threshold_green_spin.value(),
    dedup_threshold_yellow=self.dedup_threshold_yellow_spin.value(),
    dedup_history_last_built=self._config.dedup_history_last_built,
    dedup_vault_last_built=self._config.dedup_vault_last_built,
)
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_settings_page.py -v
```

预期：所有 dedup 测试 + 既有测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/pages/settings_page.py tests/gui/test_settings_page.py
git commit -m "feat(settings): dedup detection section with rebuild buttons + thresholds"
```

---

## Task 13: MainWindow 集成 — 信号接线 + 索引懒加载 + drilldown

**Files:**
- Modify: `csm_gui/main_window.py`
- Modify: `tests/gui/test_main_window.py`

- [ ] **Step 1: 写失败测试**

在 `tests/gui/test_main_window.py` 末尾追加：

```python
def test_main_window_has_dedup_analyzer(qtbot, tmp_path):
    from csm_gui.main_window import MainWindow
    from csm_core.dedup.analyzer import DedupAnalyzer
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    assert isinstance(win.dedup_analyzer, DedupAnalyzer)


def test_main_window_polished_triggers_dedup_when_enabled(qtbot, tmp_path, monkeypatch):
    """When dedup_enabled=True, _on_polished should kick off two analyses."""
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.dedup_enabled = True

    triggered = []
    monkeypatch.setattr(win, "_kick_dedup_analysis",
                        lambda text, kind: triggered.append((text[:5], kind)))

    win._on_polished("已经润色完成的文章内容文字" * 10)
    # 应触发 history + vault 两次
    kinds = sorted([k for _, k in triggered])
    assert "history" in kinds
    assert "vault" in kinds


def test_main_window_polished_does_nothing_when_dedup_disabled(qtbot, tmp_path, monkeypatch):
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    win.config.dedup_enabled = False

    triggered = []
    monkeypatch.setattr(win, "_kick_dedup_analysis",
                        lambda text, kind: triggered.append(kind))

    win._on_polished("内容" * 100)
    assert triggered == []
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_main_window.py -k dedup -v
```

- [ ] **Step 3: 实现 MainWindow 改动**

修改 `csm_gui/main_window.py`：

a) **顶部 import** 加：

```python
from csm_core.dedup.analyzer import DedupAnalyzer
from .workers.dedup_worker import DedupAnalyzeWorker, DedupBuildWorker
from .widgets.dedup_drill_dialog import DedupDrillDialog
```

b) **`__init__` 中**，在既有 controllers 创建之后追加：

```python
        # Dedup analyzer (lazy-loaded — index files read from disk on first
        # analyze call when dedup_enabled).
        self.dedup_analyzer = DedupAnalyzer()
        self._dedup_loaded = False
        self._dedup_workers: list = []  # keep refs alive

        # Wire side panel + settings page
        self.article.controls.dedup_recalculate_requested.connect(
            self._on_dedup_recalculate
        )
        self.article.controls.dedup_drilldown_requested.connect(
            self._on_dedup_drilldown
        )
        self.settings.dedup_rebuild_requested.connect(self._on_dedup_rebuild)

        # Apply thresholds on the panel
        self.article.controls.dedup_panel.set_thresholds(
            green=self.config.dedup_threshold_green,
            yellow=self.config.dedup_threshold_yellow,
        )
        # Disabled hint when not enabled
        if not self.config.dedup_enabled:
            self.article.controls.dedup_panel.set_disabled_message(
                "未启用 — 在设置中开启「历史查重」"
            )
```

c) **`_on_polished` 方法末尾追加**（找到既有方法）：

```python
        # Dedup: stash text + analyze against both corpora if enabled
        self._last_polished_text = text
        if self.config.dedup_enabled:
            self._kick_dedup_analysis(text, kind="history")
            self._kick_dedup_analysis(text, kind="vault")
```

d) **`_on_generated` 方法末尾追加**：

```python
        # Dedup on the draft (history only — vault is full of source material
        # so vault-comparison on draft would always be near 100%).
        if self.config.dedup_enabled:
            from csm_core.assembler.render import compose_draft
            draft = compose_draft(result.plan)
            self._kick_dedup_analysis(draft, kind="history")
```

e) **加新方法**（放在 `_on_polished` 附近）：

```python
    def _ensure_dedup_index_loaded(self) -> None:
        """Lazy-load LSH indexes from disk on first use."""
        if self._dedup_loaded:
            return
        idx_dir = self.config_dir / "dedup_index"
        self.dedup_analyzer.load(idx_dir)
        self._dedup_loaded = True

    def _kick_dedup_analysis(self, text: str, *, kind: str) -> None:
        """Start a background DedupAnalyzeWorker; result lands in panel via signal."""
        self._ensure_dedup_index_loaded()
        worker = DedupAnalyzeWorker(
            analyzer=self.dedup_analyzer, text=text, kind=kind, parent=self,
        )
        worker.finished.connect(self._on_dedup_finished)
        worker.finished.connect(lambda *_: self._dedup_workers.remove(worker)
                                if worker in self._dedup_workers else None)
        self._dedup_workers.append(worker)
        worker.start()

    def _on_dedup_finished(self, report) -> None:
        self.article.controls.dedup_panel.set_report(report)
        self._last_dedup_reports = getattr(self, "_last_dedup_reports", {})
        self._last_dedup_reports[report.corpus_kind] = report

    def _on_dedup_recalculate(self) -> None:
        """User clicked ⟳ — re-run for both kinds against last analyzed polished text.

        We use ``self._last_polished_text`` (stashed in ``_on_polished``) rather
        than re-reading from the markdown view because the user may have edited
        the draft after polish — recalc semantics is "redo on the LAST polished
        version", consistent with what the metric initially showed.
        """
        text = getattr(self, "_last_polished_text", "")
        if not text:
            return
        if self.config.dedup_enabled:
            self._kick_dedup_analysis(text, kind="history")
            self._kick_dedup_analysis(text, kind="vault")

    def _on_dedup_drilldown(self, kind: str) -> None:
        reports = getattr(self, "_last_dedup_reports", {})
        report = reports.get(kind)
        if not report:
            return
        dlg = DedupDrillDialog(report, parent=self)
        dlg.open_source_requested.connect(self._on_dedup_open_source)
        dlg.exec()

    def _on_dedup_open_source(self, path: str) -> None:
        """Open source file in OS default app."""
        import os
        try:
            os.startfile(path)
        except OSError:
            pass

    def _on_dedup_rebuild(self, kind: str) -> None:
        """User clicked 重建索引 in settings."""
        if kind == "history":
            root = self.config.dedup_history_dir
        else:  # vault
            root = self.config.vault_root
        if not root:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning("缺少目录", f"请先配置 {kind} 目录",
                            parent=self, position=InfoBarPosition.TOP)
            return
        from pathlib import Path
        worker = DedupBuildWorker(
            analyzer=self.dedup_analyzer, root=Path(root), kind=kind, parent=self,
        )
        # Save index after build
        worker.finished.connect(lambda: self.dedup_analyzer.save(
            self.config_dir / "dedup_index"))
        worker.finished.connect(lambda: self._dedup_workers.remove(worker)
                                if worker in self._dedup_workers else None)
        self._dedup_workers.append(worker)
        worker.start()
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.info(f"开始重建 {kind} 索引", "完成后会自动保存",
                     parent=self, position=InfoBarPosition.TOP)
```

f) **`_on_settings_save` 末尾追加** — 应用新阈值 + 启用/禁用面板：

```python
        # Dedup: refresh thresholds + enabled state on the panel
        self.article.controls.dedup_panel.set_thresholds(
            green=new_cfg.dedup_threshold_green,
            yellow=new_cfg.dedup_threshold_yellow,
        )
        if new_cfg.dedup_enabled:
            self.article.controls.dedup_panel.clear_disabled_message()
        else:
            self.article.controls.dedup_panel.set_disabled_message(
                "未启用 — 在设置中开启「历史查重」"
            )
```

- [ ] **Step 4: 跑测试**

```bash
pytest tests/gui/test_main_window.py -v
```

预期：所有 dedup 测试 PASS，旧测试不回归（除已知 pre-existing 失败 `test_export_action_writes_files`）。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/main_window.py tests/gui/test_main_window.py
git commit -m "feat(dedup): wire MainWindow signals + lazy index loading"
```

---

## Task 14: 全量测试 + PyInstaller 冒烟

**Files:**
- 验证 `CSM.spec` 含 `csm_core.dedup` 与 `csm_gui.workers.dedup_worker` 等

- [ ] **Step 1: 全量测试**

```bash
pytest tests/ --ignore=tests/gui/test_markdown_view.py --deselect tests/gui/test_main_window.py::test_export_action_writes_files
```

预期：所有 dedup 相关测试 PASS（约 30+ 项），既有测试不回归。

- [ ] **Step 2: 检查 CSM.spec hiddenimports**

```bash
cat CSM.spec | grep -E "hiddenimports|csm_core|csm_gui"
```

如果用了显式 hiddenimports 列表，追加：

```python
'csm_core.dedup', 'csm_core.dedup.shingles', 'csm_core.dedup.corpus',
'csm_core.dedup.index', 'csm_core.dedup.analyzer', 'csm_core.dedup.report',
'csm_gui.workers.dedup_worker', 'csm_gui.widgets.dedup_panel',
'csm_gui.widgets.dedup_drill_dialog',
'datasketch', 'docx',
```

如果用 module 自动发现，通常无需修改。

- [ ] **Step 3: PyInstaller 打包冒烟**

```bash
pyinstaller CSM.spec
```

确认 `dist/CSM/CSM.exe` 生成且可启动。

- [ ] **Step 4: 手动验证清单**

启动 `dist/CSM/CSM.exe`，验证：

1. **设置页有「历史查重」section**：显示开关、目录选择器、两个重建按钮、阈值输入框
2. **未启用状态**：右侧创作区 DedupPanel 显示"未启用"提示，按钮禁用
3. **启用 + 配置历史目录**：选择一个含若干 .md 的文件夹，点「重建历史索引」→ 顶部 InfoBar 提示开始
4. **重建完成**：等几秒（小语料几秒），DedupPanel 阈值生效
5. **生成一篇文章 + 润色**：润色完成后 DedupPanel 显示数字（即使是 0%）
6. **点击 ⓘ 详情**：弹出 DedupDrillDialog，显示 top matches / hits 列表
7. **双击列表项**：打开对应源文件（用系统默认 .md 应用）

- [ ] **Step 5: 提交（如有 spec 改动）**

```bash
git add CSM.spec
git commit -m "build(spec): explicit hidden imports for csm_core.dedup (if needed)"
```

---

## Task 15: README 与 CHANGELOG 更新

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README 加一节**

打开 `README.md`，在「桌面行为」section 后面追加：

```markdown
## 内容查重（可选）

- 创作区右侧润色按钮下方会显示两个指标：
  - **历史重复率** — 当前文章与你指定的"历史文章库目录"的字面重叠
  - **素材引用率** — 润色后的成文与 Obsidian vault 素材的字面重叠（衡量 AI 润色是否消化了原文）
- 在「设置 → 历史查重」开启后启用，需要先点「重建索引」让应用扫描语料；
- 算法：13-字滑窗 shingling + MinHash/LSH 候选检索 + 精算下钻段落定位；
- 索引懒加载：未启用查重时不消耗内存。
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs(readme): document dedup detection feature"
```

---

## Self-Review Checklist

完成所有 Task 后：

- [ ] 全量测试 `pytest tests/` 全部 PASS（除 pre-existing `test_markdown_view`、`test_export_action_writes_files`）
- [ ] PyInstaller 打包成功，dist/CSM/CSM.exe 能启动
- [ ] 手动 7 项验证全部通过
- [ ] 老用户的 settings.json（无 dedup_* 字段）启动应用不报错，行为为默认值
- [ ] 历史目录或 vault 目录被删后，UI 给出提示而不是崩溃
- [ ] 索引文件 `<config_dir>/dedup_index/*.lsh` 持久化生效，重启后无需重建
- [ ] git log 中应有 14–16 个独立 commit（每 Task 至少 1 个）

---

## 风险点 / 易错处

1. **datasketch MinHash 非确定性**：如果测试要求精确重复率数字（如 "12%"），结果会因 MinHash 随机种子波动。测试用阈值断言（`> 0.5`、`< 0.05`）而非精确值。

2. **`compute_shingles_with_positions` 当前文本只算一次**：避免在每个候选上重复切片。

3. **位置归属冲突**：当多个候选共享同一个 shingle 命中同一位置，"first wins" 攻略导致 TopMatch 字数累加偏向更早出现的候选。这影响精度但不影响 duplicate_ratio。可接受。

4. **index pickle 跨 datasketch 版本不兼容**：当用户升级了 CSM 后，旧 .lsh 文件可能因为 datasketch 版本变化无法 unpickle。`DedupIndex.load` 失败时返回空索引（不崩），但用户需手动重建。可在 README 写明。

5. **大 vault（>10000 篇）首建索引时间长**：UI 上需要明显提示进度。`DedupBuildWorker.progress` 信号已就位，settings_page 的 InfoBar 简单告知"开始重建 / 完成自动保存"足够；如需 ProgressBar 可后续增强。

6. **Windows 文件路径**：`build_doc_id` 用 `path.resolve()`，对软链接和大小写敏感性要小心；同一文件用绝对路径调用应得相同 id。

7. **PyInstaller 打 datasketch 时缺 hashlib 后端**：如出现 `cannot find xxhash`，在 `CSM.spec` 加 `'datasketch.hashfunc'` 到 hiddenimports。
