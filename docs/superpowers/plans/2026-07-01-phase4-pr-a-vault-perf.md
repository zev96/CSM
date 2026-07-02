# PR-A vault-perf 实现计划（增量索引 + 长文分块）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① vault 索引增量化（stat 巡走、仅重解析变更文件、异常/配置关回退全量）；② AI 拆条长文分块（确定性切分 + 前端逐块循环 + 进度/取消/去重）。

**Architecture:** csm_core 出纯函数/纯类（`parse_one`/`IncrementalIndexer`/`split_for_atomize`）→ sidecar `vault_service.get()` 统一入口 + 5 调用点切换 + 无状态 split 路由 → 前端 materials store 分块循环。行为零回归：增量输出与全量逐字段相等；`vault_incremental=False` 或任何异常回全量；`POST /api/vault/atomize` 零改动。详见 `docs/superpowers/specs/2026-07-01-phase4-plus-design.md` §1-§2。

**Tech Stack:** Python（dataclass + pydantic + pytest）/ FastAPI sidecar / Vue 3 + Pinia + TS + vitest。

**测试命令（worktree 无 .venv，用主仓解释器 + PYTHONPATH 覆盖）：**
- csm_core：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/vault_cache/ -v
  ```
- sidecar（双路径，否则测到主仓 editable 旧码）：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4;D:\CSM\.claude\worktrees\affectionate-heisenberg-9bbcf4\sidecar"; & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_vault_service_incremental.py sidecar/tests/test_atomize_split.py -v
  ```
- 前端（worktree 若无 node_modules 先 `cd frontend; npm ci`）：
  ```powershell
  cd frontend; npx vitest run src/stores/__tests__/materials.chunk.spec.ts src/components/materials/__tests__/AtomizePanel.chunk.spec.ts
  cd frontend; npx vue-tsc -b
  ```
  > `vue-tsc -b` 可能 emit `vite.config.js`/`.d.ts` → 跑完 `git checkout -- frontend/vite.config.js` 还原。

---

## File Structure

**Unit A — csm_core 增量索引**
- Modify: `csm_core/vault/scanner.py` — 抽 `parse_one`，`scan_vault` 改用（行为字节级不变）
- Create: `csm_core/vault/index_cache.py` — `IncrementalIndexer`
- Test: `tests/core/vault_cache/__init__.py`、`test_parse_one.py`、`test_index_cache.py`

**Unit B — sidecar 接线**
- Modify: `csm_core/config.py` — `AppConfig.vault_incremental: bool = True`
- Modify: `sidecar/csm_sidecar/services/vault_service.py` — `get()` 新增、`scan()/invalidate()` 改经 indexer
- Modify: `sidecar/csm_sidecar/services/generate_service.py:186,325`、`atomize_service.py:57`、`assembler_service.py:87-89`、`vault_writer_service.py:41`、`lifespan.py:249` — 调用点切换
- Test: `sidecar/tests/test_vault_service_incremental.py`

**Unit C — 长文切分（csm_core + 路由）**
- Create: `csm_core/vault/chunking.py` — `split_for_atomize` / `ChunkResult`
- Modify: `sidecar/csm_sidecar/services/atomize_service.py` — `split()`（3 行）
- Modify: `sidecar/csm_sidecar/routes/vault_atomize.py` — `POST /api/vault/atomize/split`
- Test: `tests/core/vault_cache/test_chunking.py`、`sidecar/tests/test_atomize_split.py`

**Unit D — 前端分块循环**
- Modify: `frontend/src/stores/materials.ts` — `atomizeText` 分块路径 + `chunkProgress`/`cancelAtomize`/`lastAtomizeTruncated`
- Modify: `frontend/src/components/materials/AtomizePanel.vue` — 进度文案 + 取消按钮 + 截尾 toast
- Test: `frontend/src/stores/__tests__/materials.chunk.spec.ts`、`frontend/src/components/materials/__tests__/AtomizePanel.chunk.spec.ts`

---

# Unit A — csm_core 增量索引

## Task A1: scanner.parse_one 抽取（scan_vault 行为不变）

**Files:**
- Modify: `csm_core/vault/scanner.py`
- Create: `tests/core/vault_cache/__init__.py`（空）、`tests/core/vault_cache/test_parse_one.py`

- [ ] **Step 1: 写失败测试** `tests/core/vault_cache/test_parse_one.py`

```python
from pathlib import Path

from csm_core.vault.scanner import parse_one, scan_vault


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


GOOD = "---\n素材类型: 科普\n---\n\n正文①\n"
NO_FM = "没有 frontmatter 的裸文本\n"


def test_parse_one_good(tmp_path):
    note, warning = parse_one(_write(tmp_path / "a.md", GOOD))
    assert warning is None
    assert note is not None and note.id == "a"
    assert note.frontmatter.get("素材类型") == "科普"


def test_parse_one_missing_frontmatter(tmp_path):
    note, warning = parse_one(_write(tmp_path / "b.md", NO_FM))
    assert note is None
    assert warning == "b.md: 缺少 frontmatter"


def test_parse_one_broken_yaml(tmp_path):
    note, warning = parse_one(_write(tmp_path / "c.md", "---\n: [broken\n---\nx"))
    assert note is None
    assert warning is not None and warning.startswith("c.md: 解析失败")


def test_scan_vault_unchanged(tmp_path):
    _write(tmp_path / "a.md", GOOD)
    _write(tmp_path / "b.md", NO_FM)
    idx = scan_vault(tmp_path)
    assert [n.id for n in idx.notes] == ["a"]
    assert idx.warnings == ["b.md: 缺少 frontmatter"]
    assert idx.by_id["a"].id == "a"
```

- [ ] **Step 2: 跑测试确认失败**

Run: csm_core 测试命令指向 `tests/core/vault_cache/test_parse_one.py`
Expected: FAIL（`ImportError: parse_one`）

- [ ] **Step 3: 实现** —— `scanner.py` 的 `scan_vault` 上方加 `parse_one`，`scan_vault` 改写为调用它（`VaultIndex` 类不动）：

```python
def parse_one(md_path: Path) -> tuple[ParsedNote | None, str | None]:
    """单文件解析：返回 (note, warning)，二者恰有其一非 None。

    与 scan_vault 的逐文件逻辑等价：缺 frontmatter → (None, 警告)；
    解析异常 → (None, 警告)。供全量扫与增量索引共用。
    """
    try:
        note = parse_note(md_path)
    except Exception as exc:
        return None, f"{md_path.name}: 解析失败 — {exc}"
    if not note.frontmatter:
        return None, f"{md_path.name}: 缺少 frontmatter"
    return note, None


def scan_vault(root: Path) -> VaultIndex:
    index = VaultIndex(root=root)
    for md_path in sorted(root.rglob("*.md")):
        note, warning = parse_one(md_path)
        if warning:
            index.warnings.append(warning)
        if note is not None:
            index.notes.append(note)
            index.by_id[note.id] = note
    return index
```

- [ ] **Step 4: 跑测试确认通过** — Expected: 4 passed；再跑既有 vault 相关套件确认零回归：`... -m pytest tests/ -k "vault or scanner" -v`

- [ ] **Step 5: commit**

```bash
git add csm_core/vault/scanner.py tests/core/vault_cache/
git commit -m "refactor(vault): 抽 parse_one 供全量/增量共用（scan_vault 行为不变）"
```

---

## Task A2: IncrementalIndexer

**Files:**
- Create: `csm_core/vault/index_cache.py`
- Create: `tests/core/vault_cache/test_index_cache.py`

- [ ] **Step 1: 写失败测试** `tests/core/vault_cache/test_index_cache.py`

```python
import os
from pathlib import Path

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


def _vault(tmp_path: Path) -> Path:
    _write(tmp_path / "a.md", GOOD)
    _write(tmp_path / "b.md", GOOD.replace("科普", "痛点"))
    (tmp_path / "sub").mkdir()
    _write(tmp_path / "sub" / "c.md", "没有 frontmatter\n")
    return tmp_path


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
```

> 本文件顶部 import 需含 `import pytest`。

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ModuleNotFoundError: index_cache`）

- [ ] **Step 3: 实现** `csm_core/vault/index_cache.py`

```python
"""增量 vault 索引：stat 巡走，仅重解析变更文件。

刷新语义：每次 refresh 都全量 stat 巡走（快，纯元数据），
(mtime_ns, size) 双键判变——共享盘 mtime 粒度粗时 size 兜底。
输出与 scan_vault 全量扫逐字段一致（notes 按 path 序、警告同序）。
巡走间被删/不可读的文件本轮跳过，下轮稳定后再收。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .note_parser import ParsedNote
from .scanner import VaultIndex, parse_one


@dataclass
class _Entry:
    mtime_ns: int
    size: int
    note: ParsedNote | None      # None = 该文件是警告项（缺 frontmatter/解析失败）
    warning: str | None


class IncrementalIndexer:
    def __init__(self) -> None:
        self._root: Path | None = None
        self._files: dict[Path, _Entry] = {}

    def reset(self) -> None:
        self._root = None
        self._files.clear()

    def refresh(self, root: Path) -> VaultIndex:
        root = Path(root)
        if self._root != root:
            self.reset()
            self._root = root
        seen: set[Path] = set()
        for md_path in sorted(root.rglob("*.md")):
            try:
                st = md_path.stat()
            except OSError:
                continue                     # 巡走间被删/锁：本轮跳过
            seen.add(md_path)
            entry = self._files.get(md_path)
            if (entry is not None
                    and entry.mtime_ns == st.st_mtime_ns
                    and entry.size == st.st_size):
                continue
            note, warning = parse_one(md_path)
            self._files[md_path] = _Entry(st.st_mtime_ns, st.st_size, note, warning)
        for stale in set(self._files) - seen:
            del self._files[stale]

        index = VaultIndex(root=root)
        for path in sorted(self._files):
            e = self._files[path]
            if e.warning:
                index.warnings.append(e.warning)
            if e.note is not None:
                index.notes.append(e.note)
                index.by_id[e.note.id] = e.note
        return index
```

- [ ] **Step 4: 跑测试确认通过** — Expected: `tests/core/vault_cache/` 全绿

- [ ] **Step 5: commit**

```bash
git add csm_core/vault/index_cache.py tests/core/vault_cache/test_index_cache.py
git commit -m "feat(vault): IncrementalIndexer 增量索引（stat 巡走 + 变更重解析 + 全量等价）"
```

---

# Unit B — sidecar 接线

## Task B1: config 开关 + vault_service.get

**Files:**
- Modify: `csm_core/config.py`（`AppConfig` 内）
- Modify: `sidecar/csm_sidecar/services/vault_service.py`
- Create: `sidecar/tests/test_vault_service_incremental.py`

> **config 隔离铁律**：sidecar 测试 monkeypatch `config_service.load`，绝不读开发机真实 settings.json（[[feedback_csm_baidu_fetch_test_config_isolation]]）。

- [ ] **Step 1: 写失败测试** `sidecar/tests/test_vault_service_incremental.py`

```python
from pathlib import Path

import pytest

from csm_core.config import AppConfig
import csm_core.vault.index_cache as index_cache
from csm_sidecar.services import vault_service

GOOD = "---\n素材类型: 科普\n---\n\n正文①\n"


@pytest.fixture(autouse=True)
def _reset():
    vault_service.invalidate()
    yield
    vault_service.invalidate()


@pytest.fixture
def patch_cfg(monkeypatch):
    def _set(**kw):
        monkeypatch.setattr(
            vault_service.config_service, "load", lambda: AppConfig(**kw))
    return _set


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text(GOOD, encoding="utf-8")
    return tmp_path


def _count_parses(monkeypatch):
    """双 spy：增量路径引用 index_cache.parse_one，全量路径（scan_vault）
    引用 scanner 模块自己的 parse_one —— 两处都打点才能数全。"""
    calls = []
    import csm_core.vault.scanner as scanner
    real = scanner.parse_one

    def spy(path):
        calls.append(path.name)
        return real(path)

    monkeypatch.setattr(index_cache, "parse_one", spy)
    monkeypatch.setattr(scanner, "parse_one", spy)
    return calls


def test_config_default_on():
    assert AppConfig.model_validate({}).vault_incremental is True


def test_get_incremental_and_cached(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)
    idx1 = vault_service.get(root)
    assert list(idx1.by_id) == ["a"]
    assert vault_service.cached() is idx1
    calls = _count_parses(monkeypatch)
    vault_service.get(root)
    assert calls == []                      # 第二次 get 零重解析


def test_get_config_off_falls_back_to_full(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=False)
    root = _vault(tmp_path)
    vault_service.get(root)
    calls = _count_parses(monkeypatch)
    idx = vault_service.get(root)
    # 配置关 → 每次 get 都走 scan()（scan_vault 全量），必重解析
    assert calls == ["a.md"]
    assert list(idx.by_id) == ["a"]


def test_get_exception_falls_back_to_full(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)

    def boom(_root):
        raise RuntimeError("stat 炸了")

    monkeypatch.setattr(vault_service._indexer, "refresh", boom)
    idx = vault_service.get(root)           # 不抛，回退全量
    assert list(idx.by_id) == ["a"]


def test_scan_forces_full(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)
    vault_service.get(root)
    calls = _count_parses(monkeypatch)
    vault_service.scan(root)
    assert calls == ["a.md"]                # 强制全量重解析


def test_invalidate_resets_indexer(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)
    vault_service.get(root)
    vault_service.invalidate()
    assert vault_service.cached() is None
    calls = _count_parses(monkeypatch)
    vault_service.get(root)
    assert calls == ["a.md"]                # reset 后全量
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`AppConfig` 无 `vault_incremental` / `vault_service` 无 `get`）

- [ ] **Step 3: 实现**

`csm_core/config.py` —— `AppConfig` 内 `pricing` 字段之后加：

```python
    # 素材库增量索引：stat 巡走仅重解析变更文件；关 = 每次全量重扫（今天行为）。
    vault_incremental: bool = True
```

`vault_service.py` 整体改为（保留 `note_to_dict`/`index_summary` 不动）：

```python
"""Vault service — 统一索引入口（增量快路径 + 全量兜底）。

get()  —— 常规入口：增量刷新（配置关/异常自动回退全量）。
scan() —— 强制全量重建（「重建索引」按钮 / 写盘后失效重建）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from csm_core.vault.index_cache import IncrementalIndexer
from csm_core.vault.note_parser import ParsedNote
from csm_core.vault.scanner import VaultIndex, scan_vault

from . import config_service

logger = logging.getLogger(__name__)

_indexer = IncrementalIndexer()
_index: VaultIndex | None = None


def get(root: Path) -> VaultIndex:
    """统一入口：增量刷新；vault_incremental=False 或异常 → 全量。"""
    global _index
    if not config_service.load().vault_incremental:
        return scan(root)
    try:
        _index = _indexer.refresh(Path(root))
    except Exception:
        logger.warning("增量索引失败，回退全量扫", exc_info=True)
        return scan(root)
    return _index


def scan(root: Path) -> VaultIndex:
    """强制全量重建。直调 scan_vault——回退路径与增量代码完全独立，
    增量索引出 bug 时兜底不受牵连；reset 保证下次 get() 全量重建缓存。"""
    global _index
    _indexer.reset()
    _index = scan_vault(Path(root))
    return _index


def cached() -> VaultIndex | None:
    return _index


def invalidate() -> None:
    global _index
    _index = None
    _indexer.reset()
```

> `scan()` 不再直调 `scan_vault`——经 indexer 全量重建，输出等价（A2 等价测试背书）且缓存保温。原模块 docstring 里的 SSE 备注可删。

- [ ] **Step 4: 跑测试确认通过** — Expected: 本文件全绿 + `sidecar/tests/test_vault_routes*.py`（若有）等既有 vault 相关测试不红

- [ ] **Step 5: commit**

```bash
git add csm_core/config.py sidecar/csm_sidecar/services/vault_service.py sidecar/tests/test_vault_service_incremental.py
git commit -m "feat(vault): vault_service.get 增量入口 + vault_incremental 配置（默认开、异常回退全量）"
```

---

## Task B2: 调用点切换（5 处）

**Files:**
- Modify: `sidecar/csm_sidecar/services/generate_service.py`
- Modify: `sidecar/csm_sidecar/services/atomize_service.py`
- Modify: `sidecar/csm_sidecar/services/assembler_service.py`
- Modify: `sidecar/csm_sidecar/services/vault_writer_service.py`
- Modify: `sidecar/csm_sidecar/lifespan.py`

- [ ] **Step 1: 逐处切换（无新测试——行为由既有套件 + B1 覆盖；本 Task 是接线）**

(a) `generate_service.py`：
- import 区：删 `from csm_core.vault.scanner import scan_vault`（确认无其他引用后）；`from . import (...)` 元组补 `vault_service,`（按字母序插在 `templates_service` 前）。
- `:186` `index = scan_vault(vault_root)` → `index = vault_service.get(vault_root)`
- `:325` `index = scan_vault(vault_root)` → `index = vault_service.get(vault_root)`，并把上方 322-323 的注释改为：

```python
        # 新鲜索引 + registry（与 _run_job 一致）。get() 是增量刷新：
        # 未变更文件复用缓存、变更即时可见，保证 scopes 命中型号。
```

(b) `atomize_service.py:57` `index = vault_service.scan(root)` → `index = vault_service.get(root)`

(c) `assembler_service.py:87-89`：

```python
    index = vault_service.cached()
    if index is None:
        index = vault_service.get(Path(cfg.vault_root))
```

(d) `vault_writer_service.py:41` `idx = vault_service.scan(_root())` → `idx = vault_service.get(_root())`（注释 `# fresh scan for the picker` 改 `# 增量刷新即可：写盘后 invalidate 已保证下次全量`）

(e) `lifespan.py:249` `await run_in_threadpool(vault_service.scan, root)` → `await run_in_threadpool(vault_service.get, root)`

- [ ] **Step 2: 全量回归**

Run: sidecar 全套 `... -m pytest sidecar/tests/ -v` + csm_core `tests/`（注意 [[project_csm_creation_studio_upgrade]] 记的 5 个预存失败与本工作无关，别排查）
Expected: 除已知预存失败外全绿

- [ ] **Step 3: commit**

```bash
git add sidecar/csm_sidecar/services/generate_service.py sidecar/csm_sidecar/services/atomize_service.py sidecar/csm_sidecar/services/assembler_service.py sidecar/csm_sidecar/services/vault_writer_service.py sidecar/csm_sidecar/lifespan.py
git commit -m "refactor(vault): 生成/拆条/reroll/写入器/启动扫 统一走 vault_service.get 增量入口"
```

---

# Unit C — 长文切分

## Task C1: chunking.split_for_atomize

**Files:**
- Create: `csm_core/vault/chunking.py`
- Create: `tests/core/vault_cache/test_chunking.py`

- [ ] **Step 1: 写失败测试** `tests/core/vault_cache/test_chunking.py`

```python
from csm_core.vault.chunking import ChunkResult, split_for_atomize

SENT_END = tuple("。！？!?\n")


def _nospace(s: str) -> str:
    return "".join(s.split())


def test_short_text_single_chunk():
    r = split_for_atomize("短文。", max_chars=100)
    assert r.chunks == ["短文。"] and r.truncated is False and r.dropped_chars == 0


def test_empty():
    assert split_for_atomize("  ") == ChunkResult()


def test_chunks_respect_max_and_sentence_boundary():
    text = "".join(f"第{i}句，测试内容比较长一些。" for i in range(200))
    r = split_for_atomize(text, max_chars=500)
    assert len(r.chunks) > 1
    for c in r.chunks:
        assert len(c) <= 500
        assert c.rstrip().endswith(SENT_END) or c is r.chunks[-1]


def test_no_content_loss_when_not_truncated():
    text = "\n\n".join(f"## 标题{i}\n" + "内容句。" * 50 for i in range(6))
    r = split_for_atomize(text, max_chars=400)
    assert r.truncated is False
    assert _nospace("".join(r.chunks)) == _nospace(text)


def test_heading_prefers_new_chunk():
    text = ("引言。" * 120) + "\n\n## 参数详解\n" + ("参数句。" * 120)
    r = split_for_atomize(text, max_chars=600)
    assert any(c.lstrip().startswith("## 参数详解") for c in r.chunks)


def test_cap_truncates_tail():
    text = "长句测试内容。" * 4000          # 28000 字
    r = split_for_atomize(text, max_chars=1000, cap=3)
    assert len(r.chunks) == 3 and r.truncated is True
    assert r.dropped_chars > 0


def test_pathological_no_punct_hard_cut():
    text = "字" * 2500
    r = split_for_atomize(text, max_chars=1000)
    assert len(r.chunks) == 3
    assert all(len(c) <= 1000 for c in r.chunks)
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（`ModuleNotFoundError: chunking`）

- [ ] **Step 3: 实现** `csm_core/vault/chunking.py`

```python
"""AI 拆条长文分块：确定性切分，绝不切断句子（病理无标点长文硬切兜底）。

切点优先级：markdown 标题行 > 空行段界 > 句界（。！？!?\\n）。
贪心装填至 max_chars；缓冲已 ≥60% 满且遇标题段 → 提前断块（章节聚拢）。
超 cap 块截尾（truncated + dropped_chars），调用方负责提示。
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

_HEADING_RE = re.compile(r"^#{1,6} ")
_SENT_END = "。！？!?\n"


class ChunkResult(BaseModel):
    chunks: list[str] = Field(default_factory=list)
    truncated: bool = False
    dropped_chars: int = 0


def _sentences(block: str) -> list[str]:
    out: list[str] = []
    buf = ""
    for ch in block:
        buf += ch
        if ch in _SENT_END:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _units(text: str, max_chars: int) -> list[tuple[str, bool]]:
    """切成 (unit, 是否标题段起点)；每个 unit 保证 ≤ max_chars。"""
    units: list[tuple[str, bool]] = []
    for block in re.split(r"\n{2,}", text):
        if not block.strip():
            continue
        is_heading = bool(_HEADING_RE.match(block.lstrip()))
        chunk_block = block + "\n\n"
        if len(chunk_block) <= max_chars:
            units.append((chunk_block, is_heading))
            continue
        first = True
        for sent in _sentences(chunk_block):
            while len(sent) > max_chars:          # 病理无标点长句：硬切兜底
                units.append((sent[:max_chars], is_heading and first))
                sent = sent[max_chars:]
                first = False
            if sent:
                units.append((sent, is_heading and first))
                first = False
    return units


def split_for_atomize(text: str, *, max_chars: int = 8000, cap: int = 8) -> ChunkResult:
    text = (text or "").strip()
    if not text:
        return ChunkResult()
    if len(text) <= max_chars:
        return ChunkResult(chunks=[text])

    chunks: list[str] = []
    buf = ""
    for unit, is_heading in _units(text, max_chars):
        over = len(buf) + len(unit) > max_chars
        heading_break = is_heading and len(buf) >= max_chars * 0.6
        if buf and (over or heading_break):
            chunks.append(buf.strip())
            buf = ""
        buf += unit
    if buf.strip():
        chunks.append(buf.strip())

    if len(chunks) > cap:
        dropped = sum(len(c) for c in chunks[cap:])
        return ChunkResult(chunks=chunks[:cap], truncated=True, dropped_chars=dropped)
    return ChunkResult(chunks=chunks)
```

- [ ] **Step 4: 跑测试确认通过** — Expected: 7 passed

- [ ] **Step 5: commit**

```bash
git add csm_core/vault/chunking.py tests/core/vault_cache/test_chunking.py
git commit -m "feat(vault): split_for_atomize 长文分块（标题/段界/句界优先级 + cap 截尾）"
```

---

## Task C2: split 端点

**Files:**
- Modify: `sidecar/csm_sidecar/services/atomize_service.py`
- Modify: `sidecar/csm_sidecar/routes/vault_atomize.py`
- Create: `sidecar/tests/test_atomize_split.py`

- [ ] **Step 1: 写失败测试** `sidecar/tests/test_atomize_split.py`（`client` fixture 来自 conftest，带 token）

```python
def test_split_short(client):
    r = client.post("/api/vault/atomize/split", json={"text": "短文。"})
    assert r.status_code == 200
    body = r.json()
    assert body["chunks"] == ["短文。"]
    assert body["truncated"] is False and body["dropped_chars"] == 0


def test_split_empty(client):
    r = client.post("/api/vault/atomize/split", json={"text": ""})
    assert r.status_code == 200
    assert r.json() == {"chunks": [], "truncated": False, "dropped_chars": 0}


def test_split_long_multi_chunk(client):
    text = "测试句子内容。" * 3000        # 21000 字 > 8000
    r = client.post("/api/vault/atomize/split", json={"text": text})
    assert r.status_code == 200
    chunks = r.json()["chunks"]
    assert len(chunks) >= 2
    assert all(len(c) <= 8000 for c in chunks)


def test_split_missing_text_422(client):
    assert client.post("/api/vault/atomize/split", json={}).status_code == 422
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（404 路由不存在）

- [ ] **Step 3: 实现**

`atomize_service.py` —— import 区加 `from csm_core.vault.chunking import ChunkResult, split_for_atomize`，`_MAX_INPUT` 注释更新 + 文件尾加：

```python
def split(text: str) -> ChunkResult:
    """长文预切分（无状态纯计算，不扫库不打 LLM）。单块 ≤ _MAX_INPUT。"""
    return split_for_atomize(text or "", max_chars=_MAX_INPUT)
```

`_MAX_INPUT` 行注释改为：`# 单次拆条输入上限；前端超长时先走 /split 分块。直调超长仍截断兜底。`

`routes/vault_atomize.py` 文件尾加：

```python
class SplitBody(BaseModel):
    text: str


@router.post("/api/vault/atomize/split")
def split(body: SplitBody) -> dict[str, Any]:
    """长文预切分：纯计算无副作用，不需要 LLM/vault，无 503/400 映射。"""
    return atomize_service.split(body.text).model_dump()
```

- [ ] **Step 4: 跑测试确认通过** — Expected: 4 passed；`test_atomize_service.py`/`test_vault_atomize_routes` 既有套件不红

- [ ] **Step 5: commit**

```bash
git add sidecar/csm_sidecar/services/atomize_service.py sidecar/csm_sidecar/routes/vault_atomize.py sidecar/tests/test_atomize_split.py
git commit -m "feat(atomize): POST /api/vault/atomize/split 长文预切分端点"
```

---

# Unit D — 前端分块循环

## Task D1: materials store 分块 atomizeText

**Files:**
- Modify: `frontend/src/stores/materials.ts`
- Create: `frontend/src/stores/__tests__/materials.chunk.spec.ts`

- [ ] **Step 1: 写失败测试** `frontend/src/stores/__tests__/materials.chunk.spec.ts`

```ts
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn();
const get = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { post, get } }),
}));

import { useMaterials, type AtomDraft } from "@/stores/materials";

const atom = (text: string, folder = "营销资料库/科普"): AtomDraft => ({
  text, rel_folder: folder, material_type: "科普", product: "希喂",
  keyword: "k", filename: "f.md", confidence: "high", warnings: [],
});

describe("materials 分块拆条", () => {
  beforeEach(() => { setActivePinia(createPinia()); post.mockReset(); });

  it("短文走原路径（不调 split）", async () => {
    post.mockResolvedValueOnce({ data: { atoms: [atom("a")] } });
    const m = useMaterials();
    const out = await m.atomizeText("短文");
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][0]).toBe("/api/vault/atomize");
    expect(out).toHaveLength(1);
  });

  it("长文：split → 逐块 atomize → 合并", async () => {
    const long = "字".repeat(9000);
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2"], truncated: false, dropped_chars: 0 } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("a1")] } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("a2")] } });
    const m = useMaterials();
    const out = await m.atomizeText(long);
    expect(post.mock.calls.map((c) => c[0])).toEqual([
      "/api/vault/atomize/split", "/api/vault/atomize", "/api/vault/atomize",
    ]);
    expect(out.map((a) => a.text)).toEqual(["a1", "a2"]);
    expect(m.chunkProgress).toBeNull();          // 收尾清空
  });

  it("跨块重复原子去重", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2"], truncated: false, dropped_chars: 0 } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("同一条要点。")] } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("同一条 要点。")] } });   // 空白差异
    const m = useMaterials();
    const out = await m.atomizeText("字".repeat(9000));
    expect(out).toHaveLength(1);
  });

  it("truncated 透出", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1"], truncated: true, dropped_chars: 123 } });
    post.mockResolvedValueOnce({ data: { atoms: [] } });
    const m = useMaterials();
    await m.atomizeText("字".repeat(9000));
    expect(m.lastAtomizeTruncated).toEqual({ dropped: 123 });
  });

  it("取消中断后续块", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2", "c3"], truncated: false, dropped_chars: 0 } });
    const m = useMaterials();
    post.mockImplementationOnce(async () => {
      m.cancelAtomize();                          // 第 1 块进行中点取消
      return { data: { atoms: [atom("a1")] } };
    });
    const out = await m.atomizeText("字".repeat(9000));
    expect(out.map((a) => a.text)).toEqual(["a1"]);
    expect(post).toHaveBeenCalledTimes(2);        // split + 1 块
  });

  it("某块失败：保留已拆 + 报错中断", async () => {
    post.mockResolvedValueOnce({ data: { chunks: ["c1", "c2"], truncated: false, dropped_chars: 0 } });
    post.mockResolvedValueOnce({ data: { atoms: [atom("a1")] } });
    post.mockRejectedValueOnce(new Error("net"));
    const m = useMaterials();
    const out = await m.atomizeText("字".repeat(9000));
    expect(out.map((a) => a.text)).toEqual(["a1"]);
    expect(m.intakeError).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend; npx vitest run src/stores/__tests__/materials.chunk.spec.ts`
Expected: FAIL（`chunkProgress`/`cancelAtomize`/`lastAtomizeTruncated` 不存在；长文仍单调用）

- [ ] **Step 3: 实现** —— `materials.ts`：

(a) state 区（`intakeError` 旁）加：

```ts
  const chunkProgress = ref<{ current: number; total: number } | null>(null);
  const lastAtomizeTruncated = ref<{ dropped: number } | null>(null);
  const chunkCancelled = ref(false);

  const CHUNK_THRESHOLD = 8000;

  function cancelAtomize(): void {
    chunkCancelled.value = true;
  }

  function atomKey(a: AtomDraft): string {
    return `${a.rel_folder ?? ""}|${a.text.replace(/[\s\p{P}]/gu, "").slice(0, 80)}`;
  }
```

(b) `atomizeText` 整体替换为：

```ts
  async function atomizeText(text: string): Promise<AtomDraft[]> {
    intakeError.value = null;
    lastAtomizeTruncated.value = null;
    if (text.length <= CHUNK_THRESHOLD) {
      try {
        const r = await useSidecar().client.post("/api/vault/atomize", { text });
        return r.data.atoms ?? [];
      } catch (e: any) {
        intakeError.value = errMsg(e);
        return [];
      }
    }
    // 长文：先切块再逐块拆条（进度可见、块间可取消、跨块去重）
    chunkCancelled.value = false;
    let chunks: string[] = [];
    try {
      const r = await useSidecar().client.post("/api/vault/atomize/split", { text });
      chunks = r.data.chunks ?? [];
      if (r.data.truncated) {
        lastAtomizeTruncated.value = { dropped: r.data.dropped_chars ?? 0 };
      }
    } catch (e: any) {
      intakeError.value = errMsg(e);
      return [];
    }
    const seen = new Set<string>();
    const merged: AtomDraft[] = [];
    chunkProgress.value = { current: 0, total: chunks.length };
    try {
      for (let i = 0; i < chunks.length; i++) {
        if (chunkCancelled.value) break;
        chunkProgress.value = { current: i + 1, total: chunks.length };
        try {
          const r = await useSidecar().client.post("/api/vault/atomize", { text: chunks[i] });
          for (const a of (r.data.atoms ?? []) as AtomDraft[]) {
            const k = atomKey(a);
            if (seen.has(k)) continue;
            seen.add(k);
            merged.push(a);
          }
        } catch (e: any) {
          intakeError.value = errMsg(e);      // 中断但保留已拆的块
          break;
        }
      }
    } finally {
      chunkProgress.value = null;
    }
    return merged;
  }
```

(c) store `return {...}` 补：`chunkProgress, lastAtomizeTruncated, cancelAtomize,`

- [ ] **Step 4: 跑测试确认通过** — Expected: 6 passed；既有 `materials` 相关 spec 不红

- [ ] **Step 5: commit**

```bash
git add frontend/src/stores/materials.ts frontend/src/stores/__tests__/materials.chunk.spec.ts
git commit -m "feat(atomize): 前端长文分块循环（进度/取消/跨块去重/截尾透出）"
```

---

## Task D2: AtomizePanel 进度/取消/截尾 toast + vue-tsc

**Files:**
- Modify: `frontend/src/components/materials/AtomizePanel.vue`
- Create: `frontend/src/components/materials/__tests__/AtomizePanel.chunk.spec.ts`

- [ ] **Step 1: 写失败测试** `AtomizePanel.chunk.spec.ts`

```ts
import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const post = vi.fn().mockResolvedValue({ data: { atoms: [] } });
const get = vi.fn().mockResolvedValue({ data: { folders: [] } });
vi.mock("@/stores/sidecar", () => ({ useSidecar: () => ({ client: { post, get } }) }));

import AtomizePanel from "@/components/materials/AtomizePanel.vue";
import { useMaterials } from "@/stores/materials";

describe("AtomizePanel 分块 UI", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("chunkProgress 时显示进度并出现取消按钮", async () => {
    const w = mount(AtomizePanel, { global: { stubs: { teleport: true } } });
    const m = useMaterials();
    m.chunkProgress = { current: 2, total: 4 };
    await w.vm.$nextTick();
    expect(w.text()).toContain("分块 2/4");
    expect(w.find("[data-atomize-cancel]").exists()).toBe(true);
  });

  it("点取消调 cancelAtomize", async () => {
    const w = mount(AtomizePanel, { global: { stubs: { teleport: true } } });
    const m = useMaterials();
    m.chunkProgress = { current: 1, total: 3 };
    const spy = vi.spyOn(m, "cancelAtomize");
    await w.vm.$nextTick();
    await w.find("[data-atomize-cancel]").trigger("click");
    expect(spy).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — Expected: FAIL（无进度文案/取消按钮）

- [ ] **Step 3: 实现** —— `AtomizePanel.vue`：

(a) `run()` 里 `const a = await m.atomizeText(text.value);` 之后加：

```ts
    if (m.lastAtomizeTruncated) {
      notify.push(`原文超长，已截尾 ${m.lastAtomizeTruncated.dropped} 字（最多 8 块）`, { tone: "warn" });
    }
```

(b) 模板里拆条按钮的 `atomizing` 分支替换为（进度感知）：

```html
          <span v-if="atomizing" class="inline-flex items-center gap-1">
            <Spinner :size="12" />
            <template v-if="m.chunkProgress">分块 {{ m.chunkProgress.current }}/{{ m.chunkProgress.total }} 拆条中…</template>
            <template v-else>拆条中…</template>
          </span>
```

(c) 按钮组里「AI 拆条」按钮后加取消按钮：

```html
        <button v-if="m.chunkProgress" data-atomize-cancel
          class="rounded-lg border border-ink/15 px-3 py-1.5 text-sm text-ink/70"
          @click="m.cancelAtomize()">
          取消
        </button>
```

- [ ] **Step 4: 跑测试 + vue-tsc**

```powershell
cd frontend; npx vitest run src/components/materials/__tests__/AtomizePanel.chunk.spec.ts src/stores/__tests__/materials.chunk.spec.ts
cd frontend; npx vue-tsc -b
```
Expected: 全 passed；vue-tsc 0 错（fixture 字面量 union 显式标注 `AtomDraft`，CSM#144 教训）。跑完 `git checkout -- frontend/vite.config.js` 还原 emit。

- [ ] **Step 5: commit**

```bash
git add frontend/src/components/materials/AtomizePanel.vue frontend/src/components/materials/__tests__/AtomizePanel.chunk.spec.ts
git commit -m "feat(atomize): AtomizePanel 分块进度/取消/截尾提示"
```

---

# 收尾

- [ ] **全量回归**：csm_core `tests/` + sidecar `sidecar/tests/` + 前端全量 vitest + `vue-tsc -b`（5 个预存失败与本工作无关）。
- [ ] **最终综合审查**（opus）：增量/全量逐字段等价、5 调用点全切且无遗漏 scan_vault 直调（grep 验证 sidecar 内无 `scan_vault(`）、fail-open 三层（配置关/异常/巡走中 OSError）、分块不破句、前端取消/去重/截尾、零回归。
- [ ] **收尾 PR**：push `claude/phase4-vault-perf` + `gh pr create`（中文 body + 🤖 trailer），停在 pending 等网页 merge。

## 备注（实现者注意）

1. **共享盘红线**：所有测试用 tmp_path 合成 vault，绝不碰 `D:\家电组共享\DATA`。
2. **config 隔离铁律**：sidecar 测试 monkeypatch `vault_service.config_service.load`。
3. **mtime 分辨率**：测试改文件后用 `os.utime(ns=+2ms)` 显式 bump，防低分辨率文件系统 flaky。
4. **monkeypatch 目标是 `index_cache.parse_one`**（indexer 内部引用），不是 `scanner.parse_one`。
5. **teleport stub + 字面量 union**：组件测试 mount 加 `global:{stubs:{teleport:true}}`；fixture 显式标 `AtomDraft`。
