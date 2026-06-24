# Phase 1 — 品牌型号记忆库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 app 从已有 vault 笔记实时解析出每个 (品牌, 型号) 的结构化「记忆」(参数/认证/话术/背书/介绍/测试 + 缺口体检)，作为后续注入与事实核对的事实源。

**Architecture:** 纯 Python 解析层 `csm_core/brand_memory/`，输入 `VaultIndex`（已有 `scan_vault`）输出 `BrandModelMemory`（pydantic，不落盘）。品牌×型号矩阵：背书品牌级、其余型号级。维度取「文件夹+文件名」（不依赖不可靠的 `素材类型` 字段）。复用 `note_parser`（①②变体）+ `test_framework.section_parser`（H2 分节）。

**Tech Stack:** Python 3.11+ / pydantic v2 / pytest（`tests/core/...`，`pytest -v --tb=short`）。

参考 spec：[Phase 1 设计稿](../specs/2026-06-23-phase1-brand-model-memory-design.md)。

---

## 计划序列（Phase 1 拆 5 个独立可交付 plan）

| Plan | 范围 | 依赖 | 本文档 |
|---|---|---|---|
| **1 解析层** | `csm_core/brand_memory/`：models / identity / specs 解析 / resolver / 白名单构建 | — | **✅ 全量细化（下文）** |
| 2 增强脚本 + registry | 文件名→品牌/型号 回填脚本（副本+diff）、别名表、修 `build_brand_registry` | 复用 Plan1 identity | **✅ [全量细化](2026-06-23-phase1-plan2-registry-backfill.md)** |
| 3 注入 + 事实核对门禁 | `prompts.brand_facts`、`generate_service` 注入步+token预算、`csm_core/factcheck/`、导出门禁+放行、feature flags | Plan1 + Plan2 | **✅ [全量细化](2026-06-23-phase1-plan3-inject-factcheck.md)** |
| 4 skill 解耦 | 拆 `家电科普博主.md`→人设/去AI味/合并、`role` 字段、模板 default_skill_id 迁移 | — | **✅ [全量细化](2026-06-24-phase1-plan4-skill-decouple.md)** |
| 5a UI·素材库 | 「素材库」入口 + 「品牌型号」tab（只读+缺口+注入预览）+ `brand-memory` API | Plan1+3 | **✅ [全量细化](2026-06-24-phase1-plan5a-material-library.md)** |
| 5b UI·收官 | `SkillEditView` role 下拉 + ArticleView factcheck 审查面板 | Plan3+4 + 5a | 待细化（5a 合并后） |

> 每个 plan 跑通即得可测软件。Plan 1 是地基，先做。Plans 2–5 在 Plan 1 合并后逐个细化为同样粒度的任务。

---

# Plan 1：解析层 `csm_core/brand_memory/`

## File Structure

- `csm_core/brand_memory/__init__.py` — 导出 `resolve_memory`, `BrandModelMemory`。
- `csm_core/brand_memory/model.py` — `SpecValue`、`BrandModelMemory`（pydantic）。
- `csm_core/brand_memory/identity.py` — 品牌别名 + 文件名→(品牌,型号)。
- `csm_core/brand_memory/specs.py` — 产品参数表 → `dict[字段, SpecValue]`。
- `csm_core/brand_memory/resolver.py` — VaultIndex + (品牌,型号) → `BrandModelMemory`。
- `csm_core/brand_memory/whitelist.py` — 记忆 + 注入文本 → 事实白名单（数字集合 + 认证）。
- `tests/core/brand_memory/{__init__.py,test_identity.py,test_specs.py,test_resolver.py,test_whitelist.py}`。

---

### Task 1: 包骨架 + 数据模型

**Files:**
- Create: `csm_core/brand_memory/__init__.py`
- Create: `csm_core/brand_memory/model.py`
- Create: `tests/core/brand_memory/__init__.py`
- Test: `tests/core/brand_memory/test_model.py`

- [ ] **Step 1: 写失败测试**

`tests/core/brand_memory/test_model.py`:
```python
from csm_core.brand_memory.model import SpecValue, BrandModelMemory


def test_specvalue_defaults():
    sv = SpecValue(field="吸力(AW)", raw="220", numbers=[220.0], unit="AW")
    assert sv.is_approx is False
    assert sv.numbers == [220.0]


def test_memory_minimal():
    m = BrandModelMemory(brand="CEWEY", model="DS18", category="吸尘器", role="主推")
    assert m.specs == {} and m.scripts == {} and m.role == "主推"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/brand_memory/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'csm_core.brand_memory'`

- [ ] **Step 3: 写实现**

`csm_core/brand_memory/__init__.py`:
```python
"""Brand/model memory — resolve structured per-model facts from the vault."""
```

`csm_core/brand_memory/model.py`:
```python
"""BrandModelMemory — resolver output (in-memory, never persisted)."""
from __future__ import annotations
from pydantic import BaseModel, Field


class SpecValue(BaseModel):
    field: str                       # 参数名，如 "吸力(AW)"
    raw: str                         # 原始单元格文本，如 "15/25/40min"
    numbers: list[float] = Field(default_factory=list)  # 解析出的数值（空=占位/非数值）
    unit: str = ""                   # 单位，如 "min" / "Pa"
    is_approx: bool = False          # 含 约/近/≤/起 等近似标记


class BrandModelMemory(BaseModel):
    brand: str
    model: str
    category: str                    # 品类，如 "吸尘器"
    role: str                        # "主推" | "竞品"
    specs: dict[str, SpecValue] = Field(default_factory=dict)
    certs: list[str] = Field(default_factory=list)
    scripts: dict[str, list[str]] = Field(default_factory=dict)  # 维度 -> 变体
    endorsements: list[str] = Field(default_factory=list)        # 品牌级
    intro: list[str] = Field(default_factory=list)
    tests: dict[str, str] = Field(default_factory=dict)          # 测试项 -> 结果
    coverage: dict = Field(default_factory=dict)                 # 缺口体检
```

`tests/core/brand_memory/__init__.py`: （空文件）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/brand_memory/test_model.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add csm_core/brand_memory/__init__.py csm_core/brand_memory/model.py tests/core/brand_memory/__init__.py tests/core/brand_memory/test_model.py
git commit -m "feat(brand_memory): 加 SpecValue/BrandModelMemory 数据模型"
```

---

### Task 2: 文件名 → (品牌, 型号) + 别名

**Files:**
- Create: `csm_core/brand_memory/identity.py`
- Test: `tests/core/brand_memory/test_identity.py`

- [ ] **Step 1: 写失败测试**

`tests/core/brand_memory/test_identity.py`:
```python
from csm_core.brand_memory.identity import canonical_brand, parse_brand_model

ALIASES = {
    "CEWEY": ["CEWEY", "希喂"],
    "小米": ["小米", "米家"],
    "戴森": ["戴森"],
    "友望": ["友望"],
    "追觅": ["追觅"],
}


def test_canonical_brand_folds_alias():
    assert canonical_brand("米家", ALIASES) == "小米"
    assert canonical_brand("希喂", ALIASES) == "CEWEY"
    assert canonical_brand("未知", ALIASES) == "未知"


def test_parse_brand_model_strips_suffix_and_brand():
    assert parse_brand_model("CEWEYDS18-产品参数", ALIASES) == ("CEWEY", "DS18")
    assert parse_brand_model("戴森V12-产品参数", ALIASES) == ("戴森", "V12")
    assert parse_brand_model("米家3C-产品参数", ALIASES) == ("小米", "3C")
    assert parse_brand_model("友望大橘Ultra-产品参数", ALIASES) == ("友望", "大橘Ultra")


def test_parse_brand_model_unparseable_returns_none():
    assert parse_brand_model("某杂牌X9-产品参数", ALIASES) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/brand_memory/test_identity.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: 写实现**

`csm_core/brand_memory/identity.py`:
```python
"""Resolve (品牌, 型号) from a 产品参数 filename stem + brand-alias folding.

The real vault has no 品牌/型号 frontmatter (only the filename), and brand
aliases differ between folder names and frontmatter (希喂 vs CEWEY). This
module is the single place that (a) folds an alias to its canonical brand
and (b) splits a stem like ``CEWEYDS18-产品参数`` into ("CEWEY", "DS18").
Seed alias table; Phase 0 taxonomy extends it.
"""
from __future__ import annotations

# canonical 品牌 -> 所有写法（含 canonical 自身）。
BRAND_ALIASES: dict[str, list[str]] = {
    "CEWEY": ["CEWEY", "希喂"],
    "小米": ["小米", "米家"],
    "戴森": ["戴森"],
    "追觅": ["追觅"],
    "美的": ["美的"],
    "海尔": ["海尔"],
    "石头": ["石头"],
    "松下": ["松下"],
    "苏泊尔": ["苏泊尔"],
    "德尔玛": ["德尔玛"],
    "小狗": ["小狗"],
    "友望": ["友望"],
    "京造": ["京造"],
}

_STEM_SUFFIXES = ("-产品参数", "-测试结果")


def canonical_brand(name: str, aliases: dict[str, list[str]] = BRAND_ALIASES) -> str:
    """Fold any alias to its canonical brand; unknown names pass through."""
    for canon, al in aliases.items():
        if name == canon or name in al:
            return canon
    return name


def parse_brand_model(
    stem: str, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> tuple[str, str] | None:
    """Split a product-note stem into (canonical_brand, model).

    Strips a trailing ``-产品参数`` / ``-测试结果``, then matches the longest
    known brand alias prefix. Returns ``None`` when no known brand prefixes
    the stem (caller adds it to a manual-review list).
    """
    name = stem
    for suffix in _STEM_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    flat = sorted(
        ((al, canon) for canon, als in aliases.items() for al in als),
        key=lambda t: len(t[0]), reverse=True,
    )
    for alias, canon in flat:
        if name.startswith(alias) and len(name) > len(alias):
            return canon, name[len(alias):]
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/brand_memory/test_identity.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add csm_core/brand_memory/identity.py tests/core/brand_memory/test_identity.py
git commit -m "feat(brand_memory): 文件名解析品牌/型号 + 别名归一"
```

---

### Task 3: 产品参数表 → `dict[字段, SpecValue]`

**Files:**
- Create: `csm_core/brand_memory/specs.py`
- Test: `tests/core/brand_memory/test_specs.py`

- [ ] **Step 1: 写失败测试**

`tests/core/brand_memory/test_specs.py`:
```python
from csm_core.brand_memory.specs import parse_spec_table

BODY = """
## 性能参数

| 参数 | 数值 |
|------|------|
| 吸力(AW) | 220 |
| 真空度(Pa) | 0 |
| 最低噪音（dB） | 70dB |
| 电机功率 | 未说明 |

## 续航电池

| 参数 | 数值 |
|------|------|
| 不同档位续航 | 15/25/40min |

## 基础信息

| 参数 | 数值 |
|------|------|
| 认证检测 | CE、FCC、CB、3C |
"""


def test_parses_numeric_with_unit():
    specs = parse_spec_table(BODY)
    assert specs["吸力(AW)"].numbers == [220.0]
    assert specs["最低噪音（dB）"].numbers == [70.0]
    assert specs["最低噪音（dB）"].unit == "dB"


def test_range_value_yields_multiple_numbers():
    specs = parse_spec_table(BODY)
    assert specs["不同档位续航"].numbers == [15.0, 25.0, 40.0]
    assert specs["不同档位续航"].unit == "min"


def test_placeholder_and_zero_have_no_numbers():
    specs = parse_spec_table(BODY)
    # 占位/0 仍保留字段（供缺口体检），但 numbers 为空（不进白名单）。
    assert specs["真空度(Pa)"].numbers == []
    assert specs["电机功率"].numbers == []


def test_non_numeric_cell_kept_as_raw():
    specs = parse_spec_table(BODY)
    assert specs["认证检测"].raw == "CE、FCC、CB、3C"
    assert specs["认证检测"].numbers == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/brand_memory/test_specs.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

`csm_core/brand_memory/specs.py`:
```python
"""Parse a 产品参数 note body into ``{字段: SpecValue}``.

产品参数 notes are H2 sections (## 性能参数 …) each holding a two-column
markdown table ``| 参数 | 数值 |``. We reuse the test_framework H2 splitter
then parse each table row. Placeholder cells (未说明/-/无/暂无/0) are kept
as fields (so 缺口体检 can flag them) but yield no numbers (so they never
enter the fact whitelist).
"""
from __future__ import annotations
import re
from csm_core.test_framework.section_parser import extract_brand_sections
from .model import SpecValue

_ROW_RE = re.compile(r"^\s*\|(.+?)\|(.+?)\|\s*$")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_SEP_CELL_RE = re.compile(r"^[\s\-:]+$")           # 表头分隔行 |---|---|
_APPROX = ("约", "近", "≤", "<", "＜", "≥", "＞", ">", "起", "最高", "最低")
_PLACEHOLDERS = {"", "-", "无", "未说明", "暂无", "暂无数据", "/", "0"}


def _is_placeholder(value: str) -> bool:
    return value.strip() in _PLACEHOLDERS


def _extract_unit(value: str) -> str:
    # 去掉数字、分隔符、近似号，剩下的尾部当单位（启发式，够用即可）。
    tail = _NUM_RE.sub("", value)
    tail = re.sub(r"[\s/、,，~\-±:：()（）]", "", tail)
    for mark in _APPROX:
        tail = tail.replace(mark, "")
    return tail.strip()


def parse_spec_table(body: str) -> dict[str, SpecValue]:
    specs: dict[str, SpecValue] = {}
    for section in extract_brand_sections(body):
        for line in section.body.splitlines():
            m = _ROW_RE.match(line)
            if not m:
                continue
            field, value = m.group(1).strip(), m.group(2).strip()
            if not field or field == "参数" or _SEP_CELL_RE.match(field):
                continue
            if _is_placeholder(value):
                specs[field] = SpecValue(field=field, raw=value)
                continue
            numbers = [float(n) for n in _NUM_RE.findall(value)]
            specs[field] = SpecValue(
                field=field, raw=value, numbers=numbers,
                unit=_extract_unit(value),
                is_approx=any(mark in value for mark in _APPROX),
            )
    return specs
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/brand_memory/test_specs.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add csm_core/brand_memory/specs.py tests/core/brand_memory/test_specs.py
git commit -m "feat(brand_memory): 产品参数表解析为 SpecValue（占位/区间/单位处理）"
```

---

### Task 4: Resolver — VaultIndex + (品牌,型号) → BrandModelMemory

**Files:**
- Create: `csm_core/brand_memory/resolver.py`
- Modify: `csm_core/brand_memory/__init__.py`（导出 `resolve_memory`）
- Test: `tests/core/brand_memory/test_resolver.py`

- [ ] **Step 1: 写失败测试**（用 `tmp_path` 写真实笔记 + `scan_vault`，走真实解析路径）

`tests/core/brand_memory/test_resolver.py`:
```python
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.brand_memory.resolver import resolve_memory

VAULT = "营销资料库/产品模块/吸尘器"


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _make_vault(root: Path) -> None:
    _write(root / VAULT / "产品参数/CEWEYDS18-产品参数.md",
           "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
           "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 220 |\n\n"
           "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 认证检测 | CE、FCC |\n")
    _write(root / VAULT / "希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md",
           "---\n产品: 吸尘器\n素材类型: 动力系统\n核心关键词: x\n---\n"
           "① 220AW强劲吸力。\n\n② 12万转电机。\n")
    _write(root / VAULT / "希喂推荐内容/品牌背书/吸尘器-CEWEY品牌背书-品牌定位①.md",
           "---\n产品: 吸尘器\n素材类型: 品牌定位\n核心关键词: x\n---\n"
           "① CEWEY 是技术型品牌。\n")
    _write(root / VAULT / "竞品推荐内容/竞品-戴森V12.md",
           "---\n产品: 吸尘器\n素材类型: 产品推荐理由\n核心关键词: x\n---\n"
           "① 戴森 V12 高端机型。\n")


def test_resolves_own_brand_deep(tmp_path):
    _make_vault(tmp_path)
    index = scan_vault(tmp_path)
    mem = resolve_memory("CEWEY", "DS18", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.role == "主推"
    assert mem.specs["吸力(AW)"].numbers == [220.0]
    assert mem.certs == ["CE", "FCC"]
    assert mem.scripts["动力系统"] == ["220AW强劲吸力。", "12万转电机。"]
    assert any("技术型品牌" in e for e in mem.endorsements)
    assert mem.coverage["has_tests"] is False


def test_resolves_competitor_shallow(tmp_path):
    _make_vault(tmp_path)
    index = scan_vault(tmp_path)
    mem = resolve_memory("戴森", "V12", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.role == "竞品"
    assert any("V12" in i for i in mem.intro)
    assert mem.scripts == {}   # 竞品无技术话术
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/brand_memory/test_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: csm_core.brand_memory.resolver`

- [ ] **Step 3: 写实现**

`csm_core/brand_memory/resolver.py`:
```python
"""Assemble a BrandModelMemory for a (品牌, 型号) from an existing VaultIndex.

Mapping (see spec §2.2): specs/certs ← 产品参数；scripts ← <品牌>推荐内容/
{核心,次要}技术（维度取文件夹+文件名，不依赖 素材类型）；endorsements ←
品牌背书；intro ← 竞品推荐内容/希喂推荐内容；tests ← 品牌产品测试结果。
"""
from __future__ import annotations
import re
from csm_core.vault.scanner import VaultIndex
from csm_core.vault.note_parser import ParsedNote
from csm_core.test_framework.section_parser import extract_brand_sections
from .identity import BRAND_ALIASES, canonical_brand, parse_brand_model
from .specs import parse_spec_table
from .model import BrandModelMemory

_CIRCLED = "".join(chr(c) for c in range(0x2460, 0x2474))  # ①..⑳
_DIM_RE = re.compile(r"(?:核心技术|次要技术)-(.+)$")
_CERT_SPLIT_RE = re.compile(r"[、,，/]+")


def _rel_parts(note: ParsedNote, index: VaultIndex) -> tuple[str, ...]:
    try:
        return note.path.relative_to(index.root).parts
    except ValueError:
        return ()


def _dimension_from_stem(stem: str) -> str | None:
    m = _DIM_RE.search(stem)
    if not m:
        return None
    return m.group(1).rstrip(_CIRCLED).strip() or None


def _brand_folder_aliases(brand: str, aliases: dict[str, list[str]]) -> list[str]:
    return aliases.get(brand, [brand])


def resolve_memory(
    brand: str, model: str, category: str, index: VaultIndex,
    *, own_brands: set[str], aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> BrandModelMemory:
    brand = canonical_brand(brand, aliases)
    role = "主推" if brand in own_brands else "竞品"
    brand_writings = {f"{a}推荐内容" for a in _brand_folder_aliases(brand, aliases)}

    specs: dict = {}
    certs: list[str] = []
    scripts: dict[str, list[str]] = {}
    endorsements: list[str] = []
    intro: list[str] = []
    tests: dict[str, str] = {}

    for note in index.notes:
        parts = _rel_parts(note, index)
        if not parts:
            continue
        # 产品参数：按文件名解析出的 (品牌,型号) 命中
        if "产品参数" in parts:
            bm = parse_brand_model(note.id, aliases)
            if bm == (brand, model):
                specs = parse_spec_table(note.raw_body)
                certs = _certs_from_specs(specs)
            continue
        # 该品牌的「<品牌>推荐内容」子树
        if brand_writings & set(parts):
            if "品牌背书" in parts:
                endorsements.extend(note.variants or [note.raw_body])
            else:
                dim = _dimension_from_stem(note.id)
                if dim:
                    scripts.setdefault(dim, []).extend(note.variants or [note.raw_body])
            continue
        # 竞品介绍
        if "竞品推荐内容" in parts and model in note.id:
            intro.extend(note.variants or [note.raw_body])
            continue
        # 品牌产品测试结果
        if "品牌产品测试结果" in parts and model in note.id:
            for sec in extract_brand_sections(note.raw_body):
                tests[sec.normalized_title] = sec.body

    coverage = {
        "has_specs": bool(specs),
        "has_tests": bool(tests),
        "script_dimensions": len(scripts),
        "empty_spec_fields": [k for k, v in specs.items() if not v.numbers and not v.raw.strip("-/")],
    }
    return BrandModelMemory(
        brand=brand, model=model, category=category, role=role,
        specs=specs, certs=certs, scripts=scripts,
        endorsements=endorsements, intro=intro, tests=tests, coverage=coverage,
    )


def _certs_from_specs(specs: dict) -> list[str]:
    cell = next((v.raw for k, v in specs.items() if "认证" in k), "")
    return [c.strip() for c in _CERT_SPLIT_RE.split(cell) if c.strip()]
```

修改 `csm_core/brand_memory/__init__.py`:
```python
"""Brand/model memory — resolve structured per-model facts from the vault."""
from .model import BrandModelMemory, SpecValue
from .resolver import resolve_memory

__all__ = ["BrandModelMemory", "SpecValue", "resolve_memory"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/brand_memory/test_resolver.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add csm_core/brand_memory/resolver.py csm_core/brand_memory/__init__.py tests/core/brand_memory/test_resolver.py
git commit -m "feat(brand_memory): resolver 从 VaultIndex 组装型号记忆（主推深/竞品浅）"
```

---

### Task 5: 事实白名单构建（注入源 ∪ specs ∪ 认证）

**Files:**
- Create: `csm_core/brand_memory/whitelist.py`
- Test: `tests/core/brand_memory/test_whitelist.py`

- [ ] **Step 1: 写失败测试**

`tests/core/brand_memory/test_whitelist.py`:
```python
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.brand_memory.whitelist import build_fact_whitelist, normalize_numbers


def test_normalize_handles_wan_and_decimal():
    assert normalize_numbers("12万转，35kPa，1.2L") == {120000.0, 35.0, 1.2}


def test_whitelist_unions_specs_and_injected_text():
    mem = BrandModelMemory(
        brand="CEWEY", model="DS18", category="吸尘器", role="主推",
        specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])},
        certs=["CE", "FCC"],
    )
    wl = build_fact_whitelist(mem, injected_texts=["实测气流 1700L/min，22项黑科技"])
    assert 220.0 in wl.numbers          # 来自 specs
    assert 1700.0 in wl.numbers         # 来自注入话术
    assert 22.0 in wl.numbers
    assert "CE" in wl.certs


def test_out_of_whitelist_number_detected():
    mem = BrandModelMemory(brand="CEWEY", model="DS18", category="吸尘器", role="主推",
                           specs={"吸力(AW)": SpecValue(field="吸力(AW)", raw="220", numbers=[220.0])})
    wl = build_fact_whitelist(mem, injected_texts=[])
    # 250 既不在 specs 也不在注入源 → 越界
    assert 250.0 not in wl.numbers
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/core/brand_memory/test_whitelist.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

`csm_core/brand_memory/whitelist.py`:
```python
"""Build the per-generation fact whitelist used by the export-time factcheck.

白名单 = 本次注入源里出现的数字 ∪ 该型号 specs 数值 ∪ 认证。判据：成稿
里出现的数字若不在白名单 = LLM 凭空引入。这里只构建白名单；匹配/拦截在
Plan 3 的 csm_core/factcheck/。
"""
from __future__ import annotations
import re
from pydantic import BaseModel, Field
from .model import BrandModelMemory

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*万")


class FactWhitelist(BaseModel):
    numbers: set[float] = Field(default_factory=set)
    certs: set[str] = Field(default_factory=set)


def normalize_numbers(text: str) -> set[float]:
    """Extract numeric facts, expanding ``N万`` to N*10000."""
    out: set[float] = set()
    consumed: list[tuple[int, int]] = []
    for m in _WAN_RE.finditer(text):
        out.add(float(m.group(1)) * 10000)
        consumed.append(m.span())
    for m in _NUM_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        out.add(float(m.group()))
    return out


def build_fact_whitelist(
    memory: BrandModelMemory, injected_texts: list[str],
) -> FactWhitelist:
    numbers: set[float] = set()
    for sv in memory.specs.values():
        numbers.update(sv.numbers)
    for text in injected_texts:
        numbers.update(normalize_numbers(text))
    return FactWhitelist(numbers=numbers, certs=set(memory.certs))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/core/brand_memory/test_whitelist.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 跑整包 + 提交**

Run: `pytest tests/core/brand_memory/ -v`
Expected: PASS（全部）

```bash
git add csm_core/brand_memory/whitelist.py tests/core/brand_memory/test_whitelist.py
git commit -m "feat(brand_memory): 事实白名单构建（注入源∪specs∪认证 + 万/小数归一）"
```

---

### Task 6: 真实 vault 冒烟测试（集成，标记 integration）

**Files:**
- Test: `tests/core/brand_memory/test_real_vault_smoke.py`

- [ ] **Step 1: 写测试**（默认跳过；仅在开发机存在真实 vault 时手动跑，验证解析层吃得下真实数据）

```python
import os
import pytest
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.brand_memory.resolver import resolve_memory

VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_cewey_ds18_resolves_from_real_vault():
    index = scan_vault(VAULT)
    mem = resolve_memory("CEWEY", "DS18", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.role == "主推"
    assert mem.specs.get("吸力(AW)") and mem.specs["吸力(AW)"].numbers == [220.0]
    assert mem.scripts, "希喂推荐内容 话术应被解析到"
    assert mem.endorsements, "品牌背书应被解析到"
```

- [ ] **Step 2: 手动跑一次（开发机）**

Run: `pytest tests/core/brand_memory/test_real_vault_smoke.py -v -m integration`
Expected: PASS（真实 vault 在本机时）；否则 SKIPPED。

- [ ] **Step 3: 提交**

```bash
git add tests/core/brand_memory/test_real_vault_smoke.py
git commit -m "test(brand_memory): 真实 vault 解析冒烟测试（integration，默认跳过）"
```

---

## Plan 1 之后：Plans 2–5 范围（合并 Plan 1 后逐个细化）

- **Plan 2 增强脚本 + registry**：`scripts/backfill_brand_model.py`（遍历 `产品参数`/`核心·次要技术`/`品牌产品测试结果`，用 Plan1 `parse_brand_model` 回填 `品牌/型号`，输出 diff + 无法解析清单，副本先跑）；改 `csm_core/vault/brand_registry.py` 用别名归一 + 回填后非空；更新 vault `CLAUDE.md §3`。
- **Plan 3 注入 + 门禁**：`csm_core/llm/prompts.py` 加 `brand_facts`；`generate_service._run_job` 注入步 + token 预算（每维度 ≤N 变体）；`csm_core/factcheck/`（抽取/归一/匹配/多型号槽位作用域）；导出前门禁 + 会话级放行；feature flags `brand_memory.inject` / `brand_memory.factcheck`。
- **Plan 4 skill 解耦**：拆 `家电科普博主.md` → persona / humanize / 合并；`role` frontmatter；`skills_service` + `SkillEditView` 暴露 role；模板 `default_skill_id` 迁移到合并 skill。
- **Plan 5 UI**：`LeftNav.NAV_TOP` 加「素材库」；`routes/brand_memory.py` + `brand_memory_service.py`（list / detail）；前端「品牌型号」tab（只读 + 缺口体检 + 注入预览）+ store；中英双语。

---

## Self-Review（对照 spec）

- **Spec 覆盖**：spec §2.1 模型→Task1；§2.2 映射(维度取文件夹+文件名、intro、认证)→Task3/4；§2.3 动态白名单→Task5；§3 增强脚本→Plan2；§4 注入+门禁→Plan3；§5 skill→Plan4；§6 UI→Plan5；§10 测试(集成)→Task6。✅ Plan 1 范围内无遗漏。
- **占位符扫描**：无 TBD/TODO；每个 code step 含完整代码与可跑命令/期望输出。✅
- **类型一致性**：`SpecValue`/`BrandModelMemory` 字段（numbers/certs/scripts/coverage）在 Task1 定义，Task3/4/5 一致引用；`parse_brand_model` 签名 Task2 定义、Task4 一致调用；`resolve_memory(..., own_brands=...)` 关键字参数 Task4 与 Task6 一致。✅
