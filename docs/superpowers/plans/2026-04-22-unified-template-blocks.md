# 统一模板块模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `Framework` 层合并进 `Template`——模板的 `blocks` 数组既是内容声明又是文章骨架；引入 `hero_brand` + `competitor_pool` 区域标记完成主品/竞品推荐列表；删除整个 framework 层；GUI 的"模块"标签页改为块树编辑器。

**Architecture:**
- `Template` 不再持有 `slots` / `render_order` / `default_framework`，改为 `blocks: list[Block]`，`Block` 是一个按 `kind` 判别的 tagged union（`paragraph` / `heading` / `numbered_list` / `hero_brand` / `competitor_pool` / `literal`）。
- `assembler` 线性遍历 blocks，按 kind 分派；采样类块（paragraph / numbered_list / competitor_pool）产出 `BlockResult`，结构类块（heading / literal / hero_brand）产出字面量或标记节点。
- `renderer` 做"区域收编"：`hero_brand` 到下一个 `competitor_pool`（或块尾）之间的 paragraph / numbered_list 输出被聚合为主品"推荐理由"正文；`competitor_pool` 沿用 `hero_brand.number_style` 连续编号。

**Tech Stack:** Python 3.14, Pydantic v2, PyQt6 + qfluentwidgets, pytest + pytest-qt.

**Spec:** [docs/superpowers/specs/2026-04-22-unified-template-blocks-design.md](../specs/2026-04-22-unified-template-blocks-design.md)

**Files to touch / create / delete**

Create:
- `scripts/migrate_framework_to_blocks.py`
- `tests/core/template/test_block_schema.py`
- `tests/core/assembler/test_block_sampler.py`
- `tests/core/assembler/test_block_renderer.py`
- `tests/scripts/test_migrate_framework_to_blocks.py`

Modify:
- `csm_core/template/schema.py`（核心 schema 重写）
- `csm_core/template/loader.py`（保持接口，适配新 schema）
- `csm_core/assembler/plan.py`（重命名 `SlotAssignment` → `BlockResult`，新增 block kind 字段）
- `csm_core/assembler/sampler.py`（`sample_slot` → `sample_block`，按 kind 分派）
- `csm_core/assembler/constraints.py`（`assemble_plan` 遍历 blocks）
- `csm_core/assembler/render.py`（全新 compose_draft，区域收编 + 编号）
- `csm_core/pipeline.py`（移除 framework 相关参数与分支）
- `csm_gui/widgets/slot_tree_widget.py`（扩展为块树，加 kind 选择器）
- `csm_gui/pages/template_manager_page.py`（移除"框架"标签页）
- `csm_gui/widgets/template_editor_panel.py`（适配新 schema）
- `csm_gui/forms/generation_form.py`（移除 framework 下拉）
- `csm_gui/controllers/article_controller.py`（移除 framework_id）
- 相关老测试（删除或改造）

Delete:
- `csm_core/framework/` 整目录（`__init__.py`, `schema.py`, `loader.py`, `renderer.py`, `trace.py`）
- `csm_gui/widgets/framework_list_panel.py`
- `csm_gui/widgets/framework_editor_panel.py`
- `csm_gui/widgets/framework_block_card.py`
- `tests/**/test_framework_*.py`（framework 相关单测）
- `frameworks/` 目录（迁移后）

---

## Phase 1 — 新 Schema

### Task 1: 新 Block 类型与 Template schema

**Files:**
- Modify: `csm_core/template/schema.py`（完全重写）
- Test: `tests/core/template/test_block_schema.py`（新建）

- [ ] **Step 1: Write the failing schema tests**

```python
# tests/core/template/test_block_schema.py
import pytest
from csm_core.template.schema import Template


def _min_tpl(**blocks):
    return {
        "id": "t1", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": list(blocks.get("blocks", [])),
    }


def test_paragraph_block_roundtrips():
    d = _min_tpl(blocks=[{
        "kind": "paragraph", "id": "s1", "label": "痛点",
        "source": {"type": "notes_query", "module": "吸尘器/痛点"},
        "pick_notes": 1, "pick_variants_per_note": 1,
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].kind == "paragraph"
    assert tpl.blocks[0].id == "s1"


def test_heading_block_requires_text():
    d = _min_tpl(blocks=[{"kind": "heading", "id": "h1", "level": 2}])
    with pytest.raises(Exception):
        Template.model_validate(d)


def test_numbered_list_defaults():
    d = _min_tpl(blocks=[{
        "kind": "numbered_list", "id": "n1", "label": "科普",
        "source": {"type": "notes_query", "module": "吸尘器/科普"},
    }])
    tpl = Template.model_validate(d)
    b = tpl.blocks[0]
    assert b.number_style == "1."
    assert b.pick_notes == 3
    assert b.item_separator == "\n\n"


def test_hero_brand_literal_title():
    d = _min_tpl(blocks=[{
        "kind": "hero_brand", "id": "h1",
        "title": "CEWEY DS18", "number_style": "1.",
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].title == "CEWEY DS18"
    assert tpl.blocks[0].reason_label == "推荐理由："


def test_competitor_pool_source_required():
    d = _min_tpl(blocks=[{
        "kind": "competitor_pool", "id": "c1",
        "source": {"type": "notes_query", "module": "吸尘器/竞品"},
        "pick_notes": {"random_between": [2, 2]},
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].pick_notes.random_between == [2, 2]


def test_literal_block_roundtrips():
    d = _min_tpl(blocks=[{"kind": "literal", "id": "l1", "text": "完。"}])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].text == "完。"


def test_paragraph_children_flat_list():
    d = _min_tpl(blocks=[{
        "kind": "paragraph", "id": "s6", "label": "品牌背书",
        "source": {"type": "notes_query", "module": "希喂/品牌背书"},
        "children": [
            {
                "kind": "paragraph", "id": "s6_1", "label": "海外口碑",
                "source": {"type": "notes_query", "module": "希喂/品牌背书"},
            }
        ],
    }])
    tpl = Template.model_validate(d)
    assert tpl.blocks[0].children[0].id == "s6_1"


def test_template_rejects_unknown_kind():
    d = _min_tpl(blocks=[{"kind": "bogus", "id": "x"}])
    with pytest.raises(Exception):
        Template.model_validate(d)


def test_blocks_must_be_nonempty():
    with pytest.raises(Exception):
        Template.model_validate(_min_tpl(blocks=[]))


def test_duplicate_block_ids_rejected():
    d = _min_tpl(blocks=[
        {"kind": "literal", "id": "x", "text": "a"},
        {"kind": "literal", "id": "x", "text": "b"},
    ])
    with pytest.raises(ValueError, match="duplicate"):
        Template.model_validate(d)
```

- [ ] **Step 2: Run to confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/core/template/test_block_schema.py -v
```

Expected: all FAIL (schema doesn't yet have new types).

- [ ] **Step 3: Rewrite `csm_core/template/schema.py`**

```python
"""Pydantic models for the unified block-based template DSL."""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, Field, model_validator


# ── Sources (unchanged) ───────────────────────────────────────────────
class NotesQuerySource(BaseModel):
    type: Literal["notes_query"] = "notes_query"
    module: str
    filter: dict[str, Any] = Field(default_factory=dict)


class BrandFixedSource(BaseModel):
    type: Literal["brand_fixed"] = "brand_fixed"
    brand: str
    model: str


class BrandPoolSource(BaseModel):
    type: Literal["brand_pool"] = "brand_pool"
    exclude_brands: list[str] = Field(default_factory=list)


class TestResultsAlignedSource(BaseModel):
    __test__ = False
    type: Literal["test_results_aligned"] = "test_results_aligned"
    follow_slot: str
    module: str


SourceT = Annotated[
    Union[NotesQuerySource, BrandFixedSource, BrandPoolSource, TestResultsAlignedSource],
    Field(discriminator="type"),
]


class PickCountSpec(BaseModel):
    random_between: list[int] | None = None
    user_configurable: bool = False
    default: int | None = None
    range: list[int] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.random_between and len(self.random_between) != 2:
            raise ValueError("random_between must be [min, max]")
        if self.user_configurable and (self.default is None or self.range is None):
            raise ValueError("user_configurable requires default + range")
        return self


PickNotes = Union[int, PickCountSpec]
NumberStyle = Literal["1.", "一、", "none"]


# ── Block types ───────────────────────────────────────────────────────
class ParagraphBlock(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    id: str
    label: str = ""
    source: SourceT
    pick_notes: PickNotes = 1
    pick_variants_per_note: int = 1
    constraints: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    children: list["ParagraphBlock"] = Field(default_factory=list)


class HeadingBlock(BaseModel):
    kind: Literal["heading"] = "heading"
    id: str
    level: Literal[1, 2, 3] = 2
    index: str = ""
    text: str = Field(min_length=1)


class NumberedListBlock(BaseModel):
    kind: Literal["numbered_list"] = "numbered_list"
    id: str
    label: str = ""
    source: SourceT
    pick_notes: PickNotes = 3
    number_style: NumberStyle = "1."
    item_separator: str = "\n\n"


class HeroBrandBlock(BaseModel):
    kind: Literal["hero_brand"] = "hero_brand"
    id: str
    title: str = Field(min_length=1)
    reason_label: str = "推荐理由："
    number_style: NumberStyle = "1."


class CompetitorPoolBlock(BaseModel):
    kind: Literal["competitor_pool"] = "competitor_pool"
    id: str
    source: SourceT
    pick_notes: PickNotes = 2
    reason_label: str = "推荐理由："


class LiteralBlock(BaseModel):
    kind: Literal["literal"] = "literal"
    id: str
    text: str = Field(min_length=1)


Block = Annotated[
    Union[
        ParagraphBlock, HeadingBlock, NumberedListBlock,
        HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    ],
    Field(discriminator="kind"),
]


# ── Template ──────────────────────────────────────────────────────────
class SEODefaults(BaseModel):
    target_word_count: list[int] = Field(default_factory=lambda: [1500, 2000])
    keyword_density: list[int] = Field(default_factory=lambda: [5, 8])
    long_tail_keywords: list[str] = Field(default_factory=list)
    tone: str = "小红书笔记体"
    force_h2: bool = True


class Template(BaseModel):
    id: str
    name: str
    product: str
    version: int = 1
    system_prompt_default: str = ""
    seo_defaults: SEODefaults = Field(default_factory=SEODefaults)
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_structure(self):
        ids: set[str] = set()

        def walk(items: list) -> None:
            for b in items:
                if b.id in ids:
                    raise ValueError(f"duplicate block id '{b.id}'")
                ids.add(b.id)
                if isinstance(b, ParagraphBlock):
                    walk(b.children)

        walk(self.blocks)

        # depends_on must reference a known (flat or nested) paragraph id
        def paragraph_ids(items: list) -> set[str]:
            out: set[str] = set()
            for b in items:
                if isinstance(b, ParagraphBlock):
                    out.add(b.id)
                    out |= paragraph_ids(b.children)
            return out

        known = paragraph_ids(self.blocks)

        def check_deps(items: list) -> None:
            for b in items:
                if isinstance(b, ParagraphBlock):
                    for dep in b.depends_on:
                        if dep not in known:
                            raise ValueError(
                                f"block '{b.id}' depends_on unknown id '{dep}'"
                            )
                    check_deps(b.children)

        check_deps(self.blocks)
        return self


# backwards-compat alias: nothing in the new world references Slot, but
# some external tooling (legacy test fixtures) may import it briefly
# during migration. The migration script deletes these refs.
```

- [ ] **Step 4: Run tests again**

```bash
.venv/Scripts/python.exe -m pytest tests/core/template/test_block_schema.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/template/schema.py tests/core/template/test_block_schema.py
git commit -m "feat(schema): unified block model replacing Slot+render_order

Template.blocks is now a tagged union of
paragraph/heading/numbered_list/hero_brand/competitor_pool/literal.
Validator enforces unique ids (across nested paragraph children)
and valid depends_on references."
```

---

### Task 2: Loader 保持接口，删除旧 Slot 测试

**Files:**
- Modify: `csm_core/template/loader.py`（无改动，但运行旧测试确认 loader 仍通过）
- Modify: `templates/daogou-changjing-renqun.json`（先不动，留给 Task 13 迁移脚本）
- Delete / rewrite: `tests/core/template/test_schema.py`（旧 Slot 测试）
- Modify: `tests/core/template/test_loader.py`（改为新 schema fixture）

- [ ] **Step 1: Locate and remove legacy slot-based tests**

```bash
.venv/Scripts/python.exe -m pytest tests/core/template/ --collect-only 2>&1 | head -50
```

- [ ] **Step 2: Delete `tests/core/template/test_schema.py` if it exists (its coverage is now in `test_block_schema.py`)**

```bash
git rm tests/core/template/test_schema.py 2>/dev/null || true
```

- [ ] **Step 3: Update `tests/core/template/test_loader.py`** — replace its fixture with the new block schema. Content:

```python
import json
from pathlib import Path
from csm_core.template.loader import load_template, save_template, list_templates


def _fixture_dict():
    return {
        "id": "t1", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": [
            {"kind": "literal", "id": "l1", "text": "hello"},
        ],
    }


def test_load_and_save_roundtrip(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_fixture_dict()), encoding="utf-8")
    tpl = load_template(p)
    assert tpl.id == "t1"
    assert tpl.blocks[0].kind == "literal"
    out = tmp_path / "out.json"
    save_template(tpl, out)
    round = load_template(out)
    assert round.id == tpl.id


def test_list_templates_returns_display_names(tmp_path):
    d = tmp_path / "tpls"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({**_fixture_dict(), "name": "第二"}), encoding="utf-8")
    (d / "b.json").write_text(json.dumps({**_fixture_dict(), "name": "第一"}), encoding="utf-8")
    items = list_templates(d)
    assert [n for n, _ in items] == ["第一", "第二"]
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/core/template/ -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A tests/core/template/
git commit -m "test(template): update loader tests to new block schema"
```

---

## Phase 2 — Assembler（采样阶段）

### Task 3: `BlockResult` 在 plan.py

**Files:**
- Modify: `csm_core/assembler/plan.py`

- [ ] **Step 1: Write failing test** — `tests/core/assembler/test_plan.py`

```python
import json
from csm_core.assembler.plan import (
    PickedVariant, BlockResult, AssemblyPlan,
)


def test_block_result_literal_roundtrip():
    br = BlockResult(block_id="l1", kind="literal", text="hello")
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0, results=[br])
    reparsed = AssemblyPlan.from_json(plan.to_json())
    assert reparsed.results[0].text == "hello"


def test_block_result_paragraph_with_picks():
    pv = PickedVariant(note_id="n1", variant_index=0, text="abc")
    br = BlockResult(block_id="s1", kind="paragraph", picks=[pv])
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0, results=[br])
    found = plan.get_result("s1")
    assert found is not None and found.picks[0].text == "abc"
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/test_plan.py -v
```

- [ ] **Step 3: Rewrite `csm_core/assembler/plan.py`**

```python
"""AssemblyPlan — serializable result of block-level sampling."""
from __future__ import annotations
import json
from typing import Any, Literal
from pydantic import BaseModel, Field


class PickedVariant(BaseModel):
    note_id: str
    variant_index: int
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)


BlockKind = Literal[
    "paragraph", "heading", "numbered_list",
    "hero_brand", "competitor_pool", "literal",
]


class BlockResult(BaseModel):
    """Sampler output for one block.

    - paragraph / numbered_list: populated ``picks`` from vault sampling.
    - competitor_pool: ``picks`` where each pick's ``meta['title']`` holds
      the competitor title (from 型号 frontmatter) and ``text`` is the chosen
      candidate reason.
    - heading / literal / hero_brand: ``text`` holds the literal rendered
      string (``text`` for heading, ``title`` for hero_brand, raw ``text``
      for literal). ``picks`` is empty.
    - The block's own meta (number_style, reason_label, level, index) is
      copied into ``meta`` so the renderer doesn't need the original Block.
    """
    block_id: str
    kind: BlockKind
    picks: list[PickedVariant] = Field(default_factory=list)
    text: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    # Nested results from ParagraphBlock.children, preserved in order.
    children: list["BlockResult"] = Field(default_factory=list)


class AssemblyPlan(BaseModel):
    keyword: str
    template_id: str
    seed: int
    results: list[BlockResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, payload: str) -> "AssemblyPlan":
        return cls.model_validate(json.loads(payload))

    def get_result(self, block_id: str) -> BlockResult | None:
        def search(items: list[BlockResult]) -> BlockResult | None:
            for r in items:
                if r.block_id == block_id:
                    return r
                found = search(r.children)
                if found is not None:
                    return found
            return None
        return search(self.results)
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/test_plan.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/assembler/plan.py tests/core/assembler/test_plan.py
git commit -m "feat(assembler): BlockResult replaces SlotAssignment

Tagged by kind; carries picks for sample-based kinds and literal
text for heading/literal/hero_brand. Children preserve paragraph
sub-variant hierarchy."
```

---

### Task 4: 新 sampler — `sample_block`

**Files:**
- Modify: `csm_core/assembler/sampler.py`
- Test: `tests/core/assembler/test_block_sampler.py`（新建）

- [ ] **Step 1: Write failing tests**

```python
# tests/core/assembler/test_block_sampler.py
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.assembler.sampler import sample_block
from csm_core.template.schema import (
    ParagraphBlock, HeadingBlock, NumberedListBlock,
    HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    NotesQuerySource,
)


def _write(vault: Path, rel: str, frontmatter: dict, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    p.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")


def test_sample_heading_returns_text_block_result(tmp_path):
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = HeadingBlock(id="h1", level=2, index="一", text="{keyword}怎么选")
    br = sample_block(blk, idx, reg, seed=0, user_config={})
    assert br.kind == "heading"
    assert br.text == "{keyword}怎么选"
    assert br.meta == {"level": 2, "index": "一"}
    assert br.picks == []


def test_sample_literal(tmp_path):
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    br = sample_block(LiteralBlock(id="l1", text="完。"), idx, reg, seed=0, user_config={})
    assert br.kind == "literal" and br.text == "完。"


def test_sample_hero_brand(tmp_path):
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    hb = HeroBrandBlock(id="h", title="CEWEY DS18", number_style="1.")
    br = sample_block(hb, idx, reg, seed=0, user_config={})
    assert br.kind == "hero_brand"
    assert br.text == "CEWEY DS18"
    assert br.meta["number_style"] == "1."
    assert br.meta["reason_label"] == "推荐理由："


def test_sample_paragraph_from_vault(tmp_path):
    _write(tmp_path, "A/a.md", {"产品": "吸尘器"}, "段落A文本")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = ParagraphBlock(
        id="s1", label="A",
        source=NotesQuerySource(module="A"),
        pick_notes=1, pick_variants_per_note=1,
    )
    br = sample_block(blk, idx, reg, seed=42, user_config={})
    assert br.kind == "paragraph"
    assert len(br.picks) == 1
    assert "段落A文本" in br.picks[0].text


def test_sample_numbered_list_picks_N(tmp_path):
    for i in range(5):
        _write(tmp_path, f"L/{i}.md", {"产品": "吸尘器"}, f"条目{i}")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = NumberedListBlock(
        id="n1", label="L", source=NotesQuerySource(module="L"),
        pick_notes=3, number_style="1.",
    )
    br = sample_block(blk, idx, reg, seed=1, user_config={})
    assert br.kind == "numbered_list"
    assert len(br.picks) == 3
    assert br.meta["number_style"] == "1."


def test_sample_competitor_pool_extracts_title_from_frontmatter(tmp_path):
    # file body has ①②③ so parse_note splits into variants
    body = (
        "① 第一版推荐理由文字…\n\n"
        "② 第二版推荐理由文字…\n\n"
        "③ 第三版推荐理由文字…\n"
    )
    _write(tmp_path, "竞品/戴森V8.md", {"型号": "戴森V8", "产品": "吸尘器"}, body)
    _write(tmp_path, "竞品/小狗T12.md", {"型号": "小狗T12", "产品": "吸尘器"}, body)
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = CompetitorPoolBlock(
        id="cp", source=NotesQuerySource(module="竞品"),
        pick_notes={"random_between": [2, 2]},
    )
    br = sample_block(blk, idx, reg, seed=3, user_config={})
    assert br.kind == "competitor_pool"
    assert len(br.picks) == 2
    for p in br.picks:
        assert p.meta.get("title") in ("戴森V8", "小狗T12")
        assert "推荐理由文字" in p.text


def test_competitor_pool_no_type_key_falls_back_to_stem(tmp_path):
    _write(tmp_path, "竞品/无型号的竞品.md", {"产品": "吸尘器"}, "整篇作为单一理由。")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = CompetitorPoolBlock(
        id="cp", source=NotesQuerySource(module="竞品"),
        pick_notes=1,
    )
    br = sample_block(blk, idx, reg, seed=0, user_config={})
    assert br.picks[0].meta["title"] == "无型号的竞品"
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/test_block_sampler.py -v
```

- [ ] **Step 3: Rewrite `csm_core/assembler/sampler.py`**

```python
"""Block-level sampling (dispatch by kind)."""
from __future__ import annotations
import random
from typing import Any
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..vault.note_parser import ParsedNote
from ..template.schema import (
    ParagraphBlock, HeadingBlock, NumberedListBlock,
    HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    NotesQuerySource, BrandFixedSource, BrandPoolSource,
    TestResultsAlignedSource, PickCountSpec, PickNotes,
)
from .plan import BlockResult, PickedVariant


class EmptyPoolError(Exception):
    """Raised when a sample-based block has an empty candidate pool."""


def _resolve_pick_count(
    pick_notes: PickNotes, block_id: str,
    user_config: dict[str, int], rng: random.Random,
) -> int:
    if isinstance(pick_notes, int):
        return pick_notes
    if pick_notes.random_between:
        lo, hi = pick_notes.random_between
        return rng.randint(lo, hi)
    if pick_notes.user_configurable:
        n = user_config.get(block_id, pick_notes.default or 1)
        if pick_notes.range is not None:
            lo, hi = pick_notes.range
            if not (lo <= n <= hi):
                raise ValueError(
                    f"block '{block_id}': pick count {n} out of range [{lo}, {hi}]"
                )
        return n
    return 1


def _pick_variant(note: ParsedNote, rng: random.Random) -> tuple[int, str]:
    if not note.variants:
        return 0, note.raw_body
    idx = rng.randrange(len(note.variants))
    return idx, note.variants[idx]


def _meta_for_note(note: ParsedNote) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("品牌", "型号"):
        if key in note.frontmatter:
            meta["brand" if key == "品牌" else "model"] = note.frontmatter[key]
    return meta


def _sample_notes_source(
    block_id: str, source: NotesQuerySource, constraints: list[str],
    pick_notes: PickNotes, pick_variants_per_note: int,
    index: VaultIndex, rng: random.Random,
    user_config: dict[str, int],
) -> list[PickedVariant]:
    pool = index.query(module=source.module, filters=source.filter)
    if not pool:
        raise EmptyPoolError(f"block '{block_id}': empty pool in module '{source.module}'")
    requested = _resolve_pick_count(pick_notes, block_id, user_config, rng)
    if "unique_notes" in constraints:
        actual = min(requested, len(pool))
        chosen = rng.sample(pool, actual)
    else:
        actual = requested
        chosen = [rng.choice(pool) for _ in range(requested)]
    capped = "unique_notes" in constraints and actual < requested
    picks: list[PickedVariant] = []
    for note in chosen:
        for _ in range(pick_variants_per_note):
            vi, text = _pick_variant(note, rng)
            meta = _meta_for_note(note)
            if capped:
                meta.update({"capped": True, "requested": requested, "available": actual})
            picks.append(PickedVariant(
                note_id=note.id, variant_index=vi, text=text, meta=meta,
            ))
    return picks


def sample_block(
    block, index: VaultIndex, registry: BrandRegistry,
    *, seed: int, user_config: dict[str, int],
    aligned_models: list[str] | None = None,
) -> BlockResult:
    rng = random.Random(f"{seed}-{block.id}")

    if isinstance(block, HeadingBlock):
        return BlockResult(
            block_id=block.id, kind="heading",
            text=block.text,
            meta={"level": block.level, "index": block.index},
        )

    if isinstance(block, LiteralBlock):
        return BlockResult(block_id=block.id, kind="literal", text=block.text)

    if isinstance(block, HeroBrandBlock):
        return BlockResult(
            block_id=block.id, kind="hero_brand", text=block.title,
            meta={
                "number_style": block.number_style,
                "reason_label": block.reason_label,
            },
        )

    if isinstance(block, ParagraphBlock):
        picks = _sample_source_for_block(block, index, registry, rng, user_config, aligned_models)
        # children are sampled by the caller (assemble_plan) so that
        # depends_on resolution sees their picks.
        return BlockResult(block_id=block.id, kind="paragraph", picks=picks)

    if isinstance(block, NumberedListBlock):
        assert isinstance(block.source, NotesQuerySource), \
            f"numbered_list block '{block.id}' only supports notes_query source"
        picks = _sample_notes_source(
            block.id, block.source, constraints=["unique_notes"],
            pick_notes=block.pick_notes, pick_variants_per_note=1,
            index=index, rng=rng, user_config=user_config,
        )
        return BlockResult(
            block_id=block.id, kind="numbered_list", picks=picks,
            meta={
                "number_style": block.number_style,
                "item_separator": block.item_separator,
            },
        )

    if isinstance(block, CompetitorPoolBlock):
        assert isinstance(block.source, NotesQuerySource), \
            f"competitor_pool block '{block.id}' only supports notes_query source"
        picks = _sample_notes_source(
            block.id, block.source, constraints=["unique_notes"],
            pick_notes=block.pick_notes, pick_variants_per_note=1,
            index=index, rng=rng, user_config=user_config,
        )
        # attach competitor title from frontmatter 型号 / stem fallback
        enriched: list[PickedVariant] = []
        for p in picks:
            meta = dict(p.meta)
            title = meta.get("model") or p.note_id
            meta["title"] = title
            enriched.append(p.model_copy(update={"meta": meta}))
        return BlockResult(
            block_id=block.id, kind="competitor_pool", picks=enriched,
            meta={"reason_label": block.reason_label},
        )

    raise EmptyPoolError(f"block '{block.id}': unsupported type {type(block).__name__}")


def _sample_source_for_block(
    block: ParagraphBlock, index: VaultIndex, registry: BrandRegistry,
    rng: random.Random, user_config: dict[str, int],
    aligned_models: list[str] | None,
) -> list[PickedVariant]:
    src = block.source
    if isinstance(src, NotesQuerySource):
        return _sample_notes_source(
            block.id, src, block.constraints, block.pick_notes,
            block.pick_variants_per_note, index, rng, user_config,
        )
    if isinstance(src, BrandFixedSource):
        return [PickedVariant(
            note_id=f"{src.model}-fixed", variant_index=0,
            text=f"{src.brand} {src.model}",
            meta={"brand": src.brand, "model": src.model},
        )]
    if isinstance(src, BrandPoolSource):
        candidates = [
            m for m in registry.all_models()
            if registry.brand_of(m) not in src.exclude_brands
        ]
        if not candidates:
            raise EmptyPoolError(f"block '{block.id}': brand pool empty")
        n = _resolve_pick_count(block.pick_notes, block.id, user_config, rng)
        actual = min(n, len(candidates))
        chosen = rng.sample(candidates, actual)
        capped = actual < n
        return [
            PickedVariant(
                note_id=f"{m}-brand", variant_index=0,
                text=f"{registry.brand_of(m)} {m}",
                meta={
                    "brand": registry.brand_of(m), "model": m,
                    **({"capped": True, "requested": n, "available": actual} if capped else {}),
                },
            )
            for m in chosen
        ]
    if isinstance(src, TestResultsAlignedSource):
        if aligned_models is None:
            raise EmptyPoolError(
                f"block '{block.id}': test_results_aligned requires aligned_models"
            )
        picks: list[PickedVariant] = []
        for model in aligned_models:
            matches = index.query(module=src.module, filters={"型号": model})
            note = matches[0] if matches else None
            if note is None:
                picks.append(PickedVariant(
                    note_id=f"__missing__:{model}-测试结果", variant_index=0,
                    text=f"[缺数据：{model} 测试结果]",
                    meta={"model": model, "missing": True},
                ))
            else:
                vi, text = _pick_variant(note, rng)
                picks.append(PickedVariant(
                    note_id=note.id, variant_index=vi, text=text,
                    meta={"model": model, "brand": registry.brand_of(model) or ""},
                ))
        return picks
    raise EmptyPoolError(f"block '{block.id}': unknown source {type(src).__name__}")
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/test_block_sampler.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/assembler/sampler.py tests/core/assembler/test_block_sampler.py
git commit -m "feat(assembler): block-level sampler dispatch by kind

- paragraph/numbered_list/competitor_pool sample from vault sources
- heading/literal/hero_brand produce literal text nodes
- competitor_pool enriches pick meta with 'title' from 型号 frontmatter
  (stem fallback); body ①②③ splits are handled by parse_note's
  existing variant logic so one file → N candidate reasons, random 1 picked"
```

---

### Task 5: `assemble_plan` 遍历 blocks（含 children）

**Files:**
- Modify: `csm_core/assembler/constraints.py`
- Test: `tests/core/assembler/test_constraints.py`（改造）

- [ ] **Step 1: Update/write tests** — replace slot-based fixtures with block fixtures.

```python
# tests/core/assembler/test_constraints.py (rewrite)
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.schema import Template
from csm_core.assembler.constraints import assemble_plan


def _mktpl(blocks):
    return Template.model_validate({
        "id": "t", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": blocks,
    })


def _write(vault: Path, rel: str, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n产品: 吸尘器\n---\n{body}\n", encoding="utf-8")


def test_assemble_runs_all_block_kinds(tmp_path):
    _write(tmp_path, "A/a.md", "段落 A")
    tpl = _mktpl([
        {"kind": "heading", "id": "h1", "level": 2, "text": "题"},
        {"kind": "paragraph", "id": "p1", "label": "A",
         "source": {"type": "notes_query", "module": "A"}},
        {"kind": "literal", "id": "l1", "text": "end"},
    ])
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    plan = assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={},
    )
    kinds = [r.kind for r in plan.results]
    assert kinds == ["heading", "paragraph", "literal"]
    assert plan.results[1].picks[0].text.strip() == "段落 A"


def test_paragraph_children_are_sampled_nested(tmp_path):
    _write(tmp_path, "P/parent.md", "父")
    _write(tmp_path, "P/child.md", "子")
    tpl = _mktpl([{
        "kind": "paragraph", "id": "p1", "label": "parent",
        "source": {"type": "notes_query", "module": "P"},
        "children": [{
            "kind": "paragraph", "id": "p1_1", "label": "child",
            "source": {"type": "notes_query", "module": "P"},
        }],
    }])
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    plan = assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={},
    )
    assert plan.results[0].children[0].block_id == "p1_1"
    assert plan.results[0].children[0].picks
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/test_constraints.py -v
```

- [ ] **Step 3: Rewrite `csm_core/assembler/constraints.py`**

```python
"""Orchestrate block-level sampling.

For paragraph blocks with depends_on, the dependency graph is
respected (topological order over paragraph ids). Non-paragraph
blocks run in declaration order and never participate in the
dependency graph.
"""
from __future__ import annotations
from ..vault.scanner import VaultIndex
from ..vault.brand_registry import BrandRegistry
from ..template.schema import (
    Template, ParagraphBlock, TestResultsAlignedSource,
)
from .plan import AssemblyPlan, BlockResult
from .sampler import sample_block


def _collect_paragraph_ids(blocks) -> list[str]:
    out: list[str] = []
    def walk(items):
        for b in items:
            if isinstance(b, ParagraphBlock):
                out.append(b.id)
                walk(b.children)
    walk(blocks)
    return out


def _resolve_aligned_models(
    block_id: str, source: TestResultsAlignedSource,
    results_by_id: dict[str, BlockResult],
) -> list[str]:
    follow_ids = source.follow_slot.split("+")
    models: list[str] = []
    for fid in follow_ids:
        r = results_by_id.get(fid)
        if not r:
            continue
        for p in r.picks:
            m = p.meta.get("model")
            if m and m not in models:
                models.append(m)
    return models


def assemble_plan(
    *, keyword: str, template: Template,
    index: VaultIndex, registry: BrandRegistry,
    seed: int, user_config: dict[str, int],
) -> AssemblyPlan:
    results_by_id: dict[str, BlockResult] = {}
    warnings: list[str] = []

    def sample_paragraph_tree(p: ParagraphBlock) -> BlockResult:
        aligned = None
        if isinstance(p.source, TestResultsAlignedSource):
            aligned = _resolve_aligned_models(p.id, p.source, results_by_id)
        r = sample_block(
            p, index, registry, seed=seed, user_config=user_config,
            aligned_models=aligned,
        )
        missing = [pk for pk in r.picks if pk.meta.get("missing")]
        if missing:
            warnings.append(
                f"block '{p.id}': {len(missing)} 测试数据缺失 "
                f"({[pk.note_id for pk in missing]})"
            )
        capped = next((pk for pk in r.picks if pk.meta.get("capped")), None)
        if capped is not None:
            note_text = (
                f"请求 {capped.meta['requested']} 条，"
                f"池内仅 {capped.meta['available']} 条可用"
            )
            r.note = note_text
            warnings.append(f"block '{p.id}': {note_text}")
        results_by_id[p.id] = r
        r.children = [sample_paragraph_tree(c) for c in p.children]
        return r

    top: list[BlockResult] = []
    for b in template.blocks:
        if isinstance(b, ParagraphBlock):
            top.append(sample_paragraph_tree(b))
        else:
            r = sample_block(b, index, registry, seed=seed, user_config=user_config)
            results_by_id[b.id] = r
            top.append(r)

    return AssemblyPlan(
        keyword=keyword, template_id=template.id, seed=seed,
        results=top, warnings=warnings,
    )
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/ -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/assembler/constraints.py tests/core/assembler/test_constraints.py
git commit -m "feat(assembler): assemble_plan walks blocks + nested paragraph children"
```

---

## Phase 3 — Renderer（组装草稿）

### Task 6: `compose_draft` 以 blocks 为输入（区域收编 + 编号）

**Files:**
- Modify: `csm_core/assembler/render.py`（完全重写）
- Test: `tests/core/assembler/test_block_renderer.py`（新建）

- [ ] **Step 1: Write failing tests**

```python
# tests/core/assembler/test_block_renderer.py
from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.assembler.render import compose_draft


def _plan(*results):
    return AssemblyPlan(keyword="k", template_id="t", seed=0, results=list(results))


def test_plain_paragraph_and_heading():
    p = _plan(
        BlockResult(block_id="h", kind="heading", text="题",
                    meta={"level": 2, "index": "一"}),
        BlockResult(block_id="s", kind="paragraph",
                    picks=[PickedVariant(note_id="n", variant_index=0, text="段落正文")]),
    )
    out = compose_draft(p)
    assert out == "## 一、题\n\n段落正文"


def test_literal_substitutes_keyword():
    p = _plan(BlockResult(block_id="l", kind="literal", text="关于 {keyword}"))
    p.keyword = "吸尘器"
    assert compose_draft(p) == "关于 吸尘器"


def test_numbered_list_formats_with_number_style():
    p = _plan(BlockResult(
        block_id="n", kind="numbered_list",
        picks=[
            PickedVariant(note_id="a", variant_index=0, text="aaa"),
            PickedVariant(note_id="b", variant_index=0, text="bbb"),
            PickedVariant(note_id="c", variant_index=0, text="ccc"),
        ],
        meta={"number_style": "1.", "item_separator": "\n\n"},
    ))
    assert compose_draft(p) == "1. aaa\n\n2. bbb\n\n3. ccc"


def test_hero_brand_without_pool_renders_standalone():
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY DS18",
                    meta={"number_style": "1.", "reason_label": "推荐理由："}),
        BlockResult(block_id="p1", kind="paragraph",
                    picks=[PickedVariant(note_id="a", variant_index=0, text="理由 A")]),
        BlockResult(block_id="p2", kind="paragraph",
                    picks=[PickedVariant(note_id="b", variant_index=0, text="理由 B")]),
    )
    # region runs until blocks end
    assert compose_draft(p) == (
        "1. CEWEY DS18\n推荐理由：\n理由 A\n\n理由 B"
    )


def test_hero_brand_closed_by_competitor_pool_continuous_numbering():
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY DS18",
                    meta={"number_style": "1.", "reason_label": "推荐理由："}),
        BlockResult(block_id="p1", kind="paragraph",
                    picks=[PickedVariant(note_id="a", variant_index=0, text="品牌背书")]),
        BlockResult(block_id="cp", kind="competitor_pool",
                    picks=[
                        PickedVariant(note_id="n1", variant_index=0, text="理由A",
                                      meta={"title": "戴森V8"}),
                        PickedVariant(note_id="n2", variant_index=0, text="理由B",
                                      meta={"title": "小狗T12"}),
                    ],
                    meta={"reason_label": "推荐理由："}),
    )
    out = compose_draft(p)
    assert out == (
        "1. CEWEY DS18\n推荐理由：\n品牌背书\n\n"
        "2. 戴森V8\n推荐理由：理由A\n\n"
        "3. 小狗T12\n推荐理由：理由B"
    )


def test_competitor_pool_standalone_starts_from_one():
    p = _plan(BlockResult(
        block_id="cp", kind="competitor_pool",
        picks=[
            PickedVariant(note_id="n1", variant_index=0, text="r1",
                          meta={"title": "A"}),
            PickedVariant(note_id="n2", variant_index=0, text="r2",
                          meta={"title": "B"}),
        ],
        meta={"reason_label": "推荐理由："},
    ))
    assert compose_draft(p) == "1. A\n推荐理由：r1\n\n2. B\n推荐理由：r2"


def test_chinese_number_style():
    p = _plan(BlockResult(
        block_id="n", kind="numbered_list",
        picks=[PickedVariant(note_id="a", variant_index=0, text="x"),
               PickedVariant(note_id="b", variant_index=0, text="y")],
        meta={"number_style": "一、", "item_separator": "\n\n"},
    ))
    assert compose_draft(p) == "一、x\n\n二、y"


def test_paragraph_children_flatten_into_region():
    """Sub-variants under a paragraph render as additional paragraph body."""
    child = BlockResult(
        block_id="p1_1", kind="paragraph",
        picks=[PickedVariant(note_id="c", variant_index=0, text="子变体")],
    )
    p = _plan(
        BlockResult(block_id="h", kind="hero_brand", text="CEWEY",
                    meta={"number_style": "1.", "reason_label": "推荐理由："}),
        BlockResult(
            block_id="p1", kind="paragraph",
            picks=[PickedVariant(note_id="p", variant_index=0, text="主段")],
            children=[child],
        ),
    )
    assert compose_draft(p) == (
        "1. CEWEY\n推荐理由：\n主段\n\n子变体"
    )


def test_paragraph_empty_picks_skipped():
    p = _plan(
        BlockResult(block_id="s1", kind="paragraph", picks=[]),
        BlockResult(block_id="s2", kind="paragraph",
                    picks=[PickedVariant(note_id="a", variant_index=0, text="X")]),
    )
    assert compose_draft(p) == "X"
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/test_block_renderer.py -v
```

- [ ] **Step 3: Rewrite `csm_core/assembler/render.py`**

```python
"""Render an AssemblyPlan to draft text — block dispatch + hero regions."""
from __future__ import annotations
import re
from .plan import AssemblyPlan, BlockResult, PickedVariant

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

_CN_DIGITS = "零一二三四五六七八九十"


def _format_index(i: int, style: str) -> str:
    """Return the numeric prefix for a list item (1-based)."""
    if style == "none":
        return ""
    if style == "1.":
        return f"{i}."
    if style == "一、":
        if 1 <= i <= 10:
            return f"{_CN_DIGITS[i]}、"
        # 11–99: 十一、十二、二十、二十一 …
        if 11 <= i <= 19:
            return f"十{_CN_DIGITS[i - 10]}、"
        if 20 <= i <= 99:
            tens, ones = divmod(i, 10)
            if ones == 0:
                return f"{_CN_DIGITS[tens]}十、"
            return f"{_CN_DIGITS[tens]}十{_CN_DIGITS[ones]}、"
        return f"{i}、"
    return f"{i}."


def _substitute(text: str, variables: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        return variables.get(name, m.group(0))
    return _VAR_RE.sub(repl, text)


def _paragraph_text(r: BlockResult) -> str:
    """Flatten a paragraph result (including children) into a single text block."""
    parts = [p.text for p in r.picks]
    for c in r.children:
        if c.kind == "paragraph":
            ct = _paragraph_text(c)
            if ct:
                parts.append(ct)
    return "\n\n".join(parts)


def _numbered_list_text(r: BlockResult) -> str:
    style = r.meta.get("number_style", "1.")
    sep = r.meta.get("item_separator", "\n\n")
    items = [f"{_format_index(i + 1, style)} {p.text}".strip()
             for i, p in enumerate(r.picks)]
    return sep.join(items)


def compose_draft(plan: AssemblyPlan) -> str:
    """Render the plan to draft text.

    Region semantics: a `hero_brand` block opens a region. All
    subsequent paragraph / numbered_list block results until the next
    `competitor_pool`, the next `hero_brand`, or end of results are
    aggregated as the hero's reason body (each rendered normally, then
    joined with blank lines). The `competitor_pool` then appends its
    own items continuing the hero's numbering.
    """
    variables = {"keyword": plan.keyword}
    parts: list[str] = []
    i = 0
    while i < len(plan.results):
        r = plan.results[i]
        if r.kind == "hero_brand":
            chunk, i = _render_hero_region(plan.results, i, variables)
            if chunk:
                parts.append(chunk)
            continue
        if r.kind == "competitor_pool":
            parts.append(_render_competitor_pool(r, start_index=1))
            i += 1
            continue
        chunk = _render_standalone(r, variables)
        if chunk:
            parts.append(chunk)
        i += 1
    return "\n\n".join(p for p in parts if p)


def _render_standalone(r: BlockResult, variables: dict[str, str]) -> str:
    if r.kind == "heading":
        level = r.meta.get("level", 2)
        prefix = "#" * level
        idx = r.meta.get("index", "")
        text = _substitute(r.text, variables)
        return f"{prefix} {idx}、{text}" if idx else f"{prefix} {text}"
    if r.kind == "literal":
        return _substitute(r.text, variables)
    if r.kind == "paragraph":
        return _paragraph_text(r)
    if r.kind == "numbered_list":
        if not r.picks:
            return ""
        return _numbered_list_text(r)
    if r.kind == "hero_brand":
        # standalone hero without region close: rendered as bare title
        return r.text
    return ""


def _render_hero_region(
    results: list[BlockResult], start: int, variables: dict[str, str],
) -> tuple[str, int]:
    hero = results[start]
    style = hero.meta.get("number_style", "1.")
    reason_label = hero.meta.get("reason_label", "推荐理由：")
    body_parts: list[str] = []
    j = start + 1
    pool_result: BlockResult | None = None
    while j < len(results):
        nxt = results[j]
        if nxt.kind == "competitor_pool":
            pool_result = nxt
            break
        if nxt.kind == "hero_brand":
            break
        if nxt.kind == "paragraph":
            body_parts.append(_paragraph_text(nxt))
        elif nxt.kind == "numbered_list" and nxt.picks:
            body_parts.append(_numbered_list_text(nxt))
        elif nxt.kind in ("heading", "literal"):
            body_parts.append(_render_standalone(nxt, variables))
        j += 1

    hero_title = _substitute(hero.text, variables)
    body = "\n\n".join(p for p in body_parts if p)
    if body:
        hero_chunk = f"{_format_index(1, style)} {hero_title}\n{reason_label}\n{body}"
    else:
        hero_chunk = f"{_format_index(1, style)} {hero_title}\n{reason_label}".rstrip()

    if pool_result is None:
        return hero_chunk, j

    pool_chunk = _render_competitor_pool(pool_result, start_index=2, style=style)
    return f"{hero_chunk}\n\n{pool_chunk}", j + 1


def _render_competitor_pool(
    r: BlockResult, *, start_index: int, style: str = "1.",
) -> str:
    label = r.meta.get("reason_label", "推荐理由：")
    items: list[str] = []
    for k, p in enumerate(r.picks):
        n = start_index + k
        title = p.meta.get("title") or p.note_id
        items.append(f"{_format_index(n, style)} {title}\n{label}{p.text}")
    return "\n\n".join(items)
```

- [ ] **Step 4: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/core/assembler/test_block_renderer.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/assembler/render.py tests/core/assembler/test_block_renderer.py
git commit -m "feat(renderer): compose_draft with hero-region fold + continuous numbering

- hero_brand opens a region; subsequent paragraph/numbered_list are
  aggregated as the hero's reason body
- competitor_pool closes the region and continues the hero numbering;
  standalone competitor_pool numbers from 1
- number_style: 1. / 一、 / none (Chinese digits 1-99 supported)"
```

---

## Phase 4 — Pipeline 清理

### Task 7: pipeline.py 移除 framework 分支

**Files:**
- Modify: `csm_core/pipeline.py`
- Modify: existing integration tests that use `framework_id` / `frameworks_dir`

- [ ] **Step 1: Grep for framework references in tests**

```bash
.venv/Scripts/python.exe -m pytest --collect-only 2>&1 | grep -i framework
```

Note which tests need updating.

- [ ] **Step 2: Rewrite `csm_core/pipeline.py`**

```python
"""End-to-end orchestration: keyword + template → article."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .vault.scanner import scan_vault
from .vault.brand_registry import build_brand_registry
from .template.loader import load_template
from .assembler.constraints import assemble_plan
from .assembler.plan import AssemblyPlan
from .assembler.render import compose_draft
from .llm.client import LLMClient
from .llm.prompts import build_prompt, PromptInputs
from .export.markdown import export_article


STAGES = ("扫描资料库", "加载模板", "采样 blocks", "组装 prompt", "调用 LLM", "导出")


@dataclass
class GenerateRequest:
    keyword: str
    vault_root: Path
    template_path: Path
    out_dir: Path
    llm_client: LLMClient
    user_skill_prompt: str | None = None
    seed: int = 0
    user_config: dict[str, int] | None = None
    draft_only: bool = False


@dataclass
class GenerateResult:
    markdown_path: str
    assembly_json_path: str
    plan: AssemblyPlan
    final_text: str


def generate(
    req: GenerateRequest,
    on_stage: Callable[[str], None] | None = None,
) -> GenerateResult:
    def _emit(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    _emit("扫描资料库")
    index = scan_vault(req.vault_root)
    registry = build_brand_registry(req.vault_root)

    _emit("加载模板")
    template = load_template(req.template_path)

    _emit("采样 blocks")
    plan = assemble_plan(
        keyword=req.keyword, template=template,
        index=index, registry=registry,
        seed=req.seed, user_config=req.user_config or {},
    )

    _emit("组装 prompt")
    draft = compose_draft(plan)

    if req.draft_only:
        return GenerateResult(
            markdown_path="", assembly_json_path="",
            plan=plan, final_text="",
        )

    system, user = build_prompt(PromptInputs(
        template_system_prompt=template.system_prompt_default,
        user_skill_prompt=req.user_skill_prompt,
        seo=template.seo_defaults,
        keyword=req.keyword, draft=draft,
    ))

    _emit("调用 LLM")
    final_text = req.llm_client.complete(system=system, user=user)

    _emit("导出")
    paths = export_article(
        out_dir=req.out_dir, keyword=req.keyword, final_text=final_text,
        plan=plan,
        prompt_snapshot={
            "system": system, "user": user,
            "provider": type(req.llm_client).__name__,
        },
    )
    return GenerateResult(
        markdown_path=paths["markdown"],
        assembly_json_path=paths["assembly_json"],
        plan=plan, final_text=final_text,
    )
```

- [ ] **Step 3: Update `csm_core/export/markdown.py`** if it references `plan.slots`

```bash
.venv/Scripts/python.exe -c "import csm_core.export.markdown" 2>&1 | head -5
```

If it errors, grep for `plan.slots` / `SlotAssignment` in export/markdown.py and replace with `plan.results` / `BlockResult` (preserve JSON structure — the export just dumps plan.to_json()).

- [ ] **Step 4: Run the whole suite, note failures; triage**

```bash
.venv/Scripts/python.exe -m pytest tests/ -x -q 2>&1 | tail -30
```

Expected failures in: any test calling `GenerateRequest(framework_id=...)`, any test using `plan.slots`, any test importing from `csm_core.framework`. Fix each:
- remove `framework_id` / `frameworks_dir` kwargs
- rename `plan.slots` → `plan.results`
- drop `from csm_core.framework...` imports and related assertions (these are covered by Task 10's deletion)

- [ ] **Step 5: Commit**

```bash
git add csm_core/pipeline.py csm_core/export/markdown.py tests/
git commit -m "refactor(pipeline): drop framework integration; generate uses compose_draft directly"
```

---

## Phase 5 — 迁移脚本（在删除旧代码前跑一次）

### Task 8: migrate_framework_to_blocks.py

**Files:**
- Create: `scripts/migrate_framework_to_blocks.py`
- Create: `tests/scripts/test_migrate_framework_to_blocks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_migrate_framework_to_blocks.py
import json, shutil
from pathlib import Path
from scripts.migrate_framework_to_blocks import migrate


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_migrate_bundles_paragraph_slots_into_blocks(tmp_path):
    tpl_dir = tmp_path / "templates"
    fw_dir = tmp_path / "frameworks"
    _write(tpl_dir / "t1.json", {
        "id": "t1", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "slots": [
            {"id": "s1", "label": "痛点",
             "source": {"type": "notes_query", "module": "A"},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
            {"id": "s2", "label": "科普",
             "source": {"type": "notes_query", "module": "B"},
             "pick_notes": 3, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
        ],
        "render_order": ["s1", "s2"],
        "default_framework": "fw1",
    })
    _write(fw_dir / "fw1.json", {
        "id": "fw1", "name": "F", "variables": [],
        "blocks": [
            {"kind": "paragraph", "slot": "s1"},
            {"kind": "heading", "level": 2, "index": "一", "text": "标题"},
            {"kind": "numbered_list", "slot": "s2"},
        ],
    })

    report = migrate(tpl_dir, fw_dir)
    assert report["migrated"] == ["t1.json"]
    assert report["skipped"] == []
    data = json.loads((tpl_dir / "t1.json").read_text(encoding="utf-8"))
    kinds = [b["kind"] for b in data["blocks"]]
    assert kinds == ["paragraph", "heading", "numbered_list"]
    assert data["blocks"][0]["id"] == "s1"
    assert data["blocks"][0]["source"]["module"] == "A"
    assert data["blocks"][2]["pick_notes"] == 3
    assert "slots" not in data and "render_order" not in data
    assert (tpl_dir / "_migrated_backup" / "t1.json").exists()


def test_migrate_skips_brand_reason_list(tmp_path):
    tpl_dir = tmp_path / "templates"
    fw_dir = tmp_path / "frameworks"
    _write(tpl_dir / "t1.json", {
        "id": "t1", "name": "T", "product": "x", "version": 1,
        "system_prompt_default": "", "seo_defaults": {},
        "slots": [
            {"id": "s1", "label": "品牌",
             "source": {"type": "notes_query", "module": "A"},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
        ],
        "render_order": ["s1"],
        "default_framework": "fw1",
    })
    _write(fw_dir / "fw1.json", {
        "id": "fw1", "name": "F", "variables": [],
        "blocks": [
            {"kind": "brand_reason_list", "slots": ["s1"], "reason_label": "r:"},
        ],
    })
    report = migrate(tpl_dir, fw_dir)
    assert "t1.json" in report["skipped"]
    # original untouched (still has slots)
    assert "slots" in json.loads((tpl_dir / "t1.json").read_text(encoding="utf-8"))


def test_migrate_idempotent_on_already_new_schema(tmp_path):
    tpl_dir = tmp_path / "templates"
    fw_dir = tmp_path / "frameworks"
    _write(tpl_dir / "t1.json", {
        "id": "t1", "name": "T", "product": "x", "version": 1,
        "system_prompt_default": "", "seo_defaults": {},
        "blocks": [{"kind": "literal", "id": "l1", "text": "x"}],
    })
    fw_dir.mkdir()
    report = migrate(tpl_dir, fw_dir)
    assert report["skipped_already_new"] == ["t1.json"]
```

- [ ] **Step 2: Run, confirm FAIL**

```bash
.venv/Scripts/python.exe -m pytest tests/scripts/test_migrate_framework_to_blocks.py -v
```

- [ ] **Step 3: Create `scripts/migrate_framework_to_blocks.py`**

```python
"""One-shot migration: fold framework.json into template.blocks.

Usage::

    python scripts/migrate_framework_to_blocks.py \
        --templates-dir templates \
        --frameworks-dir frameworks \
        [--apply]  # default dry-run prints summary only

Rules:
  1. For each template *.json in old schema (has top-level ``slots`` key):
     - Look up its framework by ``default_framework`` id, or a sibling
       framework whose basename matches the template basename.
     - If no framework found: skip with warning.
     - If framework has a ``brand_reason_list`` block: skip with warning
       (requires manual conversion to hero_brand + competitor_pool).
     - Otherwise: build new ``blocks`` list by walking framework.blocks,
       replacing ``paragraph`` / ``numbered_list`` with the full slot
       object (source / pick_notes / children) from the template.
  2. Back up original template to ``templates/_migrated_backup/`` before
     overwriting.
  3. Idempotent: skip any template already in new schema (has ``blocks``).
"""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path


def _is_new_schema(data: dict) -> bool:
    return "blocks" in data and "slots" not in data


def _find_framework(fw_dir: Path, tpl_path: Path, default_id: str | None) -> Path | None:
    if default_id:
        for p in fw_dir.glob("*.json"):
            if p.stem == default_id:
                return p
    # fallback: same stem
    candidate = fw_dir / f"{tpl_path.stem}.json"
    if candidate.exists():
        return candidate
    return None


def _slots_by_id(slots: list[dict]) -> dict[str, dict]:
    return {s["id"]: s for s in slots}


def _slot_to_paragraph_block(slot: dict) -> dict:
    # strip keys that are meaningless on a block, keep sampling config
    return {
        "kind": "paragraph",
        "id": slot["id"],
        "label": slot.get("label", ""),
        "source": slot["source"],
        "pick_notes": slot.get("pick_notes", 1),
        "pick_variants_per_note": slot.get("pick_variants_per_note", 1),
        "constraints": slot.get("constraints", []),
        "depends_on": slot.get("depends_on", []),
        "children": [_slot_to_paragraph_block(c) for c in slot.get("children", [])],
    }


def _slot_to_numbered_list_block(slot: dict) -> dict:
    pn = slot.get("pick_notes", 3)
    return {
        "kind": "numbered_list",
        "id": slot["id"],
        "label": slot.get("label", ""),
        "source": slot["source"],
        "pick_notes": pn if isinstance(pn, (int, dict)) else 3,
        "number_style": "1.",
        "item_separator": "\n\n",
    }


def _heading_block(fb: dict) -> dict:
    return {
        "kind": "heading",
        "id": f"h_{fb.get('index') or 'x'}",
        "level": fb.get("level", 2),
        "index": fb.get("index", ""),
        "text": fb["text"],
    }


def _literal_block(fb: dict) -> dict:
    return {"kind": "literal", "id": "lit", "text": fb["text"]}


def _convert_blocks(
    fw_blocks: list[dict], slots: list[dict],
) -> tuple[list[dict] | None, str | None]:
    sb = _slots_by_id(slots)
    out: list[dict] = []
    used_heading_ids: set[str] = set()
    for fb in fw_blocks:
        kind = fb["kind"]
        if kind == "brand_reason_list":
            return None, "framework uses brand_reason_list — manual rewrite required"
        if kind == "paragraph":
            slot = sb.get(fb["slot"])
            if slot is None:
                return None, f"framework references unknown slot '{fb['slot']}'"
            out.append(_slot_to_paragraph_block(slot))
        elif kind == "numbered_list":
            slot = sb.get(fb["slot"])
            if slot is None:
                return None, f"framework references unknown slot '{fb['slot']}'"
            out.append(_slot_to_numbered_list_block(slot))
        elif kind == "heading":
            blk = _heading_block(fb)
            base = blk["id"]
            i = 1
            while blk["id"] in used_heading_ids:
                i += 1
                blk["id"] = f"{base}_{i}"
            used_heading_ids.add(blk["id"])
            out.append(blk)
        elif kind == "literal":
            blk = _literal_block(fb)
            # make id unique
            idx = sum(1 for b in out if b.get("id", "").startswith("lit"))
            blk["id"] = f"lit_{idx + 1}"
            out.append(blk)
        else:
            return None, f"unknown framework block kind '{kind}'"
    return out, None


def migrate(templates_dir: Path, frameworks_dir: Path, *, apply: bool = True) -> dict:
    tpl_dir = Path(templates_dir)
    fw_dir = Path(frameworks_dir)
    backup_dir = tpl_dir / "_migrated_backup"

    report: dict[str, list[str]] = {
        "migrated": [], "skipped": [], "skipped_already_new": [],
    }

    for tpl_path in sorted(tpl_dir.glob("*.json")):
        data = json.loads(tpl_path.read_text(encoding="utf-8"))
        if _is_new_schema(data):
            report["skipped_already_new"].append(tpl_path.name)
            continue
        fw_path = _find_framework(
            fw_dir, tpl_path, data.get("default_framework"),
        )
        if fw_path is None:
            report["skipped"].append(tpl_path.name)
            print(f"SKIP {tpl_path.name}: no framework found")
            continue
        fw_data = json.loads(fw_path.read_text(encoding="utf-8"))
        new_blocks, err = _convert_blocks(fw_data["blocks"], data.get("slots", []))
        if err:
            report["skipped"].append(tpl_path.name)
            print(f"SKIP {tpl_path.name}: {err}")
            continue
        new_data = {
            "id": data["id"], "name": data["name"],
            "product": data["product"], "version": data.get("version", 1),
            "system_prompt_default": data.get("system_prompt_default", ""),
            "seo_defaults": data.get("seo_defaults", {}),
            "blocks": new_blocks,
        }
        if apply:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tpl_path, backup_dir / tpl_path.name)
            tpl_path.write_text(
                json.dumps(new_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        report["migrated"].append(tpl_path.name)
        print(f"OK {tpl_path.name}")

    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates-dir", default="templates")
    ap.add_argument("--frameworks-dir", default="frameworks")
    ap.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    args = ap.parse_args()
    report = migrate(Path(args.templates_dir), Path(args.frameworks_dir), apply=args.apply)
    print("\n== summary ==")
    for k, v in report.items():
        print(f"{k}: {len(v)} — {v}")
    print(f"(apply={args.apply})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/scripts/test_migrate_framework_to_blocks.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_framework_to_blocks.py tests/scripts/test_migrate_framework_to_blocks.py
git commit -m "feat(scripts): migrate_framework_to_blocks — fold framework into template"
```

---

### Task 9: 对真实数据跑迁移 + 手工重建 brand_reason_list

**Files:**
- Modify: `templates/daogou-changjing-renqun.json`（迁移脚本 + 手工）

- [ ] **Step 1: Dry-run first to see what happens**

```bash
.venv/Scripts/python.exe scripts/migrate_framework_to_blocks.py \
    --templates-dir templates --frameworks-dir frameworks
```

Expected: reports `daogou-changjing-renqun.json` as **skipped** (because framework uses `brand_reason_list`).

- [ ] **Step 2: Manually rewrite `templates/daogou-changjing-renqun.json`** into new schema.

Open the current template and framework, and construct the new file by hand. The target structure (keep all existing slot sampling configs; use the same `source` / `pick_notes` / children etc.):

```json
{
  "id": "daogou-changjing-renqun",
  "name": "导购文-科普导购文",
  "product": "吸尘器",
  "version": 2,
  "system_prompt_default": "<unchanged>",
  "seo_defaults": { ... unchanged ... },
  "blocks": [
    { "kind": "paragraph", "id": "slot_1", ...},
    { "kind": "paragraph", "id": "slot_2", ...},
    { "kind": "paragraph", "id": "slot_3", ...},
    { "kind": "paragraph", "id": "slot_4", ...},
    { "kind": "heading", "id": "h_1", "level": 2, "index": "一", "text": "{keyword}应该怎么选？" },
    { "kind": "numbered_list", "id": "slot_5", "label": "挑选攻略",
      "source": { ... slot_5 source ... },
      "pick_notes": { "random_between": [3, 3] },
      "number_style": "1." },
    { "kind": "heading", "id": "h_2", "level": 2, "index": "二", "text": "{keyword}推荐" },
    { "kind": "hero_brand", "id": "hero_1",
      "title": "CEWEY DS18无线吸尘器",
      "reason_label": "推荐理由：", "number_style": "1." },
    { "kind": "paragraph", "id": "slot_6", "label": "品牌背书",
      "source": { ... slot_6 source ... },
      "children": [
        { "kind": "paragraph", "id": "slot_6_1", ... },
        { "kind": "paragraph", "id": "slot_6_2", ... },
        { "kind": "paragraph", "id": "slot_6_3", ... },
        { "kind": "paragraph", "id": "slot_6_4", ... }
      ]
    },
    { "kind": "paragraph", "id": "slot_7", "label": "核心技术",
      "source": { ... slot_7 source ... },
      "children": [
        { "kind": "paragraph", "id": "slot_7_1", ... }
      ]
    },
    { "kind": "competitor_pool", "id": "comp_1",
      "source": { ... slot_8 source ... },
      "pick_notes": { "random_between": [2, 2] },
      "reason_label": "推荐理由：" },
    { "kind": "heading", "id": "h_3", "level": 2, "index": "三", "text": "总结" },
    { "kind": "paragraph", "id": "slot_summary", ... }
  ]
}
```

Copy `source`, `pick_notes`, `pick_variants_per_note`, `constraints`, `depends_on` fields verbatim from each slot in the old template.

- [ ] **Step 3: Backup original, then overwrite**

```bash
mkdir -p templates/_migrated_backup
cp templates/daogou-changjing-renqun.json templates/_migrated_backup/
# then edit templates/daogou-changjing-renqun.json with the new structure
```

- [ ] **Step 4: Validate**

```bash
.venv/Scripts/python.exe -c "from csm_core.template.loader import load_template; tpl = load_template('templates/daogou-changjing-renqun.json'); print(len(tpl.blocks), 'blocks'); print([b.kind for b in tpl.blocks])"
```

Expected: clean output showing block kinds.

- [ ] **Step 5: Commit**

```bash
git add templates/daogou-changjing-renqun.json templates/_migrated_backup/
git commit -m "chore(templates): migrate daogou-changjing-renqun to unified block schema

hero_brand (CEWEY DS18) + paragraph (品牌背书 + 核心技术 with children)
+ competitor_pool (竞品推荐内容) replaces the old brand_reason_list."
```

---

## Phase 6 — 删除 framework 层 + GUI 清理

### Task 10: 删除 csm_core/framework/ + framework GUI + framework tests

**Files:**
- Delete: `csm_core/framework/` 整目录
- Delete: `csm_gui/widgets/framework_list_panel.py`, `framework_editor_panel.py`, `framework_block_card.py`
- Delete: `frameworks/` 目录
- Delete: 所有 `tests/**/test_framework_*.py`

- [ ] **Step 1: Find all framework test files**

```bash
ls tests/core/framework/ tests/gui/ 2>/dev/null | grep -i framework
```

- [ ] **Step 2: Remove files**

```bash
git rm -rf csm_core/framework/
git rm csm_gui/widgets/framework_list_panel.py
git rm csm_gui/widgets/framework_editor_panel.py
git rm csm_gui/widgets/framework_block_card.py
git rm -rf tests/core/framework/ 2>/dev/null || true
git rm tests/gui/test_framework_*.py 2>/dev/null || true
git rm -rf frameworks/
```

- [ ] **Step 3: Search for leftover imports**

```bash
.venv/Scripts/python.exe -c "import csm_core" 2>&1 | head -5
```

If anything still imports from `csm_core.framework`, fix it (likely in `csm_gui/pages/template_manager_page.py` — see Task 11).

- [ ] **Step 4: Run core test suite**

```bash
.venv/Scripts/python.exe -m pytest tests/core/ -x -q 2>&1 | tail -15
```

Expected: PASS (GUI failures are Task 11's problem).

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: remove framework layer (schema, loader, renderer, GUI, tests, data)

Framework logic fully merged into Template's unified block model.
Migration script (scripts/migrate_framework_to_blocks.py) handled
existing data in the previous commit."
```

---

### Task 11: template_manager_page 移除"框架"标签 + GenerationForm/Controller 清理

**Files:**
- Modify: `csm_gui/pages/template_manager_page.py`
- Modify: `csm_gui/forms/generation_form.py`
- Modify: `csm_gui/controllers/article_controller.py`

- [ ] **Step 1: Inspect each file for framework references**

```bash
.venv/Scripts/python.exe -c "import csm_gui" 2>&1 | head -10
```

Use Grep/Read to find `Framework` / `framework_id` / `frameworks_dir` usages in these three files.

- [ ] **Step 2: Edit `csm_gui/pages/template_manager_page.py`** — remove the `QTabWidget` + "框架" tab; collapse to just the template editor (list panel + editor panel directly).

The page should end up with the same layout as before the framework tab was added (which is a simple horizontal split). Read commit `bbae3fc` ("framework editor panel + list panel + tabs") to see exactly what to revert.

- [ ] **Step 3: Edit `csm_gui/forms/generation_form.py`** — remove the framework dropdown widget (added in commit `cc69b6c`) and its `framework_id` signal/field.

- [ ] **Step 4: Edit `csm_gui/controllers/article_controller.py`** — remove `framework_id` parameter forwarding to `GenerateRequest` (added in commit `d64ebc4`).

- [ ] **Step 5: Run GUI tests**

```bash
.venv/Scripts/python.exe -m pytest tests/gui/ -x -q 2>&1 | tail -15
```

Fix any remaining breakage from framework removal.

- [ ] **Step 6: Commit**

```bash
git add csm_gui/
git commit -m "refactor(gui): remove framework tab, dropdown, and controller plumbing

Revert cc69b6c / d64ebc4 / bbae3fc — the framework concept no longer
exists. The Template Manager page is just list + editor again."
```

---

### Task 12: slot_tree_widget → block tree（kind 选择器 + 分 kind 字段）

**Files:**
- Modify: `csm_gui/widgets/slot_tree_widget.py`（主要改动）
- Modify: `csm_gui/widgets/template_editor_panel.py`（load_template / save_template 走新 schema）
- Test: `tests/gui/test_template_editor_panel.py`（adapt）

This is the biggest single task. Break into steps carefully.

- [ ] **Step 1: Read the current `slot_tree_widget.py`** (~790 lines) to map out what exists. It currently renders rows for `Slot` with: directory ComboBox, label LineEdit, pick_notes SpinBox, children tree, and up/down/delete buttons.

- [ ] **Step 2: Design the new row model**

Each tree row now has a **kind selector** (dropdown: 段落 / 标题 / 编号列表 / 主品区域 / 竞品池 / 固定文本) as the leftmost widget after the row-number label. Fields shown per kind:

| Kind | Fields shown |
|---|---|
| 段落 | 目录 ComboBox · label · pick_notes · 子变体 tree |
| 标题 | level SpinBox · index · text |
| 编号列表 | 目录 · label · pick_notes · number_style · item_separator（默认隐藏，高级） |
| 主品区域 | title · reason_label · number_style |
| 竞品池 | 目录 · pick_notes · reason_label |
| 固定文本 | text (multi-line) |

Implement by extracting a `_BlockRow` QWidget that owns a `QStackedLayout` — one page per kind — and swaps pages when the kind combo changes. Previously the row was always in "paragraph mode"; this stack lets one row represent any kind.

- [ ] **Step 3: Write failing test**

```python
# tests/gui/test_template_editor_panel.py (add case)
def test_template_editor_loads_all_block_kinds(qtbot, tmp_path):
    import json
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    tpl_path = tmp_path / "t.json"
    tpl_path.write_text(json.dumps({
        "id": "t", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": [
            {"kind": "paragraph", "id": "p1", "label": "痛点",
             "source": {"type": "notes_query", "module": "A"}},
            {"kind": "heading", "id": "h1", "level": 2, "index": "一", "text": "题"},
            {"kind": "hero_brand", "id": "hb1", "title": "CEWEY"},
            {"kind": "competitor_pool", "id": "cp1",
             "source": {"type": "notes_query", "module": "竞品"},
             "pick_notes": {"random_between": [2, 2]}},
            {"kind": "literal", "id": "l1", "text": "end"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.load_template(tpl_path)
    blocks = panel.slots_page.get_blocks()
    assert [b.kind for b in blocks] == [
        "paragraph", "heading", "hero_brand", "competitor_pool", "literal",
    ]


def test_template_editor_saves_round_trip(qtbot, tmp_path):
    import json
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    tpl_path = tmp_path / "t.json"
    original = {
        "id": "t", "name": "T", "product": "x", "version": 1,
        "system_prompt_default": "", "seo_defaults": {},
        "blocks": [
            {"kind": "literal", "id": "l1", "text": "hello"},
            {"kind": "heading", "id": "h1", "level": 2, "index": "", "text": "T"},
        ],
    }
    tpl_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.load_template(tpl_path)
    assert panel.save() is True
    saved = json.loads(tpl_path.read_text(encoding="utf-8"))
    assert [b["kind"] for b in saved["blocks"]] == ["literal", "heading"]
```

- [ ] **Step 4: Implement block-row in `slot_tree_widget.py`**

Add a `BLOCK_KINDS` list and a kind selector to each row. The existing "paragraph"-only form becomes the "段落" page in a `QStackedWidget` — one page per kind. Key API changes:

- Rename public methods on the tree widget:
  - `load_slots(slots)` → `load_blocks(blocks)` (accept list of `Block` pydantic objects)
  - `get_slots()` → `get_blocks()` (return list of `Block` pydantic objects)
  - `add_root_slot()` → `add_root_block(kind: str = "paragraph")`
- Keep the "children" ability only on paragraph kind; other kinds hide the expand chevron.

Because `slot_tree_widget.py` is large, prefer editing in place rather than a full rewrite. Changes should be:

1. Add imports for all block types from `csm_core.template.schema`.
2. Add `BLOCK_KINDS = ["paragraph", "heading", "numbered_list", "hero_brand", "competitor_pool", "literal"]`.
3. Replace the row constructor so it takes a `Block` instead of a `Slot`; stash the kind; expose a `.to_block()` method.
4. Build a `QStackedWidget` in the row with one page per kind; current paragraph UI goes on page 0.
5. Add simple pages for each other kind using qfluentwidgets equivalents.
6. Rename the public methods.

- [ ] **Step 5: Update `csm_gui/widgets/template_editor_panel.py`**

Replace `self.slots_page.load_slots(tpl.slots)` with `self.slots_page.load_blocks(tpl.blocks)`, and `_build_template_dict` to write `blocks` (not `slots` / `render_order`).

- [ ] **Step 6: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/gui/test_template_editor_panel.py -v
```

Iterate until PASS.

- [ ] **Step 7: Launch GUI manually and sanity-check**

```bash
.venv/Scripts/python.exe -m csm_gui
```

Open `templates/daogou-changjing-renqun.json`, verify all block kinds render correctly, edit one field, save, reopen — round-trip OK.

- [ ] **Step 8: Commit**

```bash
git add csm_gui/widgets/slot_tree_widget.py csm_gui/widgets/template_editor_panel.py tests/gui/test_template_editor_panel.py
git commit -m "feat(gui): block tree — kind selector + per-kind field pages

Template Manager's 模块 tab now supports all 6 block kinds
(paragraph/heading/numbered_list/hero_brand/competitor_pool/literal)
via a per-row QStackedWidget. Paragraph keeps its sub-variant tree;
other kinds hide it."
```

---

## Phase 7 — 最终清理

### Task 13: 全量测试 + E2E 回归

- [ ] **Step 1: Full suite**

```bash
.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -20
```

- [ ] **Step 2: Fix any remaining failures**

Common remaining issues to expect:
- E2E pipeline test (commit `ad162bd`) still references framework_id — drop those params.
- `tests/core/template/` had integration tests that built `Template(slots=[...], render_order=[...])` — update fixtures to use `blocks=[...]`.

For each failure: read the test, determine whether it's exercising a removed feature (delete test) or a renamed attribute (update test).

- [ ] **Step 3: Grep for stale references**

```bash
.venv/Scripts/python.exe -c "
import subprocess
for needle in ['SlotAssignment', 'plan.slots', 'render_order', 'default_framework', 'framework_id', 'frameworks_dir']:
    print(f'=== {needle} ===')
    subprocess.run(['git', 'grep', '-n', needle])
"
```

Any hits outside `docs/superpowers/` and `templates/_migrated_backup/` are bugs — fix.

- [ ] **Step 4: Manual smoke test**

```bash
.venv/Scripts/python.exe -m csm_gui
```

- Open template, navigate to 模块 tab, verify all 6 kinds visible.
- Generate an article (draft-only) using the migrated template — confirm:
  - Headings render with `## 一、...` form.
  - 主品 (CEWEY) has `1.` prefix, body contains 品牌背书 + 核心技术 samples.
  - Competitors are `2.` and `3.`, each with reason text sampled from ①②③ candidates.
  - 总结 block renders after the competitor list.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: full-suite green after block-model migration"
```

---

### Task 14: Spec 状态更新 + 可选：PR 说明

**Files:**
- Modify: `docs/superpowers/specs/2026-04-22-unified-template-blocks-design.md` — header `Status` → `Implemented`.

- [ ] **Step 1: Update status line**

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-04-22-unified-template-blocks-design.md
git commit -m "docs(spec): mark unified-template-blocks as Implemented"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Block union (paragraph/heading/numbered_list/hero_brand/competitor_pool/literal) — Task 1
- [x] Numbered list samples N from dir, auto numbers — Tasks 4, 6
- [x] hero_brand + competitor_pool region + continuous numbering — Tasks 4, 6
- [x] competitor file format (`型号` frontmatter + ①②③ body split) — Task 4
- [x] `render_order` / `default_framework` removed — Task 1
- [x] Migration script — Task 8–9
- [x] Framework layer deleted — Task 10
- [x] GUI block tree — Task 12
- [x] number_style 1./一、/none — Task 6

**Placeholder scan:** none.

**Type consistency:**
- `BlockResult.kind` uses string literal matching `Block.kind`.
- `plan.results` (not `plan.slots`) is used consistently.
- `sample_block` (not `sample_slot`) everywhere new code references the sampler.
- `load_blocks` / `get_blocks` (not `load_slots`) in GUI tree.

---

**Plan complete and saved to [docs/superpowers/plans/2026-04-22-unified-template-blocks.md](docs/superpowers/plans/2026-04-22-unified-template-blocks.md). Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
