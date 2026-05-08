# Skills Management + Template Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete dead/migrated template fields (`version`, `system_prompt_default`, `seo_defaults`), move their content into `.md` skill files, add a Skills management page in the nav, fix the new-template dialog, and auto-generate template IDs.

**Architecture:** One-shot migration script rewrites template JSONs (backup → strip fields → write skill file). `Template.extra="ignore"` keeps old JSONs loadable. `Template.default_skill_id` points to the template's migrated skill so the article page can preselect it. `build_prompt()` loses the template/SEO layers — skill .md becomes the sole system-prompt source. A new `SkillsPage` wraps `skill_dir` CRUD over `.md` files using `QPlainTextEdit`.

**Tech Stack:** Python 3.14, PyQt6, qfluentwidgets, pydantic v2, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-23-skills-and-template-cleanup-design.md`

**Branch note:** Per superpowers, this work should happen on a feature branch (e.g. `feat/skills-page`). If the human controller hasn't branched yet, branch before Task 1. All commits use Conventional Commits (`feat:`/`refactor:`/`test:`/`chore:`).

---

## File Structure

**Created:**
- `csm_gui/pages/skills_page.py` — new nav page (list + editor)
- `csm_gui/widgets/skill_editor_panel.py` — right-side editor widget
- `csm_gui/widgets/skill_list_panel.py` — left-side list + new/delete widget
- `csm_gui/widgets/skill_skeleton.py` — constant holding the skeleton markdown for new skills
- `scripts/migrate_template_to_skill.py` — one-shot migration CLI
- `tests/scripts/test_migrate_template_to_skill.py`
- `tests/gui/test_skills_page.py`
- `tests/gui/test_skill_list_panel.py`
- `tests/gui/test_skill_editor_panel.py`

**Modified:**
- `csm_core/template/schema.py` — delete `SEODefaults`, delete `version/system_prompt_default/seo_defaults`, add `default_skill_id: str | None`, add `model_config = ConfigDict(extra="ignore")`
- `csm_core/llm/prompts.py` — drop `_format_seo_block`, drop `template_system_prompt`/`seo` from `PromptInputs`
- `csm_core/pipeline.py` — update `build_prompt` call site
- `csm_core/batch/runner.py` — update `build_prompt` call site, auto-load `template.default_skill_id` from `skill_dir`
- `csm_core/batch/runner.py` signature — accept `skill_dir: Path | None` (for auto-loading template default)
- `csm_gui/widgets/template_list_panel.py` — dialog parent → `window()`, drop id field, auto-generate id
- `csm_gui/widgets/template_editor_panel.py` — delete 版本 / 系统提示词 / SEO 默认参数 groups, add 默认 Skill combo
- `csm_gui/widgets/controls_panel.py` — accept `preferred_skill: str | None`, preselect it
- `csm_gui/pages/article_page.py` — pass template.default_skill_id to ControlsPanel when loading a result
- `csm_gui/main_window.py` — register SkillsPage in nav
- `tests/core/template/test_schema.py` — update for removed fields + `extra="ignore"`
- `tests/core/test_prompts.py` — update for simplified `build_prompt`
- `tests/core/test_pipeline.py` — update for simplified pipeline call
- `tests/core/batch/test_runner.py` — update for simplified batch call
- `tests/gui/test_template_editor.py` — update for removed groups + added combo
- `tests/gui/test_template_list_panel.py` — update for 2-field dialog + auto id

**Deleted:** none (data files stay; schema code drops classes).

---

## Task 1: Template Schema — Drop Dead Fields, Add `default_skill_id`, Forward-Compat

**Files:**
- Modify: `csm_core/template/schema.py:120-135`
- Modify: `tests/core/template/test_schema.py`

- [ ] **Step 1: Write the failing schema test**

Add to `tests/core/template/test_schema.py`:

```python
from pydantic import ValidationError
from csm_core.template.schema import Template, LiteralBlock


def _minimal_template_dict(**overrides) -> dict:
    d = {
        "id": "t1",
        "name": "T",
        "product": "吸尘器",
        "blocks": [{"kind": "literal", "id": "lit", "text": "hi"}],
    }
    d.update(overrides)
    return d


def test_template_loads_without_dead_fields():
    tpl = Template.model_validate(_minimal_template_dict())
    assert tpl.id == "t1"
    # New optional field defaults to None.
    assert tpl.default_skill_id is None


def test_template_silently_ignores_legacy_fields():
    """Old JSONs still carry version / system_prompt_default / seo_defaults.
    extra='ignore' lets them load; values are discarded."""
    legacy = _minimal_template_dict(
        version=3,
        system_prompt_default="you are an editor",
        seo_defaults={"target_word_count": [500, 800], "tone": "冷静"},
    )
    tpl = Template.model_validate(legacy)
    assert not hasattr(tpl, "version")
    assert not hasattr(tpl, "system_prompt_default")
    assert not hasattr(tpl, "seo_defaults")


def test_template_accepts_default_skill_id():
    tpl = Template.model_validate(_minimal_template_dict(default_skill_id="xhs"))
    assert tpl.default_skill_id == "xhs"
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/core/template/test_schema.py::test_template_loads_without_dead_fields tests/core/template/test_schema.py::test_template_silently_ignores_legacy_fields tests/core/template/test_schema.py::test_template_accepts_default_skill_id -v`
Expected: FAIL — `default_skill_id` doesn't exist yet; legacy fields currently parse and keep values.

- [ ] **Step 3: Edit `csm_core/template/schema.py`**

Replace lines 120-135 (SEODefaults class + Template class) with:

```python
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Template(BaseModel):
    # extra='ignore' tolerates legacy JSONs that still carry
    # version/system_prompt_default/seo_defaults after migration; new saves
    # won't emit those fields because they're not declared here.
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    product: str
    default_skill_id: str | None = None
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_structure(self):
        # ... (existing body unchanged; keep the walk/check_deps logic)
```

Keep the existing `_validate_structure` body verbatim. Delete the entire `SEODefaults` class (lines 120-125).

- [ ] **Step 4: Run schema tests, expect pass**

Run: `pytest tests/core/template/test_schema.py -v`
Expected: PASS (new 3 + existing tests still green).

- [ ] **Step 5: Search for any lingering `SEODefaults` imports**

Run: `grep -rn "SEODefaults" csm_core csm_gui tests`
Expected: hits in `csm_core/llm/prompts.py`, `csm_gui/widgets/template_list_panel.py`, `csm_gui/widgets/template_editor_panel.py`, `tests/core/test_prompts.py`. These are addressed in later tasks.

- [ ] **Step 6: Commit**

```bash
git add csm_core/template/schema.py tests/core/template/test_schema.py
git commit -m "refactor(schema): drop SEODefaults/version/system_prompt, add default_skill_id"
```

---

## Task 2: Simplify `build_prompt()` — Skill Becomes Sole System Prompt

**Files:**
- Modify: `csm_core/llm/prompts.py` (whole file)
- Modify: `tests/core/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Replace `tests/core/test_prompts.py` contents with:

```python
from csm_core.llm.prompts import PromptInputs, build_prompt


def test_build_prompt_uses_skill_only_as_system():
    system, user = build_prompt(PromptInputs(
        user_skill_prompt="be concise.",
        keyword="吸尘器",
        draft="draft text",
    ))
    assert system == "be concise."
    assert "吸尘器" in user
    assert "draft text" in user


def test_build_prompt_empty_skill_yields_empty_system():
    system, user = build_prompt(PromptInputs(
        user_skill_prompt=None,
        keyword="吸尘器",
        draft="draft",
    ))
    assert system == ""
    assert "【毛坯文】" in user


def test_build_prompt_strips_skill_whitespace():
    system, _ = build_prompt(PromptInputs(
        user_skill_prompt="   \n  hello \n ",
        keyword="k",
        draft="d",
    ))
    assert system == "hello"
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/core/test_prompts.py -v`
Expected: FAIL — `PromptInputs` still requires `template_system_prompt` and `seo`.

- [ ] **Step 3: Rewrite `csm_core/llm/prompts.py`**

Replace the entire file with:

```python
"""Compose prompt from a single user-selected skill. Template-level
system_prompt / SEO constraints were folded into the skill .md at migration
time (see scripts/migrate_template_to_skill.py); they no longer live on
the Template model."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PromptInputs:
    user_skill_prompt: str | None
    keyword: str
    draft: str


def build_prompt(inputs: PromptInputs) -> tuple[str, str]:
    system = (inputs.user_skill_prompt or "").strip()
    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"【毛坯文】\n{inputs.draft}\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
    )
    return system, user
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/core/test_prompts.py -v`
Expected: PASS (3/3).

- [ ] **Step 5: Commit**

```bash
git add csm_core/llm/prompts.py tests/core/test_prompts.py
git commit -m "refactor(prompts): skill .md is now the only system-prompt source"
```

---

## Task 3: Update `pipeline.py` Call Site

**Files:**
- Modify: `csm_core/pipeline.py:72-77`
- Modify: `tests/core/test_pipeline.py`

- [ ] **Step 1: Update existing pipeline test**

Find the test(s) in `tests/core/test_pipeline.py` that construct `GenerateRequest` or assert on the prompt system layer. Adjust so they no longer depend on `template.system_prompt_default` or `template.seo_defaults`. Representative fix:

```python
# Before any test that reads prompt_snapshot["system"]:
req = GenerateRequest(
    keyword="k", vault_root=vault, template_path=tpl_path,
    out_dir=out, llm_client=client,
    user_skill_prompt="skill text",  # now the ONLY system layer
)
result = generate(req)
with open(result.assembly_json_path.replace(".json", ".prompt.json")) as f:
    snap = json.load(f)
# (adapt to however snapshot is actually persisted — just drop any
# "SEO 约束" / "template_system_prompt" assertions)
```

If any test builds a Template with `system_prompt_default=` or `seo_defaults=`, remove those kwargs — the schema no longer accepts them (they're `extra="ignore"` so construction still works, but it's dead code; prefer removal).

- [ ] **Step 2: Run pipeline tests, see failure**

Run: `pytest tests/core/test_pipeline.py -v`
Expected: FAIL — `build_prompt` called with removed `template_system_prompt` / `seo` kwargs.

- [ ] **Step 3: Update `csm_core/pipeline.py`**

Replace lines 72-77:

```python
    system, user = build_prompt(PromptInputs(
        user_skill_prompt=req.user_skill_prompt,
        keyword=req.keyword, draft=draft,
    ))
```

- [ ] **Step 4: Run pipeline tests, expect pass**

Run: `pytest tests/core/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add csm_core/pipeline.py tests/core/test_pipeline.py
git commit -m "refactor(pipeline): drop template_system_prompt/seo from build_prompt call"
```

---

## Task 4: Update `batch/runner.py` + Auto-Load Template's Default Skill

Batch generation currently passes `user_skill_prompt=None`. After migration, each template has a `default_skill_id`; the runner should load that skill's `.md` from `skill_dir` and use it as the prompt.

**Files:**
- Modify: `csm_core/batch/runner.py` (signature + call site)
- Modify: `tests/core/batch/test_runner.py`

- [ ] **Step 1: Read current runner signature**

Run: `sed -n '1,60p' csm_core/batch/runner.py` (via Bash) OR use Read tool on `csm_core/batch/runner.py` lines 1-60. Locate the `run_batch` function signature so you can add `skill_dir: Path | None = None` without breaking existing callers.

- [ ] **Step 2: Write the failing test**

Add to `tests/core/batch/test_runner.py`:

```python
def test_runner_loads_default_skill_from_template(tmp_path, monkeypatch):
    """When template.default_skill_id is set and skill_dir points at a dir
    containing <id>.md, the runner reads it and passes its content as
    user_skill_prompt."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    (skill_dir / "polish.md").write_text("SKILL BODY", encoding="utf-8")

    captured = {}

    class FakeLLM:
        def complete(self, system, user):
            captured["system"] = system
            return "final"

    # (Use the existing fixtures / helpers in this test file to build a
    # minimal Template with default_skill_id="polish" and run run_batch.
    # Assert:)
    # assert captured["system"] == "SKILL BODY"
```

(The subagent implementing this task should fill in the fixture plumbing using whatever `test_runner.py` already provides — a minimal `Template`, `VaultIndex`, `out_dir`, etc. Don't invent new fixtures; reuse.)

- [ ] **Step 3: Run test, expect failure**

Run: `pytest tests/core/batch/test_runner.py::test_runner_loads_default_skill_from_template -v`
Expected: FAIL — runner doesn't know about `skill_dir` yet.

- [ ] **Step 4: Update runner signature + body**

In `csm_core/batch/runner.py`:
- Add `skill_dir: Path | None = None` to `run_batch` signature.
- Before the per-keyword loop, compute:

```python
    # Resolve default skill once per batch. If the template has no default
    # or the .md is missing, fall back to empty system prompt (same as before
    # migration when a template had no system_prompt_default).
    user_skill_prompt: str | None = None
    if template.default_skill_id and skill_dir is not None:
        skill_path = Path(skill_dir) / f"{template.default_skill_id}.md"
        if skill_path.is_file():
            user_skill_prompt = skill_path.read_text(encoding="utf-8")
```

- Replace the existing `build_prompt(PromptInputs(...))` block (lines 73-79) with:

```python
            system, user = build_prompt(PromptInputs(
                user_skill_prompt=user_skill_prompt,
                keyword=keyword,
                draft=draft,
            ))
```

- [ ] **Step 5: Run batch runner tests, expect pass**

Run: `pytest tests/core/batch/test_runner.py -v`
Expected: PASS.

- [ ] **Step 6: Wire `skill_dir` in `csm_gui/controllers/batch_controller.py`**

Find where `BatchController` calls `run_batch` and add `skill_dir=Path(self._config.skill_dir) if self._config.skill_dir else None`. Read the file first to locate the exact call.

- [ ] **Step 7: Commit**

```bash
git add csm_core/batch/runner.py tests/core/batch/test_runner.py csm_gui/controllers/batch_controller.py
git commit -m "feat(batch): auto-load template.default_skill_id from skill_dir"
```

---

## Task 5: Migration Script

One-shot CLI: scans a templates directory, for each `.json` renders a `.md` next to the current `skill_dir` containing the template's old `system_prompt_default + SEO block`, writes `<template-id>-migrated.md`, updates the template JSON by (a) setting `default_skill_id = "<id>-migrated"`, (b) removing the three legacy fields, and (c) backing the original up to `<file>.bak`.

**Files:**
- Create: `scripts/migrate_template_to_skill.py`
- Create: `tests/scripts/test_migrate_template_to_skill.py`

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/__init__.py` if missing (empty file).

Create `tests/scripts/test_migrate_template_to_skill.py`:

```python
"""Tests for one-shot template→skill migration."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from scripts.migrate_template_to_skill import migrate_file, migrate_directory


def _write_legacy_template(dir_: Path, tid: str, sys_prompt: str, seo: dict) -> Path:
    p = dir_ / f"{tid}.json"
    p.write_text(json.dumps({
        "id": tid, "name": tid, "product": "吸尘器",
        "version": 1,
        "system_prompt_default": sys_prompt,
        "seo_defaults": seo,
        "blocks": [{"kind": "literal", "id": "lit", "text": "hi"}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_migrate_file_writes_skill_and_rewrites_json(tmp_path):
    tpl_dir = tmp_path / "templates"; tpl_dir.mkdir()
    skill_dir = tmp_path / "skills"; skill_dir.mkdir()

    tpl = _write_legacy_template(
        tpl_dir, "tpl-a",
        sys_prompt="你是家电编辑。",
        seo={
            "target_word_count": [1500, 2000],
            "keyword_density": [5, 8],
            "tone": "小红书笔记体",
            "force_h2": True,
            "long_tail_keywords": ["家用吸尘器推荐", "宠物吸尘器对比"],
        },
    )

    result = migrate_file(tpl, skill_dir)
    assert result is not None
    skill_path = skill_dir / "tpl-a-migrated.md"
    assert skill_path.is_file()

    content = skill_path.read_text(encoding="utf-8")
    assert "你是家电编辑。" in content
    assert "1500-2000" in content
    assert "5-8" in content
    assert "小红书笔记体" in content
    assert "家用吸尘器推荐" in content
    assert "必须使用 H2" in content

    rewritten = json.loads(tpl.read_text(encoding="utf-8"))
    assert rewritten["default_skill_id"] == "tpl-a-migrated"
    assert "version" not in rewritten
    assert "system_prompt_default" not in rewritten
    assert "seo_defaults" not in rewritten

    backup = tpl.with_suffix(tpl.suffix + ".bak")
    assert backup.is_file()
    # Backup preserves the original legacy structure.
    assert "system_prompt_default" in json.loads(backup.read_text(encoding="utf-8"))


def test_migrate_file_is_idempotent(tmp_path):
    tpl_dir = tmp_path / "t"; tpl_dir.mkdir()
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    tpl = _write_legacy_template(tpl_dir, "x", "s", {
        "target_word_count": [100, 200], "keyword_density": [1, 2],
        "tone": "t", "force_h2": False, "long_tail_keywords": [],
    })

    migrate_file(tpl, skill_dir)
    second = migrate_file(tpl, skill_dir)
    assert second is None  # already migrated — skip


def test_migrate_directory_migrates_all_and_skips_non_json(tmp_path):
    tpl_dir = tmp_path / "t"; tpl_dir.mkdir()
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    _write_legacy_template(tpl_dir, "a", "A", {
        "target_word_count": [1, 2], "keyword_density": [1, 2],
        "tone": "t", "force_h2": True, "long_tail_keywords": [],
    })
    _write_legacy_template(tpl_dir, "b", "B", {
        "target_word_count": [1, 2], "keyword_density": [1, 2],
        "tone": "t", "force_h2": True, "long_tail_keywords": [],
    })
    (tpl_dir / "README.txt").write_text("not a template", encoding="utf-8")

    results = migrate_directory(tpl_dir, skill_dir)
    assert len(results) == 2
    assert (skill_dir / "a-migrated.md").is_file()
    assert (skill_dir / "b-migrated.md").is_file()


def test_migrate_file_noop_when_no_legacy_fields(tmp_path):
    """A template that's already been migrated (no legacy fields) should be
    skipped, not overwritten."""
    tpl_dir = tmp_path / "t"; tpl_dir.mkdir()
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    p = tpl_dir / "clean.json"
    p.write_text(json.dumps({
        "id": "clean", "name": "c", "product": "p",
        "default_skill_id": "some-skill",
        "blocks": [{"kind": "literal", "id": "lit", "text": "hi"}],
    }, ensure_ascii=False), encoding="utf-8")

    assert migrate_file(p, skill_dir) is None
```

- [ ] **Step 2: Run tests, expect failure (import error)**

Run: `pytest tests/scripts/test_migrate_template_to_skill.py -v`
Expected: FAIL — `scripts.migrate_template_to_skill` doesn't exist.

- [ ] **Step 3: Create `scripts/migrate_template_to_skill.py`**

```python
"""One-shot migration: fold template.system_prompt_default + template.seo_defaults
into a standalone .md skill file and strip those fields from the template JSON.

Usage:
    python -m scripts.migrate_template_to_skill <templates_dir> <skill_dir>

Idempotent: re-running on an already-migrated template is a no-op. The original
JSON is backed up as <file>.bak before rewriting.
"""
from __future__ import annotations
import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LEGACY_FIELDS = ("version", "system_prompt_default", "seo_defaults")


def _render_skill_md(tid: str, sys_prompt: str, seo: dict) -> str:
    """Build the markdown body for the migrated skill file."""
    parts: list[str] = []
    if sys_prompt.strip():
        parts.append(sys_prompt.strip())

    seo_lines: list[str] = ["## SEO 约束"]
    wc = seo.get("target_word_count") or [1500, 2000]
    kd = seo.get("keyword_density") or [5, 8]
    seo_lines.append(f"- 目标字数：{wc[0]}-{wc[1]} 字")
    seo_lines.append(f"- 主关键词密度：{kd[0]}-{kd[1]}%")
    seo_lines.append(f"- 语气风格：{seo.get('tone', '').strip() or '自然'}")
    if seo.get("force_h2"):
        seo_lines.append("- 必须使用 H2 (##) 段落标题分隔核心板块")
    long_tail = seo.get("long_tail_keywords") or []
    if long_tail:
        seo_lines.append(f"- 长尾关键词（自然嵌入）：{', '.join(long_tail)}")
    parts.append("\n".join(seo_lines))

    body = "\n\n".join(parts).rstrip() + "\n"
    header = f"# {tid} — 迁移自模板基础设置\n\n"
    return header + body


def migrate_file(tpl_path: Path, skill_dir: Path) -> Path | None:
    """Migrate one template file. Returns the path to the new skill .md, or
    None if the template had no legacy fields (already migrated / never had any)."""
    tpl_path = Path(tpl_path); skill_dir = Path(skill_dir)
    data = json.loads(tpl_path.read_text(encoding="utf-8"))

    if not any(k in data for k in LEGACY_FIELDS):
        logger.info("%s: no legacy fields, skipping", tpl_path.name)
        return None

    tid = data.get("id") or tpl_path.stem
    new_skill_id = f"{tid}-migrated"
    skill_path = skill_dir / f"{new_skill_id}.md"

    # Backup the original JSON before we touch it.
    backup = tpl_path.with_suffix(tpl_path.suffix + ".bak")
    shutil.copy2(tpl_path, backup)

    # Write skill .md (idempotent on content — if the file already exists,
    # overwrite; the backup preserves any prior manual edits).
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = _render_skill_md(
        tid=tid,
        sys_prompt=data.get("system_prompt_default", ""),
        seo=data.get("seo_defaults") or {},
    )
    skill_path.write_text(body, encoding="utf-8")

    # Rewrite template JSON: strip legacy, set default_skill_id.
    cleaned = {k: v for k, v in data.items() if k not in LEGACY_FIELDS}
    cleaned["default_skill_id"] = new_skill_id
    tpl_path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("migrated %s -> %s", tpl_path.name, skill_path.name)
    return skill_path


def migrate_directory(tpl_dir: Path, skill_dir: Path) -> list[Path]:
    """Migrate every *.json directly under tpl_dir. Returns skill paths for
    successfully migrated templates."""
    results: list[Path] = []
    for p in sorted(Path(tpl_dir).glob("*.json")):
        out = migrate_file(p, skill_dir)
        if out is not None:
            results.append(out)
    return results


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("templates_dir", type=Path)
    ap.add_argument("skill_dir", type=Path)
    args = ap.parse_args(argv)

    if not args.templates_dir.is_dir():
        print(f"error: {args.templates_dir} is not a directory", file=sys.stderr)
        return 2
    migrated = migrate_directory(args.templates_dir, args.skill_dir)
    print(f"migrated {len(migrated)} template(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run migration tests, expect pass**

Run: `pytest tests/scripts/test_migrate_template_to_skill.py -v`
Expected: PASS (4/4).

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_template_to_skill.py tests/scripts/test_migrate_template_to_skill.py tests/scripts/__init__.py
git commit -m "feat(migration): one-shot template→skill migration script"
```

---

## Task 6: New-Template Dialog — Parent + Auto-ID + 2 Fields

**Files:**
- Modify: `csm_gui/widgets/template_list_panel.py:32-71, 197-232`
- Modify: `tests/gui/test_template_list_panel.py`

- [ ] **Step 1: Write the failing test**

Check existing `tests/gui/test_template_list_panel.py` for style; append or replace:

```python
import re
import pytest
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from csm_gui.widgets.template_list_panel import TemplateListPanel, _NewTemplateDialog


@pytest.fixture
def panel(qtbot, tmp_path):
    p = TemplateListPanel()
    qtbot.addWidget(p)
    p.set_directory(tmp_path)
    return p


def test_new_dialog_has_only_name_and_product_inputs(qtbot):
    dlg = _NewTemplateDialog(parent=None)
    qtbot.addWidget(dlg)
    assert not hasattr(dlg, "id_input")
    assert hasattr(dlg, "name_input")
    assert hasattr(dlg, "product_input")


def test_new_template_auto_generates_timestamp_id(panel, tmp_path, qtbot, monkeypatch):
    """Clicking 创建 with just name+product should produce a template with a
    generated id like 'template-<epoch>' and a <id>.json file on disk."""
    # Stub the dialog to pretend the user filled in name + product.
    from csm_gui.widgets import template_list_panel as mod

    class FakeDlg:
        def __init__(self, parent=None):
            self.name_input = type("X", (), {"text": lambda self_: "My Template"})()
            self.product_input = type("X", (), {"text": lambda self_: "吸尘器"})()
        def exec(self): return True

    monkeypatch.setattr(mod, "_NewTemplateDialog", FakeDlg)
    panel._on_new()

    jsons = list(tmp_path.glob("*.json"))
    assert len(jsons) == 1
    assert re.match(r"^template-\d{9,11}\.json$", jsons[0].name)
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/gui/test_template_list_panel.py::test_new_dialog_has_only_name_and_product_inputs tests/gui/test_template_list_panel.py::test_new_template_auto_generates_timestamp_id -v`
Expected: FAIL — `id_input` still exists; auto-id logic doesn't exist.

- [ ] **Step 3: Update `_NewTemplateDialog`**

Replace `csm_gui/widgets/template_list_panel.py` lines 32-71 with:

```python
class _NewTemplateDialog(MessageBoxBase):
    """Two-field dialog (name + product). Template id is auto-generated by
    the caller using a unix timestamp."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(400)
        self.titleLabel = SubtitleLabel("新建模板", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.viewLayout.addWidget(BodyLabel("模板名称"))
        self.name_input = LineEdit(self)
        self.name_input.setPlaceholderText("如：导购文-场景人群型")
        self.viewLayout.addWidget(self.name_input)

        self.viewLayout.addWidget(BodyLabel("产品类别"))
        self.product_input = LineEdit(self)
        self.product_input.setPlaceholderText("如：吸尘器")
        self.viewLayout.addWidget(self.product_input)

        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")

    def validate(self) -> bool:
        for name, field in [
            ("模板名称", self.name_input),
            ("产品类别", self.product_input),
        ]:
            if not field.text().strip():
                InfoBar.error(
                    "验证失败", f"{name} 不能为空",
                    parent=self, position=InfoBarPosition.TOP,
                )
                return False
        return True
```

- [ ] **Step 4: Update `_on_new`**

Replace lines 197-232:

```python
    def _on_new(self) -> None:
        if self._dir is None:
            InfoBar.warning(
                "未选择目录", "请先选择模板目录，再新建模板",
                parent=self.window(), position=InfoBarPosition.TOP, duration=4000,
            )
            return

        # parent = window so the dialog centers on the main window instead
        # of this narrow left-side panel (which used to obscure the editor).
        dlg = _NewTemplateDialog(self.window())
        if not dlg.exec():
            return

        tpl_name = dlg.name_input.text().strip()
        tpl_product = dlg.product_input.text().strip()

        # Auto-generated id: template-<epoch>. Collision is effectively
        # impossible within one second; retain the -N suffix fallback as
        # a belt-and-braces guard.
        import time
        tpl_id = f"template-{int(time.time())}"
        target = self._dir / f"{tpl_id}.json"
        suffix = 1
        while target.exists():
            target = self._dir / f"{tpl_id}-{suffix}.json"
            suffix += 1
        actual_id = target.stem

        skeleton = Template(
            id=actual_id,
            name=tpl_name,
            product=tpl_product,
            blocks=[LiteralBlock(id="intro", text="引言")],
        )
        save_template(skeleton, target)

        self.refresh()
        self.select_by_path(target)
        self.template_selected.emit(target)
        InfoBar.success(
            "创建成功", f"模板「{tpl_name}」已创建",
            parent=self.window(), position=InfoBarPosition.TOP, duration=3000,
        )
```

Also update the import at line 25 to drop `SEODefaults`:

```python
from csm_core.template.schema import Template, LiteralBlock
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/gui/test_template_list_panel.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add csm_gui/widgets/template_list_panel.py tests/gui/test_template_list_panel.py
git commit -m "feat(template-list): auto id + window-parented dialog + 2 fields"
```

---

## Task 7: Template Editor — Delete 3 Groups, Add 默认 Skill Combo

**Files:**
- Modify: `csm_gui/widgets/template_editor_panel.py` (significant edits across `_build_info_tab`, `load_template`, `_build_template_dict`)
- Modify: `tests/gui/test_template_editor.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/gui/test_template_editor.py`:

```python
def test_info_tab_has_no_version_prompt_seo_fields(qtbot, tmp_path):
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    assert not hasattr(panel, "version_spin")
    assert not hasattr(panel, "prompt_edit")
    assert not hasattr(panel, "wc_min_spin")
    assert not hasattr(panel, "kd_min_spin")
    assert not hasattr(panel, "tone_input")
    assert not hasattr(panel, "force_h2_switch")
    assert not hasattr(panel, "long_tail_input")


def test_info_tab_has_default_skill_combo(qtbot, tmp_path):
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    (skill_dir / "alpha.md").write_text("a", encoding="utf-8")
    (skill_dir / "beta.md").write_text("b", encoding="utf-8")
    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.set_skill_dir(skill_dir)
    items = [panel.default_skill_combo.itemText(i)
             for i in range(panel.default_skill_combo.count())]
    assert items == ["（无）", "alpha", "beta"]
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/gui/test_template_editor.py::test_info_tab_has_no_version_prompt_seo_fields tests/gui/test_template_editor.py::test_info_tab_has_default_skill_combo -v`
Expected: FAIL — fields still exist; combo doesn't.

- [ ] **Step 3: Rewrite `_build_info_tab`**

Replace lines 131-245 with:

```python
    def _build_info_tab(self) -> QWidget:
        page = ScrollArea(self)
        page.setWidgetResizable(True)
        page.setStyleSheet(
            "QScrollArea, #scrollWidget {background: transparent; border: none;}"
        )
        inner = QWidget()
        inner.setObjectName("scrollWidget")
        page.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        basic_card = CardWidget(inner)
        basic_lay = QVBoxLayout(basic_card)
        basic_lay.setContentsMargins(16, 12, 16, 12)
        basic_lay.setSpacing(6)
        basic_lay.addWidget(StrongBodyLabel("基础设置"))

        basic_lay.addWidget(BodyLabel("名称"))
        self.name_input = LineEdit(basic_card)
        self.name_input.textChanged.connect(self._mark_dirty)
        basic_lay.addWidget(self.name_input)

        basic_lay.addWidget(BodyLabel("产品"))
        self.product_input = LineEdit(basic_card)
        self.product_input.textChanged.connect(self._mark_dirty)
        basic_lay.addWidget(self.product_input)

        basic_lay.addWidget(BodyLabel("默认 Skill"))
        self.default_skill_combo = ComboBox(basic_card)
        # Populated later via set_skill_dir(); start with the empty option.
        self.default_skill_combo.addItem("（无）")
        self.default_skill_combo.currentIndexChanged.connect(self._mark_dirty)
        basic_lay.addWidget(self.default_skill_combo)

        lay.addWidget(basic_card)
        lay.addStretch(1)
        return page
```

- [ ] **Step 4: Add `set_skill_dir` method + update `load_template`, `_build_template_dict`**

Near the other public methods (e.g. after `set_vault_root`), add:

```python
    def set_skill_dir(self, skill_dir: Path | None) -> None:
        """Rebuild the default-skill combo from the given directory."""
        self._skill_dir = Path(skill_dir) if skill_dir else None
        self.default_skill_combo.blockSignals(True)
        try:
            self.default_skill_combo.clear()
            self.default_skill_combo.addItem("（无）")
            if self._skill_dir and self._skill_dir.is_dir():
                for p in sorted(self._skill_dir.glob("*.md")):
                    self.default_skill_combo.addItem(p.stem)
        finally:
            self.default_skill_combo.blockSignals(False)
```

In `load_template` (replacing the lines that set version/prompt/SEO widgets — around 299-315):

```python
        self.name_input.setText(tpl.name)
        self.product_input.setText(tpl.product)

        # Default skill picker.
        self.default_skill_combo.blockSignals(True)
        try:
            target = tpl.default_skill_id or ""
            # Walk items to find a matching stem; default to index 0 (无).
            idx = 0
            for i in range(self.default_skill_combo.count()):
                if self.default_skill_combo.itemText(i) == target:
                    idx = i; break
            self.default_skill_combo.setCurrentIndex(idx)
        finally:
            self.default_skill_combo.blockSignals(False)

        self.slots_page.load_blocks(tpl.blocks)
```

In `_build_template_dict` (replace lines 360-382):

```python
    def _build_template_dict(self) -> dict:
        blocks = self.slots_page.get_blocks()
        skill_text = self.default_skill_combo.currentText()
        default_skill_id = None if skill_text == "（无）" else skill_text
        return {
            "id": self._template_id,
            "name": self.name_input.text().strip(),
            "product": self.product_input.text().strip(),
            "default_skill_id": default_skill_id,
            "blocks": [b.model_dump() for b in blocks],
        }
```

Also drop the `SEODefaults` import at line 43:

```python
from csm_core.template.schema import Template
```

And initialize `self._skill_dir: Path | None = None` at the top of `__init__` (alongside `self._vault_root`).

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/gui/test_template_editor.py -v`
Expected: PASS (the two new tests + any existing green tests).

- [ ] **Step 6: Wire `set_skill_dir` from `TemplateManagerPage` + `MainWindow._on_settings_save`**

Read `csm_gui/pages/template_manager_page.py` and find where it calls editor methods on settings change (e.g. `apply_config`). Add a `self.editor.set_skill_dir(...)` call alongside existing wiring. Similarly, call it once on page construction with the initial config's `skill_dir`.

- [ ] **Step 7: Commit**

```bash
git add csm_gui/widgets/template_editor_panel.py csm_gui/pages/template_manager_page.py tests/gui/test_template_editor.py
git commit -m "refactor(template-editor): drop version/prompt/seo, add default_skill_id combo"
```

---

## Task 8: Skill List Panel (left side of SkillsPage)

**Files:**
- Create: `csm_gui/widgets/skill_skeleton.py`
- Create: `csm_gui/widgets/skill_list_panel.py`
- Create: `tests/gui/test_skill_list_panel.py`

- [ ] **Step 1: Write skeleton constant**

Create `csm_gui/widgets/skill_skeleton.py`:

```python
"""Starter markdown body for new skills.

Matches the structure of the existing xiaohongshu-polish.md example so
users have a consistent four-section starting point (style / structure /
prohibitions / output). The { product } placeholder is prose only — no
templating substitution; users edit it in place."""

SKILL_SKELETON = """# 新 Skill

你是一位专注于 { product } 品类的内容编辑。收到毛坯文后，按下面的规则进行**润色改写**。

## 风格约束

- 开头钩子：
- 段落密度：
- 口语化：
- 数字保留：必须逐字保留所有参数、价格、型号。
- 品牌/型号：必须原样保留。

## 结构约束

- 保留毛坯文的所有 H2 段落及其顺序。
- 不得新增虚构内容。

## 禁止项

- 禁止引流话术（"点击关注"、"免费领"等）。
- 禁止绝对化承诺词（"最"、"第一"、"100%"、"根治"）。

## 输出

直接输出润色后的完整正文 Markdown，不要加任何前言或代码块包裹。
"""
```

- [ ] **Step 2: Write the failing list-panel test**

Create `tests/gui/test_skill_list_panel.py`:

```python
import pytest
from pathlib import Path
from csm_gui.widgets.skill_list_panel import SkillListPanel


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    (tmp_path / "beta.md").write_text("B", encoding="utf-8")
    (tmp_path / "README.txt").write_text("ignore me", encoding="utf-8")
    return tmp_path


def test_panel_lists_md_files_sorted(qtbot, skill_dir):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    items = [p.list_widget.item(i).text() for i in range(p.list_widget.count())]
    assert items == ["alpha", "beta"]  # .txt ignored, sorted


def test_panel_emits_selected_signal(qtbot, skill_dir):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    with qtbot.waitSignal(p.skill_selected, timeout=1000) as blocker:
        p.list_widget.setCurrentRow(1)
        p._on_item_clicked()
    assert blocker.args[0].name == "beta.md"


def test_panel_new_skill_writes_skeleton(qtbot, skill_dir, monkeypatch):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)

    # Monkey-patch the prompt dialog to return "gamma".
    monkeypatch.setattr(p, "_prompt_new_name", lambda: "gamma")
    p._on_new()

    target = skill_dir / "gamma.md"
    assert target.is_file()
    assert "# 新 Skill" in target.read_text(encoding="utf-8")


def test_panel_new_skill_refuses_collision(qtbot, skill_dir, monkeypatch):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)

    monkeypatch.setattr(p, "_prompt_new_name", lambda: "alpha")  # already exists
    # Capture InfoBar calls? Simpler: verify alpha.md content is untouched.
    before = (skill_dir / "alpha.md").read_text(encoding="utf-8")
    p._on_new()
    after = (skill_dir / "alpha.md").read_text(encoding="utf-8")
    assert before == after


def test_panel_delete_moves_to_trash(qtbot, skill_dir, monkeypatch):
    p = SkillListPanel()
    qtbot.addWidget(p)
    p.set_directory(skill_dir)
    p.list_widget.setCurrentRow(0)  # alpha

    # Confirm dialog → yes.
    monkeypatch.setattr(p, "_confirm_delete", lambda name: True)
    p._on_delete()

    assert not (skill_dir / "alpha.md").is_file()
    assert (skill_dir / ".trash" / "alpha.md").is_file()
```

- [ ] **Step 3: Run tests, expect failure**

Run: `pytest tests/gui/test_skill_list_panel.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Implement `SkillListPanel`**

Create `csm_gui/widgets/skill_list_panel.py`:

```python
"""Skill directory picker + list + new/delete actions.

Mirrors TemplateListPanel's visual language: CardWidget rows, soft-delete
to <dir>/.trash/, InfoBar feedback. Skill files are plain .md; the panel
knows nothing about their contents.
"""
from __future__ import annotations
import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel,
    LineEdit, PrimaryPushButton, PushButton, FluentIcon,
    ListWidget, CardWidget, MessageBox, MessageBoxBase,
    InfoBar, InfoBarPosition,
)

from .skill_skeleton import SKILL_SKELETON


class _NewSkillDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(400)
        self.viewLayout.addWidget(SubtitleLabel("新建 Skill", self))
        self.viewLayout.addWidget(BodyLabel("Skill 名称（将作为文件名）"))
        self.name_input = LineEdit(self)
        self.name_input.setPlaceholderText("如：xiaohongshu-polish")
        self.viewLayout.addWidget(self.name_input)
        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")

    def validate(self) -> bool:
        if not self.name_input.text().strip():
            InfoBar.error("验证失败", "名称不能为空",
                          parent=self, position=InfoBarPosition.TOP)
            return False
        return True


class SkillListPanel(QWidget):
    """Left-side list panel.

    Signals
    -------
    skill_selected(Path): fired when the user clicks a .md file.
    skill_dir_changed(Path): fired when the scanned directory changes.
    """

    skill_selected = pyqtSignal(Path)
    skill_dir_changed = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir: Path | None = None
        self._paths: list[Path] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        dir_card = CardWidget(self)
        dir_lay = QVBoxLayout(dir_card)
        dir_lay.setContentsMargins(16, 12, 16, 12)
        dir_lay.setSpacing(6)
        dir_lay.addWidget(StrongBodyLabel("Skill 目录"))
        row = QHBoxLayout()
        self.dir_input = LineEdit(dir_card)
        self.dir_input.setPlaceholderText("选择 Skill 目录 …")
        self.dir_input.setReadOnly(True)
        row.addWidget(self.dir_input, 1)
        self.browse_btn = PushButton("浏览", dir_card, FluentIcon.FOLDER)
        self.browse_btn.clicked.connect(self._pick_dir)
        row.addWidget(self.browse_btn)
        dir_lay.addLayout(row)
        root.addWidget(dir_card)

        list_card = CardWidget(self)
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(12, 8, 12, 8)
        list_lay.setSpacing(6)
        list_lay.addWidget(BodyLabel("Skill 列表"))
        self.list_widget = ListWidget(list_card)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        list_lay.addWidget(self.list_widget, 1)
        root.addWidget(list_card, 1)

        btn_card = CardWidget(self)
        btn_lay = QHBoxLayout(btn_card)
        btn_lay.setContentsMargins(12, 8, 12, 8)
        btn_lay.setSpacing(8)
        self.new_btn = PrimaryPushButton(FluentIcon.ADD, "新建 Skill", btn_card)
        self.new_btn.clicked.connect(self._on_new)
        btn_lay.addWidget(self.new_btn)
        self.delete_btn = PushButton(FluentIcon.DELETE, "删除", btn_card)
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.setEnabled(False)
        btn_lay.addWidget(self.delete_btn)
        root.addWidget(btn_card)

    # ── Public API ──
    def set_directory(self, path: Path) -> None:
        self._dir = Path(path)
        self.dir_input.setText(str(self._dir))
        self.refresh()
        self.skill_dir_changed.emit(self._dir)

    def refresh(self) -> None:
        self.list_widget.clear()
        self._paths = []
        self.delete_btn.setEnabled(False)
        if self._dir is None or not self._dir.is_dir():
            return
        for p in sorted(self._dir.glob("*.md")):
            self.list_widget.addItem(p.stem)
            self._paths.append(p)

    def current_path(self) -> Path | None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._paths):
            return self._paths[row]
        return None

    # ── Slots ──
    def _pick_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择 Skill 目录")
        if p:
            self.set_directory(Path(p))

    def _on_item_clicked(self) -> None:
        path = self.current_path()
        if path:
            self.delete_btn.setEnabled(True)
            self.skill_selected.emit(path)

    def _prompt_new_name(self) -> str | None:
        """Show new-skill dialog. Returns stem, or None on cancel. Override
        in tests via monkeypatch."""
        dlg = _NewSkillDialog(self.window())
        if not dlg.exec():
            return None
        return dlg.name_input.text().strip()

    def _on_new(self) -> None:
        if self._dir is None:
            InfoBar.warning("未选择目录", "请先选择 Skill 目录",
                            parent=self.window(), position=InfoBarPosition.TOP)
            return
        name = self._prompt_new_name()
        if not name:
            return
        target = self._dir / f"{name}.md"
        if target.exists():
            InfoBar.error("已存在", f"「{name}」已存在，请换个名字",
                          parent=self.window(), position=InfoBarPosition.TOP)
            return
        target.write_text(SKILL_SKELETON, encoding="utf-8")
        self.refresh()
        # Select the new row.
        for i, p in enumerate(self._paths):
            if p == target:
                self.list_widget.setCurrentRow(i)
                self.skill_selected.emit(p)
                break
        InfoBar.success("已创建", f"「{name}.md」",
                        parent=self.window(), position=InfoBarPosition.TOP)

    def _confirm_delete(self, name: str) -> bool:
        dlg = MessageBox(
            "删除 Skill",
            f"确认删除「{name}」？\n删除后文件将移入 .trash/ 目录。",
            self.window(),
        )
        dlg.yesButton.setText("删除")
        dlg.cancelButton.setText("取消")
        return bool(dlg.exec())

    def _on_delete(self) -> None:
        path = self.current_path()
        if path is None:
            return
        if not self._confirm_delete(path.stem):
            return
        trash = path.parent / ".trash"
        trash.mkdir(exist_ok=True)
        dest = trash / path.name
        n = 1
        while dest.exists():
            dest = trash / f"{path.stem}-{n}{path.suffix}"
            n += 1
        shutil.move(str(path), str(dest))
        self.refresh()
        InfoBar.success("已删除", f"「{path.stem}」已移入 .trash/",
                        parent=self.window(), position=InfoBarPosition.TOP)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/gui/test_skill_list_panel.py -v`
Expected: PASS (5/5).

- [ ] **Step 6: Commit**

```bash
git add csm_gui/widgets/skill_skeleton.py csm_gui/widgets/skill_list_panel.py tests/gui/test_skill_list_panel.py
git commit -m "feat(skills): skill list panel with new/delete + skeleton"
```

---

## Task 9: Skill Editor Panel (right side of SkillsPage)

**Files:**
- Create: `csm_gui/widgets/skill_editor_panel.py`
- Create: `tests/gui/test_skill_editor_panel.py`

- [ ] **Step 1: Write the failing editor test**

Create `tests/gui/test_skill_editor_panel.py`:

```python
import pytest
from pathlib import Path
from csm_gui.widgets.skill_editor_panel import SkillEditorPanel


@pytest.fixture
def skill_file(tmp_path):
    p = tmp_path / "alpha.md"
    p.write_text("# Alpha\n\nhello", encoding="utf-8")
    return p


def test_load_populates_editor(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    assert panel.editor.toPlainText() == "# Alpha\n\nhello"
    assert panel.name_input.text() == "alpha"
    assert panel.is_dirty() is False


def test_edit_marks_dirty(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.editor.setPlainText("# changed")
    assert panel.is_dirty() is True


def test_save_writes_and_clears_dirty(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.editor.setPlainText("# saved")
    assert panel.save() is True
    assert skill_file.read_text(encoding="utf-8") == "# saved"
    assert panel.is_dirty() is False


def test_rename_via_name_input(qtbot, skill_file):
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.name_input.setText("renamed")
    panel.save()
    assert not skill_file.exists()
    assert (skill_file.parent / "renamed.md").is_file()


def test_rename_collision_aborts_save(qtbot, skill_file, tmp_path):
    # Create a sibling that the rename would collide with.
    (tmp_path / "other.md").write_text("other", encoding="utf-8")
    panel = SkillEditorPanel()
    qtbot.addWidget(panel)
    panel.load_skill(skill_file)
    panel.name_input.setText("other")
    assert panel.save() is False
    # Original file still exists (rename aborted, not partial).
    assert skill_file.is_file()
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/gui/test_skill_editor_panel.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `SkillEditorPanel`**

Create `csm_gui/widgets/skill_editor_panel.py`:

```python
"""Right-side skill editor: name input + plain-text markdown editor + save.

Atomic write (tmp file + replace) and collision-aware rename, matching the
template editor's behaviour. No markdown rendering — skills are prose that
feeds an LLM; what-you-see-is-what-the-model-gets is the right invariant.
"""
from __future__ import annotations
import os
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    StrongBodyLabel, BodyLabel,
    LineEdit, PlainTextEdit, PrimaryPushButton, FluentIcon,
    CardWidget, InfoBar, InfoBarPosition,
)


class SkillEditorPanel(QWidget):
    """Editor for a single skill .md file."""

    saved = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Path | None = None
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        name_card = CardWidget(self)
        name_lay = QVBoxLayout(name_card)
        name_lay.setContentsMargins(16, 12, 16, 12)
        name_lay.setSpacing(6)
        name_lay.addWidget(StrongBodyLabel("Skill"))
        name_lay.addWidget(BodyLabel("名称（保存时重命名文件）"))
        self.name_input = LineEdit(name_card)
        self.name_input.textChanged.connect(self._mark_dirty)
        name_lay.addWidget(self.name_input)
        root.addWidget(name_card)

        edit_card = CardWidget(self)
        edit_lay = QVBoxLayout(edit_card)
        edit_lay.setContentsMargins(16, 12, 16, 12)
        edit_lay.setSpacing(6)
        edit_lay.addWidget(StrongBodyLabel("内容（Markdown）"))
        self.editor = PlainTextEdit(edit_card)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(mono)
        self.editor.textChanged.connect(self._mark_dirty)
        edit_lay.addWidget(self.editor, 1)
        root.addWidget(edit_card, 1)

        bar = QWidget(self)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(16, 8, 16, 8)
        self.dirty_label = BodyLabel("● 有未保存的更改", bar)
        self.dirty_label.setVisible(False)
        bar_lay.addWidget(self.dirty_label)
        bar_lay.addStretch(1)
        self.save_btn = PrimaryPushButton(FluentIcon.SAVE, "保存", bar)
        self.save_btn.setFixedHeight(40)
        self.save_btn.clicked.connect(self.save)
        bar_lay.addWidget(self.save_btn)
        root.addWidget(bar)

        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save)

        self._set_enabled(False)

    # ── Public API ──
    def load_skill(self, path: Path) -> None:
        self._current_path = Path(path)
        self.name_input.blockSignals(True)
        self.editor.blockSignals(True)
        try:
            self.name_input.setText(self._current_path.stem)
            self.editor.setPlainText(self._current_path.read_text(encoding="utf-8"))
        finally:
            self.name_input.blockSignals(False)
            self.editor.blockSignals(False)
        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(True)

    def is_dirty(self) -> bool:
        return self._dirty

    def clear(self) -> None:
        self._current_path = None
        self.name_input.clear()
        self.editor.clear()
        self._dirty = False
        self.dirty_label.setVisible(False)
        self._set_enabled(False)

    def save(self) -> bool:
        if self._current_path is None:
            return False
        new_stem = self.name_input.text().strip()
        if not new_stem:
            InfoBar.error("保存失败", "名称不能为空",
                          parent=self.window(), position=InfoBarPosition.TOP)
            return False

        target = self._current_path.with_name(f"{new_stem}.md")
        if target != self._current_path and target.exists():
            InfoBar.error("保存失败", f"「{new_stem}」已存在",
                          parent=self.window(), position=InfoBarPosition.TOP)
            return False

        # Atomic write to the target path, then remove the old path if renamed.
        tmp = target.with_suffix(".md.tmp")
        tmp.write_text(self.editor.toPlainText(), encoding="utf-8")
        os.replace(tmp, target)
        if target != self._current_path:
            self._current_path.unlink(missing_ok=True)

        self._current_path = target
        self._dirty = False
        self.dirty_label.setVisible(False)
        InfoBar.success("已保存", target.name,
                        parent=self.window(), position=InfoBarPosition.TOP)
        self.saved.emit(target)
        return True

    # ── Internal ──
    def _set_enabled(self, enabled: bool) -> None:
        self.save_btn.setEnabled(enabled)
        self.editor.setEnabled(enabled)
        self.name_input.setEnabled(enabled)

    def _mark_dirty(self, *_) -> None:
        if not self._dirty:
            self._dirty = True
            self.dirty_label.setVisible(True)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/gui/test_skill_editor_panel.py -v`
Expected: PASS (5/5).

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/skill_editor_panel.py tests/gui/test_skill_editor_panel.py
git commit -m "feat(skills): skill editor panel with atomic save + rename"
```

---

## Task 10: SkillsPage (compose left + right) + Dirty Switch Guard

**Files:**
- Create: `csm_gui/pages/skills_page.py`
- Create: `tests/gui/test_skills_page.py`

- [ ] **Step 1: Write the failing test**

Create `tests/gui/test_skills_page.py`:

```python
import pytest
from pathlib import Path
from csm_gui.pages.skills_page import SkillsPage
from csm_gui.config import AppConfig


@pytest.fixture
def skill_dir(tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    (tmp_path / "beta.md").write_text("B", encoding="utf-8")
    return tmp_path


def test_page_selects_first_skill_on_load(qtbot, skill_dir):
    cfg = AppConfig(skill_dir=str(skill_dir))
    page = SkillsPage(config=cfg)
    qtbot.addWidget(page)
    page.list_panel.list_widget.setCurrentRow(0)
    page.list_panel._on_item_clicked()
    assert page.editor_panel.name_input.text() == "alpha"


def test_apply_config_rescans(qtbot, skill_dir, tmp_path):
    cfg = AppConfig(skill_dir=None)
    page = SkillsPage(config=cfg)
    qtbot.addWidget(page)
    # Simulate settings change.
    cfg2 = AppConfig(skill_dir=str(skill_dir))
    page.apply_config(cfg2)
    items = [page.list_panel.list_widget.item(i).text()
             for i in range(page.list_panel.list_widget.count())]
    assert items == ["alpha", "beta"]


def test_switch_skill_with_dirty_prompts_confirm(qtbot, skill_dir, monkeypatch):
    cfg = AppConfig(skill_dir=str(skill_dir))
    page = SkillsPage(config=cfg)
    qtbot.addWidget(page)

    page.list_panel.list_widget.setCurrentRow(0)
    page.list_panel._on_item_clicked()
    page.editor_panel.editor.setPlainText("# dirty")
    assert page.editor_panel.is_dirty()

    # User picks "discard" when prompted.
    monkeypatch.setattr(page, "_resolve_dirty", lambda: "discard")
    page.list_panel.list_widget.setCurrentRow(1)
    page.list_panel._on_item_clicked()
    # Switched, alpha.md on disk unchanged.
    assert page.editor_panel.name_input.text() == "beta"
    assert (skill_dir / "alpha.md").read_text(encoding="utf-8") == "A"
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/gui/test_skills_page.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `SkillsPage`**

Create `csm_gui/pages/skills_page.py`:

```python
"""Top-level Skills management page — list + editor, wired up."""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QHBoxLayout
from qfluentwidgets import MessageBox

from ..config import AppConfig
from ..widgets.skill_list_panel import SkillListPanel
from ..widgets.skill_editor_panel import SkillEditorPanel


class SkillsPage(QWidget):
    """Two-column page: directory-scoped list on the left, editor on the right."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("skillsPage")  # required by FluentWindow nav
        self._config = config

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.list_panel = SkillListPanel(self)
        self.list_panel.setFixedWidth(280)
        self.list_panel.skill_selected.connect(self._on_skill_selected)
        root.addWidget(self.list_panel)

        self.editor_panel = SkillEditorPanel(self)
        self.editor_panel.saved.connect(self._on_saved)
        root.addWidget(self.editor_panel, 1)

        if config.skill_dir:
            self.list_panel.set_directory(Path(config.skill_dir))

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        if cfg.skill_dir:
            self.list_panel.set_directory(Path(cfg.skill_dir))
        else:
            # No directory → clear editor; panel shows empty list.
            self.editor_panel.clear()

    # ── Slots ──
    def _on_skill_selected(self, path: Path) -> None:
        if self.editor_panel.is_dirty():
            decision = self._resolve_dirty()
            if decision == "cancel":
                return
            if decision == "save":
                if not self.editor_panel.save():
                    return
            # "discard" → fall through, load new one without saving.
        self.editor_panel.load_skill(path)

    def _on_saved(self, path: Path) -> None:
        # File might have been renamed; refresh list.
        self.list_panel.refresh()

    def _resolve_dirty(self) -> str:
        """Prompt on unsaved changes. Returns one of: 'save', 'discard', 'cancel'.
        Override in tests via monkeypatch."""
        dlg = MessageBox(
            "未保存的更改",
            "当前 Skill 有未保存的改动。是否保存？",
            self.window(),
        )
        dlg.yesButton.setText("保存")
        dlg.cancelButton.setText("丢弃")
        if dlg.exec():
            return "save"
        return "discard"
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/gui/test_skills_page.py -v`
Expected: PASS (3/3).

- [ ] **Step 5: Commit**

```bash
git add csm_gui/pages/skills_page.py tests/gui/test_skills_page.py
git commit -m "feat(skills): SkillsPage composes list + editor with dirty guard"
```

---

## Task 11: Register SkillsPage in Nav, Propagate `skill_dir` Changes

**Files:**
- Modify: `csm_gui/main_window.py`

- [ ] **Step 1: Read current nav registration**

Already known from Task 7 prep: lines 79-88 register home / article / template_manager / settings. Nav icons use `FluentIcon`.

- [ ] **Step 2: Add SkillsPage import + instantiate + register**

At the import block (lines 5-12), add:

```python
from .pages.skills_page import SkillsPage
```

After line 80 (`self.template_manager = TemplateManagerPage(...)`), add:

```python
        self.skills = SkillsPage(config=self.config, parent=self)
```

After line 84 (`self.addSubInterface(self.template_manager, ...)`), insert:

```python
        self.addSubInterface(self.skills, FluentIcon.DICTIONARY, "Skills")
```

In `_on_settings_save` (line 98), add:

```python
        self.skills.apply_config(new_cfg)
```

- [ ] **Step 3: Manual smoke (no unit test for nav wiring)**

Run: `python -m csm_gui`
Expected: app launches, nav panel shows "Skills" item with dictionary icon. Clicking it opens SkillsPage. No regressions on existing pages.

(If CI doesn't support GUI smoke, skip the manual step and rely on `tests/gui/test_skills_page.py`.)

- [ ] **Step 4: Commit**

```bash
git add csm_gui/main_window.py
git commit -m "feat(nav): register SkillsPage between 模板 and 设置"
```

---

## Task 12: ControlsPanel Preselects Template's Default Skill

**Files:**
- Modify: `csm_gui/widgets/controls_panel.py`
- Modify: `csm_gui/pages/article_page.py` (where `load_result` is called; pass template default)
- Modify: `csm_gui/main_window.py:_on_generated` if the template object isn't already plumbed through

- [ ] **Step 1: Write the failing test**

Add to `tests/gui/test_controls_panel.py` (create if missing):

```python
import pytest
from pathlib import Path
from csm_gui.widgets.controls_panel import ControlsPanel


def test_preselect_sets_combo(qtbot, tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    (tmp_path / "beta.md").write_text("B", encoding="utf-8")
    panel = ControlsPanel(skill_dir=tmp_path, preferred_skill="beta")
    qtbot.addWidget(panel)
    assert panel.skill_combo.currentText() == "beta"


def test_preselect_unknown_falls_back_to_wu(qtbot, tmp_path):
    (tmp_path / "alpha.md").write_text("A", encoding="utf-8")
    panel = ControlsPanel(skill_dir=tmp_path, preferred_skill="nonexistent")
    qtbot.addWidget(panel)
    assert panel.skill_combo.currentText() == "无"


def test_set_preferred_skill_after_construction(qtbot, tmp_path):
    (tmp_path / "x.md").write_text("x", encoding="utf-8")
    panel = ControlsPanel(skill_dir=tmp_path)
    qtbot.addWidget(panel)
    panel.set_preferred_skill("x")
    assert panel.skill_combo.currentText() == "x"
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/gui/test_controls_panel.py -v`
Expected: FAIL — `preferred_skill` kwarg and `set_preferred_skill` method don't exist.

- [ ] **Step 3: Update `ControlsPanel.__init__` and add `set_preferred_skill`**

In `csm_gui/widgets/controls_panel.py`, replace the `__init__` signature and add a helper:

```python
    def __init__(
        self,
        skill_dir: Path | None,
        provider_default: str = "",
        preferred_skill: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ControlsPanel")
        self._skill_dir = Path(skill_dir) if skill_dir else None

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        root.addWidget(BodyLabel("润色风格", self))
        self.skill_combo = ComboBox(self)
        self.skill_combo.setMinimumWidth(200)
        self._populate_skills()
        if preferred_skill:
            self.set_preferred_skill(preferred_skill)
        root.addWidget(self.skill_combo)

        # ... (rest unchanged)

    def set_preferred_skill(self, name: str | None) -> None:
        """Select the combo entry matching `name` (skill stem). Silently
        falls back to '无' if the name isn't in the current combo."""
        if not name:
            self.skill_combo.setCurrentIndex(0)
            return
        for i in range(self.skill_combo.count()):
            if self.skill_combo.itemText(i) == name:
                self.skill_combo.setCurrentIndex(i)
                return
        self.skill_combo.setCurrentIndex(0)
```

Also update `set_skill_dir` to accept an optional preferred_skill arg for re-preselection after a rescan:

```python
    def set_skill_dir(self, skill_dir: Path | None, preferred_skill: str | None = None) -> None:
        self._skill_dir = Path(skill_dir) if skill_dir else None
        self.skill_combo.clear()
        self._populate_skills()
        if preferred_skill:
            self.set_preferred_skill(preferred_skill)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/gui/test_controls_panel.py -v`
Expected: PASS (3/3).

- [ ] **Step 5: Plumb the preferred skill through ArticlePage / MainWindow**

Read `csm_gui/pages/article_page.py` to find where `ControlsPanel` is constructed and where `load_result(template, plan, draft, final_text)` lives. After loading a result, call:

```python
        self.controls.set_preferred_skill(template.default_skill_id)
```

(If `load_result` already takes a `template` arg — it does, per `main_window.py:124` — this is a one-line addition inside that method.)

- [ ] **Step 6: Commit**

```bash
git add csm_gui/widgets/controls_panel.py csm_gui/pages/article_page.py tests/gui/test_controls_panel.py
git commit -m "feat(controls): preselect template.default_skill_id in polish combo"
```

---

## Task 13: Run Full Regression + Migrate Repo Templates

**Files:**
- Run: all tests
- Run: migration script against `templates/`

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: all green. If anything fails, fix before proceeding. Common breakage: tests in `tests/core/assembler/` that built `Template(..., version=1, system_prompt_default="", seo_defaults=SEODefaults())`. These now omit those kwargs (the `SEODefaults` import must be dropped too).

- [ ] **Step 2: Dry-run migration on actual repo templates**

```bash
# Set skill_dir to examples/skills for dogfood; adjust per user preference.
python -m scripts.migrate_template_to_skill templates examples/skills
```

Expected output: `migrated 2 template(s).` (two JSON files in `templates/`).

- [ ] **Step 3: Inspect the migrated artifacts**

```bash
ls examples/skills/
cat examples/skills/daogou-changjing-renqun-migrated.md
cat templates/daogou-changjing-renqun.json
```

Expected:
- New `*-migrated.md` files under `examples/skills/`
- `templates/*.json` now contain `default_skill_id` and lack the three legacy fields
- `templates/*.json.bak` backups exist

- [ ] **Step 4: Run pipeline sanity check**

Do a single generate (either via a test fixture or the GUI). Draft should look identical to pre-migration; polish should include the same system prompt content (now coming from the skill .md).

If there's a pipeline smoke test in `tests/core/test_pipeline.py` that exercises the end-to-end flow, re-run it: `pytest tests/core/test_pipeline.py -v`.

- [ ] **Step 5: Commit the migrated data**

```bash
git add templates/ examples/skills/
git commit -m "chore: migrate bundled templates to default_skill_id + skill .md"
```

- [ ] **Step 6: Final regression**

```bash
pytest -q
```

Expected: green. If green, proceed to `superpowers:finishing-a-development-branch`.

---

## Post-Implementation

After Task 13 passes, invoke `superpowers:finishing-a-development-branch` to review the PR-equivalent change set, open a PR, and merge.
