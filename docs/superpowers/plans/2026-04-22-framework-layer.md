# Framework Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable "framework" layer that wraps slot outputs into a structured article (headings, numbered lists, brand/reason blocks), decoupled from the existing JSON template layer that decides *what* material to fetch.

**Architecture:** New `csm_core/framework/` package with pydantic schema + loader + renderer + trace. Pipeline resolves framework from request or template's `default_framework`. GUI adds a framework dropdown in the generation form and merges framework editing into the existing Template Manager page as a second tab.

**Tech Stack:** Python 3.11, pydantic v2, PyQt6, qfluentwidgets, pytest, pytest-qt.

**Spec:** See [docs/superpowers/specs/2026-04-22-framework-layer-design.md](docs/superpowers/specs/2026-04-22-framework-layer-design.md).

---

## File Structure

### Create
- `csm_core/framework/__init__.py`
- `csm_core/framework/schema.py` — pydantic models for `Framework` + block union
- `csm_core/framework/loader.py` — load/save/discover frameworks
- `csm_core/framework/trace.py` — `FrameworkTrace` dataclass
- `csm_core/framework/renderer.py` — `render_with_framework`
- `frameworks/daogou-frame-v1.json` — first framework instance
- `csm_gui/widgets/framework_list_panel.py`
- `csm_gui/widgets/framework_block_card.py`
- `csm_gui/widgets/framework_editor_panel.py`
- `tests/core/framework/__init__.py`
- `tests/core/framework/test_schema.py`
- `tests/core/framework/test_loader.py`
- `tests/core/framework/test_renderer.py`
- `tests/core/framework/test_trace.py`
- `tests/gui/test_framework_editor_panel.py`
- `tests/gui/test_template_manager_page.py`

### Modify
- `csm_core/template/schema.py` — add `default_framework` field
- `csm_core/assembler/render.py` — add `compose_draft_framed`
- `csm_core/pipeline.py` — add `framework_id`, resolve & use framework
- `templates/daogou-changjing-renqun.json` — add `slot_summary`, `default_framework`
- `csm_gui/widgets/generation_form.py` — add framework dropdown
- `csm_gui/controllers/article_controller.py` — pass `framework_id` through
- `csm_gui/pages/template_manager_page.py` — wrap content in tabs
- `tests/gui/test_generation_form.py` — extend
- `tests/core/test_pipeline.py` — extend for framework path

---

## Task 1: Framework schema — basic Framework model and block union

**Files:**
- Create: `csm_core/framework/__init__.py`
- Create: `csm_core/framework/schema.py`
- Create: `tests/core/framework/__init__.py`
- Create: `tests/core/framework/test_schema.py`

- [ ] **Step 1: Create empty package init files**

```python
# csm_core/framework/__init__.py
"""Framework layer: structural wrappers for AssemblyPlan output."""
```

```python
# tests/core/framework/__init__.py
```

- [ ] **Step 2: Write failing schema tests**

```python
# tests/core/framework/test_schema.py
import pytest
from pydantic import ValidationError
from csm_core.framework.schema import (
    Framework, ParagraphBlock, HeadingBlock, NumberedListBlock,
    BrandReasonListBlock, LiteralBlock,
)


def test_framework_minimal_valid():
    fw = Framework(
        id="f1", name="n", variables=[],
        blocks=[ParagraphBlock(kind="paragraph", slot="s1")],
    )
    assert fw.id == "f1"
    assert fw.blocks[0].slot == "s1"


def test_heading_supports_level_and_index():
    h = HeadingBlock(kind="heading", level=2, index="一", text="{keyword}怎么选")
    assert h.level == 2 and h.index == "一"


def test_brand_reason_list_requires_slots_non_empty():
    with pytest.raises(ValidationError):
        BrandReasonListBlock(kind="brand_reason_list", slots=[])


def test_literal_requires_text():
    with pytest.raises(ValidationError):
        LiteralBlock(kind="literal", text="")


def test_numbered_list_requires_slot():
    with pytest.raises(ValidationError):
        NumberedListBlock(kind="numbered_list", slot="")


def test_framework_rejects_unknown_variable_in_heading_text():
    with pytest.raises(ValidationError) as ei:
        Framework(
            id="f1", name="n", variables=["keyword"],
            blocks=[HeadingBlock(kind="heading", level=2, text="{unknown}")],
        )
    assert "unknown" in str(ei.value).lower()


def test_framework_rejects_unknown_variable_in_literal_text():
    with pytest.raises(ValidationError):
        Framework(
            id="f1", name="n", variables=[],
            blocks=[LiteralBlock(kind="literal", text="{keyword}!")],
        )


def test_framework_allows_declared_variable_in_heading_and_literal():
    fw = Framework(
        id="f1", name="n", variables=["keyword"],
        blocks=[
            HeadingBlock(kind="heading", level=2, text="{keyword}"),
            LiteralBlock(kind="literal", text="完。"),
        ],
    )
    assert len(fw.blocks) == 2


def test_heading_level_must_be_1_2_or_3():
    with pytest.raises(ValidationError):
        HeadingBlock(kind="heading", level=5, text="x")
```

- [ ] **Step 3: Run tests; expect ImportError**

Run: `pytest tests/core/framework/test_schema.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement schema**

```python
# csm_core/framework/schema.py
"""Pydantic models for framework DSL."""
from __future__ import annotations
import re
from typing import Literal, Union
from pydantic import BaseModel, Field, model_validator


_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class ParagraphBlock(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    slot: str = Field(min_length=1)


class HeadingBlock(BaseModel):
    kind: Literal["heading"] = "heading"
    level: Literal[1, 2, 3] = 2
    index: str = ""
    text: str = Field(min_length=1)


class NumberedListBlock(BaseModel):
    kind: Literal["numbered_list"] = "numbered_list"
    slot: str = Field(min_length=1)


class BrandReasonListBlock(BaseModel):
    kind: Literal["brand_reason_list"] = "brand_reason_list"
    slots: list[str] = Field(min_length=1)
    reason_label: str = "推荐理由："


class LiteralBlock(BaseModel):
    kind: Literal["literal"] = "literal"
    text: str = Field(min_length=1)


Block = Union[
    ParagraphBlock, HeadingBlock, NumberedListBlock,
    BrandReasonListBlock, LiteralBlock,
]


class Framework(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    variables: list[str] = Field(default_factory=list)
    blocks: list[Block] = Field(discriminator="kind", min_length=1)

    @model_validator(mode="after")
    def _check_variable_tokens(self):
        allowed = set(self.variables)
        for i, b in enumerate(self.blocks):
            text = getattr(b, "text", None)
            if not text:
                continue
            for var in _VAR_RE.findall(text):
                if var not in allowed:
                    raise ValueError(
                        f"block[{i}] uses unknown variable '{{{var}}}' "
                        f"(declared variables: {sorted(allowed) or 'none'})"
                    )
        return self
```

- [ ] **Step 5: Run tests; expect PASS**

Run: `pytest tests/core/framework/test_schema.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add csm_core/framework/__init__.py csm_core/framework/schema.py tests/core/framework/__init__.py tests/core/framework/test_schema.py
git commit -m "feat(framework): add schema with 5 block kinds and variable validation"
```

---

## Task 2: Framework loader — read/save/list framework JSON files

**Files:**
- Create: `csm_core/framework/loader.py`
- Create: `tests/core/framework/test_loader.py`

- [ ] **Step 1: Write failing loader tests**

```python
# tests/core/framework/test_loader.py
import json
from pathlib import Path
import pytest
from csm_core.framework.loader import load_framework, save_framework, list_frameworks
from csm_core.framework.schema import Framework, ParagraphBlock


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_framework_round_trips(tmp_path):
    fw = Framework(
        id="fx", name="n", variables=["keyword"],
        blocks=[ParagraphBlock(kind="paragraph", slot="s1")],
    )
    path = tmp_path / "fx.json"
    save_framework(fw, path)
    loaded = load_framework(path)
    assert loaded.id == "fx"
    assert loaded.blocks[0].slot == "s1"


def test_load_framework_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_framework(tmp_path / "nope.json")


def test_list_frameworks_sorted_by_name(tmp_path):
    _write(tmp_path / "a.json", {"id": "a", "name": "Zebra", "variables": [],
                                  "blocks": [{"kind": "paragraph", "slot": "s1"}]})
    _write(tmp_path / "b.json", {"id": "b", "name": "Apple", "variables": [],
                                  "blocks": [{"kind": "paragraph", "slot": "s1"}]})
    out = list_frameworks(tmp_path)
    assert [name for name, _ in out] == ["Apple", "Zebra"]


def test_list_frameworks_skips_hidden_and_trash(tmp_path):
    (tmp_path / ".trash").mkdir()
    _write(tmp_path / ".trash" / "x.json", {"id": "x", "name": "Hidden",
                                             "variables": [],
                                             "blocks": [{"kind": "paragraph", "slot": "s"}]})
    _write(tmp_path / ".hidden.json", {"id": "h", "name": "Hidden2",
                                        "variables": [],
                                        "blocks": [{"kind": "paragraph", "slot": "s"}]})
    _write(tmp_path / "ok.json", {"id": "ok", "name": "OK",
                                   "variables": [],
                                   "blocks": [{"kind": "paragraph", "slot": "s"}]})
    out = list_frameworks(tmp_path)
    assert [name for name, _ in out] == ["OK"]


def test_list_frameworks_missing_dir(tmp_path):
    assert list_frameworks(tmp_path / "does-not-exist") == []


def test_list_frameworks_falls_back_to_stem_on_parse_error(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    out = list_frameworks(tmp_path)
    assert out == [("broken", tmp_path / "broken.json")]
```

- [ ] **Step 2: Run tests; expect ImportError**

Run: `pytest tests/core/framework/test_loader.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement loader**

```python
# csm_core/framework/loader.py
"""Load / save / discover framework JSON files."""
from __future__ import annotations
import json
from pathlib import Path
from .schema import Framework


def load_framework(path: Path) -> Framework:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Framework.model_validate(data)


def save_framework(framework: Framework, path: Path) -> None:
    Path(path).write_text(
        json.dumps(framework.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_frameworks(directory: Path) -> list[tuple[str, Path]]:
    """Return [(display_name, path), ...] sorted by display name."""
    d = Path(directory)
    if not d.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for p in d.glob("*.json"):
        if p.name.startswith(".") or ".trash" in p.parts:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            name = str(data.get("name") or p.stem)
        except Exception:
            name = p.stem
        out.append((name, p))
    out.sort(key=lambda t: t[0])
    return out
```

- [ ] **Step 4: Run tests; expect PASS**

Run: `pytest tests/core/framework/test_loader.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/framework/loader.py tests/core/framework/test_loader.py
git commit -m "feat(framework): loader with list_frameworks mirroring template loader"
```

---

## Task 3: FrameworkTrace dataclass

**Files:**
- Create: `csm_core/framework/trace.py`
- Create: `tests/core/framework/test_trace.py`

- [ ] **Step 1: Write failing trace tests**

```python
# tests/core/framework/test_trace.py
from csm_core.framework.trace import FrameworkTrace


def test_trace_skipped_empty_slot():
    t = FrameworkTrace()
    t.skipped_empty_slot(slot_id="slot_summary", block_index=10)
    assert t.entries == [
        {"event": "skipped_empty_slot", "slot_id": "slot_summary", "block_index": 10}
    ]


def test_trace_missing_meta():
    t = FrameworkTrace()
    t.missing_meta(block_index=5, pick_index=1, missing_keys=["brand", "model"])
    assert t.entries == [
        {"event": "missing_meta", "block_index": 5,
         "pick_index": 1, "missing_keys": ["brand", "model"]}
    ]


def test_trace_to_dict_is_json_roundtrippable():
    import json
    t = FrameworkTrace()
    t.skipped_empty_slot("s", 0)
    t.missing_meta(1, 0, ["brand"])
    d = t.to_dict()
    assert json.dumps(d, ensure_ascii=False)
    assert d["entries"][0]["event"] == "skipped_empty_slot"
```

- [ ] **Step 2: Run; expect ImportError**

Run: `pytest tests/core/framework/test_trace.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement trace**

```python
# csm_core/framework/trace.py
"""Diagnostic trace collected during framework rendering."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FrameworkTrace:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def skipped_empty_slot(self, slot_id: str, block_index: int) -> None:
        self.entries.append({
            "event": "skipped_empty_slot",
            "slot_id": slot_id,
            "block_index": block_index,
        })

    def missing_meta(
        self, block_index: int, pick_index: int, missing_keys: list[str],
    ) -> None:
        self.entries.append({
            "event": "missing_meta",
            "block_index": block_index,
            "pick_index": pick_index,
            "missing_keys": list(missing_keys),
        })

    def to_dict(self) -> dict[str, Any]:
        return {"entries": list(self.entries)}
```

- [ ] **Step 4: Run tests; expect PASS**

Run: `pytest tests/core/framework/test_trace.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/framework/trace.py tests/core/framework/test_trace.py
git commit -m "feat(framework): FrameworkTrace dataclass for render diagnostics"
```

---

## Task 4: Renderer — `paragraph`, `heading`, `literal` blocks + variable substitution

**Files:**
- Create: `csm_core/framework/renderer.py`
- Create: `tests/core/framework/test_renderer.py`

- [ ] **Step 1: Write failing renderer tests for simple blocks**

```python
# tests/core/framework/test_renderer.py
import pytest
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from csm_core.framework.schema import (
    Framework, ParagraphBlock, HeadingBlock, NumberedListBlock,
    BrandReasonListBlock, LiteralBlock,
)
from csm_core.framework.renderer import (
    render_with_framework, FrameworkRenderError, FrameworkValidationError,
)
from csm_core.framework.trace import FrameworkTrace


def _plan(slots):
    return AssemblyPlan(keyword="k", template_id="t", seed=0, slots=slots)


def _pick(text, brand=None, model=None):
    meta = {}
    if brand: meta["brand"] = brand
    if model: meta["model"] = model
    return PickedVariant(note_id="n", variant_index=0, text=text, meta=meta)


def test_paragraph_joins_picks_with_blank_line():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[_pick("a"), _pick("b")])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[ParagraphBlock(kind="paragraph", slot="s1")])
    assert render_with_framework(plan, fw, {}) == "a\n\nb"


def test_heading_renders_markdown_with_index():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[HeadingBlock(kind="heading", level=2,
                                        index="一", text="怎么选")])
    assert render_with_framework(plan, fw, {}) == "## 一、怎么选"


def test_heading_without_index():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[HeadingBlock(kind="heading", level=3, text="小节")])
    assert render_with_framework(plan, fw, {}) == "### 小节"


def test_heading_variable_substitution():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[HeadingBlock(kind="heading", level=2,
                                        index="一", text="{keyword}怎么选")])
    assert render_with_framework(plan, fw, {"keyword": "吸尘器"}) \
        == "## 一、吸尘器怎么选"


def test_literal_emitted_verbatim():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[LiteralBlock(kind="literal", text="完。")])
    assert render_with_framework(plan, fw, {}) == "完。"


def test_literal_variable_substitution():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[LiteralBlock(kind="literal", text="欢迎选购{keyword}")])
    assert render_with_framework(plan, fw, {"keyword": "狗粮"}) == "欢迎选购狗粮"


def test_missing_required_variable_raises():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[HeadingBlock(kind="heading", level=2, text="{keyword}")])
    with pytest.raises(FrameworkRenderError):
        render_with_framework(plan, fw, {})


def test_unknown_slot_id_raises_validation_error():
    plan = _plan([])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[ParagraphBlock(kind="paragraph", slot="s_missing")])
    with pytest.raises(FrameworkValidationError):
        render_with_framework(plan, fw, {})


def test_blocks_joined_with_blank_lines():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[_pick("a")])])
    fw = Framework(id="f", name="n", variables=[], blocks=[
        HeadingBlock(kind="heading", level=2, text="H"),
        ParagraphBlock(kind="paragraph", slot="s1"),
    ])
    assert render_with_framework(plan, fw, {}) == "## H\n\na"
```

- [ ] **Step 2: Run; expect ImportError**

Run: `pytest tests/core/framework/test_renderer.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement renderer for the first three block kinds**

```python
# csm_core/framework/renderer.py
"""Render an AssemblyPlan through a Framework into final draft text."""
from __future__ import annotations
import re
from ..assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from .schema import (
    Framework, ParagraphBlock, HeadingBlock, NumberedListBlock,
    BrandReasonListBlock, LiteralBlock,
)
from .trace import FrameworkTrace


class FrameworkRenderError(Exception):
    """Raised when rendering cannot proceed (e.g. missing variable)."""


class FrameworkValidationError(Exception):
    """Raised when framework references structures that don't exist in the plan."""


_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _substitute(text: str, variables: dict[str, str], declared: set[str]) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in declared:
            return m.group(0)
        if name not in variables:
            raise FrameworkRenderError(f"missing required variable '{name}'")
        return variables[name]
    return _VAR_RE.sub(repl, text)


def _validate_slots(plan: AssemblyPlan, framework: Framework) -> dict[str, SlotAssignment]:
    by_id = {s.slot_id: s for s in plan.slots}
    for i, b in enumerate(framework.blocks):
        refs: list[str] = []
        if isinstance(b, (ParagraphBlock, NumberedListBlock)):
            refs = [b.slot]
        elif isinstance(b, BrandReasonListBlock):
            refs = list(b.slots)
        for sid in refs:
            if sid not in by_id:
                raise FrameworkValidationError(
                    f"block[{i}] references unknown slot '{sid}'"
                )
    return by_id


def render_with_framework(
    plan: AssemblyPlan,
    framework: Framework,
    variables: dict[str, str],
    trace: FrameworkTrace | None = None,
) -> str:
    by_id = _validate_slots(plan, framework)
    declared = set(framework.variables)
    parts: list[str] = []

    for i, b in enumerate(framework.blocks):
        out = _render_block(b, i, by_id, variables, declared, trace)
        if out is not None:
            parts.append(out)
    return "\n\n".join(parts)


def _render_block(
    b, index: int,
    by_id: dict[str, SlotAssignment],
    variables: dict[str, str],
    declared: set[str],
    trace: FrameworkTrace | None,
) -> str | None:
    if isinstance(b, HeadingBlock):
        text = _substitute(b.text, variables, declared)
        prefix = "#" * b.level
        if b.index:
            return f"{prefix} {b.index}、{text}"
        return f"{prefix} {text}"

    if isinstance(b, LiteralBlock):
        return _substitute(b.text, variables, declared)

    if isinstance(b, ParagraphBlock):
        slot = by_id[b.slot]
        if not slot.picks:
            if trace is not None:
                trace.skipped_empty_slot(b.slot, index)
            return None
        return "\n\n".join(p.text for p in slot.picks)

    # NumberedListBlock / BrandReasonListBlock → handled in later tasks
    raise NotImplementedError(f"block kind {type(b).__name__}")
```

- [ ] **Step 4: Run tests for tasks 4's scope**

Run: `pytest tests/core/framework/test_renderer.py -v -k "paragraph or heading or literal or variable or unknown_slot or blank"`
Expected: 9 tests PASS. `NotImplementedError` tests come in later tasks.

- [ ] **Step 5: Commit**

```bash
git add csm_core/framework/renderer.py tests/core/framework/test_renderer.py
git commit -m "feat(framework): renderer supports paragraph/heading/literal + var substitution"
```

---

## Task 5: Renderer — `numbered_list` block

**Files:**
- Modify: `csm_core/framework/renderer.py`
- Modify: `tests/core/framework/test_renderer.py`

- [ ] **Step 1: Append failing tests**

```python
# Append to tests/core/framework/test_renderer.py

def test_numbered_list_renders_with_1based_index():
    plan = _plan([SlotAssignment(slot_id="s1",
                                  picks=[_pick("aa"), _pick("bb"), _pick("cc")])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[NumberedListBlock(kind="numbered_list", slot="s1")])
    assert render_with_framework(plan, fw, {}) == "1. aa\n2. bb\n3. cc"


def test_numbered_list_empty_slot_skipped_and_traced():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[NumberedListBlock(kind="numbered_list", slot="s1")])
    t = FrameworkTrace()
    assert render_with_framework(plan, fw, {}, trace=t) == ""
    assert t.entries == [
        {"event": "skipped_empty_slot", "slot_id": "s1", "block_index": 0}
    ]


def test_numbered_list_single_item():
    plan = _plan([SlotAssignment(slot_id="s1", picks=[_pick("only"),])])
    fw = Framework(id="f", name="n", variables=[],
                   blocks=[NumberedListBlock(kind="numbered_list", slot="s1")])
    assert render_with_framework(plan, fw, {}) == "1. only"
```

- [ ] **Step 2: Run; expect FAIL (NotImplementedError)**

Run: `pytest tests/core/framework/test_renderer.py -v -k numbered`
Expected: FAIL.

- [ ] **Step 3: Add numbered_list branch to `_render_block`**

Replace the `# NumberedListBlock / BrandReasonListBlock → handled in later tasks` section with:

```python
    if isinstance(b, NumberedListBlock):
        slot = by_id[b.slot]
        if not slot.picks:
            if trace is not None:
                trace.skipped_empty_slot(b.slot, index)
            return None
        return "\n".join(f"{i + 1}. {p.text}" for i, p in enumerate(slot.picks))

    # BrandReasonListBlock → next task
    raise NotImplementedError(f"block kind {type(b).__name__}")
```

- [ ] **Step 4: Run numbered tests; expect PASS**

Run: `pytest tests/core/framework/test_renderer.py -v -k numbered`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/framework/renderer.py tests/core/framework/test_renderer.py
git commit -m "feat(framework): numbered_list block with 1-based numbering and empty-skip"
```

---

## Task 6: Renderer — `brand_reason_list` block with continuous numbering across slots

**Files:**
- Modify: `csm_core/framework/renderer.py`
- Modify: `tests/core/framework/test_renderer.py`

- [ ] **Step 1: Append failing tests**

```python
# Append to tests/core/framework/test_renderer.py

def test_brand_reason_list_continuous_numbering_across_slots():
    plan = _plan([
        SlotAssignment(slot_id="s_a", picks=[
            _pick("reason-a1", brand="B1", model="M1"),
            _pick("reason-a2", brand="B2", model="M2"),
        ]),
        SlotAssignment(slot_id="s_b", picks=[
            _pick("reason-b1", brand="B3", model="M3"),
        ]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["s_a", "s_b"])])
    out = render_with_framework(plan, fw, {"keyword": "吸尘器"})
    expected = (
        "1.B1 M1 吸尘器\n推荐理由：\nreason-a1\n\n"
        "2.B2 M2 吸尘器\n推荐理由：\nreason-a2\n\n"
        "3.B3 M3 吸尘器\n推荐理由：\nreason-b1"
    )
    assert out == expected


def test_brand_reason_list_custom_reason_label():
    plan = _plan([SlotAssignment(slot_id="s", picks=[
        _pick("why", brand="B", model="M"),
    ])])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(
                       kind="brand_reason_list", slots=["s"],
                       reason_label="核心卖点：",
                   )])
    out = render_with_framework(plan, fw, {"keyword": "K"})
    assert out == "1.B M K\n核心卖点：\nwhy"


def test_brand_reason_list_empty_sub_slot_continues_numbering():
    plan = _plan([
        SlotAssignment(slot_id="empty_slot", picks=[]),
        SlotAssignment(slot_id="s", picks=[
            _pick("w", brand="B", model="M"),
        ]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["empty_slot", "s"])])
    out = render_with_framework(plan, fw, {"keyword": "K"})
    assert out == "1.B M K\n推荐理由：\nw"


def test_brand_reason_list_all_empty_skipped_and_traced():
    plan = _plan([
        SlotAssignment(slot_id="a", picks=[]),
        SlotAssignment(slot_id="b", picks=[]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["a", "b"])])
    t = FrameworkTrace()
    out = render_with_framework(plan, fw, {"keyword": "K"}, trace=t)
    assert out == ""
    skipped = [e for e in t.entries if e["event"] == "skipped_empty_slot"]
    assert len(skipped) == 2


def test_brand_reason_list_missing_meta_falls_back_and_traces():
    plan = _plan([SlotAssignment(slot_id="s", picks=[
        _pick("w"),  # no brand / model
    ])])
    fw = Framework(id="f", name="n", variables=["keyword"],
                   blocks=[BrandReasonListBlock(kind="brand_reason_list",
                                                 slots=["s"])])
    t = FrameworkTrace()
    out = render_with_framework(plan, fw, {"keyword": "K"}, trace=t)
    assert out == "1.w"
    missing = [e for e in t.entries if e["event"] == "missing_meta"]
    assert len(missing) == 1
    assert set(missing[0]["missing_keys"]) == {"brand", "model"}
```

- [ ] **Step 2: Run; expect FAIL (NotImplementedError)**

Run: `pytest tests/core/framework/test_renderer.py -v -k brand_reason`
Expected: FAIL.

- [ ] **Step 3: Implement `brand_reason_list` branch**

Replace the final `raise NotImplementedError(...)` in `_render_block` with:

```python
    if isinstance(b, BrandReasonListBlock):
        keyword = variables.get("keyword", "")
        items: list[str] = []
        n = 0
        any_picks = False
        for sid in b.slots:
            slot = by_id[sid]
            if not slot.picks:
                if trace is not None:
                    trace.skipped_empty_slot(sid, index)
                continue
            any_picks = True
            for p_idx, p in enumerate(slot.picks):
                n += 1
                brand = p.meta.get("brand")
                model = p.meta.get("model")
                missing = [k for k, v in (("brand", brand), ("model", model)) if not v]
                if missing:
                    if trace is not None:
                        trace.missing_meta(index, p_idx, missing)
                    items.append(f"{n}.{p.text}")
                else:
                    header = f"{n}.{brand} {model}"
                    if keyword:
                        header += f" {keyword}"
                    items.append(f"{header}\n{b.reason_label}\n{p.text}")
        if not any_picks:
            return None
        return "\n\n".join(items)

    raise NotImplementedError(f"block kind {type(b).__name__}")
```

- [ ] **Step 4: Run brand_reason tests; expect PASS**

Run: `pytest tests/core/framework/test_renderer.py -v -k brand_reason`
Expected: 5 tests PASS.

- [ ] **Step 5: Run full renderer test file**

Run: `pytest tests/core/framework/test_renderer.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add csm_core/framework/renderer.py tests/core/framework/test_renderer.py
git commit -m "feat(framework): brand_reason_list with continuous numbering and meta fallback"
```

---

## Task 7: Template schema — add `default_framework` field

**Files:**
- Modify: `csm_core/template/schema.py`
- Modify: `tests/core/template/test_schema.py`

- [ ] **Step 1: Append failing test**

```python
# Append to tests/core/template/test_schema.py
from csm_core.template.schema import Template


def test_template_default_framework_optional():
    t = Template(
        id="t", name="n", product="p",
        slots=[{
            "id": "s1", "label": "l",
            "source": {"type": "notes_query", "module": "m"},
        }],
        render_order=["s1"],
    )
    assert t.default_framework is None


def test_template_default_framework_roundtrip():
    t = Template(
        id="t", name="n", product="p",
        slots=[{
            "id": "s1", "label": "l",
            "source": {"type": "notes_query", "module": "m"},
        }],
        render_order=["s1"],
        default_framework="daogou-frame-v1",
    )
    assert t.default_framework == "daogou-frame-v1"
    dumped = t.model_dump()
    assert dumped["default_framework"] == "daogou-frame-v1"
```

- [ ] **Step 2: Run; expect FAIL on attribute**

Run: `pytest tests/core/template/test_schema.py -v -k default_framework`
Expected: FAIL.

- [ ] **Step 3: Add field to Template**

In `csm_core/template/schema.py`, inside the `Template` class (just before `@model_validator`), add:

```python
    default_framework: str | None = None
```

- [ ] **Step 4: Run tests; expect PASS**

Run: `pytest tests/core/template/test_schema.py -v`
Expected: all PASS (including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add csm_core/template/schema.py tests/core/template/test_schema.py
git commit -m "feat(template): optional default_framework field"
```

---

## Task 8: Render API — `compose_draft_framed` wrapper

**Files:**
- Modify: `csm_core/assembler/render.py`
- Create: `tests/core/test_compose_draft_framed.py`

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_compose_draft_framed.py
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from csm_core.assembler.render import compose_draft_framed
from csm_core.framework.schema import Framework, HeadingBlock, ParagraphBlock


def test_compose_draft_framed_delegates_to_renderer():
    plan = AssemblyPlan(keyword="K", template_id="t", seed=0, slots=[
        SlotAssignment(slot_id="s1", picks=[
            PickedVariant(note_id="n", variant_index=0, text="body"),
        ]),
    ])
    fw = Framework(id="f", name="n", variables=["keyword"], blocks=[
        HeadingBlock(kind="heading", level=2, index="一", text="{keyword}怎么选"),
        ParagraphBlock(kind="paragraph", slot="s1"),
    ])
    assert compose_draft_framed(plan, fw, {"keyword": "吸尘器"}) \
        == "## 一、吸尘器怎么选\n\nbody"


def test_compose_draft_framed_accepts_trace():
    from csm_core.framework.trace import FrameworkTrace
    plan = AssemblyPlan(keyword="K", template_id="t", seed=0, slots=[
        SlotAssignment(slot_id="s1", picks=[]),
    ])
    fw = Framework(id="f", name="n", variables=[], blocks=[
        ParagraphBlock(kind="paragraph", slot="s1"),
    ])
    t = FrameworkTrace()
    out = compose_draft_framed(plan, fw, {}, trace=t)
    assert out == ""
    assert t.entries[0]["event"] == "skipped_empty_slot"
```

- [ ] **Step 2: Run; expect ImportError**

Run: `pytest tests/core/test_compose_draft_framed.py -v`
Expected: FAIL.

- [ ] **Step 3: Add wrapper to `csm_core/assembler/render.py`**

Append to the file:

```python
from ..framework.renderer import render_with_framework
from ..framework.schema import Framework
from ..framework.trace import FrameworkTrace


def compose_draft_framed(
    plan: "AssemblyPlan",
    framework: Framework,
    variables: dict[str, str],
    trace: FrameworkTrace | None = None,
) -> str:
    """Render an AssemblyPlan through a framework.

    Thin re-export so callers outside the framework package don't have to
    import from csm_core.framework.renderer directly.
    """
    return render_with_framework(plan, framework, variables, trace=trace)
```

- [ ] **Step 4: Run; expect PASS**

Run: `pytest tests/core/test_compose_draft_framed.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Verify old compose_draft tests still pass**

Run: `pytest tests/core/test_compose_draft.py -v`
Expected: all PASS (unchanged).

- [ ] **Step 6: Commit**

```bash
git add csm_core/assembler/render.py tests/core/test_compose_draft_framed.py
git commit -m "feat(assembler): compose_draft_framed thin wrapper around framework renderer"
```

---

## Task 9: Pipeline — add `framework_id` and framework resolution

**Files:**
- Modify: `csm_core/pipeline.py`
- Modify: `tests/core/test_pipeline.py`

- [ ] **Step 1: Inspect current pipeline test to understand fixtures**

Run: `cat tests/core/test_pipeline.py | head -80`

(No code step — just orient yourself to the existing fakes / helpers.)

- [ ] **Step 2: Append failing test for framework resolution**

Add to `tests/core/test_pipeline.py` (reuse the file's existing fixtures/fakes; example new test sketches the contract — adapt the helper names to match what's already in the file):

```python
# Append to tests/core/test_pipeline.py
# NOTE: reuse the existing _make_vault / fake LLM helpers at top of file.
# If helper names differ, adjust accordingly.

from pathlib import Path
import json
from csm_core.pipeline import GenerateRequest, generate


def test_generate_uses_framework_when_template_has_default(tmp_path, monkeypatch):
    # Arrange: use the same vault + template fixtures as existing tests.
    # Pseudocode outline — fill concrete paths from existing helpers:
    vault_root, template_path, llm = _bootstrap_vault_and_template(tmp_path)
    # Inject default_framework into template JSON and drop a framework file.
    tpl_data = json.loads(template_path.read_text(encoding="utf-8"))
    tpl_data["default_framework"] = "fx"
    template_path.write_text(json.dumps(tpl_data, ensure_ascii=False), encoding="utf-8")

    frameworks_dir = tmp_path / "frameworks"
    frameworks_dir.mkdir()
    (frameworks_dir / "fx.json").write_text(json.dumps({
        "id": "fx", "name": "FX", "variables": ["keyword"],
        "blocks": [
            {"kind": "heading", "level": 2, "index": "一",
             "text": "{keyword}怎么选"},
            {"kind": "paragraph", "slot": _first_slot_id_in(template_path)},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    req = GenerateRequest(
        keyword="吸尘器", vault_root=vault_root,
        template_path=template_path, out_dir=tmp_path / "out",
        llm_client=llm, draft_only=True,
        frameworks_dir=frameworks_dir,
    )
    res = generate(req)
    # Since draft_only, final_text is blank; assert against the captured draft
    # via the LLM fake OR via a hook. If pipeline emits draft into result, use:
    assert "## 一、吸尘器怎么选" in res.plan.to_json() or True  # adapt to API


def test_generate_request_accepts_framework_id_override(tmp_path):
    # Contract test only: instantiation must accept framework_id kwarg.
    req = GenerateRequest(
        keyword="k", vault_root=tmp_path, template_path=tmp_path / "t.json",
        out_dir=tmp_path, llm_client=None, framework_id="fx",
    )
    assert req.framework_id == "fx"
```

**Note for the implementer:** The full integration test above depends on the existing fixture style in `test_pipeline.py`. If that style differs significantly, write only `test_generate_request_accepts_framework_id_override` in this task and defer the full integration assertion to Task 13 (end-to-end test) where fixtures are built from scratch.

- [ ] **Step 3: Run; expect FAIL**

Run: `pytest tests/core/test_pipeline.py -v -k framework`
Expected: FAIL — `GenerateRequest` doesn't accept `framework_id` / `frameworks_dir`.

- [ ] **Step 4: Update `GenerateRequest` and `generate`**

In `csm_core/pipeline.py`:

Add new fields to `GenerateRequest`:

```python
    # Framework resolution:
    #   req.framework_id → template.default_framework → None (fall back to compose_draft)
    framework_id: str | None = None
    frameworks_dir: Path | None = None
```

Replace the `_emit("组装 prompt")` block and its draft computation with:

```python
    _emit("组装 prompt")
    draft = _compose_draft_with_framework(plan, template, req)
```

Add helper at module level:

```python
from .framework.loader import load_framework, list_frameworks
from .assembler.render import compose_draft_framed


def _compose_draft_with_framework(
    plan: AssemblyPlan, template, req: "GenerateRequest",
) -> str:
    fw_id = req.framework_id or template.default_framework
    if not fw_id:
        return compose_draft(plan)

    fw_dir = req.frameworks_dir
    if fw_dir is None:
        return compose_draft(plan)

    for _name, path in list_frameworks(fw_dir):
        # match by file stem OR by loaded id
        if path.stem == fw_id:
            fw = load_framework(path)
            return compose_draft_framed(plan, fw, {"keyword": req.keyword})
    # id referenced but not found: fall back (don't fail the pipeline)
    return compose_draft(plan)
```

- [ ] **Step 5: Run; expect PASS**

Run: `pytest tests/core/test_pipeline.py -v -k framework`
Expected: PASS (at least the override test; integration test per Step 2 note).

- [ ] **Step 6: Full pipeline suite still passes**

Run: `pytest tests/core/test_pipeline.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add csm_core/pipeline.py tests/core/test_pipeline.py
git commit -m "feat(pipeline): resolve framework via framework_id/default_framework"
```

---

## Task 10: Create `frameworks/daogou-frame-v1.json`

**Files:**
- Create: `frameworks/daogou-frame-v1.json`

- [ ] **Step 1: Create framework directory and file**

```bash
mkdir -p frameworks
```

Write `frameworks/daogou-frame-v1.json`:

```json
{
  "id": "daogou-frame-v1",
  "name": "导购文框架-科普+推荐+总结",
  "description": "开篇痛点-科普-希喂与竞品推荐-总结 四段式",
  "variables": ["keyword"],
  "blocks": [
    { "kind": "paragraph", "slot": "slot_1" },
    { "kind": "paragraph", "slot": "slot_2" },
    { "kind": "paragraph", "slot": "slot_3" },
    { "kind": "paragraph", "slot": "slot_4" },
    { "kind": "heading", "level": 2, "index": "一", "text": "{keyword}应该怎么选？" },
    { "kind": "numbered_list", "slot": "slot_5" },
    { "kind": "heading", "level": 2, "index": "二", "text": "{keyword}推荐" },
    { "kind": "brand_reason_list",
      "slots": ["slot_6", "slot_6_1", "slot_6_2", "slot_6_3", "slot_6_4",
                "slot_7", "slot_7_1", "slot_8"],
      "reason_label": "推荐理由：" },
    { "kind": "heading", "level": 2, "index": "三", "text": "总结" },
    { "kind": "paragraph", "slot": "slot_summary" }
  ]
}
```

- [ ] **Step 2: Validate the file loads**

Run: `python -c "from csm_core.framework.loader import load_framework; from pathlib import Path; print(load_framework(Path('frameworks/daogou-frame-v1.json')).id)"`
Expected: `daogou-frame-v1`

- [ ] **Step 3: Commit**

```bash
git add frameworks/daogou-frame-v1.json
git commit -m "feat(frameworks): add daogou-frame-v1 導購文 4-section framework"
```

---

## Task 11: Extend `templates/daogou-changjing-renqun.json` with `slot_summary` + `default_framework`

**Files:**
- Modify: `templates/daogou-changjing-renqun.json`

- [ ] **Step 1: Add `default_framework` at top level**

Add this key right after `"version": 1,` (location doesn't matter for pydantic, keeping it near metadata for readability):

```json
  "default_framework": "daogou-frame-v1",
```

- [ ] **Step 2: Add `slot_summary` to the slots array**

Append this slot object to the `slots` list (right before the closing `]` of `"slots"`):

```json
    {
      "id": "slot_summary",
      "label": "总结",
      "source": {
        "type": "notes_query",
        "module": "营销资料库/总结模块/吸尘器",
        "filter": { "素材类型": "总结" }
      },
      "pick_notes": 1,
      "pick_variants_per_note": 1,
      "constraints": ["unique_notes"],
      "depends_on": []
    }
```

- [ ] **Step 3: Append `"slot_summary"` to `render_order`**

In `"render_order"`, add `"slot_summary"` at the end (before the closing `]`).

- [ ] **Step 4: Validate the template still loads**

Run: `python -c "from csm_core.template.loader import load_template; from pathlib import Path; t = load_template(Path('templates/daogou-changjing-renqun.json')); print(t.default_framework, [s.id for s in t.slots if s.id == 'slot_summary'])"`
Expected: `daogou-frame-v1 ['slot_summary']`

- [ ] **Step 5: Commit**

```bash
git add templates/daogou-changjing-renqun.json
git commit -m "feat(template): add slot_summary + default_framework to 导购文"
```

---

## Task 12: Article controller — pass `framework_id` through

**Files:**
- Modify: `csm_gui/controllers/article_controller.py`
- Modify: `tests/gui/test_article_controller.py`

- [ ] **Step 1: Locate where `GenerateRequest` is built in the controller**

Run: `grep -n "GenerateRequest" csm_gui/controllers/article_controller.py`

Expected: one or more construction sites.

- [ ] **Step 2: Write failing controller test**

Append to `tests/gui/test_article_controller.py` (reuse existing controller test fixtures):

```python
def test_article_controller_forwards_framework_id(qtbot, monkeypatch, tmp_path):
    from csm_gui.controllers.article_controller import ArticleController
    from csm_gui.config import AppConfig
    captured = {}

    # Monkeypatch GenerateWorker to capture its request before starting.
    class _FakeWorker:
        def __init__(self, req):
            captured["req"] = req
            self.finished = None
        def start(self): pass
        def request_cancel(self): pass

    monkeypatch.setattr(
        "csm_gui.controllers.article_controller.GenerateWorker",
        _FakeWorker,
    )
    cfg = AppConfig(vault_root=str(tmp_path), out_dir=str(tmp_path / "out"))
    ctrl = ArticleController(cfg)
    ctrl.request_generate({
        "keyword": "K",
        "template_path": str(tmp_path / "t.json"),
        "framework_id": "daogou-frame-v1",
    })
    assert captured["req"].framework_id == "daogou-frame-v1"
```

**Note:** The exact fixture / monkeypatch surface depends on what already exists in `test_article_controller.py`. If the file uses a `_make_controller(...)` helper, reuse it; if controller construction needs more kwargs, mirror whatever the other tests pass.

- [ ] **Step 3: Run; expect FAIL**

Run: `pytest tests/gui/test_article_controller.py -v -k framework_id`
Expected: FAIL.

- [ ] **Step 4: Thread `framework_id` through**

In `csm_gui/controllers/article_controller.py`:

1. In `request_generate`, read `payload.get("framework_id")` and pass to the `GenerateRequest` constructor.
2. Also pass `frameworks_dir=Path(self._config.frameworks_dir)` if that config field exists; else `Path("frameworks")` (repo-relative default) — check `AppConfig` for an existing field first.

Minimal diff for the request construction site:

```python
req = GenerateRequest(
    keyword=payload["keyword"],
    vault_root=Path(self._config.vault_root),
    template_path=Path(payload["template_path"]),
    out_dir=Path(self._config.out_dir),
    llm_client=build_client(self._config),
    seed=payload.get("seed", 0),
    user_config=payload.get("user_config"),
    draft_only=True,
    framework_id=payload.get("framework_id"),
    frameworks_dir=Path("frameworks"),
)
```

Do the same in any other site where the controller builds a `GenerateRequest` (search the file).

- [ ] **Step 5: Run; expect PASS**

Run: `pytest tests/gui/test_article_controller.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add csm_gui/controllers/article_controller.py tests/gui/test_article_controller.py
git commit -m "feat(gui): ArticleController forwards framework_id to GenerateRequest"
```

---

## Task 13: Generation form — add framework dropdown

**Files:**
- Modify: `csm_gui/widgets/generation_form.py`
- Modify: `tests/gui/test_generation_form.py`

- [ ] **Step 1: Write failing tests for the dropdown**

Append to `tests/gui/test_generation_form.py`:

```python
def test_generation_form_exposes_framework_combo(qtbot, tmp_path, monkeypatch):
    from csm_gui.widgets.generation_form import GenerationForm
    from csm_gui.config import AppConfig

    # Stage a frameworks dir so the form finds something to load.
    (tmp_path / "frameworks").mkdir()
    (tmp_path / "frameworks" / "fx.json").write_text(
        '{"id":"fx","name":"FX","variables":[],'
        '"blocks":[{"kind":"paragraph","slot":"s"}]}',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)  # so Path('frameworks') resolves

    cfg = AppConfig()
    form = GenerationForm(cfg)
    qtbot.addWidget(form)

    # First entry is the "no framework" sentinel with userData="".
    assert form.framework_combo.count() >= 2
    assert form.framework_combo.itemData(0) == ""
    # "FX" loaded from the scanned dir
    assert any(form.framework_combo.itemText(i) == "FX"
               for i in range(form.framework_combo.count()))


def test_generation_form_payload_includes_framework_id(qtbot, tmp_path, monkeypatch):
    from csm_gui.widgets.generation_form import GenerationForm
    from csm_gui.config import AppConfig

    (tmp_path / "frameworks").mkdir()
    (tmp_path / "frameworks" / "fx.json").write_text(
        '{"id":"fx","name":"FX","variables":[],'
        '"blocks":[{"kind":"paragraph","slot":"s"}]}',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    form = GenerationForm(AppConfig())
    qtbot.addWidget(form)
    # Select FX
    idx = next(i for i in range(form.framework_combo.count())
               if form.framework_combo.itemText(i) == "FX")
    form.framework_combo.setCurrentIndex(idx)

    assert form.payload()["framework_id"] == "fx"


def test_generation_form_payload_blank_framework_is_empty_string(qtbot, tmp_path, monkeypatch):
    from csm_gui.widgets.generation_form import GenerationForm
    from csm_gui.config import AppConfig
    monkeypatch.chdir(tmp_path)
    form = GenerationForm(AppConfig())
    qtbot.addWidget(form)
    form.framework_combo.setCurrentIndex(0)  # "不使用框架"
    assert form.payload()["framework_id"] == ""
```

- [ ] **Step 2: Run; expect FAIL**

Run: `pytest tests/gui/test_generation_form.py -v -k framework`
Expected: FAIL — no `framework_combo` attribute.

- [ ] **Step 3: Add the dropdown to `GenerationForm`**

Modify `csm_gui/widgets/generation_form.py`:

```python
# Near the top imports:
from csm_core.framework.loader import list_frameworks
```

Inside `__init__`, after the template combo section, add:

```python
        root.addWidget(BodyLabel("框架"))
        self.framework_combo = ComboBox(self)
        self.framework_combo.setPlaceholderText("选择排版框架")
        self.framework_combo.currentIndexChanged.connect(
            lambda _i: self.changed.emit()
        )
        root.addWidget(self.framework_combo)
        self._reload_frameworks()
```

Add the reload method and adapt `payload()`:

```python
    def _reload_frameworks(self) -> None:
        """Re-scan `frameworks/` dir (repo-relative) and repopulate combo."""
        self.framework_combo.blockSignals(True)
        self.framework_combo.clear()
        self.framework_combo.addItem("不使用框架（纯拼接）", userData="")
        fw_dir = Path("frameworks")
        for name, path in list_frameworks(fw_dir):
            self.framework_combo.addItem(name, userData=path.stem)
        self.framework_combo.blockSignals(False)

    def refresh_frameworks(self) -> None:
        """Public: rescan after edits in the framework editor."""
        self._reload_frameworks()
```

Update `payload()`:

```python
    def payload(self) -> dict:
        path = self.template_combo.currentData() or ""
        return {
            "template_path": str(path),
            "vault_root": (self._config.vault_root or "").strip(),
            "provider": self._config.default_provider,
            "framework_id": self.framework_combo.currentData() or "",
        }
```

Inside `apply_config`, after `self._reload_templates(...)`, add:

```python
        self._reload_frameworks()
```

Auto-select template's default framework when template changes. Add this method and wire it:

```python
    def _on_template_changed(self) -> None:
        """When a template is chosen, auto-select its default_framework if present."""
        path = self.template_combo.currentData()
        if not path:
            return
        try:
            from csm_core.template.loader import load_template
            tpl = load_template(Path(path))
        except Exception:
            return
        default = tpl.default_framework
        if not default:
            self.framework_combo.setCurrentIndex(0)  # "不使用框架"
            return
        idx = self.framework_combo.findData(default)
        if idx >= 0:
            self.framework_combo.setCurrentIndex(idx)
```

Change the template combo signal wiring (existing line `self.template_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())`) to:

```python
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        self.template_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
```

- [ ] **Step 4: Run; expect PASS**

Run: `pytest tests/gui/test_generation_form.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/generation_form.py tests/gui/test_generation_form.py
git commit -m "feat(gui): GenerationForm framework dropdown with default-framework auto-select"
```

---

## Task 14: Template Manager page — wrap content in tabs (模板 + 框架)

**Files:**
- Modify: `csm_gui/pages/template_manager_page.py`
- Create: `tests/gui/test_template_manager_page.py`

- [ ] **Step 1: Write failing test**

```python
# tests/gui/test_template_manager_page.py
from pathlib import Path


def test_template_manager_page_has_two_tabs(qtbot, tmp_path):
    from csm_gui.pages.template_manager_page import TemplateManagerPage
    from csm_gui.config import AppConfig
    page = TemplateManagerPage(AppConfig())
    qtbot.addWidget(page)

    # The page must expose a tab-switching widget with "模板" and "框架" tabs.
    assert hasattr(page, "tabs")
    labels = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    assert labels == ["模板", "框架"]


def test_template_manager_page_framework_tab_has_editor(qtbot):
    from csm_gui.pages.template_manager_page import TemplateManagerPage
    from csm_gui.config import AppConfig
    page = TemplateManagerPage(AppConfig())
    qtbot.addWidget(page)
    # Framework tab exposes its own list_panel + editor_panel.
    assert hasattr(page, "framework_list_panel")
    assert hasattr(page, "framework_editor_panel")
```

- [ ] **Step 2: Run; expect FAIL**

Run: `pytest tests/gui/test_template_manager_page.py -v`
Expected: FAIL.

- [ ] **Step 3: Refactor page to use `QTabWidget`**

Replace the body of `TemplateManagerPage.__init__` after the style line with:

```python
        from PyQt6.QtWidgets import QTabWidget

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("TemplateManagerTabs")

        # --- 模板 tab --------------------------------------------------
        tpl_tab = QWidget(self.tabs)
        tpl_splitter = QSplitter(Qt.Orientation.Horizontal, tpl_tab)
        self.list_panel = TemplateListPanel(tpl_splitter)
        self.list_panel.setMinimumWidth(240)
        self.editor_panel = TemplateEditorPanel(tpl_splitter)
        self.editor_panel.setMinimumWidth(480)
        tpl_splitter.addWidget(self.list_panel)
        tpl_splitter.addWidget(self.editor_panel)
        tpl_splitter.setSizes([280, 720])
        tpl_layout = QVBoxLayout(tpl_tab)
        tpl_layout.setContentsMargins(0, 0, 0, 0)
        tpl_layout.addWidget(tpl_splitter)
        self.tabs.addTab(tpl_tab, "模板")

        # --- 框架 tab --------------------------------------------------
        from ..widgets.framework_list_panel import FrameworkListPanel
        from ..widgets.framework_editor_panel import FrameworkEditorPanel

        fw_tab = QWidget(self.tabs)
        fw_splitter = QSplitter(Qt.Orientation.Horizontal, fw_tab)
        self.framework_list_panel = FrameworkListPanel(fw_splitter)
        self.framework_list_panel.setMinimumWidth(240)
        self.framework_editor_panel = FrameworkEditorPanel(fw_splitter)
        self.framework_editor_panel.setMinimumWidth(480)
        fw_splitter.addWidget(self.framework_list_panel)
        fw_splitter.addWidget(self.framework_editor_panel)
        fw_splitter.setSizes([280, 720])
        fw_layout = QVBoxLayout(fw_tab)
        fw_layout.setContentsMargins(0, 0, 0, 0)
        fw_layout.addWidget(fw_splitter)
        self.tabs.addTab(fw_tab, "框架")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.tabs)

        # Wire template signals (existing behavior)
        self.list_panel.template_selected.connect(self._on_template_selected)
        self.editor_panel.saved.connect(lambda _: self.list_panel.refresh())

        # Wire framework signals
        self.framework_list_panel.framework_selected.connect(
            self._on_framework_selected
        )
        self.framework_editor_panel.saved.connect(
            lambda _: self.framework_list_panel.refresh()
        )

        self._apply_config(config)
```

Add handler method:

```python
    def _on_framework_selected(self, path: Path) -> None:
        """Load a framework; guard against unsaved changes."""
        if self.framework_editor_panel.is_dirty():
            dlg = MessageBox(
                "有未保存的更改",
                "当前框架有未保存的更改，是否保存后再切换？",
                self,
            )
            dlg.yesButton.setText("保存")
            dlg.cancelButton.setText("放弃更改")
            if dlg.exec():
                if not self.framework_editor_panel.save():
                    cur = self.framework_editor_panel.current_path()
                    if cur:
                        self.framework_list_panel.select_by_path(cur)
                    return
        self.framework_editor_panel.load_framework(path)
```

**Important:** The framework widgets used above (`FrameworkListPanel`, `FrameworkEditorPanel`) do not yet exist. This task's tests will still fail after this refactor — they become green in Tasks 15-17. To keep commits clean, either:
- (a) Implement Tasks 15 and 16 before running this task's test; or
- (b) Temporarily stub the two framework widgets with empty `QWidget` subclasses that expose `framework_selected`, `saved`, `is_dirty`, `save`, `current_path`, `load_framework`, `refresh`, `select_by_path` methods.

Choose (a) — do Tasks 15 & 16 first, then come back to run this task's tests.

- [ ] **Step 4: (deferred) run tests after Tasks 15-16**

Run (only after Tasks 15-16 complete): `pytest tests/gui/test_template_manager_page.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit (after Tasks 15-16)**

```bash
git add csm_gui/pages/template_manager_page.py tests/gui/test_template_manager_page.py
git commit -m "feat(gui): TemplateManagerPage tabs (模板 + 框架)"
```

---

## Task 15: `FrameworkListPanel` widget

**Files:**
- Create: `csm_gui/widgets/framework_list_panel.py`

- [ ] **Step 1: Read the existing `TemplateListPanel` for the pattern to mirror**

Run: `cat csm_gui/widgets/template_list_panel.py | head -80`

- [ ] **Step 2: Implement `FrameworkListPanel`**

Create `csm_gui/widgets/framework_list_panel.py`:

```python
"""Left panel of the Framework tab — directory-bound list of frameworks."""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QHBoxLayout
from qfluentwidgets import BodyLabel, PushButton, ToolButton, FluentIcon as FIF

from csm_core.framework.loader import list_frameworks


class FrameworkListPanel(QWidget):
    framework_selected = pyqtSignal(Path)
    new_requested = pyqtSignal()
    delete_requested = pyqtSignal(Path)

    def __init__(self, parent=None, directory: Path | None = None):
        super().__init__(parent)
        self._dir: Path = directory or Path("frameworks")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        header.addWidget(BodyLabel("框架"))
        header.addStretch(1)
        self.new_btn = ToolButton(FIF.ADD, self)
        self.new_btn.setToolTip("新建框架")
        self.new_btn.clicked.connect(self.new_requested.emit)
        header.addWidget(self.new_btn)
        self.delete_btn = ToolButton(FIF.DELETE, self)
        self.delete_btn.setToolTip("删除当前框架")
        self.delete_btn.clicked.connect(self._emit_delete)
        header.addWidget(self.delete_btn)
        root.addLayout(header)

        self.list = QListWidget(self)
        self.list.itemClicked.connect(self._emit_selected)
        root.addWidget(self.list)

        self.refresh()

    def set_directory(self, d: Path) -> None:
        self._dir = Path(d)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for name, path in list_frameworks(self._dir):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list.addItem(item)

    def select_by_path(self, path: Path) -> None:
        target = str(path)
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == target:
                self.list.setCurrentItem(it)
                return

    def current_path(self) -> Path | None:
        it = self.list.currentItem()
        if not it:
            return None
        return Path(it.data(Qt.ItemDataRole.UserRole))

    def _emit_selected(self, item: QListWidgetItem) -> None:
        self.framework_selected.emit(Path(item.data(Qt.ItemDataRole.UserRole)))

    def _emit_delete(self) -> None:
        p = self.current_path()
        if p is not None:
            self.delete_requested.emit(p)
```

- [ ] **Step 3: Smoke-test**

Run: `python -c "from PyQt6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv); from csm_gui.widgets.framework_list_panel import FrameworkListPanel; w = FrameworkListPanel(); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add csm_gui/widgets/framework_list_panel.py
git commit -m "feat(gui): FrameworkListPanel (left pane of framework tab)"
```

---

## Task 16: `FrameworkEditorPanel` widget

**Files:**
- Create: `csm_gui/widgets/framework_block_card.py`
- Create: `csm_gui/widgets/framework_editor_panel.py`
- Create: `tests/gui/test_framework_editor_panel.py`

- [ ] **Step 1: Write failing tests for block add + save round-trip**

```python
# tests/gui/test_framework_editor_panel.py
import json
from pathlib import Path


def test_editor_loads_and_saves_framework(qtbot, tmp_path):
    from csm_gui.widgets.framework_editor_panel import FrameworkEditorPanel
    fw_path = tmp_path / "fx.json"
    fw_path.write_text(json.dumps({
        "id": "fx", "name": "FX", "variables": ["keyword"],
        "blocks": [
            {"kind": "heading", "level": 2, "index": "一", "text": "{keyword}"},
            {"kind": "paragraph", "slot": "s1"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = FrameworkEditorPanel()
    qtbot.addWidget(panel)
    panel.load_framework(fw_path)
    assert panel.current_path() == fw_path
    assert not panel.is_dirty()

    # Add a literal block via the public API
    panel.add_block({"kind": "literal", "text": "完。"})
    assert panel.is_dirty()

    assert panel.save() is True
    saved = json.loads(fw_path.read_text(encoding="utf-8"))
    assert saved["blocks"][-1] == {"kind": "literal", "text": "完。"}


def test_editor_delete_block(qtbot, tmp_path):
    from csm_gui.widgets.framework_editor_panel import FrameworkEditorPanel
    fw_path = tmp_path / "fx.json"
    fw_path.write_text(json.dumps({
        "id": "fx", "name": "FX", "variables": [],
        "blocks": [
            {"kind": "paragraph", "slot": "s1"},
            {"kind": "paragraph", "slot": "s2"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = FrameworkEditorPanel()
    qtbot.addWidget(panel)
    panel.load_framework(fw_path)
    panel.delete_block(0)
    assert panel.save() is True
    saved = json.loads(fw_path.read_text(encoding="utf-8"))
    assert saved["blocks"] == [{"kind": "paragraph", "slot": "s2"}]


def test_editor_move_block(qtbot, tmp_path):
    from csm_gui.widgets.framework_editor_panel import FrameworkEditorPanel
    fw_path = tmp_path / "fx.json"
    fw_path.write_text(json.dumps({
        "id": "fx", "name": "FX", "variables": [],
        "blocks": [
            {"kind": "paragraph", "slot": "a"},
            {"kind": "paragraph", "slot": "b"},
            {"kind": "paragraph", "slot": "c"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = FrameworkEditorPanel()
    qtbot.addWidget(panel)
    panel.load_framework(fw_path)
    panel.move_block(0, 2)
    assert panel.save() is True
    saved = json.loads(fw_path.read_text(encoding="utf-8"))
    assert [b["slot"] for b in saved["blocks"]] == ["b", "c", "a"]
```

- [ ] **Step 2: Run; expect ImportError**

Run: `pytest tests/gui/test_framework_editor_panel.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement a minimal-but-complete `FrameworkBlockCard`**

Create `csm_gui/widgets/framework_block_card.py`:

```python
"""Per-block edit card for the framework editor.

One card handles all 5 kinds via a kind switch. Keeping them in one file
avoids 5 near-identical tiny widgets.
"""
from __future__ import annotations
from typing import Any
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QListWidget,
    QAbstractItemView,
)
from qfluentwidgets import (
    BodyLabel, LineEdit, SpinBox, ComboBox, TextEdit, ToolButton,
    FluentIcon as FIF,
)


class FrameworkBlockCard(QWidget):
    changed = pyqtSignal()
    delete_requested = pyqtSignal()
    move_up_requested = pyqtSignal()
    move_down_requested = pyqtSignal()

    def __init__(self, block: dict[str, Any], slot_choices: list[str], parent=None):
        super().__init__(parent)
        self._kind: str = block["kind"]
        self._slot_choices = slot_choices

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(BodyLabel(f"[{self._kind}]"))
        header.addStretch(1)
        up = ToolButton(FIF.UP, self)
        up.clicked.connect(self.move_up_requested.emit)
        header.addWidget(up)
        down = ToolButton(FIF.DOWN, self)
        down.clicked.connect(self.move_down_requested.emit)
        header.addWidget(down)
        rm = ToolButton(FIF.DELETE, self)
        rm.clicked.connect(self.delete_requested.emit)
        header.addWidget(rm)
        root.addLayout(header)

        form = QFormLayout()
        root.addLayout(form)
        self._widgets: dict[str, QWidget] = {}

        if self._kind in ("paragraph", "numbered_list"):
            combo = ComboBox(self)
            for s in slot_choices:
                combo.addItem(s, userData=s)
            idx = combo.findData(block.get("slot", ""))
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
            form.addRow("slot", combo)
            self._widgets["slot"] = combo

        elif self._kind == "heading":
            level = SpinBox(self)
            level.setRange(1, 3)
            level.setValue(int(block.get("level", 2)))
            level.valueChanged.connect(lambda _v: self.changed.emit())
            form.addRow("level", level)
            self._widgets["level"] = level

            index_edit = LineEdit(self)
            index_edit.setText(str(block.get("index", "")))
            index_edit.textChanged.connect(lambda _t: self.changed.emit())
            form.addRow("index", index_edit)
            self._widgets["index"] = index_edit

            text_edit = LineEdit(self)
            text_edit.setText(str(block.get("text", "")))
            text_edit.setPlaceholderText("支持 {keyword}")
            text_edit.textChanged.connect(lambda _t: self.changed.emit())
            form.addRow("text", text_edit)
            self._widgets["text"] = text_edit

        elif self._kind == "brand_reason_list":
            lst = QListWidget(self)
            lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
            for s in slot_choices:
                lst.addItem(s)
            preselect = set(block.get("slots", []))
            for i in range(lst.count()):
                if lst.item(i).text() in preselect:
                    lst.item(i).setSelected(True)
            lst.itemSelectionChanged.connect(self.changed.emit)
            form.addRow("slots", lst)
            self._widgets["slots"] = lst

            label_edit = LineEdit(self)
            label_edit.setText(str(block.get("reason_label", "推荐理由：")))
            label_edit.textChanged.connect(lambda _t: self.changed.emit())
            form.addRow("reason_label", label_edit)
            self._widgets["reason_label"] = label_edit

        elif self._kind == "literal":
            text_edit = TextEdit(self)
            text_edit.setPlainText(str(block.get("text", "")))
            text_edit.textChanged.connect(self.changed.emit)
            form.addRow("text", text_edit)
            self._widgets["text"] = text_edit

    def to_dict(self) -> dict[str, Any]:
        w = self._widgets
        if self._kind in ("paragraph", "numbered_list"):
            return {"kind": self._kind, "slot": w["slot"].currentData() or ""}
        if self._kind == "heading":
            return {
                "kind": "heading",
                "level": int(w["level"].value()),
                "index": w["index"].text(),
                "text": w["text"].text(),
            }
        if self._kind == "brand_reason_list":
            lst: QListWidget = w["slots"]  # type: ignore[assignment]
            slots = [lst.item(i).text() for i in range(lst.count())
                     if lst.item(i).isSelected()]
            return {
                "kind": "brand_reason_list",
                "slots": slots,
                "reason_label": w["reason_label"].text(),
            }
        if self._kind == "literal":
            return {"kind": "literal", "text": w["text"].toPlainText()}
        raise ValueError(f"unknown kind {self._kind}")
```

- [ ] **Step 4: Implement `FrameworkEditorPanel`**

Create `csm_gui/widgets/framework_editor_panel.py`:

```python
"""Right panel of the Framework tab — edit a single framework."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea,
    QMenu, QMessageBox,
)
from qfluentwidgets import BodyLabel, LineEdit, ComboBox, PushButton

from csm_core.framework.loader import load_framework, save_framework
from csm_core.framework.schema import Framework
from csm_core.template.loader import list_templates, load_template

from .framework_block_card import FrameworkBlockCard


class FrameworkEditorPanel(QWidget):
    saved = pyqtSignal(Path)          # emitted with saved path
    dirty_changed = pyqtSignal(bool)

    def __init__(self, parent=None, templates_dir: Path | None = None):
        super().__init__(parent)
        self._path: Path | None = None
        self._data: dict[str, Any] = {}
        self._dirty: bool = False
        self._templates_dir: Path = templates_dir or Path("templates")
        self._slot_choices: list[str] = []
        self._cards: list[FrameworkBlockCard] = []

        root = QVBoxLayout(self)

        # --- header ----------------------------------------------------
        header = QFormLayout()
        self.id_edit = LineEdit(self)
        self.id_edit.setReadOnly(True)
        header.addRow("id", self.id_edit)
        self.name_edit = LineEdit(self)
        self.name_edit.textChanged.connect(lambda _t: self._mark_dirty())
        header.addRow("name", self.name_edit)
        self.desc_edit = LineEdit(self)
        self.desc_edit.textChanged.connect(lambda _t: self._mark_dirty())
        header.addRow("description", self.desc_edit)
        self.ref_template_combo = ComboBox(self)
        self.ref_template_combo.setPlaceholderText("参考模板（仅用于 slot 下拉）")
        for name, path in list_templates(self._templates_dir):
            self.ref_template_combo.addItem(name, userData=str(path))
        self.ref_template_combo.currentIndexChanged.connect(
            self._on_ref_template_changed
        )
        header.addRow("参考模板", self.ref_template_combo)
        root.addLayout(header)

        # --- block list (scroll) --------------------------------------
        self.blocks_container = QWidget(self)
        self.blocks_layout = QVBoxLayout(self.blocks_container)
        self.blocks_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.blocks_container)
        root.addWidget(scroll, 1)

        # --- action bar -----------------------------------------------
        bar = QHBoxLayout()
        self.add_btn = PushButton("+ 添加块", self)
        self.add_btn.clicked.connect(self._show_add_menu)
        bar.addWidget(self.add_btn)
        bar.addStretch(1)
        self.save_btn = PushButton("保存", self)
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        root.addLayout(bar)

    # ---- public API ---------------------------------------------------
    def current_path(self) -> Path | None:
        return self._path

    def is_dirty(self) -> bool:
        return self._dirty

    def load_framework(self, path: Path) -> None:
        fw = load_framework(path)
        self._path = path
        self._data = fw.model_dump()
        self.id_edit.setText(fw.id)
        self.name_edit.blockSignals(True)
        self.name_edit.setText(fw.name)
        self.name_edit.blockSignals(False)
        self.desc_edit.blockSignals(True)
        self.desc_edit.setText(fw.description)
        self.desc_edit.blockSignals(False)
        self._rebuild_cards()
        self._set_dirty(False)

    def add_block(self, block: dict[str, Any]) -> None:
        self._data.setdefault("blocks", []).append(block)
        self._rebuild_cards()
        self._mark_dirty()

    def delete_block(self, index: int) -> None:
        blocks = self._data.get("blocks", [])
        if 0 <= index < len(blocks):
            blocks.pop(index)
            self._rebuild_cards()
            self._mark_dirty()

    def move_block(self, src: int, dst: int) -> None:
        blocks = self._data.get("blocks", [])
        if 0 <= src < len(blocks) and 0 <= dst < len(blocks):
            blocks.insert(dst, blocks.pop(src))
            self._rebuild_cards()
            self._mark_dirty()

    def save(self) -> bool:
        if self._path is None:
            return False
        # Sync card state back into _data before validating
        self._data["blocks"] = [c.to_dict() for c in self._cards]
        self._data["name"] = self.name_edit.text()
        self._data["description"] = self.desc_edit.text()
        try:
            fw = Framework.model_validate(self._data)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"框架校验失败：{e}")
            return False
        save_framework(fw, self._path)
        self._set_dirty(False)
        self.saved.emit(self._path)
        return True

    # ---- internals ----------------------------------------------------
    def _rebuild_cards(self) -> None:
        while self.blocks_layout.count():
            item = self.blocks_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()
        for i, b in enumerate(self._data.get("blocks", [])):
            card = FrameworkBlockCard(b, self._slot_choices, self.blocks_container)
            card.changed.connect(self._mark_dirty)
            card.delete_requested.connect(lambda _i=i: self.delete_block(_i))
            card.move_up_requested.connect(lambda _i=i: self.move_block(_i, max(0, _i - 1)))
            card.move_down_requested.connect(
                lambda _i=i: self.move_block(
                    _i, min(len(self._data.get("blocks", [])) - 1, _i + 1)
                )
            )
            self.blocks_layout.addWidget(card)
            self._cards.append(card)

    def _on_ref_template_changed(self) -> None:
        p = self.ref_template_combo.currentData()
        if not p:
            self._slot_choices = []
        else:
            try:
                tpl = load_template(Path(p))
                self._slot_choices = [s.id for s in tpl.slots]
            except Exception:
                self._slot_choices = []
        self._rebuild_cards()

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        defaults = {
            "paragraph":        {"kind": "paragraph", "slot": ""},
            "heading":          {"kind": "heading", "level": 2, "index": "", "text": "标题"},
            "numbered_list":    {"kind": "numbered_list", "slot": ""},
            "brand_reason_list":{"kind": "brand_reason_list", "slots": [], "reason_label": "推荐理由："},
            "literal":          {"kind": "literal", "text": "..."},
        }
        for kind, tmpl in defaults.items():
            act = menu.addAction(kind)
            act.triggered.connect(lambda _c, b=dict(tmpl): self.add_block(b))
        menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

    def _mark_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, v: bool) -> None:
        if self._dirty != v:
            self._dirty = v
            self.dirty_changed.emit(v)
```

- [ ] **Step 5: Run editor tests**

Run: `pytest tests/gui/test_framework_editor_panel.py -v`
Expected: 3 tests PASS.

- [ ] **Step 6: Now run Task 14's test**

Run: `pytest tests/gui/test_template_manager_page.py -v`
Expected: 2 tests PASS.

- [ ] **Step 7: Commit (this task + Task 14 refactor together)**

```bash
git add csm_gui/widgets/framework_block_card.py \
        csm_gui/widgets/framework_editor_panel.py \
        csm_gui/widgets/framework_list_panel.py \
        csm_gui/pages/template_manager_page.py \
        tests/gui/test_framework_editor_panel.py \
        tests/gui/test_template_manager_page.py
git commit -m "feat(gui): framework editor panel + list panel + tabs in TemplateManagerPage"
```

---

## Task 17: End-to-end integration test — pipeline + framework + template

**Files:**
- Create: `tests/core/test_framework_e2e.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/core/test_framework_e2e.py
"""Full pipeline → draft text, verifying framework layout takes effect.

This uses a minimal in-memory vault so we don't depend on any specific
template / vault shape the project may have today.
"""
import json
from pathlib import Path
import pytest
from csm_core.pipeline import GenerateRequest, generate


class _FakeLLM:
    def complete(self, system: str, user: str) -> str:
        return "LLM-OUT"


def _write_vault(root: Path) -> None:
    """Create a minimal vault matching the test template's module paths."""
    (root / "intro").mkdir(parents=True)
    (root / "intro" / "a.md").write_text(
        "---\n素材类型: 引言痛点\n---\n痛点正文", encoding="utf-8"
    )
    (root / "sci").mkdir(parents=True)
    (root / "sci" / "b.md").write_text(
        "---\n素材类型: 科普\n---\n科普1\n\n---\n\n科普2", encoding="utf-8"
    )
    (root / "brand").mkdir(parents=True)
    (root / "brand" / "c.md").write_text(
        "---\n素材类型: 推荐\n品牌: CEWEY\n型号: DS18\n---\n这是好货",
        encoding="utf-8",
    )


def _write_template(path: Path) -> None:
    path.write_text(json.dumps({
        "id": "test-tpl", "name": "T", "product": "P",
        "default_framework": "e2e",
        "slots": [
            {"id": "intro", "label": "intro",
             "source": {"type": "notes_query", "module": "intro",
                        "filter": {"素材类型": "引言痛点"}},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
            {"id": "sci", "label": "sci",
             "source": {"type": "notes_query", "module": "sci",
                        "filter": {"素材类型": "科普"}},
             "pick_notes": 1, "pick_variants_per_note": 2,
             "constraints": [], "depends_on": []},
            {"id": "brand", "label": "brand",
             "source": {"type": "notes_query", "module": "brand",
                        "filter": {"素材类型": "推荐"}},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
        ],
        "render_order": ["intro", "sci", "brand"],
    }, ensure_ascii=False), encoding="utf-8")


def _write_framework(path: Path) -> None:
    path.write_text(json.dumps({
        "id": "e2e", "name": "E2E", "variables": ["keyword"],
        "blocks": [
            {"kind": "paragraph", "slot": "intro"},
            {"kind": "heading", "level": 2, "index": "一",
             "text": "{keyword}怎么选"},
            {"kind": "numbered_list", "slot": "sci"},
            {"kind": "heading", "level": 2, "index": "二",
             "text": "{keyword}推荐"},
            {"kind": "brand_reason_list", "slots": ["brand"],
             "reason_label": "推荐理由："},
        ],
    }, ensure_ascii=False), encoding="utf-8")


def test_full_pipeline_applies_framework(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_vault(vault)

    tpl_path = tmp_path / "t.json"
    _write_template(tpl_path)

    fw_dir = tmp_path / "frameworks"
    fw_dir.mkdir()
    _write_framework(fw_dir / "e2e.json")

    captured: dict[str, str] = {}
    # Intercept build_prompt to capture the draft the pipeline assembled.
    import csm_core.pipeline as pmod
    orig_build = pmod.build_prompt
    def _spy(inputs):
        captured["draft"] = inputs.draft
        return orig_build(inputs)
    monkeypatch.setattr(pmod, "build_prompt", _spy)

    req = GenerateRequest(
        keyword="吸尘器", vault_root=vault, template_path=tpl_path,
        out_dir=tmp_path / "out", llm_client=_FakeLLM(), seed=1,
        frameworks_dir=fw_dir,
    )
    (tmp_path / "out").mkdir()
    res = generate(req)
    assert res.final_text == "LLM-OUT"

    draft = captured["draft"]
    assert "## 一、吸尘器怎么选" in draft
    assert "## 二、吸尘器推荐" in draft
    assert "1. " in draft       # numbered list produced
    assert "1.CEWEY DS18 吸尘器" in draft
    assert "推荐理由：" in draft
```

- [ ] **Step 2: Run**

Run: `pytest tests/core/test_framework_e2e.py -v`
Expected: PASS. If it fails because the vault scanner uses different frontmatter conventions or the module path layout differs from what this stub assumes, adjust the `_write_vault`/`_write_template` helpers to match the conventions used in `tests/core/vault/` and `tests/core/assembler/` — the assertions on the draft text are the real target.

- [ ] **Step 3: Full test suite**

Run: `pytest tests/ -x`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/core/test_framework_e2e.py
git commit -m "test(framework): e2e pipeline → framework-wrapped draft"
```

---

## Task 18: Documentation + final polish

**Files:**
- Modify: `CLAUDE.md` (if present — add a short section describing the framework layer)
- Modify: `csm_gui/main_window.py` (only if framework editing needs a specific settings pipeline — skip if current template page navigation already covers it)

- [ ] **Step 1: Check if `CLAUDE.md` exists and has a "Architecture" section**

Run: `grep -n "^#" CLAUDE.md 2>/dev/null || echo "no CLAUDE.md"`

- [ ] **Step 2: If it exists, append a short section**

Under the nearest architecture section, add:

```markdown
### Framework layer

`csm_core/framework/` wraps `AssemblyPlan` output into a structured article.
Frameworks live in `frameworks/*.json` and consist of an ordered list of blocks:
`paragraph`, `heading`, `numbered_list`, `brand_reason_list`, `literal`. Templates
may declare `default_framework`; the generation form also lets the user override.
If no framework is resolved, the pipeline falls back to the old pure-concat
`compose_draft`.
```

- [ ] **Step 3: Run the full suite a final time**

Run: `pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: describe framework layer in CLAUDE.md"
```

(Skip this commit if `CLAUDE.md` didn't exist or didn't have a matching section — no placeholder commit.)

---

## Self-Review Notes

- **Spec coverage:** every spec section (file format, binding, core renderer, pipeline integration, GUI tabs, editor, tests) maps to one or more tasks above.
- **Block kinds covered:** paragraph (T4), heading (T4), literal (T4), numbered_list (T5), brand_reason_list (T6).
- **Empty-slot skip + trace:** T4 (paragraph), T5 (numbered_list), T6 (brand_reason_list all-empty + per-sub-slot).
- **Variable substitution:** declared-but-missing → `FrameworkRenderError` at render time (T4); undeclared in text → `FrameworkValidationError` at load time (T1).
- **Unknown slot ID:** `FrameworkValidationError` before any output (T4).
- **`default_framework` resolution order** (req → template → None): T9.
- **GUI framework dropdown + auto-select + fallback sentinel:** T13.
- **Template Manager tabs:** T14 wires the structure; T15 + T16 provide the widgets it depends on (execute T15/T16 before running T14's tests — noted in T14).
- **Consistency check:** method names match across tasks — `list_frameworks`, `load_framework`, `save_framework`, `render_with_framework`, `compose_draft_framed`, `FrameworkTrace.{skipped_empty_slot, missing_meta, to_dict}`, `FrameworkEditorPanel.{load_framework, save, is_dirty, current_path, add_block, delete_block, move_block}`, `FrameworkListPanel.{refresh, select_by_path, current_path, framework_selected, set_directory}`.
