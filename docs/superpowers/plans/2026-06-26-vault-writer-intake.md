# Vault 写入器 + 手动录入（Phase 3a）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建确定性 Vault 写入器引擎 + MaterialsView「录入」tab 手动表单，把结构化素材安全写回共享盘 vault（规范 frontmatter/命名/双链/索引登记，diff/不覆盖/可撤销，无 AI）。

**Architecture:** 三层。csm_core 纯引擎（`folder_profile` 邻居推断 + `writer` plan/commit/undo，FS 直读不依赖 sidecar）；sidecar 薄服务+路由（取 `cfg.vault_root`、复用 `vault_service` 缓存与失效、校验路径）；前端 MaterialsView 真 tab + `IntakeForm.vue` 四步（选文件夹→自适应表单→diff→确认/撤销）。

**Tech Stack:** Python 3.12 / FastAPI / pytest（后端）；Vue 3 + Pinia + TS / vitest（前端）。

**设计稿:** [2026-06-26-vault-writer-intake-design.md](../specs/2026-06-26-vault-writer-intake-design.md)

**关键约定（实现者必读）:**
- **测试红线**：写/撤销测试一律用 pytest `tmp_path` 合成 vault，**绝不写真实共享盘 `D:\家电组共享\DATA`**。真实库只读回归用 `@pytest.mark.skipif(vault 不存在)` 门禁。
- 后端测试：PowerShell 双 PYTHONPATH。在 worktree 根跑：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"
  & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest <路径> -q
  ```
- 前端测试：`cd frontend; npx vitest run <spec>`；**推前必跑 `npx vue-tsc -b`**（vitest=esbuild 不做类型检查，CSM#144 栽过）。
- 圈码变体标记复用 `csm_core.vault.note_parser.VARIANT_MARKERS`（①..⑳，U+2460–U+2473），勿另造。
- `today` 一律由调用方传入引擎（纯函数可测）；路由用 `datetime.date.today().isoformat()`。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `csm_core/vault/folder_profile.py` | 邻居推断：扫一个文件夹的笔记 → FolderProfile | 新建 |
| `csm_core/vault/writer.py` | 写入引擎：plan(纯算)/commit(落盘+登记)/undo(撤销) | 新建 |
| `tests/core/vault/__init__.py` | 测试包标记 | 新建（若无） |
| `tests/core/vault/test_folder_profile.py` | folder_profile 单测（合成 vault） | 新建 |
| `tests/core/vault/test_writer.py` | writer 单测（合成 vault） | 新建 |
| `tests/core/vault/test_writer_real_vault.py` | 真实库只读回归（门禁 skip） | 新建 |
| `sidecar/csm_sidecar/services/vault_writer_service.py` | 薄服务：cfg/路径校验/缓存失效/委托引擎 | 新建 |
| `sidecar/csm_sidecar/routes/vault_writer.py` | GET writable-folders / POST plan·commit·undo | 新建 |
| `sidecar/csm_sidecar/main.py` | 注册新路由 | 改 |
| `sidecar/tests/test_vault_writer_routes.py` | 路由集成测（tmp vault via cfg） | 新建 |
| `frontend/src/stores/materials.ts` | 加 intake 状态/动作 + receipt | 改 |
| `frontend/src/components/materials/IntakeForm.vue` | 录入表单组件 | 新建 |
| `frontend/src/views/MaterialsView.vue` | 假 tab → 真 tab（品牌型号｜录入） | 改 |
| `frontend/src/stores/__tests__/materials.intake.spec.ts` | store intake 单测 | 新建 |
| `frontend/src/components/materials/__tests__/IntakeForm.spec.ts` | 组件单测 | 新建 |

---

## Unit A — csm_core 引擎（folder_profile + writer）

### Task A1: FolderProfile 邻居推断

**Files:**
- Create: `csm_core/vault/folder_profile.py`
- Create: `tests/core/vault/__init__.py`（空文件）、`tests/core/vault/test_folder_profile.py`

- [ ] **Step 1: 写失败测试**

`tests/core/vault/test_folder_profile.py`：
```python
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault import folder_profile as fp


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _variants_vault(root: Path) -> None:
    _write(root, "科普模块/吸尘器/挑选攻略/吸尘器-吸力选购.md",
           "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n\n② 看真空度\n")
    _write(root, "科普模块/吸尘器/挑选攻略/吸尘器-续航选购.md",
           "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 续航\n---\n\n① 看续航\n\n② 看电池\n")


def _spec_vault(root: Path) -> None:
    _write(root, "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md",
           "---\n产品: 吸尘器\n素材类型: 产品参数\n品牌: CEWEY\n型号: CEWEYDS18\n---\n\n"
           "## 性能参数\n\n| 参数 | 数值 |\n|------|------|\n| 吸力 | 220 |\n")


def test_profile_variants_folder(tmp_path):
    _variants_vault(tmp_path)
    idx = scan_vault(tmp_path)
    prof = fp.profile_folder(idx, "科普模块/吸尘器/挑选攻略")
    assert prof.body_shape == "variants"
    assert prof.sample_count == 2
    assert prof.defaults.get("产品") == "吸尘器"
    assert prof.defaults.get("素材类型") == "科普选购"
    assert "核心关键词" in prof.frontmatter_keys
    assert prof.material_types == ["科普选购"]


def test_profile_spec_table_folder(tmp_path):
    _spec_vault(tmp_path)
    idx = scan_vault(tmp_path)
    prof = fp.profile_folder(idx, "产品模块/吸尘器/产品参数")
    assert prof.body_shape == "spec_table"
    assert "品牌" in prof.frontmatter_keys and "型号" in prof.frontmatter_keys


def test_list_writable_folders(tmp_path):
    _variants_vault(tmp_path)
    _spec_vault(tmp_path)
    idx = scan_vault(tmp_path)
    rels = {p.rel_folder for p in fp.list_writable_folders(idx)}
    assert "科普模块/吸尘器/挑选攻略" in rels
    assert "产品模块/吸尘器/产品参数" in rels


def test_empty_folder_profile_is_unknown(tmp_path):
    idx = scan_vault(tmp_path)
    prof = fp.profile_folder(idx, "不存在/文件夹")
    assert prof.sample_count == 0
    assert prof.body_shape == "unknown"
    assert prof.frontmatter_keys == []
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/vault/test_folder_profile.py -q
```
预期：FAIL（`ModuleNotFoundError: csm_core.vault.folder_profile`）。

- [ ] **Step 3: 实现 `folder_profile.py`**

```python
"""Infer what shape to write into a vault folder from its existing notes.

The vault is the source of truth (CLAUDE.md has drifted), so the intake form
mirrors a target folder's existing notes rather than a hardcoded taxonomy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .note_parser import ParsedNote, VARIANT_MARKERS
from .scanner import VaultIndex

_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_LEAD_KEYS = ("产品", "素材类型", "核心关键词")


@dataclass(frozen=True)
class FolderProfile:
    rel_folder: str
    frontmatter_keys: list[str] = field(default_factory=list)
    defaults: dict[str, str] = field(default_factory=dict)
    body_shape: str = "unknown"          # "variants" | "spec_table" | "unknown"
    sample_count: int = 0
    material_types: list[str] = field(default_factory=list)


def _rel_folder_of(note: ParsedNote, root) -> str | None:
    try:
        parts = note.path.relative_to(root).parts[:-1]
    except ValueError:
        return None
    return "/".join(parts)


def _is_variants(note: ParsedNote) -> bool:
    if len(note.variants) >= 2:
        return True
    return any(m in note.raw_body for m in VARIANT_MARKERS)


def _is_spec_table(note: ParsedNote) -> bool:
    return len(_TABLE_RE.findall(note.raw_body)) >= 2


def profile_folder(index: VaultIndex, rel_folder: str) -> FolderProfile:
    notes = [n for n in index.notes if _rel_folder_of(n, index.root) == rel_folder]
    if not notes:
        return FolderProfile(rel_folder=rel_folder)

    # frontmatter keys: union preserving order, lead keys first.
    seen: dict[str, None] = {}
    for n in notes:
        for k in (n.frontmatter or {}):
            seen.setdefault(k, None)
    keys = [k for k in _LEAD_KEYS if k in seen] + [k for k in seen if k not in _LEAD_KEYS]

    # defaults: scalar key whose value is identical across ≥ half the notes.
    defaults: dict[str, str] = {}
    for k in keys:
        vals = [str(n.frontmatter[k]) for n in notes
                if k in n.frontmatter and not isinstance(n.frontmatter[k], list)]
        if vals and vals.count(vals[0]) * 2 >= len(notes) and len(set(vals)) == 1:
            defaults[k] = vals[0]

    # material types present (for picker label).
    mats: dict[str, None] = {}
    for n in notes:
        mt = n.frontmatter.get("素材类型")
        if isinstance(mt, str) and mt:
            mats.setdefault(mt, None)

    # body shape: majority vote.
    v = sum(_is_variants(n) for n in notes)
    s = sum(_is_spec_table(n) for n in notes)
    shape = "variants" if v >= s and v > 0 else "spec_table" if s > 0 else "unknown"

    return FolderProfile(
        rel_folder=rel_folder,
        frontmatter_keys=keys,
        defaults=defaults,
        body_shape=shape,
        sample_count=len(notes),
        material_types=list(mats.keys()),
    )


def list_writable_folders(index: VaultIndex) -> list[FolderProfile]:
    """Every folder that directly holds ≥1 parsed note, each profiled."""
    rels: dict[str, None] = {}
    for n in index.notes:
        rel = _rel_folder_of(n, index.root)
        if rel:
            rels.setdefault(rel, None)
    return [profile_folder(index, r) for r in sorted(rels)]
```

> 注：`note_parser.py` 已导出 `VARIANT_MARKERS`（见文件第 13 行）。`_is_spec_table` 用「≥2 个表格行」判定（表头 + 至少一行数据），避免单行误判。

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/vault/test_folder_profile.py -q
```
预期：PASS（4 passed）。

- [ ] **Step 5: commit**

```bash
git add csm_core/vault/folder_profile.py tests/core/vault/__init__.py tests/core/vault/test_folder_profile.py
git commit -m "feat(3a): folder_profile 邻居推断（body_shape/frontmatter_keys/defaults）"
```

---

### Task A2: 写入引擎 writer.py（plan/commit/undo）

**Files:**
- Create: `csm_core/vault/writer.py`
- Create: `tests/core/vault/test_writer.py`

- [ ] **Step 1: 写失败测试**

`tests/core/vault/test_writer.py`：
```python
import hashlib
from pathlib import Path
import pytest
from csm_core.vault import writer


def _index_vault(root: Path) -> None:
    (root / "科普模块/吸尘器/挑选攻略").mkdir(parents=True, exist_ok=True)
    (root / "科普模块/吸尘器/吸尘器科普内容索引.md").write_text(
        "---\n产品: 吸尘器\n---\n\n# 科普索引\n\n## 挑选攻略\n\n旧内容\n", encoding="utf-8")


def _plan(root: Path):
    return writer.plan_note(
        root,
        rel_folder="科普模块/吸尘器/挑选攻略",
        filename="吸尘器-噪音选购.md",
        frontmatter={"产品": "吸尘器", "素材类型": "科普选购", "核心关键词": ["噪音"]},
        body_shape="variants",
        variants=["看噪音分贝", "看降噪结构"],
        today="2026-06-26",
    )


def test_plan_renders_full_note(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    assert p.rel_path == "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md"
    assert p.conflict is False
    assert "素材类型: 科普选购" in p.full_text
    assert "① 看噪音分贝" in p.full_text and "② 看降噪结构" in p.full_text
    # 双链尾按最近祖先索引（吸尘器科普内容索引），不照 CLAUDE.md 死表
    assert "**返回上层**: [[吸尘器科普内容索引|吸尘器科普内容索引]]" in p.full_text
    assert "**返回主页**: [[关联数据库]]" in p.full_text
    assert p.index_rel == "科普模块/吸尘器/吸尘器科普内容索引.md"
    assert p.index_line == "- [[吸尘器-噪音选购]] · 科普选购 · 2026-06-26"


def test_plan_spec_table_body(tmp_path):
    (tmp_path / "产品模块/吸尘器/产品参数").mkdir(parents=True, exist_ok=True)
    p = writer.plan_note(
        tmp_path, rel_folder="产品模块/吸尘器/产品参数",
        filename="CEWEYDS19-产品参数.md",
        frontmatter={"产品": "吸尘器", "素材类型": "产品参数", "型号": "CEWEYDS19"},
        body_shape="spec_table",
        spec_rows=[{"group": "性能参数", "key": "吸力", "value": "230"},
                   {"group": "性能参数", "key": "真空度", "value": "38000"}],
        today="2026-06-26")
    assert "## 性能参数" in p.full_text
    assert "| 吸力 | 230 |" in p.full_text and "| 真空度 | 38000 |" in p.full_text


def test_plan_no_index_warns(tmp_path):
    (tmp_path / "孤立文件夹").mkdir(parents=True, exist_ok=True)
    p = writer.plan_note(
        tmp_path, rel_folder="孤立文件夹", filename="吸尘器-x.md",
        frontmatter={"产品": "吸尘器"}, body_shape="variants",
        variants=["a"], today="2026-06-26")
    assert p.index_rel is None and p.index_line is None
    assert any("无祖先索引" in w for w in p.warnings)
    assert "**返回主页**: [[关联数据库]]" in p.full_text


def test_plan_conflict_when_exists(tmp_path):
    _index_vault(tmp_path)
    (tmp_path / "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md").write_text("x", encoding="utf-8")
    assert _plan(tmp_path).conflict is True


def test_commit_writes_file_and_registers(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    receipt = writer.commit_note(p, tmp_path)
    target = tmp_path / p.rel_path
    assert target.read_text(encoding="utf-8") == p.full_text
    assert receipt.content_sha == hashlib.sha256(p.full_text.encode("utf-8")).hexdigest()
    idx_text = (tmp_path / p.index_rel).read_text(encoding="utf-8")
    assert "## App 新增（待人工归入）" in idx_text
    assert "- [[吸尘器-噪音选购]] · 科普选购 · 2026-06-26" in idx_text
    assert "旧内容" in idx_text  # 人工内容未被破坏


def test_commit_idempotent_block(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    writer.commit_note(p, tmp_path)
    (tmp_path / p.rel_path).unlink()       # 删文件但留索引行
    writer.commit_note(p, tmp_path)        # 再写一次
    idx_text = (tmp_path / p.index_rel).read_text(encoding="utf-8")
    assert idx_text.count("- [[吸尘器-噪音选购]] ·") == 1   # 不重复登记


def test_commit_refuses_overwrite(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    writer.commit_note(p, tmp_path)
    with pytest.raises(FileExistsError):
        writer.commit_note(p, tmp_path)


def test_undo_deletes_when_unchanged(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    receipt = writer.commit_note(p, tmp_path)
    warnings = writer.undo_write(receipt, tmp_path)
    assert not (tmp_path / p.rel_path).exists()
    idx_text = (tmp_path / p.index_rel).read_text(encoding="utf-8")
    assert "吸尘器-噪音选购" not in idx_text
    assert warnings == []


def test_undo_skips_when_modified(tmp_path):
    _index_vault(tmp_path)
    p = _plan(tmp_path)
    receipt = writer.commit_note(p, tmp_path)
    (tmp_path / p.rel_path).write_text("被人工改了", encoding="utf-8")
    warnings = writer.undo_write(receipt, tmp_path)
    assert (tmp_path / p.rel_path).exists()             # 没删
    assert any("已被改动" in w for w in warnings)
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/vault/test_writer.py -q
```
预期：FAIL（`ModuleNotFoundError: csm_core.vault.writer`）。

- [ ] **Step 3: 实现 `writer.py`**

```python
"""Deterministic vault note writer — render structured material → 规范 .md.

Writes obey the *real* vault (CLAUDE.md has drifted): backlink tail targets the
nearest-ancestor index discovered by scanning (not §5.2's stale table), and the
note is registered only in a writer-owned "## App 新增" block — never the
hand-curated index tables. plan_note is pure (no disk write); commit_note writes
and refuses to overwrite; undo_write is best-effort single-level.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .note_parser import VARIANT_MARKERS

_APP_BLOCK = "## App 新增（待人工归入）"


@dataclass(frozen=True)
class NotePlan:
    rel_folder: str
    filename: str
    rel_path: str
    frontmatter: dict[str, Any]
    body: str
    backlink_tail: str
    full_text: str
    index_rel: str | None
    index_line: str | None
    conflict: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WriteReceipt:
    created_rel: str
    content_sha: str
    index_rel: str | None = None
    index_line: str | None = None


def _render_frontmatter(fm: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines.extend(f"  - {item}" for item in v)
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _render_body(body_shape, variants, spec_rows) -> str:
    if body_shape == "variants":
        items = variants or []
        return "\n\n".join(
            f"{VARIANT_MARKERS[i]} {str(t).strip()}" for i, t in enumerate(items))
    if body_shape == "spec_table":
        groups: dict[str, list[tuple[str, str]]] = {}
        for r in spec_rows or []:
            groups.setdefault(r.get("group") or "参数", []).append(
                (str(r["key"]), str(r["value"])))
        chunks = []
        for g, rows in groups.items():
            t = [f"## {g}", "", "| 参数 | 数值 |", "|------|------|"]
            t.extend(f"| {k} | {v} |" for k, v in rows)
            chunks.append("\n".join(t))
        return "\n\n".join(chunks)
    return ""


def _find_index(vault_root: Path, rel_folder: str) -> Path | None:
    cur = vault_root / rel_folder
    while True:
        matches = sorted(cur.glob("*索引*.md"))
        if matches:
            return matches[0]
        if cur == vault_root:
            return None
        cur = cur.parent


def _backlink_tail(index_stem: str | None) -> str:
    home = "**返回主页**: [[关联数据库]]"
    if index_stem:
        return f"---\n**返回上层**: [[{index_stem}|{index_stem}]] | {home}"
    return f"---\n{home}"


def plan_note(
    vault_root: Path, *,
    rel_folder: str, filename: str,
    frontmatter: dict[str, Any], body_shape: str, today: str,
    variants: list[str] | None = None,
    spec_rows: list[dict[str, Any]] | None = None,
) -> NotePlan:
    vault_root = Path(vault_root)
    warnings: list[str] = []
    rel_path = f"{rel_folder}/{filename}"
    body = _render_body(body_shape, variants, spec_rows)

    idx = _find_index(vault_root, rel_folder)
    if idx is None:
        warnings.append("无祖先索引，跳过登记")
        index_rel = index_line = index_stem = None
    else:
        index_rel = idx.relative_to(vault_root).as_posix()
        index_stem = idx.stem
        stem = filename[:-3] if filename.endswith(".md") else filename
        index_line = f"- [[{stem}]] · {frontmatter.get('素材类型', '')} · {today}"

    tail = _backlink_tail(index_stem)
    full_text = f"{_render_frontmatter(frontmatter)}\n\n{body}\n\n{tail}\n"
    conflict = (vault_root / rel_path).exists()
    return NotePlan(
        rel_folder=rel_folder, filename=filename, rel_path=rel_path,
        frontmatter=frontmatter, body=body, backlink_tail=tail, full_text=full_text,
        index_rel=index_rel, index_line=index_line, conflict=conflict, warnings=warnings)


def _append_index_line(idx_path: Path, line: str) -> None:
    raw = idx_path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    if line in lines:
        return  # idempotent
    try:
        h = next(i for i, l in enumerate(lines) if l.strip() == _APP_BLOCK)
    except StopIteration:
        idx_path.write_text(raw.rstrip() + f"\n\n{_APP_BLOCK}\n{line}\n", encoding="utf-8")
        return
    last = h
    for k in range(h + 1, len(lines)):
        if lines[k].startswith("- "):
            last = k
        elif lines[k].strip() == "":
            continue
        else:
            break
    lines.insert(last + 1, line)
    idx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def commit_note(plan: NotePlan, vault_root: Path) -> WriteReceipt:
    vault_root = Path(vault_root)
    target = vault_root / plan.rel_path
    if target.exists():
        raise FileExistsError(plan.rel_path)
    target.write_text(plan.full_text, encoding="utf-8")
    sha = hashlib.sha256(plan.full_text.encode("utf-8")).hexdigest()
    if plan.index_rel and plan.index_line:
        _append_index_line(vault_root / plan.index_rel, plan.index_line)
    return WriteReceipt(
        created_rel=plan.rel_path, content_sha=sha,
        index_rel=plan.index_rel, index_line=plan.index_line)


def undo_write(receipt: WriteReceipt, vault_root: Path) -> list[str]:
    vault_root = Path(vault_root)
    warnings: list[str] = []
    target = vault_root / receipt.created_rel
    if target.exists():
        cur = hashlib.sha256(target.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if cur == receipt.content_sha:
            target.unlink()
        else:
            warnings.append(f"{receipt.created_rel} 已被改动，未删除")
    else:
        warnings.append(f"{receipt.created_rel} 不存在")
    if receipt.index_rel and receipt.index_line:
        idx = vault_root / receipt.index_rel
        if idx.exists():
            lines = idx.read_text(encoding="utf-8-sig").splitlines()
            if receipt.index_line in lines:
                lines.remove(receipt.index_line)
                idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
            else:
                warnings.append("索引登记行未找到，跳过")
    return warnings
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/vault/test_writer.py -q
```
预期：PASS（9 passed）。

- [ ] **Step 5: commit**

```bash
git add csm_core/vault/writer.py tests/core/vault/test_writer.py
git commit -m "feat(3a): vault writer 引擎 plan/commit/undo（不覆盖+幂等登记+安全撤销）"
```

---

### Task A3: 真实库只读回归

**Files:**
- Create: `tests/core/vault/test_writer_real_vault.py`

- [ ] **Step 1: 写测试（门禁 skip，只读）**

```python
"""真实库只读回归：仅验证 body_shape 探测，绝不 commit/写盘。"""
from pathlib import Path
import pytest
from csm_core.vault.scanner import scan_vault
from csm_core.vault import folder_profile as fp

_VAULT = Path(r"D:\家电组共享\DATA")

pytestmark = pytest.mark.skipif(
    not _VAULT.exists(), reason="真实 vault 不可用（CI/他机）")


def test_real_vault_body_shape_detection():
    idx = scan_vault(_VAULT)
    profiles = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    挑选 = next((p for r, p in profiles.items() if r.endswith("挑选攻略")), None)
    参数 = next((p for r, p in profiles.items() if r.endswith("产品参数")), None)
    assert 挑选 is not None and 挑选.body_shape == "variants"
    assert 参数 is not None and 参数.body_shape == "spec_table"
```

- [ ] **Step 2: 跑测试确认通过（开发机）**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/vault/test_writer_real_vault.py -q
```
预期：PASS（1 passed）；他机无 vault 则 skipped。

- [ ] **Step 3: commit**

```bash
git add tests/core/vault/test_writer_real_vault.py
git commit -m "test(3a): 真实库只读回归（body_shape 探测，门禁 skip）"
```

---

## Unit B — sidecar 服务 + 路由

### Task B1: vault_writer_service（薄服务）

**Files:**
- Create: `sidecar/csm_sidecar/services/vault_writer_service.py`

- [ ] **Step 1: 实现服务**（先实现，路由测试在 B2 一并验证——服务无独立 IO 逻辑，由路由测覆盖）

```python
"""Thin service for the vault writer routes.

Resolves cfg.vault_root, reuses vault_service's cached index for profiling,
validates folder/filename stay inside the root, and delegates to the pure
csm_core.vault.writer engine. Invalidates the vault cache after writes so the
new note shows up in subsequent scans.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from csm_core.vault import folder_profile, writer
from . import config_service, vault_service


def _root() -> Path:
    cfg = config_service.load()
    if not cfg.vault_root:
        raise ValueError("vault_root 未配置 — 请先在「设置」里指定素材库路径")
    root = Path(cfg.vault_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"素材库路径不存在: {root}")
    return root


def _validate(root: Path, rel_folder: str, filename: str) -> None:
    if (not filename or " " in filename or "/" in filename
            or "\\" in filename or not filename.endswith(".md")):
        raise ValueError("文件名非法：不能含空格/路径分隔符，须以 .md 结尾")
    folder = (root / rel_folder).resolve()
    rres = root.resolve()
    if folder != rres and rres not in folder.parents:
        raise ValueError("目标文件夹越界")
    if not folder.is_dir():
        raise ValueError("目标文件夹不存在")


def list_folders() -> list[dict[str, Any]]:
    idx = vault_service.scan(_root())   # fresh scan for the picker
    return [asdict(p) for p in folder_profile.list_writable_folders(idx)]


def plan(*, rel_folder, filename, frontmatter, body_shape, variants, spec_rows, today) -> dict:
    root = _root()
    _validate(root, rel_folder, filename)
    p = writer.plan_note(
        root, rel_folder=rel_folder, filename=filename, frontmatter=frontmatter,
        body_shape=body_shape, today=today, variants=variants, spec_rows=spec_rows)
    return asdict(p)


def commit(*, rel_folder, filename, frontmatter, body_shape, variants, spec_rows, today) -> dict:
    root = _root()
    _validate(root, rel_folder, filename)
    p = writer.plan_note(
        root, rel_folder=rel_folder, filename=filename, frontmatter=frontmatter,
        body_shape=body_shape, today=today, variants=variants, spec_rows=spec_rows)
    if p.conflict:
        raise FileExistsError(p.rel_path)
    receipt = writer.commit_note(p, root)
    vault_service.invalidate()
    return asdict(receipt)


def undo(receipt: dict) -> dict:
    root = _root()
    warnings = writer.undo_write(writer.WriteReceipt(**receipt), root)
    vault_service.invalidate()
    return {"undone": True, "warnings": warnings}
```

- [ ] **Step 2: commit**

```bash
git add sidecar/csm_sidecar/services/vault_writer_service.py
git commit -m "feat(3a): vault_writer_service 薄接线（cfg/校验/缓存失效/委托引擎）"
```

---

### Task B2: 路由 + 注册 + 集成测试

**Files:**
- Create: `sidecar/csm_sidecar/routes/vault_writer.py`
- Modify: `sidecar/csm_sidecar/main.py`（import + include_router）
- Create: `sidecar/tests/test_vault_writer_routes.py`

- [ ] **Step 1: 写失败测试**

`sidecar/tests/test_vault_writer_routes.py`：
```python
from pathlib import Path
from csm_sidecar.services import config_service, vault_service


def _seed_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "科普模块/吸尘器/挑选攻略").mkdir(parents=True, exist_ok=True)
    (root / "科普模块/吸尘器/挑选攻略/吸尘器-吸力选购.md").write_text(
        "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n\n② 看真空\n",
        encoding="utf-8")
    (root / "科普模块/吸尘器/吸尘器科普内容索引.md").write_text(
        "---\n产品: 吸尘器\n---\n\n# 索引\n\n旧内容\n", encoding="utf-8")
    return root


def _use_vault(root: Path) -> None:
    config_service.patch({"vault_root": str(root)})
    vault_service.invalidate()


def test_writable_folders(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    r = client.get("/api/vault/writable-folders")
    assert r.status_code == 200
    rels = [f["rel_folder"] for f in r.json()["folders"]]
    assert "科普模块/吸尘器/挑选攻略" in rels


def test_plan_then_commit_then_undo(client, tmp_path):
    root = _seed_vault(tmp_path)
    _use_vault(root)
    body = {
        "rel_folder": "科普模块/吸尘器/挑选攻略",
        "filename": "吸尘器-噪音选购.md",
        "frontmatter": {"产品": "吸尘器", "素材类型": "科普选购", "核心关键词": ["噪音"]},
        "body_shape": "variants",
        "variants": ["看分贝", "看降噪"],
    }
    plan = client.post("/api/vault/plan", json=body).json()
    assert plan["conflict"] is False
    assert "① 看分贝" in plan["full_text"]

    commit = client.post("/api/vault/commit", json=body)
    assert commit.status_code == 200
    receipt = commit.json()
    assert (root / "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md").exists()

    undo = client.post("/api/vault/undo", json=receipt)
    assert undo.status_code == 200
    assert not (root / "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md").exists()


def test_commit_conflict_409(client, tmp_path):
    root = _seed_vault(tmp_path)
    _use_vault(root)
    body = {
        "rel_folder": "科普模块/吸尘器/挑选攻略", "filename": "吸尘器-吸力选购.md",
        "frontmatter": {"产品": "吸尘器"}, "body_shape": "variants", "variants": ["x"],
    }
    assert client.post("/api/vault/commit", json=body).status_code == 409


def test_bad_filename_400(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    body = {
        "rel_folder": "科普模块/吸尘器/挑选攻略", "filename": "有 空格.txt",
        "frontmatter": {}, "body_shape": "variants", "variants": ["x"],
    }
    assert client.post("/api/vault/commit", json=body).status_code == 400


def test_path_escape_400(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    body = {
        "rel_folder": "../..", "filename": "evil.md",
        "frontmatter": {}, "body_shape": "variants", "variants": ["x"],
    }
    assert client.post("/api/vault/plan", json=body).status_code == 400


def test_no_vault_root_400(client):
    config_service.patch({"vault_root": None})
    assert client.get("/api/vault/writable-folders").status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_vault_writer_routes.py -q
```
预期：FAIL（404，路由不存在）。

- [ ] **Step 3: 实现路由 `routes/vault_writer.py`**

```python
"""Vault 写入器路由（同步：本地文件操作快，无需 SSE）。"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import vault_writer_service

router = APIRouter(tags=["vault_writer"], dependencies=[RequireToken])


class SpecRow(BaseModel):
    group: str = ""
    key: str
    value: str


class NoteBody(BaseModel):
    rel_folder: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body_shape: str
    variants: list[str] | None = None
    spec_rows: list[SpecRow] | None = None


class UndoBody(BaseModel):
    created_rel: str
    content_sha: str
    index_rel: str | None = None
    index_line: str | None = None


def _spec_rows(body: NoteBody):
    return [r.model_dump() for r in body.spec_rows] if body.spec_rows else None


@router.get("/api/vault/writable-folders")
def writable_folders() -> dict[str, Any]:
    try:
        return {"folders": vault_writer_service.list_folders()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/vault/plan")
def plan(body: NoteBody) -> dict[str, Any]:
    try:
        return vault_writer_service.plan(
            rel_folder=body.rel_folder, filename=body.filename,
            frontmatter=body.frontmatter, body_shape=body.body_shape,
            variants=body.variants, spec_rows=_spec_rows(body),
            today=date.today().isoformat())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/vault/commit")
def commit(body: NoteBody) -> dict[str, Any]:
    try:
        return vault_writer_service.commit(
            rel_folder=body.rel_folder, filename=body.filename,
            frontmatter=body.frontmatter, body_shape=body.body_shape,
            variants=body.variants, spec_rows=_spec_rows(body),
            today=date.today().isoformat())
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=f"同名笔记已存在: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/vault/undo")
def undo(body: UndoBody) -> dict[str, Any]:
    try:
        return vault_writer_service.undo(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 4: 注册路由 `main.py`**

在 import 区（紧接 `from .routes import vault as vault_routes` 之后）加：
```python
from .routes import vault_writer as vault_writer_routes
```
在 include 区（紧接 `app.include_router(vault_routes.router)` 之后）加：
```python
app.include_router(vault_writer_routes.router)
```

- [ ] **Step 5: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest sidecar/tests/test_vault_writer_routes.py -q
```
预期：PASS（6 passed）。

- [ ] **Step 6: commit**

```bash
git add sidecar/csm_sidecar/routes/vault_writer.py sidecar/csm_sidecar/main.py sidecar/tests/test_vault_writer_routes.py
git commit -m "feat(3a): vault writer 路由 writable-folders/plan/commit/undo + 注册"
```

---

## Unit C — 前端（store + IntakeForm + MaterialsView tab）

### Task C1: materials store 加 intake 动作

**Files:**
- Modify: `frontend/src/stores/materials.ts`
- Create: `frontend/src/stores/__tests__/materials.intake.spec.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/stores/__tests__/materials.intake.spec.ts`：
```typescript
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));

import { useMaterials } from "@/stores/materials";

describe("materials store — 录入", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
  });

  it("loadFolders 填充 writableFolders", async () => {
    getMock.mockResolvedValueOnce({ data: { folders: [
      { rel_folder: "科普模块/吸尘器/挑选攻略", frontmatter_keys: ["产品"], defaults: {},
        body_shape: "variants", sample_count: 2, material_types: ["科普选购"] },
    ] } });
    const m = useMaterials();
    await m.loadFolders();
    expect(m.writableFolders.length).toBe(1);
    expect(m.writableFolders[0].body_shape).toBe("variants");
  });

  it("planNote 存 currentPlan", async () => {
    postMock.mockResolvedValueOnce({ data: { full_text: "FT", conflict: false, warnings: [] } });
    const m = useMaterials();
    await m.planNote({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(m.currentPlan?.full_text).toBe("FT");
    expect(postMock).toHaveBeenCalledWith("/api/vault/plan", expect.objectContaining({ filename: "x.md" }));
  });

  it("commitNote 存 lastReceipt + 返回 true", async () => {
    postMock.mockResolvedValueOnce({ data: { created_rel: "a/x.md", content_sha: "sha" } });
    const m = useMaterials();
    const ok = await m.commitNote({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(ok).toBe(true);
    expect(m.lastReceipt?.created_rel).toBe("a/x.md");
  });

  it("commitNote 409 冲突 → 返回 false + 设 intakeError", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "同名笔记已存在" } } });
    const m = useMaterials();
    const ok = await m.commitNote({ rel_folder: "a", filename: "x.md", frontmatter: {}, body_shape: "variants", variants: ["y"] });
    expect(ok).toBe(false);
    expect(m.intakeError).toContain("同名");
  });

  it("undoLast 调 /undo 并清 lastReceipt", async () => {
    postMock.mockResolvedValueOnce({ data: { undone: true, warnings: [] } });
    const m = useMaterials();
    m.lastReceipt = { created_rel: "a/x.md", content_sha: "sha", index_rel: null, index_line: null };
    await m.undoLast();
    expect(postMock).toHaveBeenCalledWith("/api/vault/undo", expect.objectContaining({ created_rel: "a/x.md" }));
    expect(m.lastReceipt).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/stores/__tests__/materials.intake.spec.ts
```
预期：FAIL（`m.loadFolders is not a function`）。

- [ ] **Step 3: 扩展 `materials.ts`**

在 `interface ModelDetail {…}` 之后加类型：
```typescript
export interface FolderProfile {
  rel_folder: string;
  frontmatter_keys: string[];
  defaults: Record<string, string>;
  body_shape: "variants" | "spec_table" | "unknown";
  sample_count: number;
  material_types: string[];
}
export interface NotePlan {
  rel_folder: string; filename: string; rel_path: string;
  frontmatter: Record<string, unknown>; body: string; backlink_tail: string;
  full_text: string; index_rel: string | null; index_line: string | null;
  conflict: boolean; warnings: string[];
}
export interface WriteReceipt {
  created_rel: string; content_sha: string;
  index_rel: string | null; index_line: string | null;
}
export interface NotePayload {
  rel_folder: string; filename: string;
  frontmatter: Record<string, unknown>; body_shape: string;
  variants?: string[]; spec_rows?: { group: string; key: string; value: string }[];
}
```

在 `useMaterials` 的 setup 里，现有 `detailLoading` ref 之后加状态：
```typescript
  const writableFolders = ref<FolderProfile[]>([]);
  const foldersLoading = ref(false);
  const currentPlan = ref<NotePlan | null>(null);
  const lastReceipt = ref<WriteReceipt | null>(null);
  const intakeError = ref<string | null>(null);
```

在 `select` 动作之后、`return` 之前加动作：
```typescript
  async function loadFolders(): Promise<void> {
    foldersLoading.value = true; intakeError.value = null;
    try {
      const r = await useSidecar().client.get("/api/vault/writable-folders");
      writableFolders.value = r.data.folders ?? [];
    } catch (e: any) {
      intakeError.value = errMsg(e); writableFolders.value = [];
    } finally { foldersLoading.value = false; }
  }

  async function planNote(payload: NotePayload): Promise<void> {
    intakeError.value = null;
    try {
      const r = await useSidecar().client.post("/api/vault/plan", payload);
      currentPlan.value = r.data;
    } catch (e: any) {
      intakeError.value = errMsg(e); currentPlan.value = null;
    }
  }

  async function commitNote(payload: NotePayload): Promise<boolean> {
    intakeError.value = null;
    try {
      const r = await useSidecar().client.post("/api/vault/commit", payload);
      lastReceipt.value = r.data;
      return true;
    } catch (e: any) {
      intakeError.value = errMsg(e);
      return false;
    }
  }

  async function undoLast(): Promise<void> {
    if (!lastReceipt.value) return;
    try {
      await useSidecar().client.post("/api/vault/undo", lastReceipt.value);
    } catch (e: any) {
      intakeError.value = errMsg(e);
    } finally {
      lastReceipt.value = null;
    }
  }
```

把 `return {…}` 改成（加新成员）：
```typescript
  return {
    models, loading, error, selectedModel, detail, detailLoading, list, select,
    writableFolders, foldersLoading, currentPlan, lastReceipt, intakeError,
    loadFolders, planNote, commitNote, undoLast,
  };
```

- [ ] **Step 4: 跑测试确认通过 + 类型检查**

```bash
cd frontend && npx vitest run src/stores/__tests__/materials.intake.spec.ts && npx vue-tsc -b
```
预期：vitest 5 passed；vue-tsc exit 0。
> ⚠️ `vue-tsc -b` 可能 emit `vite.config.js`/`.d.ts` 触发 vite restart——跑完 `git checkout -- vite.config.js *.d.ts` 还原（见 [reference_csm_dev_worktree_setup]）。

- [ ] **Step 5: commit**

```bash
git add frontend/src/stores/materials.ts frontend/src/stores/__tests__/materials.intake.spec.ts
git commit -m "feat(3a): materials store 加 intake（folders/plan/commit/undo + receipt）"
```

---

### Task C2: IntakeForm 组件 + MaterialsView 真 tab

**Files:**
- Create: `frontend/src/components/materials/IntakeForm.vue`
- Modify: `frontend/src/views/MaterialsView.vue`
- Create: `frontend/src/components/materials/__tests__/IntakeForm.spec.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/components/materials/__tests__/IntakeForm.spec.ts`：
```typescript
import { setActivePinia, createPinia } from "pinia";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ client: { get: getMock, post: postMock } }),
}));
vi.mock("@/composables/useNotifications", () => ({ useNotifications: () => ({ push: vi.fn() }) }));

import IntakeForm from "@/components/materials/IntakeForm.vue";

const FOLDERS = { data: { folders: [
  { rel_folder: "科普模块/吸尘器/挑选攻略", frontmatter_keys: ["产品", "素材类型", "核心关键词"],
    defaults: { 产品: "吸尘器", 素材类型: "科普选购" }, body_shape: "variants",
    sample_count: 2, material_types: ["科普选购"] },
] } };

describe("IntakeForm", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    getMock.mockReset(); postMock.mockReset();
    getMock.mockResolvedValue(FOLDERS);
  });

  it("挂载即加载文件夹列表", async () => {
    const w = mount(IntakeForm);
    await new Promise((r) => setTimeout(r));
    expect(getMock).toHaveBeenCalledWith("/api/vault/writable-folders");
    expect(w.find('[data-folder="科普模块/吸尘器/挑选攻略"]').exists()).toBe(true);
  });

  it("选文件夹后按 defaults 预填 + body 形状为变体", async () => {
    const w = mount(IntakeForm);
    await new Promise((r) => setTimeout(r));
    await w.find('[data-folder="科普模块/吸尘器/挑选攻略"]').trigger("click");
    await w.vm.$nextTick();
    expect(w.find('[data-variant-row]').exists()).toBe(true);
    const prod = w.find('[data-fm="产品"]').element as HTMLInputElement;
    expect(prod.value).toBe("吸尘器");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/materials/__tests__/IntakeForm.spec.ts
```
预期：FAIL（找不到组件文件）。

- [ ] **Step 3: 实现 `IntakeForm.vue`**

```vue
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import Spinner from "@/components/ui/Spinner.vue";
import Pill from "@/components/ui/Pill.vue";
import { useMaterials, type FolderProfile, type NotePayload } from "@/stores/materials";
import { useNotifications } from "@/composables/useNotifications";

const m = useMaterials();
const notify = useNotifications();

const selected = ref<FolderProfile | null>(null);
const filename = ref("");
const fm = reactive<Record<string, string>>({});
const variants = ref<string[]>([""]);
const specRows = ref<{ group: string; key: string; value: string }[]>([{ group: "", key: "", value: "" }]);

onMounted(() => m.loadFolders());

function pick(f: FolderProfile): void {
  selected.value = f;
  for (const k of Object.keys(fm)) delete fm[k];
  for (const k of f.frontmatter_keys) fm[k] = f.defaults[k] ?? "";
  filename.value = "";
  variants.value = [""];
  specRows.value = [{ group: "", key: "", value: "" }];
  m.currentPlan = null;
}

const isVariants = computed(() => selected.value?.body_shape !== "spec_table");

function buildPayload(): NotePayload | null {
  const f = selected.value;
  if (!f || !filename.value.trim()) return null;
  const frontmatter: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fm)) {
    if (k === "核心关键词") frontmatter[k] = String(v).split(/[，,\s]+/).filter(Boolean);
    else if (v) frontmatter[k] = v;
  }
  const payload: NotePayload = {
    rel_folder: f.rel_folder, filename: filename.value.trim(),
    frontmatter, body_shape: isVariants.value ? "variants" : "spec_table",
  };
  if (isVariants.value) payload.variants = variants.value.filter((t) => t.trim());
  else payload.spec_rows = specRows.value.filter((r) => r.key.trim());
  return payload;
}

// 防抖 diff 预览
let _t: ReturnType<typeof setTimeout> | undefined;
watch([selected, filename, fm, variants, specRows], () => {
  if (_t) clearTimeout(_t);
  _t = setTimeout(() => {
    const p = buildPayload();
    if (p) m.planNote(p);
  }, 350);
}, { deep: true });

const filenameError = computed(() => {
  const v = filename.value.trim();
  if (!v) return "";
  if (/\s/.test(v) || v.includes("/") || v.includes("\\")) return "不能含空格/路径分隔符";
  if (!v.endsWith(".md")) return "须以 .md 结尾";
  return "";
});

async function submit(): Promise<void> {
  const p = buildPayload();
  if (!p || filenameError.value || m.currentPlan?.conflict) return;
  if (await m.commitNote(p)) {
    notify.push(`已入库：${p.filename}`, { tone: "success" });
    selected.value = null;
  }
}

async function undo(): Promise<void> {
  await m.undoLast();
  notify.push("已撤销上次写入", { tone: "info" });
}

function addVariant(): void { variants.value.push(""); }
function rmVariant(i: number): void { variants.value.splice(i, 1); }
function addSpecRow(): void { specRows.value.push({ group: "", key: "", value: "" }); }
function rmSpecRow(i: number): void { specRows.value.splice(i, 1); }
</script>

<template>
  <div class="flex h-full min-h-0 gap-4">
    <!-- 左：文件夹选择 -->
    <div class="flex w-72 min-w-0 flex-col overflow-y-auto border-r border-ink/10 pr-3">
      <div v-if="m.foldersLoading" class="flex items-center gap-2 p-3 text-sm text-ink/50">
        <Spinner :size="14" /> 加载文件夹…
      </div>
      <div v-else-if="!m.writableFolders.length" class="p-3 text-sm text-ink/50">
        素材库无可写文件夹。请在「设置」确认素材库路径。
      </div>
      <button
        v-for="f in m.writableFolders" :key="f.rel_folder" :data-folder="f.rel_folder"
        class="flex flex-col gap-1 rounded-lg px-2 py-2 text-left transition-colors"
        :style="{ background: selected?.rel_folder === f.rel_folder ? 'var(--card-2, rgba(0,0,0,0.05))' : 'transparent' }"
        @click="pick(f)"
      >
        <span class="text-sm font-medium">{{ f.rel_folder }}</span>
        <div class="flex flex-wrap items-center gap-1 text-[10px] text-ink/50">
          <Pill>{{ f.body_shape === "spec_table" ? "参数表" : "变体" }}</Pill>
          <span>{{ f.sample_count }} 篇</span>
          <span v-if="f.material_types.length">· {{ f.material_types.join("/") }}</span>
        </div>
      </button>
    </div>

    <!-- 中：表单 -->
    <div class="flex w-96 min-w-0 flex-col gap-3 overflow-y-auto">
      <div v-if="!selected" class="grid h-full place-items-center text-sm text-ink/40">
        选择左侧文件夹开始录入
      </div>
      <template v-else>
        <div>
          <label class="mb-1 block text-xs text-ink/50">文件名</label>
          <input v-model="filename" data-filename placeholder="吸尘器-描述-核心词.md"
            class="w-full rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
          <p v-if="filenameError" class="mt-1 text-xs" :style="{ color: 'var(--red)' }">{{ filenameError }}</p>
        </div>
        <div v-for="k in selected.frontmatter_keys" :key="k">
          <label class="mb-1 block text-xs text-ink/50">{{ k }}</label>
          <input v-model="fm[k]" :data-fm="k"
            class="w-full rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
        </div>

        <!-- 变体 body -->
        <div v-if="isVariants" class="flex flex-col gap-2">
          <label class="text-xs text-ink/50">正文变体（①②③）</label>
          <div v-for="(_, i) in variants" :key="i" data-variant-row class="flex gap-1">
            <textarea v-model="variants[i]" rows="2"
              class="flex-1 rounded-lg border border-ink/15 px-2 py-1.5 text-sm" />
            <button class="text-xs text-ink/40" @click="rmVariant(i)">✕</button>
          </div>
          <button class="self-start text-xs text-ink/60" @click="addVariant">+ 加变体</button>
        </div>

        <!-- 参数表 body -->
        <div v-else class="flex flex-col gap-2">
          <label class="text-xs text-ink/50">参数（分组/参数/数值）</label>
          <div v-for="(row, i) in specRows" :key="i" data-spec-row class="flex gap-1">
            <input v-model="row.group" placeholder="分组" class="w-20 rounded border border-ink/15 px-1.5 py-1 text-xs" />
            <input v-model="row.key" placeholder="参数" class="w-24 rounded border border-ink/15 px-1.5 py-1 text-xs" />
            <input v-model="row.value" placeholder="数值" class="flex-1 rounded border border-ink/15 px-1.5 py-1 text-xs" />
            <button class="text-xs text-ink/40" @click="rmSpecRow(i)">✕</button>
          </div>
          <button class="self-start text-xs text-ink/60" @click="addSpecRow">+ 加行</button>
        </div>

        <div class="flex items-center gap-2 pt-2">
          <button
            class="rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
            :style="{ background: 'var(--accent, #2563eb)' }"
            :disabled="!!filenameError || !!m.currentPlan?.conflict"
            @click="submit"
          >确认入库</button>
          <button v-if="m.lastReceipt" class="rounded-lg px-3 py-1.5 text-sm text-ink/70" @click="undo">
            撤销上次写入
          </button>
        </div>
        <p v-if="m.intakeError" class="text-xs" :style="{ color: 'var(--red)' }">{{ m.intakeError }}</p>
      </template>
    </div>

    <!-- 右：diff 预览 -->
    <div class="flex min-w-0 flex-1 flex-col overflow-y-auto">
      <label class="mb-1 text-xs text-ink/50">预览（将写入的 .md 全文）</label>
      <p v-if="m.currentPlan?.conflict" class="mb-2 text-xs" :style="{ color: 'var(--red)' }">
        ⚠ 同名笔记已存在，不可覆盖——请改文件名
      </p>
      <p v-for="w in m.currentPlan?.warnings || []" :key="w" class="mb-1 text-xs text-amber-600">⚠ {{ w }}</p>
      <pre class="flex-1 whitespace-pre-wrap rounded-lg bg-ink/5 p-3 text-xs leading-relaxed text-ink/80">{{ m.currentPlan?.full_text || "填写后实时预览…" }}</pre>
      <div v-if="m.currentPlan?.index_line" class="mt-2 text-[11px] text-ink/50">
        将登记到索引：<code>{{ m.currentPlan.index_line }}</code>
      </div>
    </div>
  </div>
</template>
```

> 沿用 MaterialsView 既有风格：`Pill`/`Spinner`、inline `:style` 背景、`text-ink/xx`。`useNotifications().push(title, { tone })` —— tone ∈ `info|success|warn|error`（与 article/batch store 调用一致，**不是** `{kind,text}`）。

- [ ] **Step 4: 改 `MaterialsView.vue` 为真 tab**

把 `<script setup>` 顶部改两处：① 把现有 `import { computed, onMounted } from "vue"` 改为 `import { computed, onMounted, ref } from "vue"`（追加 `ref`，勿另起一行重复 import）；② 在 `import { useMaterials … }` 之后加：
```typescript
import IntakeForm from "@/components/materials/IntakeForm.vue";
const tab = ref<"models" | "intake">("models");
```

把模板里的假 tab 条：
```html
      <div class="flex gap-2 text-sm">
        <span class="rounded-full bg-ink/10 px-3 py-1 font-medium">品牌型号</span>
        <span class="px-3 py-1 text-ink/35">浏览（建设中）</span>
        <span class="px-3 py-1 text-ink/35">录入（建设中）</span>
      </div>
```
换成真 tab：
```html
      <div class="flex gap-2 text-sm">
        <button :data-tab="'models'" class="rounded-full px-3 py-1 font-medium"
          :style="{ background: tab === 'models' ? 'var(--ink)' : 'transparent', color: tab === 'models' ? '#fff' : 'inherit' }"
          @click="tab = 'models'">品牌型号</button>
        <button :data-tab="'intake'" class="rounded-full px-3 py-1 font-medium"
          :style="{ background: tab === 'intake' ? 'var(--ink)' : 'transparent', color: tab === 'intake' ? '#fff' : 'inherit' }"
          @click="tab = 'intake'">录入</button>
        <span class="px-3 py-1 text-ink/35">浏览（建设中）</span>
      </div>
```
把现有 `<SplitPane …>…</SplitPane>` 整块用 `<template v-if="tab === 'models'">` 包住，并在其后加：
```html
    <IntakeForm v-else-if="tab === 'intake'" />
```

- [ ] **Step 5: 跑测试确认通过 + 类型检查**

```bash
cd frontend && npx vitest run src/components/materials/__tests__/IntakeForm.spec.ts && npx vue-tsc -b
```
预期：vitest 2 passed；vue-tsc exit 0（跑后 `git checkout -- vite.config.js *.d.ts` 还原 emit）。

- [ ] **Step 6: commit**

```bash
git add frontend/src/components/materials/IntakeForm.vue frontend/src/views/MaterialsView.vue frontend/src/components/materials/__tests__/IntakeForm.spec.ts
git commit -m "feat(3a): IntakeForm 录入表单 + MaterialsView 真 tab（品牌型号｜录入）"
```

---

## 最终验收（全 Unit 完成后）

- [ ] **后端全套**：
  ```powershell
  $env:PYTHONPATH="D:\CSM\.claude\worktrees\busy-matsumoto-c087bd;D:\CSM\.claude\worktrees\busy-matsumoto-c087bd\sidecar"
  & "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest tests/core/vault sidecar/tests/test_vault_writer_routes.py -q
  ```
  预期：全 PASS（真实库测试在开发机 PASS，他机 skip）。
- [ ] **前端全套 + 类型**：`cd frontend; npx vitest run src/stores/__tests__/materials.intake.spec.ts src/components/materials/__tests__/IntakeForm.spec.ts; npx vue-tsc -b`（exit 0）。
- [ ] **已知无关失败**忽略（deepseek httpx / rate_limit / export markdown / test_cli / mining schema / zhihu_search / monitor 等历史无关项）。
- [ ] **最终综合审查**（dispatch 一个 reviewer 子代理通审 spec↔实现，零回归 + 共享盘红线确认）。
- [ ] 推分支 + `gh pr create` + 停在 pending 等用户网页 merge（**不本地 merge main**）。

---

## 自审记录（写计划后已核对）

- **Spec 覆盖**：D1(3a 范围)=全计划；D2(索引策略①)=A2 `_append_index_line`+`_backlink_tail`；D3(扫库对齐邻居)=A1 `folder_profile`+C2 表单自适应；D4(两类笔记)=A2 variants/spec_table 双渲染 + C2 两 body 编辑器。§5 API=B2。§7 安全(不覆盖/逃逸/撤销)=A2+B1+B2 测试。§8 测试隔离=A 用 tmp_path、A3 真实库只读门禁。
- **占位扫描**：无 TBD/TODO；每步含完整代码与命令。
- **类型一致**：`FolderProfile`/`NotePlan`/`WriteReceipt`/`NotePayload` 字段在 csm_core dataclass、service `asdict`、路由 pydantic、前端 interface 四处同名同形；`body_shape` 取值 `variants|spec_table|unknown` 全程一致；`VARIANT_MARKERS` 复用 note_parser 导出。
