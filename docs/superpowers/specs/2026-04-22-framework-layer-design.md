# Framework Layer — Design

**Status:** Approved (2026-04-22)
**Target:** Introduce a structural "framework" layer that wraps slot outputs into a formatted article, decoupling "what material to fetch" (existing JSON templates) from "how to lay it out" (new framework files).

## Goal

Currently `compose_draft(plan)` in [csm_core/assembler/render.py](csm_core/assembler/render.py) concatenates each slot's picks with blank lines and nothing else — no chapter headings, no numbered lists, no "推荐理由：" labels. The reference document [导购文框架模板.md](导购文框架模板.md) describes a richer layout with:

- Fixed opening paragraphs (痛点/场景/人设/过渡)
- Numbered chapter headings (`一、XXX应该怎么选？`)
- Numbered bullet lists (`1. 科普点1`, `2. 科普点2`, ...)
- Brand + reason blocks with shared numbering across multiple slots
- A closing summary section

We want these structural elements applied at draft assembly time, driven by a reusable, user-editable framework file.

## Non-Goals

- **Templating DSL.** No Mustache/Jinja/Handlebars syntax in framework files. Structure is expressed as a typed block list.
- **Fully free-form layout.** Block kinds are enumerated. If a future framework needs a new layout, we add a new kind — we don't let users invent one via string templates.
- **Framework ↔ template hard binding.** Frameworks don't list which templates they're compatible with. Validation happens at runtime against whatever template is in use.
- **Backwards-compatibility shims for the old pure-concat output.** `compose_draft` stays as the fallback for templates without a framework, but we don't version or feature-flag framework adoption.

## Architecture Overview

Three layers, top to bottom:

1. **Framework file** (`frameworks/*.json`) — ordered list of typed blocks that reference slot IDs and external variables.
2. **Core renderer** (`csm_core/framework/`) — loads framework, validates against the current template and assembly plan, renders to a string.
3. **GUI** — framework selection in the generation form; framework editor merged into the existing Template Manager page as a second tab.

Data flow at generation time:

```
req.keyword + template ──► sampler ──► AssemblyPlan
                                │
                  framework ────┴──► renderer ──► draft text
```

If no framework is resolved (request didn't specify, template has no `default_framework`), the pipeline falls back to the current `compose_draft(plan)` output.

## Framework File Format

Path: `frameworks/<id>.json`. Loaded with the same pattern as `csm_core/template/loader.py`.

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

### Top-level fields

| Field | Required | Notes |
|---|---|---|
| `id` | ✅ | unique, used for selection and as filename stem |
| `name` | ✅ | display label in GUI |
| `description` | — | optional human note |
| `variables` | ✅ | list of variable names the framework consumes; must be a subset of `{"keyword"}` for v1 |
| `blocks` | ✅ | ordered list, see below |

### Block kinds

| `kind` | Required fields | Rendering |
|---|---|---|
| `paragraph` | `slot: string` | Joins all picks of the slot with `\n\n`. |
| `heading` | `level: 1\|2\|3`, `text: string`, optional `index: string` | Renders as Markdown heading. `index` prepended with `、` if present. `text` supports `{keyword}` substitution. Example: `## 一、无线吸尘器应该怎么选？` |
| `numbered_list` | `slot: string` | Each pick becomes `N. {pick.text}` on its own line, separated by `\n`. |
| `brand_reason_list` | `slots: string[]`, optional `reason_label` (default `"推荐理由："`) | Flattens picks across listed slots in the given order, assigns a **shared continuous numbering**. Each item renders as:<br>`N.{brand} {model} {keyword}`<br>`{reason_label}`<br>`{pick.text}` — separated from the next item by a blank line. `brand`/`model` come from `PickedVariant.meta`; if either is missing the item falls back to just `pick.text` prefixed by `N.` (logged as a warning in trace). |
| `literal` | `text: string` | Static string inserted verbatim. Intended for short fixed phrases only; `{keyword}` substitution supported. |

### Variable substitution

Simple `{varname}` replacement in `heading.text` and `literal.text`. If a declared variable is missing at render time, raise `FrameworkRenderError`. Unknown variables in text (not in `variables`) raise `FrameworkValidationError` at load time.

## Template Changes

Extend [csm_core/template/schema.py](csm_core/template/schema.py) `Template` model with:

```python
default_framework: str | None = None
```

Optional; backwards-compatible with existing templates that lack it.

Edit [templates/daogou-changjing-renqun.json](templates/daogou-changjing-renqun.json):

- Add `"default_framework": "daogou-frame-v1"`
- Add a new slot `slot_summary` pointing at the user's summary module (user has the vault folder but it's currently empty — sampler will surface an empty pool, framework renderer will skip the block and log a trace entry; this is the desired behavior).

## Core Renderer

New package `csm_core/framework/`:

- **`schema.py`** — pydantic models: `Framework`, `Block` (discriminated union by `kind`), and the individual block models (`ParagraphBlock`, `HeadingBlock`, `NumberedListBlock`, `BrandReasonListBlock`, `LiteralBlock`).
- **`loader.py`** — `load_framework(path) -> Framework`, `load_frameworks_dir(dir="frameworks") -> list[Framework]`. Validates `variables` subset, unknown `{...}` tokens in text fields.
- **`renderer.py`** — `render_with_framework(plan: AssemblyPlan, framework: Framework, variables: dict[str, str], trace: FrameworkTrace | None = None) -> str`.
- **`trace.py`** — `FrameworkTrace` dataclass with a list of entries: `skipped_empty_slot(slot_id, block_index)`, `missing_meta(block_index, pick_index, missing_keys)`. Trace is optional; if provided, caller can persist it next to the assembly trace.

### Rendering semantics

- Iterate `blocks` in order. For each block, check referenced slot(s) exist in the plan; if an ID is completely unknown raise `FrameworkValidationError`. Slot existence is validated once at the top of rendering before any output is produced, so errors fail fast.
- If a referenced slot exists but has zero picks, skip the entire block and record a trace entry. For `brand_reason_list`, skip only the empty sub-slots; render the rest with continuous numbering over whatever remains. If *all* referenced slots in a `brand_reason_list` are empty, skip the whole block.
- Blocks are joined by `\n\n` when concatenated into the final string. Empty-skip does not leave a double separator.
- `{keyword}` in text fields: if the framework declares `"keyword"` in `variables` but the caller doesn't pass it, raise `FrameworkRenderError` at render time (not at load time — load time can't know the variables dict).

### `compose_draft` and `compose_draft_framed`

- Keep `compose_draft(plan)` in [csm_core/assembler/render.py](csm_core/assembler/render.py) unchanged. It's the fallback.
- Add `compose_draft_framed(plan, framework, variables) -> str` in the same file as a thin re-export of `render_with_framework`, so callers don't have to reach across packages.

## Pipeline Integration

In [csm_core/pipeline.py](csm_core/pipeline.py):

- `GenerateRequest` gets an optional `framework_id: str | None = None`.
- `run_generate` resolution order for the active framework:
  1. `req.framework_id` if provided
  2. `template.default_framework` if set
  3. `None` → fall back to `compose_draft`
- When a framework is resolved, call `compose_draft_framed(plan, framework, {"keyword": req.keyword})`. Persist the framework trace alongside the existing assembly trace (same directory, filename suffixed `-framework-trace.json`).

## GUI Changes

### Generation form

[csm_gui/widgets/generation_form.py](csm_gui/widgets/generation_form.py) adds a "框架" dropdown below the template dropdown:

- Populated by scanning `frameworks/*.json` at form load (reuses the loader).
- First option is always `"不使用框架（纯拼接）"` mapped to `None`.
- Default selection: when a template is chosen, if that template has a `default_framework` that exists in the scanned list, select it; otherwise default to `None`.
- Selection is passed to `ArticleController` → `GenerateRequest.framework_id`.

### Template Manager page: add framework tab

[csm_gui/pages/template_manager_page.py](csm_gui/pages/template_manager_page.py) gains a top-level tab switcher (`QTabWidget` or `Pivot`, matching existing qfluentwidgets style):

- **Tab 1 — 模板**: the existing template list + template editor panel, unchanged.
- **Tab 2 — 框架**: new `FrameworkListPanel` (left) + `FrameworkEditorPanel` (right), laid out identically to match look-and-feel.

No new main-menu entry; users reach frameworks through the existing "模板管理" navigation item. This matches the user's explicit preference for a consistent UX.

### Framework editor panel

New widget `csm_gui/widgets/framework_editor_panel.py`:

- **Header section**: `id` (read-only after creation), `name`, `description`, variables chip list (read-only for v1, always `["keyword"]`).
- **"参考模板" selector** (not persisted to the framework file): a dropdown of available templates. Its only purpose is to populate slot-ID dropdowns in the block editor, so the user sees real slot labels while editing. Changing it does not modify the framework; it's a purely authoring-time convenience.
- **Blocks list**: vertical list of cards, one per block, with:
  - Drag handle for reordering
  - Kind-specific edit form inline
  - Delete button
- **"+ 添加块"** button opens a kind picker menu (`paragraph` / `heading` / `numbered_list` / `brand_reason_list` / `literal`).
- **Save / Save As** buttons write back to `frameworks/<id>.json` atomically (same pattern as the template editor's save).

Per-kind inline forms:
- `paragraph`, `numbered_list`: single slot dropdown (populated from the reference template).
- `heading`: `level` (radio 1/2/3), `index` text field, `text` text field with a hint "支持 {keyword}".
- `brand_reason_list`: multi-select list of slots, `reason_label` text field.
- `literal`: text area.

### New supporting widgets

- `csm_gui/widgets/framework_list_panel.py` — mirrors `template_list_panel.py`.
- `csm_gui/widgets/framework_block_card.py` — one card type with a kind switch; kept in a single file to avoid 5 near-identical tiny widgets.

## Testing

### Core

- `tests/core/framework/test_schema.py` — valid frameworks load; each invalid shape (unknown kind, unknown `{var}`, missing required field) raises with a clear message.
- `tests/core/framework/test_renderer.py`:
  - Each block kind renders the expected string for a hand-built `AssemblyPlan`.
  - Empty slot → block skipped, trace records the skip.
  - `brand_reason_list` across 3 slots produces continuous `1./2./3./...` numbering; sub-slot empty → numbering still continuous over remaining picks.
  - Missing `brand`/`model` meta → fallback rendering + trace warning.
  - Unknown slot ID in framework → `FrameworkValidationError` before any output.
  - Missing required variable → `FrameworkRenderError`.
- `tests/core/test_pipeline.py` — extend with a test that runs `run_generate` end-to-end with a stub vault, a template that has `default_framework`, and asserts the draft contains expected heading/numbering strings.

### GUI

- `tests/gui/test_generation_form.py` — extend: framework dropdown populated; selecting a template auto-selects its `default_framework`; `None` option works.
- `tests/gui/test_framework_editor_panel.py` — new: add block of each kind, reorder, delete, save round-trips through the loader.
- `tests/gui/test_template_manager_page.py` — new (or extend existing if present): tab switching preserves unsaved state in each tab; switching away and back doesn't lose edits.

## Open Questions

None. All design points resolved during brainstorming:

- Framework-template binding: soft binding via `default_framework` + runtime slot-ID validation.
- Empty slots: skip + trace, never error.
- Summary section: uses a real `slot_summary` in the JSON template, not hardcoded in the framework.
- Scope: full core + GUI + visual editor.
- `{keyword}` source: `req.keyword` from `GenerateRequest`, already populated by the generation form.

## Acceptance Criteria

1. A user can pick a framework in the generation form; generated draft matches the framework's structure.
2. `templates/daogou-changjing-renqun.json` with the new `slot_summary` and `default_framework`, paired with `frameworks/daogou-frame-v1.json`, produces a draft whose rendering matches the layout described in [导购文框架模板.md](导购文框架模板.md) (heading style, numbered lists, brand/reason blocks, continuous numbering across 希喂 + 竞品 slots).
3. An empty `slot_summary` results in the summary block being skipped silently; trace file records the skip.
4. The Template Manager page's new 框架 tab allows creating/editing/saving a framework without leaving the page; visual style matches the existing 模板 tab.
5. All new and existing core + GUI tests pass.
