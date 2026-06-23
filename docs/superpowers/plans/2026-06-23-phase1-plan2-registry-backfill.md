# Phase 1 · Plan 2 — 文件名→品牌/型号 回填脚本 + 修 brand_registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `build_brand_registry` 在真实库返回 33 个型号（别名归一、不再返回空），并提供一个幂等、可回滚的一次性脚本，从文件名把 `品牌/型号/适用型号` 回填进 vault frontmatter（团队盘从重：默认 dry-run + 备份 + diff）。

**Architecture:** 复用 Plan 1 的 `csm_core/brand_memory/identity`（`parse_brand_model` + `canonical_brand` + `BRAND_ALIASES`）。两块互相独立、各自可交付：① 修 `csm_core/vault/brand_registry.py`（纯代码，靠文件名兜底，**即使回填前也非空**）；② 新增 `scripts/backfill_brand_model.py`（外科式插入 frontmatter，不重排 YAML、不动正文）。真实库的写入是**门禁步骤**，PR 只交付脚本+测试（不碰团队盘）。

**Tech Stack:** Python 3.12 / pydantic v2 / `python-frontmatter`（只读检测既有键，**不**用它 dump）/ pytest（`D:/CSM/.venv/Scripts/python.exe -m pytest`，从 worktree 根跑）。

参考 spec：[Phase 1 设计稿 §3](../specs/2026-06-23-phase1-brand-model-memory-design.md)（最小元数据增强）；上游 [Phase 1 总计划](2026-06-23-phase1-brand-memory.md)。

---

## 关键设计决定（执行前请确认）

这些决定基于对**真实 vault**（`D:\家电组共享\DATA\营销资料库`，33 型号、共享团队盘、无 git、LF 无 BOM）和现有代码的实测，部分**偏离 spec §3 字面**，原因如下：

1. **`型号` 用「全名」约定（含品牌前缀，如 `CEWEYDS18`），不是品牌剥离后的 `DS18`。**
   - 现有代码全栈都用全名：`tests/fixtures/mini_vault` 的 `型号: CEWEYDS18`、`assembler/sampler.py:220` 的 `index.query(filters={"型号": model})` 跨模块 join、`constraints.py` 注释明确「`型号` 是 join key」、真实测试结果笔记 `型号: CEWEY DS18`。
   - 若改成品牌剥离 `DS18`：会破坏 assembler 的 `型号` join、改写 5 个既有 registry 测试、并需把 33 篇测试结果笔记的 `型号` 一并归一（团队盘大改）。**纯 YAGNI 反模式 + 高爆炸半径。**
   - 用全名：**registry 修复零回归**（5 个既有测试全过）、assembler 不动、真实库照样 33 型号。`brand_memory`（Plan 1）解析走**文件名**不读 `型号` frontmatter，所以不受影响。
   - 影响 Q1 答复里的示例记号「`适用型号:[DS18]`」→ 本计划按全名约定写 `适用型号:[CEWEYDS18]`（与 `型号`/registry 一致）。`适用型号` 目前**无任何消费方**（resolver 按品牌+维度匹配话术，忽略它），纯为 Obsidian/Phase 3 留痕，故格式安全；若你坚持要 `DS18` 字面，改一行即可。

2. **`品牌` 写规范名（canonical）**：`米家→小米`、`希喂→CEWEY`（你已确认）。同一 CEWEY 的参数(文件名 CEWEY)/话术(文件夹 希喂推荐内容) 统一写 `CEWEY`。复用 `canonical_brand`，无新代码。

3. **技术话术（核心/次要技术）补「品牌 + 适用型号」**（你已确认）：文件名 `吸尘器-CEWEY核心技术-动力系统①` 无型号、品牌在中间 → 品牌从 `<别名>推荐内容` 文件夹推出；`适用型号` = 该品牌 `产品参数` 里的全部型号（当前 CEWEY 仅 `[CEWEYDS18]`）。仅 CEWEY（自有品牌）有技术话术（核心×3 + 次要×7）。

4. **回填一律「只增不改」**：只补**缺失**的键，**绝不覆盖**既有键、不动正文、不改目录。已存在的脏值（如测试结果 `型号: CEWEY DS18` 带空格）保留原样并写进**无法解析/异常清单**交人工，不自动改写（团队盘从重 + spec「纯增字段」）。

5. **真实库写入是门禁步骤**：本 PR 只交付脚本+测试（全绿、零 vault 写入）。对 `D:\家电组共享\DATA` 的实际 `--apply` + 改 `CLAUDE.md §3.6` 在「门禁执行 runbook」一节，需你显式放行（先整盘备份 + dry-run diff 复核 + 团队知会）。

> 真实库实测：33 篇 `产品参数` 全部能被现有 13 品牌 `BRAND_ALIASES` 解析（**0 无法解析**），所以别名表无需扩。回填目标 = 产品参数 33 + 测试结果 33 + 品牌背书 3 + 技术话术 10 = **79 篇**。

---

## File Structure

- 改 `csm_core/vault/brand_registry.py` — `build_brand_registry` 加 canonical 折叠 + `parse_brand_model` 文件名兜底（全名 `型号` 约定）。
- 改 `tests/core/vault/test_brand_registry.py` — **保留**既有 5 测试，**新增** 别名折叠 + 文件名兜底（真实库形态）+ 真实库 33 型号集成测试。
- 新增 `scripts/backfill_brand_model.py` — 回填脚本：纯派生 (`derive_note_plan`/`build_brand_models`) + 外科插入 (`insert_frontmatter_keys`) + 单篇处理 (`process_note`) + 遍历/报告/CLI (`run`/`main`)。
- 新增 `tests/scripts/test_backfill_brand_model.py` — 纯派生 + 插入 + 幂等 + 遍历 + 真实库 dry-run 集成。
- （门禁 runbook，非 repo 改动）对 `D:\家电组共享\DATA\营销资料库` 跑 `--apply`；对 `D:\家电组共享\DATA\CLAUDE.md` 加 §3.6。

---

# Part A：修 `brand_registry`（纯代码，先做）

### Task 1: registry 别名归一 + 文件名兜底（全名型号约定）

**Files:**
- Modify: `csm_core/vault/brand_registry.py`
- Test: `tests/core/vault/test_brand_registry.py`

- [ ] **Step 1: 写失败测试**（追加到文件末尾，不动既有 5 个）

`tests/core/vault/test_brand_registry.py` 追加：
```python
def test_registry_folds_brand_alias_to_canonical(tmp_path: Path):
    # 笔记写的是别名「米家」，registry 应归一到 canonical「小米」
    d = tmp_path / "营销资料库/产品模块/吸尘器/产品参数"
    d.mkdir(parents=True)
    (d / "米家3C-产品参数.md").write_text(
        "---\n产品: 吸尘器\n品牌: 米家\n型号: 米家3C\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        encoding="utf-8",
    )
    reg = build_brand_registry(tmp_path)
    assert reg.brands() == ["小米"]
    assert reg.brand_of("米家3C") == "小米"


def test_registry_falls_back_to_filename_when_no_frontmatter(tmp_path: Path):
    # 真实库形态：产品参数笔记无 品牌/型号 frontmatter，仅靠文件名
    d = tmp_path / "营销资料库/产品模块/吸尘器/产品参数"
    d.mkdir(parents=True)
    for stem in ("CEWEYDS18-产品参数", "戴森V12-产品参数", "米家3C-产品参数"):
        (d / f"{stem}.md").write_text(
            "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
            encoding="utf-8",
        )
    reg = build_brand_registry(tmp_path)
    assert set(reg.brands()) == {"CEWEY", "戴森", "小米"}
    assert set(reg.all_models()) == {"CEWEYDS18", "戴森V12", "米家3C"}
    assert reg.brand_of("米家3C") == "小米"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/vault/test_brand_registry.py -v`
Expected: 既有 5 个 PASS；2 个新测试 FAIL（`test_registry_folds_brand_alias_to_canonical` 期望 `["小米"]` 实得 `["米家"]`；`test_registry_falls_back...` 因缺 `品牌` 键当前返回空 → `set()` ≠ 期望集）。

- [ ] **Step 3: 写实现**

`csm_core/vault/brand_registry.py` 全文替换为：
```python
"""Build brand-model registry from 产品参数 note filenames + frontmatter."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .note_parser import parse_note
from ..brand_memory.identity import BRAND_ALIASES, canonical_brand, parse_brand_model


@dataclass
class BrandRegistry:
    _brand_to_models: dict[str, list[str]] = field(default_factory=dict)
    _model_to_brand: dict[str, str] = field(default_factory=dict)

    def brands(self) -> list[str]:
        return sorted(self._brand_to_models.keys())

    def models(self, brand: str) -> list[str]:
        return sorted(self._brand_to_models.get(brand, []))

    def all_models(self) -> list[str]:
        return sorted(self._model_to_brand.keys())

    def brand_of(self, model: str) -> str | None:
        return self._model_to_brand.get(model)

    def competitors_of(self, brand: str) -> list[str]:
        return [m for m, b in self._model_to_brand.items() if b != brand]

    def add(self, brand: str, model: str) -> None:
        self._brand_to_models.setdefault(brand, [])
        if model not in self._brand_to_models[brand]:
            self._brand_to_models[brand].append(model)
        self._model_to_brand[model] = brand


def build_brand_registry(
    vault_root: Path, *, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> BrandRegistry:
    """Scan <vault>/**/产品参数/*.md and construct registry.

    品牌 is folded to canonical (米家->小米, 希喂->CEWEY). When a note lacks
    品牌/型号 frontmatter (the real vault today), we fall back to parsing the
    filename via brand_memory.identity.parse_brand_model — so the registry is
    non-empty even before the one-shot backfill runs. 型号 keeps the full-stem
    convention (incl. brand prefix, e.g. CEWEYDS18) used across the assembler
    型号-join (sampler.py / constraints.py); see plan §关键设计决定 #1.
    """
    registry = BrandRegistry()
    for md in sorted(vault_root.rglob("产品参数/*.md")):
        note = parse_note(md)
        parsed = parse_brand_model(md.stem, aliases)
        brand = note.frontmatter.get("品牌") or (parsed[0] if parsed else None)
        model = note.frontmatter.get("型号") or md.stem.split("-")[0]
        if not brand or not model:
            continue
        registry.add(canonical_brand(str(brand), aliases), str(model).strip())
    return registry
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/vault/test_brand_registry.py -v`
Expected: PASS（7 passed：既有 5 + 新 2）。

- [ ] **Step 5: 跑 assembler 回归确认零爆炸**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/assembler/ tests/core/vault/ -q`
Expected: PASS（registry 全名约定不变，assembler 的 `型号` join 不受影响）。

- [ ] **Step 6: 提交**

```bash
git add csm_core/vault/brand_registry.py tests/core/vault/test_brand_registry.py
git commit -m "fix(brand_registry): 别名归一 + 文件名兜底（真实库非空 33 型号，保全名型号约定）"
```

---

### Task 2: registry 真实库 33 型号集成测试（integration，默认跳过）

**Files:**
- Test: `tests/core/vault/test_brand_registry.py`

- [ ] **Step 1: 写测试**（追加到文件末尾；需 `import pytest`、`from pathlib import Path`，文件首行已 `from pathlib import Path`，补 `import pytest`）

`tests/core/vault/test_brand_registry.py` 追加：
```python
import pytest  # noqa: E402  (顶部若已 import 则删除本行)

_REAL_VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


@pytest.mark.integration
@pytest.mark.skipif(not _REAL_VAULT.exists(), reason="真实 vault 不在本机")
def test_real_vault_registry_has_33_models():
    reg = build_brand_registry(_REAL_VAULT)
    assert len(reg.all_models()) == 33
    assert "CEWEY" in reg.brands()
    assert "小米" in reg.brands()  # 米家* 应归一到 小米，不出现「米家」品牌
    assert "米家" not in reg.brands()
    assert {"米家3C", "米家2显尘版", "米家3基站版"}.issubset(set(reg.models("小米")))
```

- [ ] **Step 2: 手动跑一次（开发机）**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/vault/test_brand_registry.py -v -m integration`
Expected: PASS（真实 vault 在本机时）；否则 SKIPPED。

- [ ] **Step 3: 提交**

```bash
git add tests/core/vault/test_brand_registry.py
git commit -m "test(brand_registry): 真实库 33 型号 + 别名归一集成测试（默认跳过）"
```

---

# Part B：回填脚本 `scripts/backfill_brand_model.py`

### Task 3: 纯派生逻辑（folder→该补哪些键，含无法解析）

**Files:**
- Create: `scripts/backfill_brand_model.py`
- Test: `tests/scripts/test_backfill_brand_model.py`

- [ ] **Step 1: 写失败测试**

`tests/scripts/test_backfill_brand_model.py`:
```python
from scripts.backfill_brand_model import derive_note_plan, build_brand_models

BM = {"CEWEY": ["CEWEYDS18"], "小米": ["米家3C"]}


def _parts(*p):
    return tuple(p)


def test_param_note_gets_brand_and_full_stem_model():
    plan = derive_note_plan(_parts("产品参数", "CEWEYDS18-产品参数.md"), "CEWEYDS18-产品参数", BM)
    assert plan.keys == {"品牌": "CEWEY", "型号": "CEWEYDS18"}
    assert plan.unparseable is None


def test_param_note_folds_alias_brand_keeps_full_stem():
    plan = derive_note_plan(_parts("产品参数", "米家3C-产品参数.md"), "米家3C-产品参数", BM)
    assert plan.keys == {"品牌": "小米", "型号": "米家3C"}


def test_test_result_note_gets_brand_and_full_stem():
    plan = derive_note_plan(
        _parts("品牌产品测试结果", "戴森V12-测试结果.md"), "戴森V12-测试结果", BM)
    assert plan.keys == {"品牌": "戴森", "型号": "戴森V12"}


def test_endorsement_note_gets_brand_only_from_folder():
    plan = derive_note_plan(
        _parts("希喂推荐内容", "品牌背书", "吸尘器-CEWEY品牌背书-品牌定位①.md"),
        "吸尘器-CEWEY品牌背书-品牌定位①", BM)
    assert plan.keys == {"品牌": "CEWEY"}


def test_script_note_gets_brand_and_applicable_models():
    plan = derive_note_plan(
        _parts("希喂推荐内容", "核心技术", "吸尘器-CEWEY核心技术-动力系统①.md"),
        "吸尘器-CEWEY核心技术-动力系统①", BM)
    assert plan.keys == {"品牌": "CEWEY", "适用型号": ["CEWEYDS18"]}


def test_non_target_note_returns_none():
    assert derive_note_plan(_parts("科普模块", "挑选攻略", "x.md"), "x", BM) is None


def test_unparseable_param_filename_flagged_not_guessed():
    plan = derive_note_plan(_parts("产品参数", "杂牌X9-产品参数.md"), "杂牌X9-产品参数", BM)
    assert plan.keys == {}
    assert "杂牌X9" in plan.unparseable


def test_build_brand_models_groups_full_stems_by_canonical(tmp_path):
    d = tmp_path / "营销资料库/产品模块/吸尘器/产品参数"
    d.mkdir(parents=True)
    for stem in ("CEWEYDS18-产品参数", "米家3C-产品参数", "米家3基站版-产品参数"):
        (d / f"{stem}.md").write_text("---\n产品: 吸尘器\n---\n体\n", encoding="utf-8")
    bm = build_brand_models(tmp_path)
    assert bm["CEWEY"] == ["CEWEYDS18"]
    assert set(bm["小米"]) == {"米家3C", "米家3基站版"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_brand_model'`

- [ ] **Step 3: 写实现**

`scripts/backfill_brand_model.py`:
```python
"""One-shot vault enhancement: backfill 品牌/型号/适用型号 frontmatter from filenames.

Usage:
    # dry-run (default): print would-change list + 无法解析清单; writes NOTHING
    python -m scripts.backfill_brand_model "<vault_root>"
    # apply: copy each modified file into <backup_dir> first, then edit in place
    python -m scripts.backfill_brand_model "<vault_root>" --apply --backup-dir "<dir>"

Folder routing (additive only — never overwrites an existing key, idempotent):
    产品参数/*.md            -> add 品牌(canonical) + 型号(full stem, e.g. CEWEYDS18)
    品牌产品测试结果/*.md     -> add 品牌(canonical) + 型号(full stem) [既有 型号 保留]
    品牌背书/*.md            -> add 品牌(canonical) only (brand-level)
    核心技术/次要技术/*.md    -> add 品牌(canonical) + 适用型号 [该品牌 产品参数 全名型号列表]

品牌 is folded to canonical (米家->小米, 希喂->CEWEY) via brand_memory.identity.
型号 keeps the full-stem convention (incl. brand prefix) so it stays consistent with
build_brand_registry + the assembler 型号-join. Notes whose brand/model can't be
derived go to the 无法解析清单 (never guessed). See the plan's 关键设计决定 section.
"""
from __future__ import annotations
import argparse
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from csm_core.brand_memory.identity import (
    BRAND_ALIASES, canonical_brand, parse_brand_model,
)

logger = logging.getLogger(__name__)

_SUFFIXES = ("-产品参数", "-测试结果")
_PARAM_DIR = "产品参数"
_TEST_DIR = "品牌产品测试结果"
_ENDORSE_DIR = "品牌背书"
_SCRIPT_DIRS = ("核心技术", "次要技术")
_WRITING_SUFFIX = "推荐内容"  # 文件夹 <品牌别名>推荐内容


@dataclass
class NotePlan:
    """What SHOULD be present on a note (derived purely from its path)."""
    keys: dict
    unparseable: str | None = None


def _full_stem_model(stem: str) -> str:
    """Stem minus a trailing -产品参数 / -测试结果 (brand prefix kept)."""
    for suf in _SUFFIXES:
        if stem.endswith(suf):
            return stem[: -len(suf)]
    return stem


def _brand_from_writing_folder(
    rel_parts: tuple[str, ...], aliases: dict[str, list[str]],
) -> str | None:
    """Canonical brand from a '<alias>推荐内容' ancestor folder, else None.

    '竞品推荐内容' folds to '竞品' which is not a known brand -> None (correctly
    excluded; 竞品推荐内容 is not a backfill target anyway).
    """
    for part in rel_parts:
        if part.endswith(_WRITING_SUFFIX):
            canon = canonical_brand(part[: -len(_WRITING_SUFFIX)], aliases)
            if canon in aliases:
                return canon
    return None


def build_brand_models(
    vault_root: Path, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> dict[str, list[str]]:
    """canonical brand -> [full-stem models], from 产品参数 filenames."""
    out: dict[str, list[str]] = {}
    for md in sorted(Path(vault_root).rglob(f"{_PARAM_DIR}/*.md")):
        parsed = parse_brand_model(md.stem, aliases)
        if not parsed:
            continue
        brand = canonical_brand(parsed[0], aliases)
        model = _full_stem_model(md.stem)
        out.setdefault(brand, [])
        if model not in out[brand]:
            out[brand].append(model)
    return out


def derive_note_plan(
    rel_parts: tuple[str, ...], stem: str,
    brand_models: dict[str, list[str]], aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> NotePlan | None:
    """Target keys for a note, or None if it's not a backfill target."""
    parts = set(rel_parts)
    if _PARAM_DIR in parts or _TEST_DIR in parts:
        kind = "产品参数" if _PARAM_DIR in parts else "测试结果"
        parsed = parse_brand_model(stem, aliases)
        if not parsed:
            return NotePlan(keys={}, unparseable=f"{stem}: {kind} 文件名无法解析品牌前缀")
        brand = canonical_brand(parsed[0], aliases)
        return NotePlan(keys={"品牌": brand, "型号": _full_stem_model(stem)})
    if _ENDORSE_DIR in parts:
        brand = _brand_from_writing_folder(rel_parts, aliases)
        if not brand:
            return NotePlan(keys={}, unparseable=f"{stem}: 品牌背书 无法从文件夹解析品牌")
        return NotePlan(keys={"品牌": brand})
    if parts & set(_SCRIPT_DIRS):
        brand = _brand_from_writing_folder(rel_parts, aliases)
        if not brand:
            return NotePlan(keys={}, unparseable=f"{stem}: 技术话术 无法从文件夹解析品牌")
        keys: dict = {"品牌": brand}
        models = brand_models.get(brand, [])
        if models:
            keys["适用型号"] = list(models)
        return NotePlan(keys=keys)
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -v`
Expected: PASS（8 passed）。

- [ ] **Step 5: 提交**

```bash
git add scripts/backfill_brand_model.py tests/scripts/test_backfill_brand_model.py
git commit -m "feat(backfill): 文件名→品牌/型号/适用型号 纯派生（folder 路由 + 无法解析清单）"
```

---

### Task 4: 外科式 frontmatter 插入（保 newline/BOM、不重排 YAML）

**Files:**
- Modify: `scripts/backfill_brand_model.py`
- Test: `tests/scripts/test_backfill_brand_model.py`

- [ ] **Step 1: 写失败测试**（追加）

`tests/scripts/test_backfill_brand_model.py` 追加：
```python
from scripts.backfill_brand_model import insert_frontmatter_keys

_LF = "---\n产品: 吸尘器\n素材类型: 产品参数\n---\n\n## 正文\n内容\n"


def test_insert_adds_before_closing_delim_preserving_lf():
    out = insert_frontmatter_keys(_LF, {"品牌": "CEWEY", "型号": "CEWEYDS18"})
    assert "\r\n" not in out
    assert out == (
        "---\n产品: 吸尘器\n素材类型: 产品参数\n"
        "品牌: CEWEY\n型号: CEWEYDS18\n"
        "---\n\n## 正文\n内容\n"
    )


def test_insert_preserves_crlf():
    crlf = _LF.replace("\n", "\r\n")
    out = insert_frontmatter_keys(crlf, {"品牌": "CEWEY"})
    assert "品牌: CEWEY\r\n---\r\n" in out
    assert "\n" not in out.replace("\r\n", "")  # 没有裸 \n


def test_insert_renders_list_as_flow_style():
    out = insert_frontmatter_keys(_LF, {"适用型号": ["CEWEYDS18"]})
    assert "适用型号: [CEWEYDS18]\n" in out


def test_insert_empty_keys_is_noop():
    assert insert_frontmatter_keys(_LF, {}) == _LF


def test_insert_without_frontmatter_block_raises():
    import pytest
    with pytest.raises(ValueError):
        insert_frontmatter_keys("没有 frontmatter 的正文\n", {"品牌": "CEWEY"})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -k insert -v`
Expected: FAIL — `ImportError: cannot import name 'insert_frontmatter_keys'`

- [ ] **Step 3: 写实现**（把这两个函数追加进 `scripts/backfill_brand_model.py`，放在 `derive_note_plan` 之后）

```python
def _render_kv(key: str, value) -> str:
    if isinstance(value, list):
        return f"{key}: [{', '.join(str(v) for v in value)}]"
    return f"{key}: {value}"


def insert_frontmatter_keys(text: str, keys: dict) -> str:
    """Insert 'k: v' lines just before the closing '---' of the frontmatter block.

    Preserves the file's newline style and everything else verbatim. ``text``
    must start with a '---' frontmatter block (BOM already stripped by caller).
    Returns ``text`` unchanged when ``keys`` is empty. We do text-level insertion
    (NOT frontmatter.dumps) on purpose: python-frontmatter would reorder/reflow
    the team's existing YAML and blow up the diff on a shared vault.
    """
    if not keys:
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    if not lines or lines[0].strip() != "---":
        raise ValueError("no frontmatter block at start of note")
    close_idx = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"), None,
    )
    if close_idx is None:
        raise ValueError("unterminated frontmatter block")
    new_lines = [_render_kv(k, v) for k, v in keys.items()]
    return nl.join(lines[:close_idx] + new_lines + lines[close_idx:])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -v`
Expected: PASS（13 passed）。

- [ ] **Step 5: 提交**

```bash
git add scripts/backfill_brand_model.py tests/scripts/test_backfill_brand_model.py
git commit -m "feat(backfill): 外科式 frontmatter 插入（保 newline/BOM、flow 列表、不重排 YAML）"
```

---

### Task 5: 单篇处理 + 幂等 + 备份（读文件、只补缺键、写回）

**Files:**
- Modify: `scripts/backfill_brand_model.py`
- Test: `tests/scripts/test_backfill_brand_model.py`

- [ ] **Step 1: 写失败测试**（追加）

`tests/scripts/test_backfill_brand_model.py` 追加：
```python
from scripts.backfill_brand_model import process_note, NotePlan


def _make_param(tmp_path):
    p = tmp_path / "CEWEYDS18-产品参数.md"
    p.write_text(
        "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n\n## 性能\n吸力 220\n",
        encoding="utf-8")
    return p


def test_process_adds_missing_keys_and_keeps_body(tmp_path):
    p = _make_param(tmp_path)
    plan = NotePlan(keys={"品牌": "CEWEY", "型号": "CEWEYDS18"})
    res = process_note(p, plan, apply=True, backup_path=None)
    assert res.status == "added"
    text = p.read_text(encoding="utf-8")
    assert "品牌: CEWEY\n" in text and "型号: CEWEYDS18\n" in text
    assert "## 性能\n吸力 220" in text  # 正文不动
    assert "素材类型: 产品参数" in text  # 既有键不动


def test_process_is_idempotent(tmp_path):
    p = _make_param(tmp_path)
    plan = NotePlan(keys={"品牌": "CEWEY", "型号": "CEWEYDS18"})
    process_note(p, plan, apply=True, backup_path=None)
    before = p.read_text(encoding="utf-8")
    res2 = process_note(p, plan, apply=True, backup_path=None)
    assert res2.status == "skip"
    assert p.read_text(encoding="utf-8") == before  # 第二次零改动


def test_process_never_overwrites_existing_key(tmp_path):
    p = tmp_path / "CEWEY DS18-测试结果.md"
    p.write_text(
        "---\n产品: 吸尘器\n型号: CEWEY DS18\n素材类型: 测试数据\n---\n正文\n",
        encoding="utf-8")
    plan = NotePlan(keys={"品牌": "CEWEY", "型号": "CEWEY DS18"})
    res = process_note(p, plan, apply=True, backup_path=None)
    assert res.status == "added"
    assert res.added == {"品牌": "CEWEY"}  # 只补 品牌
    text = p.read_text(encoding="utf-8")
    assert text.count("型号:") == 1  # 既有 型号 未被复写


def test_process_dry_run_writes_nothing(tmp_path):
    p = _make_param(tmp_path)
    before = p.read_text(encoding="utf-8")
    res = process_note(p, NotePlan(keys={"品牌": "CEWEY"}), apply=False, backup_path=None)
    assert res.status == "added"  # 报告「会改」但不落盘
    assert p.read_text(encoding="utf-8") == before


def test_process_writes_backup(tmp_path):
    p = _make_param(tmp_path)
    bak = tmp_path / "bak" / "CEWEYDS18-产品参数.md"
    process_note(p, NotePlan(keys={"品牌": "CEWEY"}), apply=True, backup_path=bak)
    assert bak.exists()
    assert "品牌:" not in bak.read_text(encoding="utf-8")  # 备份是改前原文
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -k process -v`
Expected: FAIL — `ImportError: cannot import name 'process_note'`

- [ ] **Step 3: 写实现**（追加进 `scripts/backfill_brand_model.py`）

```python
@dataclass
class NoteResult:
    path: Path
    status: str  # "added" | "skip" | "non_target" | "unparseable"
    added: dict = field(default_factory=dict)
    reason: str = ""


def _backup(src: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, backup_path)


def process_note(
    path: Path, plan: NotePlan | None, *, apply: bool, backup_path: Path | None,
) -> NoteResult:
    """Read one note, add only the MISSING target keys (additive, idempotent)."""
    if plan is None:
        return NoteResult(path=path, status="non_target")
    if plan.unparseable:
        return NoteResult(path=path, status="unparseable", reason=plan.unparseable)
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    post = frontmatter.loads(text)
    missing = {k: v for k, v in plan.keys.items() if k not in post.metadata}
    if not missing:
        return NoteResult(path=path, status="skip")
    new_text = insert_frontmatter_keys(text, missing)
    if apply:
        if backup_path is not None:
            _backup(path, backup_path)
        out = new_text.encode("utf-8")
        if had_bom:
            out = b"\xef\xbb\xbf" + out
        path.write_bytes(out)
    return NoteResult(path=path, status="added", added=missing)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -v`
Expected: PASS（18 passed）。

- [ ] **Step 5: 提交**

```bash
git add scripts/backfill_brand_model.py tests/scripts/test_backfill_brand_model.py
git commit -m "feat(backfill): 单篇处理（只补缺键/幂等/备份/dry-run 不落盘）"
```

---

### Task 6: 遍历 vault + 报告 + CLI（dry-run 默认、--apply 必带 --backup-dir）

**Files:**
- Modify: `scripts/backfill_brand_model.py`
- Test: `tests/scripts/test_backfill_brand_model.py`

- [ ] **Step 1: 写失败测试**（追加）

`tests/scripts/test_backfill_brand_model.py` 追加：
```python
from scripts.backfill_brand_model import run, main


def _build_fake_vault(root):
    base = root / "营销资料库/产品模块/吸尘器"
    tests_base = root / "营销资料库/测试项目模块/吸尘器"
    files = {
        base / "产品参数/CEWEYDS18-产品参数.md":
            "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        base / "产品参数/米家3C-产品参数.md":
            "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        base / "产品参数/杂牌X9-产品参数.md":
            "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: [x]\n---\n体\n",
        base / "希喂推荐内容/品牌背书/吸尘器-CEWEY品牌背书-品牌定位①.md":
            "---\n产品: 吸尘器\n素材类型: 品牌定位\n核心关键词: [x]\n---\n体\n",
        base / "希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md":
            "---\n产品: 吸尘器\n素材类型: 动力系统\n核心关键词: [x]\n---\n体\n",
        tests_base / "品牌产品测试结果/CEWEYDS18-测试结果.md":
            "---\n产品: 吸尘器\n型号: CEWEYDS18\n素材类型: 测试数据\n---\n体\n",
        base / "科普模块占位/挑选攻略/吸尘器-过滤系统选购.md":
            "---\n产品: 吸尘器\n素材类型: 科普原理解析\n核心关键词: [x]\n---\n体\n",
    }
    for p, t in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    return root


def test_run_dry_run_reports_but_writes_nothing(tmp_path):
    root = _build_fake_vault(tmp_path)
    snapshot = {p: p.read_text(encoding="utf-8") for p in root.rglob("*.md")}
    report = run(root, apply=False, backup_dir=None)
    # 产品参数×2(可解析) + 品牌背书×1 + 核心技术×1 + 测试结果(仅缺品牌)×1 = 5 篇会改
    assert len(report.added) == 5
    assert len(report.unparseable) == 1  # 杂牌X9
    for p, t in snapshot.items():
        assert p.read_text(encoding="utf-8") == t  # 一字未改


def test_run_apply_changes_files_and_backs_up(tmp_path):
    root = _build_fake_vault(tmp_path)
    bak = tmp_path / "_bak"
    report = run(root, apply=True, backup_dir=bak)
    assert len(report.added) == 5
    core = root / "营销资料库/产品模块/吸尘器/希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md"
    txt = core.read_text(encoding="utf-8")
    assert "品牌: CEWEY\n" in txt and "适用型号: [CEWEYDS18]\n" in txt
    # 备份存在且为改前原文
    assert list(bak.rglob("*.md"))
    # 再跑一次 → 全部已完整 → 0 added（幂等）
    report2 = run(root, apply=True, backup_dir=tmp_path / "_bak2")
    assert len(report2.added) == 0


def test_main_apply_without_backup_dir_errors(tmp_path):
    root = _build_fake_vault(tmp_path)
    rc = main([str(root), "--apply"])
    assert rc == 2  # --apply 必须配 --backup-dir
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -k "run or main" -v`
Expected: FAIL — `ImportError: cannot import name 'run'`

- [ ] **Step 3: 写实现**（追加进 `scripts/backfill_brand_model.py`，含 `main`）

```python
@dataclass
class Report:
    added: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    unparseable: list = field(default_factory=list)


def run(
    vault_root: Path, *, apply: bool, backup_dir: Path | None,
    aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> Report:
    """Walk the vault, backfill every target note, collect a report."""
    vault_root = Path(vault_root)
    brand_models = build_brand_models(vault_root, aliases)
    report = Report()
    for md in sorted(vault_root.rglob("*.md")):
        try:
            rel = md.relative_to(vault_root)
        except ValueError:
            continue
        plan = derive_note_plan(rel.parts, md.stem, brand_models, aliases)
        if plan is None:
            continue
        backup_path = (Path(backup_dir) / rel) if (apply and backup_dir) else None
        res = process_note(md, plan, apply=apply, backup_path=backup_path)
        if res.status == "added":
            report.added.append(res)
        elif res.status == "skip":
            report.skipped.append(res)
        elif res.status == "unparseable":
            report.unparseable.append(res)
    return report


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description="回填 vault 的 品牌/型号/适用型号 frontmatter（默认 dry-run）")
    ap.add_argument("vault_root", type=Path)
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run，不落盘）")
    ap.add_argument("--backup-dir", type=Path, default=None,
                    help="--apply 时的原文件备份目录（必填，团队盘从重）")
    args = ap.parse_args(argv)

    if not args.vault_root.is_dir():
        print(f"error: {args.vault_root} 不是目录", file=sys.stderr)
        return 2
    if args.apply and args.backup_dir is None:
        print("error: --apply 必须配 --backup-dir（先备份再改团队盘）", file=sys.stderr)
        return 2

    report = run(args.vault_root, apply=args.apply, backup_dir=args.backup_dir)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] 回填 {len(report.added)} 篇 / 跳过(已完整) {len(report.skipped)} 篇 "
          f"/ 无法解析 {len(report.unparseable)} 篇")
    for r in report.added:
        print(f"  + {r.path.name}: {r.added}")
    if report.unparseable:
        print("无法解析清单（需人工复核，未改动）：")
        for r in report.unparseable:
            print(f"  ! {r.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过 + 全脚本测试**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -v`
Expected: PASS（21 passed）。

- [ ] **Step 5: 提交**

```bash
git add scripts/backfill_brand_model.py tests/scripts/test_backfill_brand_model.py
git commit -m "feat(backfill): 遍历+报告+CLI（dry-run 默认、--apply 必带 --backup-dir、幂等）"
```

---

### Task 7: 真实库 dry-run 集成冒烟（integration，默认跳过）

**Files:**
- Test: `tests/scripts/test_backfill_brand_model.py`

- [ ] **Step 1: 写测试**（追加；验证脚本吃得下真实库且 0 无法解析）

`tests/scripts/test_backfill_brand_model.py` 追加：
```python
import pytest
from pathlib import Path

_REAL_VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


@pytest.mark.integration
@pytest.mark.skipif(not _REAL_VAULT.exists(), reason="真实 vault 不在本机")
def test_real_vault_dry_run_zero_unparseable():
    report = run(_REAL_VAULT, apply=False, backup_dir=None)
    assert report.unparseable == [], [r.reason for r in report.unparseable]
    # 产品参数 33 + 测试结果 33 + 品牌背书 3 + 技术话术 10 = 79 篇目标；
    # 已含 型号 的测试结果只补品牌，仍计入 added（除非 已 backfill 过）。
    assert len(report.added) + len(report.skipped) >= 79
```

- [ ] **Step 2: 手动跑一次（开发机，纯 dry-run，不碰团队盘）**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/test_backfill_brand_model.py -v -m integration`
Expected: PASS（真实 vault 在本机时）；否则 SKIPPED。

- [ ] **Step 3: 全量回归 + 提交**

Run: `D:/CSM/.venv/Scripts/python.exe -m pytest tests/scripts/ tests/core/vault/ tests/core/brand_memory/ tests/core/assembler/ -q`
Expected: PASS（含既有 assembler/registry 全绿）。

```bash
git add tests/scripts/test_backfill_brand_model.py
git commit -m "test(backfill): 真实库 dry-run 集成冒烟（0 无法解析、≥79 目标，默认跳过）"
```

---

## 门禁执行 runbook（真实库写入 —— 需用户显式放行，不在 PR 内）

> 改的是 `D:\家电组共享\DATA`（共享团队盘、无 git）。以下步骤**仅在用户放行后**执行，逐步停顿确认。

- [ ] **G1 整盘备份**：把 `D:\家电组共享\DATA\营销资料库` 整目录复制到带时间戳的备份处（脚本的 `--backup-dir` 是逐文件兜底，这一步是整盘保险）。
- [ ] **G2 dry-run 复核**：`python -m scripts.backfill_brand_model "D:\家电组共享\DATA\营销资料库"`，人工核对「会改 79 篇 / 无法解析 0 篇」+ 抽查几条 `+` 行的键正确。
- [ ] **G3 团队知会**：通知家电组「将给 vault 笔记补 品牌/型号/适用型号 frontmatter，纯增字段、可回滚」，得到确认。
- [ ] **G4 apply**：`python -m scripts.backfill_brand_model "D:\家电组共享\DATA\营销资料库" --apply --backup-dir "<时间戳备份目录>\_perfile_bak"`。
- [ ] **G5 diff 校验**：对 G1 备份做全量 diff，确认**只有新增的 `品牌/型号/适用型号` 行**、无正文/既有键改动、无 newline 翻动。
- [ ] **G6 更新 vault CLAUDE.md §3.6**：在 `D:\家电组共享\DATA\CLAUDE.md` 的「## 三、YAML Frontmatter 规范」内、§3.5 之后插入下节（否则团队整理流程会把新键当未知字段清掉——见该文件 §3.5 + 批量删字段段落）：

  ````markdown
  ### 3.6 产品/竞品模块额外字段（品牌型号记忆库）

  `产品参数` / `品牌产品测试结果` 笔记额外包含：

  ```yaml
  ---
  产品: 吸尘器
  品牌: CEWEY          # 规范品牌名（米家→小米、希喂→CEWEY）
  型号: CEWEYDS18       # 型号标识（含品牌前缀，与文件名一致）
  素材类型: 产品参数
  核心关键词: [kw1, kw2, kw3]
  ---
  ```

  `核心技术` / `次要技术` 笔记额外含 `适用型号`；`品牌背书` 仅含 `品牌`：

  ```yaml
  ---
  产品: 吸尘器
  品牌: CEWEY
  适用型号: [CEWEYDS18]   # 仅技术话术：适用型号列表（品牌背书不含此字段）
  素材类型: 核心技术
  核心关键词: [kw1, kw2, kw3]
  ---
  ```

  > `品牌`/`型号`/`适用型号` 由 `scripts/backfill_brand_model.py` 一次性回填；属**有效字段**，禁止整理流程当未知/废弃字段清除。
  ````

- [ ] **G7 回填后验证**：`pytest tests/core/vault/test_brand_registry.py -m integration`（仍 33 型号）+ 抽一篇笔记肉眼确认键正确。

---

## Self-Review（对照 spec §3 / §9）

- **Spec 覆盖**：
  - §3「回填 品牌/型号」→ Task 3-6（产品参数/测试结果 补品牌+型号；品牌背书 补品牌；技术话术 补品牌+适用型号）。✅
  - §3「别名归一（解析层与 registry 共用别名表）」→ Task 1 用 `canonical_brand` + Task 3 用同一 `BRAND_ALIASES`。✅
  - §3「修 brand_registry，真实库非空」→ Task 1（文件名兜底，回填前即非空）。✅
  - §3「同步 vault CLAUDE.md」→ runbook G6（§3.6）。✅
  - §3「安全：备份/副本/diff/幂等/可回滚」→ dry-run 默认 + `--backup-dir` 必填 + 整盘备份 G1 + diff G5 + 幂等（Task 5/6）。✅
  - §9.1「真实库 33 型号、别名归一」→ Task 2 集成测试断言。✅
- **占位符扫描**：无 TBD/TODO；每个 code step 含完整代码 + 可跑命令 + 期望输出。✅
- **类型/签名一致性**：`derive_note_plan(rel_parts, stem, brand_models, aliases) -> NotePlan|None`、`process_note(path, plan, *, apply, backup_path) -> NoteResult`、`run(vault_root, *, apply, backup_dir, aliases) -> Report`、`insert_frontmatter_keys(text, keys) -> str`、`build_brand_models(vault_root, aliases) -> dict` 在 Task 3-7 定义与调用一致；`build_brand_registry(vault_root, *, aliases)` 关键字参数 Task 1/2 一致。✅
- **导入环**：`brand_registry` → `brand_memory.identity`（identity 不 import vault）；`brand_memory.__init__` → resolver → vault.scanner（scanner 不 import brand_registry）→ 无环。✅
- **零回归**：Task 1 保「全名型号」约定 → mini_vault 既有 5 测试 + assembler `型号`-join 不变（Step 5/Task7 Step3 跑回归确认）。✅
