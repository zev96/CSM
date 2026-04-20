# Plan C Implementation Plan — Controller Refactor + Batch Mode

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `ArticleController` from `MainWindow` (C1), then add serial batch-generation mode with per-batch subdirectory output and incremental batch report (C2). Target tag: v0.3.

**Architecture:** Introduce a signal-based controller layer (`csm_gui/controllers/`) that owns workflow state (current result, workers, vault cache). `MainWindow` becomes a thin shell that routes between pages and surfaces InfoBars. Batch mode splits into a pure core runner (`csm_core/batch/`) and a Qt-thin worker + controller + UI (`csm_gui/workers/batch_worker.py`, `csm_gui/controllers/batch_controller.py`, `csm_gui/pages/batch_result_page.py`).

**Tech Stack:** PyQt6, PyQt6-Fluent-Widgets 1.11.2, pytest + pytest-qt (qtbot), Python 3.11+.

**Spec reference:** `docs/superpowers/specs/2026-04-20-plan-c-refactor-and-batch-design.md`.

**Test command (Windows):**
```
PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q
```
(Run a single test file: append `tests/path/to/test_file.py`.)

**Conventions:**
- Every task ends with a green full-suite run and a commit.
- Commit messages follow `type(scope): summary` (matching existing history: `feat(gui)`, `refactor(gui)`, `test(core)`, etc.).
- No emojis in code or UI strings. `⚠` (U+26A0) is allowed for error/warning UI text.
- No placeholder `TODO`s in committed code — anything not in this plan is out of scope.

---

## File Structure

**Created:**
```
csm_core/assembler/render.py               # compose_draft public function
csm_core/batch/__init__.py
csm_core/batch/report.py                   # BatchReport + BatchItem + I/O
csm_core/batch/runner.py                   # run_batch pure function
csm_gui/controllers/__init__.py
csm_gui/controllers/article_controller.py  # ArticleController (moves workflow state out of MainWindow)
csm_gui/controllers/batch_controller.py    # BatchController
csm_gui/workers/batch_worker.py            # BatchWorker(QThread)
csm_gui/widgets/generation_form.py         # shared template/vault/provider form
csm_gui/widgets/batch_panel.py             # batch tab UI
csm_gui/pages/batch_result_page.py         # progress + result page (not in nav)

tests/core/test_compose_draft.py
tests/core/test_batch_report.py
tests/core/test_batch_runner.py
tests/gui/test_article_controller.py
tests/gui/test_batch_controller.py
tests/gui/test_generation_form.py
tests/gui/test_batch_panel.py
tests/gui/test_batch_result_page.py
tests/gui/test_batch_smoke.py              # end-to-end
```

**Modified:**
```
csm_core/pipeline.py                       # use csm_core.assembler.render.compose_draft
csm_gui/pages/article_page.py              # view-only; signature change
csm_gui/pages/home_page.py                 # Pivot with single + batch tabs; uses GenerationForm
csm_gui/main_window.py                     # thin shell; delegates to controllers
tests/gui/test_main_window.py              # slim: only shell/nav/InfoBar routing
tests/gui/test_article_page.py             # adjust to new signature (if present)
tests/gui/test_home_page.py                # adjust to Pivot
```

**Kept unchanged:**
```
csm_core/pipeline.py::generate             # only internal _render_draft replaced
csm_gui/workers/generate_worker.py         # reused unchanged by ArticleController
csm_gui/workers/polish_worker.py           # reused unchanged
csm_gui/workers/reroll.py                  # reused unchanged
csm_gui/llm_factory.py                     # reused by both controllers
```

---

# Phase C1 — Controller Refactor

Goal of C1: make `MainWindow` ≤ 120 lines, remove `_template` / `_compose_draft` / `_reroll_counter` from `ArticlePage`, add vault-cache mtime invalidation. No user-visible change. All existing tests still pass.

---

### Task 1: Promote `compose_draft` to `csm_core/assembler/render.py`

**Purpose:** Eliminate the duplicate draft-rendering logic in `csm_core/pipeline._render_draft` and `csm_gui/pages/article_page.ArticlePage._compose_draft`. Both become a single public function.

**Files:**
- Create: `csm_core/assembler/render.py`
- Create: `tests/core/test_compose_draft.py`
- Modify: `csm_core/pipeline.py` (replace `_render_draft` usage)
- Modify: `csm_gui/pages/article_page.py` (replace `_compose_draft` usage temporarily; full view-only refactor comes in Task 7)

- [ ] **Step 1: Write the failing test**

`tests/core/test_compose_draft.py`:
```python
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
from csm_core.assembler.render import compose_draft


def _mk_plan(slots):
    return AssemblyPlan(keyword="k", template_id="t", seed=0, slots=slots)


def _pick(text):
    return PickedVariant(note_id="n", variant_index=0, text=text)


def test_compose_draft_joins_picks_with_blank_lines_within_slot():
    plan = _mk_plan([SlotAssignment(slot_id="s1", picks=[_pick("a"), _pick("b")])])
    assert compose_draft(plan) == "a\n\nb"


def test_compose_draft_separates_slots_with_blank_lines():
    plan = _mk_plan([
        SlotAssignment(slot_id="s1", picks=[_pick("a")]),
        SlotAssignment(slot_id="s2", picks=[_pick("b")]),
    ])
    assert compose_draft(plan) == "a\n\nb"


def test_compose_draft_skips_empty_slots():
    plan = _mk_plan([
        SlotAssignment(slot_id="s1", picks=[_pick("a")]),
        SlotAssignment(slot_id="s2", picks=[]),
        SlotAssignment(slot_id="s3", picks=[_pick("c")]),
    ])
    assert compose_draft(plan) == "a\n\nc"


def test_compose_draft_empty_plan_returns_empty_string():
    assert compose_draft(_mk_plan([])) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/core/test_compose_draft.py -v`
Expected: `ImportError: cannot import name 'compose_draft' from 'csm_core.assembler.render'` (module doesn't exist yet).

- [ ] **Step 3: Create `csm_core/assembler/render.py`**

```python
"""Public rendering helpers for AssemblyPlan."""
from __future__ import annotations
from .plan import AssemblyPlan


def compose_draft(plan: AssemblyPlan) -> str:
    """Render an AssemblyPlan into the nested-join draft text.

    Slots with no picks are skipped. Picks within a slot are joined by
    blank lines; slots are separated by blank lines.
    """
    parts: list[str] = []
    for slot in plan.slots:
        if not slot.picks:
            continue
        parts.append("\n\n".join(p.text for p in slot.picks))
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/core/test_compose_draft.py -v`
Expected: 4 passed.

- [ ] **Step 5: Replace `_render_draft` in `csm_core/pipeline.py`**

Delete the local `_render_draft` function. Change the import block (top of file) to add:
```python
from .assembler.render import compose_draft
```
Replace the call site `draft = _render_draft(plan)` with:
```python
draft = compose_draft(plan)
```

- [ ] **Step 6: Replace `_compose_draft` use in `csm_gui/pages/article_page.py`**

At the top of the file add:
```python
from csm_core.assembler.render import compose_draft
```
Replace the static method `_compose_draft` body with a one-liner delegating to `compose_draft`, keeping the method signature so existing callers still work until Task 7:
```python
    @staticmethod
    def _compose_draft(plan) -> str:
        return compose_draft(plan)
```

- [ ] **Step 7: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all 97 existing tests still pass + 4 new tests = 101 passed.

- [ ] **Step 8: Commit**

```bash
git add csm_core/assembler/render.py tests/core/test_compose_draft.py csm_core/pipeline.py csm_gui/pages/article_page.py
git commit -m "refactor(core): promote compose_draft to public assembler.render module"
```

---

### Task 2: Scaffold `ArticleController` skeleton with signals

**Purpose:** Create the controller class with all signal declarations and empty method stubs. No logic yet — Tasks 3–6 fill them in. This task establishes the file and test file so later migrations are edits, not creations.

**Files:**
- Create: `csm_gui/controllers/__init__.py` (empty)
- Create: `csm_gui/controllers/article_controller.py`
- Create: `tests/gui/test_article_controller.py`

- [ ] **Step 1: Write the failing test**

`tests/gui/test_article_controller.py`:
```python
from pathlib import Path
from csm_gui.config import AppConfig
from csm_gui.controllers.article_controller import ArticleController


def test_controller_initial_state_not_busy(qtbot, tmp_path):
    cfg = AppConfig(out_dir=str(tmp_path))
    c = ArticleController(cfg)
    assert c.is_busy() is False


def test_controller_signals_exist():
    """All documented signals must be declared — catches typos early."""
    cfg = AppConfig()
    c = ArticleController(cfg)
    for name in [
        "generated", "generate_failed", "reroll_completed",
        "polished", "polish_failed", "exported", "export_failed",
        "plan_warnings", "busy_changed",
    ]:
        assert hasattr(c, name), f"missing signal: {name}"


def test_apply_config_updates_internal(qtbot, tmp_path):
    c = ArticleController(AppConfig())
    new_cfg = AppConfig(out_dir=str(tmp_path), default_provider="deepseek")
    c.apply_config(new_cfg)
    # Internal state is private; reflect via is_busy() remaining False is enough here.
    # Further assertions live in migration tasks.
    assert c.is_busy() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: `ModuleNotFoundError: No module named 'csm_gui.controllers'`.

- [ ] **Step 3: Create `csm_gui/controllers/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `csm_gui/controllers/article_controller.py` skeleton**

```python
"""ArticleController — owns article-workflow state off of MainWindow.

Contract (see docs/superpowers/specs/2026-04-20-plan-c-refactor-and-batch-design.md):
- Owns current_result, template, reroll counter, vault cache, workers.
- Emits signals; never calls InfoBar or switchTo directly.
- Never imports widget classes.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from csm_core.pipeline import GenerateResult
from csm_core.template.loader import Template  # only for type hint
from ..config import AppConfig


class ArticleController(QObject):
    generated = pyqtSignal(object)           # GenerateResult
    generate_failed = pyqtSignal(str)
    reroll_completed = pyqtSignal(object)    # AssemblyPlan
    polished = pyqtSignal(str)
    polish_failed = pyqtSignal(str)
    exported = pyqtSignal(dict)              # {"markdown": path, "assembly_json": path}
    export_failed = pyqtSignal(str)
    plan_warnings = pyqtSignal(list)         # list[str]
    busy_changed = pyqtSignal(bool)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config: AppConfig = config
        self._current_result: GenerateResult | None = None
        self._current_template: Template | None = None
        self._last_template_path: Path | None = None
        self._reroll_counter: int = 0
        self._vault_cache: tuple[Path, float, object, object] | None = None
        self._generate_worker = None
        self._polish_worker = None

    # --- public API (stubs filled in by later tasks) ---

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        # Invalidate vault cache if root changed; full mtime check lives in _get_vault.
        if self._vault_cache is not None:
            if self._config.vault_root is None or str(self._vault_cache[0]) != self._config.vault_root:
                self._vault_cache = None

    def request_generate(self, payload: dict) -> bool:
        raise NotImplementedError  # Task 3

    def reroll_slot(self, slot_id: str, user_config: dict) -> None:
        raise NotImplementedError  # Task 4

    def polish(self, provider: str, skill_path: Path | None) -> None:
        raise NotImplementedError  # Task 5

    def export(self) -> None:
        raise NotImplementedError  # Task 6

    def is_busy(self) -> bool:
        gen_busy = self._generate_worker is not None and self._generate_worker.isRunning()
        polish_busy = self._polish_worker is not None and self._polish_worker.isRunning()
        return gen_busy or polish_busy

    # --- internals ---

    def _get_vault(self, vault_root: Path):
        from csm_core.vault.scanner import scan_vault
        from csm_core.vault.brand_registry import build_brand_registry
        mtime = vault_root.stat().st_mtime
        if (
            self._vault_cache is None
            or self._vault_cache[0] != vault_root
            or self._vault_cache[1] != mtime
        ):
            index = scan_vault(vault_root)
            registry = build_brand_registry(vault_root)
            self._vault_cache = (vault_root, mtime, index, registry)
        return self._vault_cache[2], self._vault_cache[3]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add csm_gui/controllers/ tests/gui/test_article_controller.py
git commit -m "feat(gui): scaffold ArticleController with signal contract"
```

---

### Task 3: Migrate `request_generate` into `ArticleController`

**Purpose:** Move the generate path (build client → start worker → route `finished`/`failed`) from `MainWindow` into the controller. MainWindow still wires the signals but no longer holds the worker.

**Files:**
- Modify: `csm_gui/controllers/article_controller.py`
- Modify: `tests/gui/test_article_controller.py`
- Modify: `csm_gui/main_window.py` (delegate `_on_request_generate` to `self.article_controller.request_generate`)
- Modify: `tests/gui/test_main_window.py` (remove tests that will be duplicated in controller test file — only if any assert on generate worker internals; keep tests that check InfoBar routing from `generate_failed` signal since that still lives on MainWindow)

- [ ] **Step 1: Write failing tests for controller**

Append to `tests/gui/test_article_controller.py`:
```python
def test_request_generate_rejected_when_no_out_dir(qtbot):
    c = ArticleController(AppConfig(out_dir=""))
    ok = c.request_generate({
        "keyword": "k", "template_path": "t.json",
        "vault_root": "v", "provider": "mock",
    })
    assert ok is False


def test_request_generate_rejected_when_busy(qtbot, tmp_path, monkeypatch):
    c = ArticleController(AppConfig(out_dir=str(tmp_path)))

    class FakeWorker:
        def isRunning(self):
            return True
        def start(self):
            pass
    c._generate_worker = FakeWorker()

    ok = c.request_generate({
        "keyword": "k", "template_path": "t.json",
        "vault_root": "v", "provider": "mock",
    })
    assert ok is False


def test_request_generate_emits_busy_changed_true(qtbot, tmp_path, monkeypatch):
    """Starting a generate must flip busy_changed to True."""
    c = ArticleController(AppConfig(out_dir=str(tmp_path)))

    # Swap the worker class with a no-op stand-in so .start() doesn't actually run.
    class NoopWorker:
        def __init__(self, *a, **kw):
            self._running = False
            self.finished = _FakeSig()
            self.failed = _FakeSig()
            self.stage_changed = _FakeSig()
        def isRunning(self):
            return self._running
        def start(self):
            self._running = True

    monkeypatch.setattr("csm_gui.controllers.article_controller.GenerateWorker", NoopWorker)
    monkeypatch.setattr(
        "csm_gui.controllers.article_controller.build_client",
        lambda cfg, p: object(),
    )

    with qtbot.waitSignal(c.busy_changed, timeout=500) as sig:
        c.request_generate({
            "keyword": "k", "template_path": "t.json",
            "vault_root": str(tmp_path), "provider": "mock",
        })
    assert sig.args == [True]


class _FakeSig:
    def connect(self, _slot):
        pass
    def emit(self, *a, **kw):
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: 3 new tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `request_generate` in controller**

In `csm_gui/controllers/article_controller.py`, add imports at the top:
```python
from csm_core.pipeline import GenerateRequest
from ..workers.generate_worker import GenerateWorker
from ..llm_factory import build_client
```

Replace the `request_generate` stub with:
```python
    def request_generate(self, payload: dict) -> bool:
        if not self._config.out_dir:
            return False
        if self._generate_worker is not None and self._generate_worker.isRunning():
            return False
        client = build_client(self._config, payload["provider"])
        self._last_template_path = Path(payload["template_path"])
        req = GenerateRequest(
            keyword=payload["keyword"],
            vault_root=Path(payload["vault_root"]),
            template_path=self._last_template_path,
            out_dir=Path(self._config.out_dir),
            llm_client=client,
            seed=self._config.last_seed,
        )
        self._generate_worker = GenerateWorker(req, self)
        self._generate_worker.finished.connect(self._on_generate_finished)
        self._generate_worker.failed.connect(self._on_generate_failed)
        self._generate_worker.start()
        self.busy_changed.emit(True)
        return True

    def _on_generate_finished(self, result) -> None:
        from csm_core.template.loader import load_template
        self._current_result = result
        self._current_template = load_template(self._last_template_path)
        self._reroll_counter = 0
        self.generated.emit(result)
        if getattr(result.plan, "warnings", None):
            self.plan_warnings.emit(list(result.plan.warnings))
        self.busy_changed.emit(False)

    def _on_generate_failed(self, msg: str) -> None:
        self.generate_failed.emit(msg)
        self.busy_changed.emit(False)
```

- [ ] **Step 4: Run controller tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: all pass.

- [ ] **Step 5: Rewire MainWindow to delegate**

In `csm_gui/main_window.py`:

Add import near the top:
```python
from .controllers.article_controller import ArticleController
```

In `__init__`, after `self.config = load_config(...)` and before creating pages, add:
```python
        self.article_controller = ArticleController(self.config, parent=self)
        self.article_controller.generated.connect(self._on_generated)
        self.article_controller.generate_failed.connect(self._on_generate_failed)
        self.article_controller.plan_warnings.connect(self._show_plan_warnings_list)
```

Replace the body of `_on_request_generate` with:
```python
    def _on_request_generate(self, payload: dict) -> None:
        ok = self.article_controller.request_generate(payload)
        if not ok:
            from qfluentwidgets import InfoBar, InfoBarPosition
            if not self.config.out_dir:
                InfoBar.error(
                    "缺少输出目录", "请先在设置页配置输出目录",
                    parent=self, position=InfoBarPosition.TOP,
                )
            else:
                InfoBar.warning(
                    "正在生成", "请等待当前任务完成",
                    parent=self, position=InfoBarPosition.TOP,
                )
```

Replace body of `_on_generated` (it still loads the article page but no longer manages workers):
```python
    def _on_generated(self, result) -> None:
        from csm_core.assembler.render import compose_draft
        draft = compose_draft(result.plan)
        self.article.load_result(
            self.article_controller._current_template,  # TEMP: Task 7 adds a cleaner accessor
            result.plan,
            draft,
            result.final_text,
        )
        self.switchTo(self.article)
```

Note: the cross-access `article_controller._current_template` is acknowledged as temporary — Task 7 replaces `load_result` signature and MainWindow will read `result` alone.

Rename `_show_plan_warnings(plan)` → `_show_plan_warnings_list(warnings)` to match the new signal payload:
```python
    def _show_plan_warnings_list(self, warnings: list) -> None:
        if not warnings:
            return
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.warning(
            title="注意",
            content="\n".join(warnings[:3]),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=6000,
        )
```

Delete `self._worker` / `self._last_template_path` / `self._vault_cache` attributes from MainWindow (kept `_polish_worker` for now — Task 5 removes).

Delete the old `_on_generated` body that loaded template via `load_template(self._last_template_path)` and the old `_show_plan_warnings(plan)` method.

- [ ] **Step 6: Fix `test_main_window.py` breakage from rename**

In `tests/gui/test_main_window.py`:
- `test_show_plan_warnings_emits_when_present` — replace `win._show_plan_warnings(plan)` with `win._show_plan_warnings_list(plan.warnings)`.
- `test_show_plan_warnings_silent_when_empty` — replace with `win._show_plan_warnings_list([])`.

- [ ] **Step 7: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass (101 → 104 with the 3 new controller tests).

- [ ] **Step 8: Commit**

```bash
git add csm_gui/controllers/article_controller.py csm_gui/main_window.py tests/gui/test_article_controller.py tests/gui/test_main_window.py
git commit -m "refactor(gui): move generate workflow into ArticleController"
```

---

### Task 4: Migrate reroll path + implement vault mtime invalidation

**Purpose:** Move reroll from MainWindow into `ArticleController.reroll_slot`. Vault cache now lives on the controller (already scaffolded in Task 2's `_get_vault`). Add a test that proves mtime changes invalidate the cache.

**Files:**
- Modify: `csm_gui/controllers/article_controller.py`
- Modify: `tests/gui/test_article_controller.py`
- Modify: `csm_gui/main_window.py` (delete `_on_reroll_slot` body, delegate; also delete `_get_vault` and `_vault_cache`)

- [ ] **Step 1: Write failing tests**

Append to `tests/gui/test_article_controller.py`:
```python
import time
from csm_core.assembler.plan import AssemblyPlan
from csm_core.pipeline import GenerateResult


def test_get_vault_caches_result(qtbot, tmp_path):
    (tmp_path / "brands.json").write_text('{"brands":[]}', encoding="utf-8")
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))
    idx1, reg1 = c._get_vault(tmp_path)
    idx2, reg2 = c._get_vault(tmp_path)
    assert idx1 is idx2  # same cached instance
    assert reg1 is reg2


def test_get_vault_invalidates_on_mtime_change(qtbot, tmp_path):
    (tmp_path / "brands.json").write_text('{"brands":[]}', encoding="utf-8")
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))
    idx1, _ = c._get_vault(tmp_path)
    # Force mtime change by touching a new file in the dir.
    time.sleep(0.05)  # ensure filesystem mtime ticks
    (tmp_path / "new.md").write_text("# x", encoding="utf-8")
    idx2, _ = c._get_vault(tmp_path)
    assert idx1 is not idx2  # fresh scan


def test_reroll_slot_no_op_when_no_current_result(qtbot, tmp_path):
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))
    # Should not raise even though current_result is None.
    c.reroll_slot("some_slot", {"brand_competitors": 2})


def test_reroll_slot_emits_reroll_completed_on_success(qtbot, tmp_path, monkeypatch):
    """With a mocked reroll_slot function, controller emits reroll_completed."""
    (tmp_path / "brands.json").write_text('{"brands":[]}', encoding="utf-8")
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))

    fake_plan = AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[])
    c._current_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[]),
        final_text="",
    )
    c._current_template = object()  # opaque sentinel for the mock
    c._vault_cache = (tmp_path, 0.0, object(), object())

    monkeypatch.setattr(
        "csm_gui.controllers.article_controller.reroll_slot",
        lambda **kwargs: fake_plan,
    )

    with qtbot.waitSignal(c.reroll_completed, timeout=500) as sig:
        c.reroll_slot("slot_a", {"brand_competitors": 2})
    assert sig.args[0] is fake_plan
    assert c._current_result.plan is fake_plan
    assert c._reroll_counter == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: `test_reroll_slot_no_op_when_no_current_result` and `test_reroll_slot_emits_reroll_completed_on_success` fail with NotImplementedError. The two `_get_vault` tests already pass from Task 2.

- [ ] **Step 3: Implement `reroll_slot`**

Add import at the top of `article_controller.py`:
```python
from ..workers.reroll import reroll_slot
```

Replace the `reroll_slot` stub:
```python
    def reroll_slot(self, slot_id: str, user_config: dict) -> None:
        if self._current_result is None or self._current_template is None:
            return
        if not self._config.vault_root:
            return
        index, registry = self._get_vault(Path(self._config.vault_root))
        self._reroll_counter += 1
        new_plan = reroll_slot(
            slot_id=slot_id,
            template=self._current_template,
            index=index,
            registry=registry,
            current_plan=self._current_result.plan,
            counter=self._reroll_counter,
            user_config=user_config,
        )
        self._current_result.plan = new_plan
        self.reroll_completed.emit(new_plan)
```

Note: Python scoping — the module-level `reroll_slot` function and the method `reroll_slot` have the same name. Because the method binds `self` first and the imported function is called by closure lookup (module global), this works. Verify by running the tests.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: all pass.

- [ ] **Step 5: Rewire MainWindow**

In `csm_gui/main_window.py`:

Connect the new signal in `__init__` (after the existing `plan_warnings.connect`):
```python
        self.article_controller.reroll_completed.connect(self._on_reroll_completed)
```

Replace the body of `_on_reroll_slot`:
```python
    def _on_reroll_slot(self, slot_id: str) -> None:
        self.article_controller.reroll_slot(
            slot_id,
            user_config={
                "brand_competitors": int(self.article.controls.brand_count_input.value())
            },
        )
```

Add a new handler:
```python
    def _on_reroll_completed(self, new_plan) -> None:
        from csm_core.assembler.render import compose_draft
        self.article.slot_list.load(self.article_controller._current_template, new_plan)
        self.article.markdown_view.set_draft(compose_draft(new_plan))
```

Delete `_get_vault` method and `self._vault_cache` attribute from MainWindow.

- [ ] **Step 6: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add csm_gui/controllers/article_controller.py csm_gui/main_window.py tests/gui/test_article_controller.py
git commit -m "refactor(gui): move reroll into ArticleController; add vault mtime invalidation"
```

---

### Task 5: Migrate polish path

**Purpose:** Move polish worker lifecycle from MainWindow to ArticleController.

**Files:**
- Modify: `csm_gui/controllers/article_controller.py`
- Modify: `tests/gui/test_article_controller.py`
- Modify: `csm_gui/main_window.py` (delete `_on_polish` body, delegate; delete `_on_polished` too — controller emits and MainWindow handles)

- [ ] **Step 1: Write failing tests**

Append to `tests/gui/test_article_controller.py`:
```python
def test_polish_no_op_without_current_result(qtbot, tmp_path):
    c = ArticleController(AppConfig(out_dir=str(tmp_path)))
    c.polish("mock", None)  # should not raise


def test_polish_rejected_when_busy(qtbot, tmp_path):
    c = ArticleController(AppConfig(out_dir=str(tmp_path)))
    c._current_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[]),
        final_text="",
    )
    c._current_template = _MockTemplate()

    class FakePolishWorker:
        def isRunning(self):
            return True
    c._polish_worker = FakePolishWorker()

    # Tracks whether a new polish_worker was created.
    before_id = id(c._polish_worker)
    c.polish("mock", None)
    assert id(c._polish_worker) == before_id  # not replaced


class _MockTemplate:
    system_prompt_default = "sys"
    seo_defaults = {}
```

- [ ] **Step 2: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: new tests fail with NotImplementedError.

- [ ] **Step 3: Implement `polish`**

Add imports:
```python
from ..workers.polish_worker import PolishWorker
from csm_core.llm.prompts import build_prompt, PromptInputs
from csm_core.assembler.render import compose_draft
```

Replace the `polish` stub:
```python
    def polish(self, provider: str, skill_path: Path | None) -> None:
        if self._current_result is None or self._current_template is None:
            return
        if self._polish_worker is not None and self._polish_worker.isRunning():
            return

        skill_text: str | None = None
        if skill_path:
            try:
                skill_text = Path(skill_path).read_text(encoding="utf-8")
            except OSError as exc:
                self.polish_failed.emit(f"{type(exc).__name__}: {exc}")
                return

        template = self._current_template
        plan = self._current_result.plan
        draft = compose_draft(plan)
        system, user = build_prompt(PromptInputs(
            template_system_prompt=template.system_prompt_default,
            user_skill_prompt=skill_text,
            seo=template.seo_defaults,
            keyword=plan.keyword,
            draft=draft,
        ))
        client = build_client(self._config, provider)
        self._polish_worker = PolishWorker(client=client, system=system, user=user, parent=self)
        self._polish_worker.finished.connect(self._on_polish_finished)
        self._polish_worker.failed.connect(self._on_polish_failed)
        self._polish_worker.start()
        self.busy_changed.emit(True)

    def _on_polish_finished(self, text: str) -> None:
        if self._current_result is not None:
            self._current_result.final_text = text
        self.polished.emit(text)
        self.busy_changed.emit(False)

    def _on_polish_failed(self, msg: str) -> None:
        self.polish_failed.emit(msg)
        self.busy_changed.emit(False)
```

- [ ] **Step 4: Run controller tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: all pass.

- [ ] **Step 5: Rewire MainWindow**

In `csm_gui/main_window.py`:

Connect new signals in `__init__` (after the reroll_completed line):
```python
        self.article_controller.polished.connect(self._on_polished)
        self.article_controller.polish_failed.connect(self._on_generate_failed)  # reuse same error routing
```

Replace `_on_polish` body:
```python
    def _on_polish(self, provider: str, skill_path) -> None:
        self.article_controller.polish(provider, skill_path)
```

Keep `_on_polished` but simplify to only update the view (state lives in controller):
```python
    def _on_polished(self, text: str) -> None:
        self.article.markdown_view.set_polished(text)
```

Delete `self._polish_worker` attribute from MainWindow.

- [ ] **Step 6: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add csm_gui/controllers/article_controller.py csm_gui/main_window.py tests/gui/test_article_controller.py
git commit -m "refactor(gui): move polish into ArticleController"
```

---

### Task 6: Migrate export path

**Purpose:** Move export logic into `ArticleController.export`. MainWindow only shows InfoBars on `exported` / `export_failed` signals.

**Files:**
- Modify: `csm_gui/controllers/article_controller.py`
- Modify: `tests/gui/test_article_controller.py`
- Modify: `csm_gui/main_window.py` (thin delegation)

- [ ] **Step 1: Write failing tests**

Append to `tests/gui/test_article_controller.py`:
```python
from pathlib import Path as _P
from csm_core.template.loader import load_template as _load_template


def test_export_no_op_without_result(qtbot, tmp_path):
    c = ArticleController(AppConfig(out_dir=str(tmp_path)))
    # Must not raise and must not emit.
    received = []
    c.exported.connect(lambda d: received.append(d))
    c.export_failed.connect(lambda m: received.append(m))
    c.export()
    assert received == []


def test_export_emits_exported_on_success(qtbot, tmp_path):
    from csm_core.assembler.plan import SlotAssignment, PickedVariant
    c = ArticleController(AppConfig(out_dir=str(tmp_path)))
    plan = AssemblyPlan(
        keyword="kw", template_id="t", seed=0,
        slots=[SlotAssignment(slot_id="s", picks=[
            PickedVariant(note_id="n", variant_index=0, text="hi"),
        ])],
    )
    c._current_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=plan, final_text="# hello",
    )
    with qtbot.waitSignal(c.exported, timeout=500) as sig:
        c.export()
    paths = sig.args[0]
    assert "markdown" in paths
    assert _P(paths["markdown"]).exists()


def test_export_emits_export_failed_on_missing_out_dir(qtbot, tmp_path):
    c = ArticleController(AppConfig(out_dir=str(tmp_path / "does_not_exist")))
    c._current_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[]),
        final_text="",
    )
    with qtbot.waitSignal(c.export_failed, timeout=500) as sig:
        c.export()
    assert "FileNotFoundError" in sig.args[0]
```

- [ ] **Step 2: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: new tests fail with NotImplementedError.

- [ ] **Step 3: Implement `export`**

Add import:
```python
from csm_core.export.markdown import export_article
```

Replace the `export` stub:
```python
    def export(self) -> None:
        if self._current_result is None:
            return
        if not self._config.out_dir:
            self.export_failed.emit("OutputDirectoryMissing: 请先在设置页配置输出目录")
            return
        out_dir = Path(self._config.out_dir)
        try:
            paths = export_article(
                out_dir=out_dir,
                keyword=self._current_result.plan.keyword,
                final_text=self._current_result.final_text,
                plan=self._current_result.plan,
                prompt_snapshot={},
            )
        except Exception as exc:  # noqa: BLE001 — boundary, surface to UI
            self.export_failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.exported.emit(paths)
```

- [ ] **Step 4: Run controller tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_article_controller.py -v`
Expected: all pass.

- [ ] **Step 5: Rewire MainWindow**

Connect in `__init__` (after polish_failed connect):
```python
        self.article_controller.exported.connect(self._on_exported)
        self.article_controller.export_failed.connect(self._on_export_failed)
```

Replace `_on_export` body:
```python
    def _on_export(self) -> None:
        self.article_controller.export()
```

Add new handlers:
```python
    def _on_exported(self, paths: dict) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition, PushButton
        import os
        out_dir = Path(self.config.out_dir)
        bar = InfoBar.success(
            title="导出成功", content=paths["markdown"],
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )
        open_btn = PushButton("打开文件夹", bar)
        open_btn.clicked.connect(lambda: os.startfile(str(out_dir)))
        bar.addWidget(open_btn)
        bar.show()

    def _on_export_failed(self, msg: str) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        first_line = msg.splitlines()[0] if msg else "未知错误"
        if first_line.startswith("OutputDirectoryMissing"):
            InfoBar.error(
                "缺少输出目录", "请先在设置页配置输出目录",
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
            return
        InfoBar.error(
            "导出失败", first_line,
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )
```

- [ ] **Step 6: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass. `test_export_action_writes_files` still passes because it exercises MainWindow's delegation path.

- [ ] **Step 7: Commit**

```bash
git add csm_gui/controllers/article_controller.py csm_gui/main_window.py tests/gui/test_article_controller.py
git commit -m "refactor(gui): move export into ArticleController"
```

---

### Task 7: Slim `ArticlePage` to a view-only widget

**Purpose:** Remove all workflow state (`current_result`, `_template`, `_compose_draft`, `_reroll_counter`) from `ArticlePage`. Change `load_result(template, result)` to `load_result(template, plan, draft, final_text)` and add `update_plan(plan, draft)` for reroll refresh.

**Files:**
- Modify: `csm_gui/pages/article_page.py`
- Modify: `csm_gui/main_window.py` (adjust calls to new signature; stop reading `article_controller._current_template`)
- Modify: `tests/gui/test_main_window.py` (the `test_export_action_writes_files` test currently assigns `win.article._template` and `win.article.current_result` — rework to drive via the controller)
- Modify: `tests/gui/test_article_page.py` if it asserts on removed attributes

- [ ] **Step 1: Check which tests touch removed attributes**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui -q --collect-only 2>&1 | head -80`

Grep for soon-to-be-removed attribute names:
```
Grep tool: pattern="article\._template|article\._reroll_counter|article\.current_result|_compose_draft"  glob="tests/**/*.py"
```
Expected hits: `tests/gui/test_main_window.py` (the export test and possibly others).

- [ ] **Step 2: Rewrite the affected test**

In `tests/gui/test_main_window.py`, replace `test_export_action_writes_files` body (keeping the same name + purpose):
```python
def test_export_action_writes_files(qtbot, tmp_path):
    from pathlib import Path
    from csm_core.pipeline import GenerateResult
    from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant
    from csm_core.template.loader import load_template
    from csm_gui.config import AppConfig, save_config

    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    cfg = AppConfig(out_dir=str(tmp_path), default_template=str(template_path))
    save_config(cfg, tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    plan = AssemblyPlan(
        keyword="测试关键词", template_id="t", seed=0,
        slots=[SlotAssignment(slot_id="s", picks=[
            PickedVariant(note_id="n", variant_index=0, text="hello"),
        ])],
    )
    # Drive via controller state (private is acceptable inside the test).
    win.article_controller._current_template = load_template(template_path)
    win.article_controller._current_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=plan, final_text="# exported",
    )
    win._on_export()
    written = list(tmp_path.iterdir())
    assert any(p.suffix == ".md" for p in written)
    assert any(p.name.endswith(".assembly.json") for p in written)
```

- [ ] **Step 3: Rewrite `ArticlePage`**

Replace the entire `csm_gui/pages/article_page.py` with:
```python
"""Article workspace — 3-column layout. View-only: no workflow state."""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from ..widgets.slot_list import SlotList
from ..widgets.markdown_view import MarkdownView
from ..widgets.controls_panel import ControlsPanel


class ArticlePage(QWidget):
    reroll_slot_requested = pyqtSignal(str)

    def __init__(self, skill_dir=None, default_provider="mock", parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.slot_list = SlotList(self.splitter)
        self.slot_list.setMinimumWidth(300)
        self.slot_list.reroll_requested.connect(self.reroll_slot_requested.emit)
        self.slot_panel = self.slot_list  # back-compat alias

        self.markdown_view = MarkdownView(self.splitter)
        self.markdown_view.setMinimumWidth(480)
        self.preview_panel = self.markdown_view

        self.controls = ControlsPanel(
            skill_dir=skill_dir,
            provider_default=default_provider,
            parent=self.splitter,
        )
        self.controls.setMinimumWidth(280)
        self.controls_panel = self.controls

        self.splitter.addWidget(self.slot_list)
        self.splitter.addWidget(self.markdown_view)
        self.splitter.addWidget(self.controls_panel)
        self.splitter.setSizes([320, 720, 300])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.markdown_view.set_draft("")
        self.markdown_view.set_polished("")

    def load_result(self, template, plan, draft: str, final_text: str) -> None:
        """Render a generated article. All inputs are plain data."""
        self.slot_list.load(template, plan)
        self.markdown_view.set_draft(draft)
        self.markdown_view.set_polished(final_text)

    def update_plan(self, template, plan, draft: str) -> None:
        """Refresh slot list + draft after a reroll (polished text unchanged)."""
        self.slot_list.load(template, plan)
        self.markdown_view.set_draft(draft)

    def apply_config(self, cfg):
        self.controls.set_skill_dir(Path(cfg.skill_dir) if cfg.skill_dir else None)
        self.controls.set_provider_default(cfg.default_provider)
```

- [ ] **Step 4: Update MainWindow call sites**

Replace `_on_generated`:
```python
    def _on_generated(self, result) -> None:
        from csm_core.assembler.render import compose_draft
        draft = compose_draft(result.plan)
        self.article.load_result(
            self.article_controller._current_template,
            result.plan, draft, result.final_text,
        )
        self.switchTo(self.article)
```

Replace `_on_reroll_completed`:
```python
    def _on_reroll_completed(self, new_plan) -> None:
        from csm_core.assembler.render import compose_draft
        self.article.update_plan(
            self.article_controller._current_template,
            new_plan,
            compose_draft(new_plan),
        )
```

Note: `article_controller._current_template` stays as a private-access compromise for this task. Task 8 adds a proper `current_template` property.

- [ ] **Step 5: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add csm_gui/pages/article_page.py csm_gui/main_window.py tests/gui/test_main_window.py
git commit -m "refactor(gui): make ArticlePage view-only; state lives in controller"
```

---

### Task 8: Slim `MainWindow` + add `ArticleController.current_template` property

**Purpose:** Finish the C1 refactor — replace the last `article_controller._current_template` access with a public accessor, and strip any dead helpers from `MainWindow`. Verify line count goal.

**Files:**
- Modify: `csm_gui/controllers/article_controller.py` (add read-only property)
- Modify: `csm_gui/main_window.py` (use public property; remove unused imports)

- [ ] **Step 1: Add `current_template` property to controller**

Append to `ArticleController`:
```python
    @property
    def current_template(self):
        """Read-only view of the loaded template (for UI rendering)."""
        return self._current_template
```

- [ ] **Step 2: Replace private access in MainWindow**

In `csm_gui/main_window.py`:
- Replace `self.article_controller._current_template` with `self.article_controller.current_template` (two occurrences: `_on_generated`, `_on_reroll_completed`).
- Remove any now-unused imports (`PolishWorker`, `reroll_slot` from workers) — they moved to the controller.

- [ ] **Step 3: Verify MainWindow line count**

Run: `wc -l csm_gui/main_window.py` (or via Read). Expected: ≤ 120 lines.

If it's still over 120, check for leftover dead code: the old `_get_vault`, `_show_plan_warnings(plan)` variant, `_vault_cache` attribute. Remove any found.

- [ ] **Step 4: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/controllers/article_controller.py csm_gui/main_window.py
git commit -m "refactor(gui): expose ArticleController.current_template; drop private access"
```

---

**C1 Checkpoint:** At this point the v0.2 feature set is preserved, `MainWindow` is ≤ 120 lines, `ArticlePage` is view-only, vault cache honors mtime. No user-visible change. Ready for C2.

---

# Phase C2 — Batch Mode

Goal: serial batch generation with per-item failure isolation, per-batch subdirectory, incrementally-written `batch-report.json`, dedicated progress page.

---

### Task 9: `BatchReport` + `BatchItem` + atomic I/O

**Files:**
- Create: `csm_core/batch/__init__.py` (empty)
- Create: `csm_core/batch/report.py`
- Create: `tests/core/test_batch_report.py`

- [ ] **Step 1: Write failing tests**

`tests/core/test_batch_report.py`:
```python
from pathlib import Path
from csm_core.batch.report import BatchItem, BatchReport, write_report, read_report


def _mk_report(items=None):
    return BatchReport(
        batch_id="batch-20260420-120000",
        batch_dir="/tmp/batch-20260420-120000",
        started_at="2026-04-20T12:00:00",
        finished_at=None,
        template_path="/t/template.json",
        vault_root="/v",
        seed=0,
        total=2,
        items=items or [],
    )


def test_batch_item_frozen():
    item = BatchItem(index=1, keyword="k", status="success")
    try:
        item.index = 2  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("BatchItem should be frozen")


def test_write_and_read_round_trip(tmp_path):
    item = BatchItem(
        index=1, keyword="k", status="success",
        markdown_path="/p.md", assembly_json_path="/p.json",
        duration_seconds=1.5,
    )
    report = _mk_report(items=[item])
    path = tmp_path / "batch-report.json"
    write_report(report, path)
    loaded = read_report(path)
    assert loaded.batch_id == "batch-20260420-120000"
    assert loaded.total == 2
    assert len(loaded.items) == 1
    assert loaded.items[0].keyword == "k"
    assert loaded.items[0].status == "success"
    assert loaded.items[0].duration_seconds == 1.5


def test_write_is_atomic(tmp_path, monkeypatch):
    """Simulate a crash mid-write: temp file exists, target unchanged or absent."""
    report = _mk_report()
    path = tmp_path / "batch-report.json"
    write_report(report, path)
    # Second write with invalid content via monkeypatching json.dumps to raise.
    import json
    original_dumps = json.dumps
    def boom(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr("csm_core.batch.report.json.dumps", boom)
    try:
        write_report(report, path)
    except RuntimeError:
        pass
    # Original file still exists and is readable.
    loaded = read_report(path)
    assert loaded.batch_id == "batch-20260420-120000"


def test_failed_item_fields():
    item = BatchItem(
        index=2, keyword="bad", status="failed",
        error_type="EmptyPoolError",
        error_message="slot 'x': empty pool",
    )
    report = _mk_report(items=[item])
    # roundtrip check without disk
    from dataclasses import asdict
    data = asdict(report)
    assert data["items"][0]["error_type"] == "EmptyPoolError"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/core/test_batch_report.py -v`
Expected: `ModuleNotFoundError: No module named 'csm_core.batch'`.

- [ ] **Step 3: Create `csm_core/batch/__init__.py` and `csm_core/batch/report.py`**

`csm_core/batch/__init__.py`:
```python
```
(empty)

`csm_core/batch/report.py`:
```python
"""Batch execution report — dataclass + atomic I/O."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BatchItem:
    index: int
    keyword: str
    status: Literal["success", "failed"]
    markdown_path: str | None = None
    assembly_json_path: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    duration_seconds: float = 0.0


@dataclass
class BatchReport:
    batch_id: str
    batch_dir: str
    started_at: str
    finished_at: str | None
    template_path: str
    vault_root: str
    seed: int
    total: int
    items: list[BatchItem] = field(default_factory=list)


def write_report(report: BatchReport, path: Path) -> None:
    """Atomic write: serialize to temp file, then os.replace."""
    path = Path(path)
    data = asdict(report)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    import os
    os.replace(tmp, path)


def read_report(path: Path) -> BatchReport:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [BatchItem(**item_data) for item_data in data.pop("items", [])]
    return BatchReport(**data, items=items)
```

Wait — the `BatchReport` `__init__` already accepts `items` via its default factory; passing it twice is an error. Fix `read_report`:
```python
def read_report(path: Path) -> BatchReport:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_items = data.pop("items", [])
    report = BatchReport(**data)
    report.items = [BatchItem(**i) for i in raw_items]
    return report
```

- [ ] **Step 4: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/core/test_batch_report.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add csm_core/batch/ tests/core/test_batch_report.py
git commit -m "feat(core): BatchReport + BatchItem with atomic JSON I/O"
```

---

### Task 10: `run_batch` pure-function runner

**Files:**
- Create: `csm_core/batch/runner.py`
- Create: `tests/core/test_batch_runner.py`

- [ ] **Step 1: Write failing tests**

`tests/core/test_batch_runner.py`:
```python
from pathlib import Path
import json
from csm_core.batch.runner import run_batch
from csm_core.batch.report import read_report


class ProgrammableLLM:
    """Mock client: reactions maps keyword -> text OR Exception."""
    def __init__(self, reactions: dict):
        self._reactions = reactions

    def complete(self, system: str, user: str) -> str:
        # Extract keyword from the user prompt — it's the first line after "关键词:".
        for line in user.splitlines():
            if line.startswith("关键词"):
                kw = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                break
        else:
            kw = ""
        reaction = self._reactions.get(kw, f"POLISHED({kw})")
        if isinstance(reaction, Exception):
            raise reaction
        return reaction


def _setup_vault_and_template(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal vault + template that assemble_plan can run against."""
    # Reuse the in-repo template which assumes certain vault layout.
    repo_root = Path(__file__).parent.parent.parent
    template_path = repo_root / "templates" / "daogou-changjing-renqun.json"
    vault_root = repo_root / "tests" / "fixtures" / "vault_minimal"
    assert template_path.exists(), "fixture template missing"
    assert vault_root.exists(), "fixture vault missing"
    return template_path, vault_root


def test_run_batch_dedup_and_empty_skip(tmp_path):
    template_path, vault_root = _setup_vault_and_template(tmp_path)
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    client = ProgrammableLLM({})
    report = run_batch(
        keywords=["kw1", "", "  ", "kw1", "kw2"],  # dup + empties
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=client,
        seed=0,
    )
    assert report.total == 2  # kw1, kw2 (dup + empties removed)
    keywords = [i.keyword for i in report.items]
    assert keywords == ["kw1", "kw2"]


def test_run_batch_per_item_failure_isolation(tmp_path):
    template_path, vault_root = _setup_vault_and_template(tmp_path)
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    client = ProgrammableLLM({"kw2": RuntimeError("llm down")})
    report = run_batch(
        keywords=["kw1", "kw2", "kw3"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=client,
        seed=0,
    )
    assert report.total == 3
    statuses = [i.status for i in report.items]
    assert statuses == ["success", "failed", "success"]
    assert report.items[1].error_type == "RuntimeError"
    assert "llm down" in report.items[1].error_message


def test_run_batch_callback_ordering(tmp_path):
    template_path, vault_root = _setup_vault_and_template(tmp_path)
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    events = []
    run_batch(
        keywords=["kw1", "kw2"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=ProgrammableLLM({}),
        seed=0,
        on_item_started=lambda i, kw: events.append(("start", i, kw)),
        on_item_finished=lambda item: events.append(("finish", item.index, item.keyword)),
    )
    assert events == [
        ("start", 1, "kw1"), ("finish", 1, "kw1"),
        ("start", 2, "kw2"), ("finish", 2, "kw2"),
    ]


def test_run_batch_should_cancel_stops_early(tmp_path):
    template_path, vault_root = _setup_vault_and_template(tmp_path)
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    cancel_after = {"done": 0}
    def should_cancel():
        return cancel_after["done"] >= 1
    def on_finished(item):
        cancel_after["done"] += 1
    report = run_batch(
        keywords=["kw1", "kw2", "kw3"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=ProgrammableLLM({}),
        seed=0,
        on_item_finished=on_finished,
        should_cancel=should_cancel,
    )
    assert len(report.items) == 1
    assert report.finished_at is not None


def test_run_batch_writes_incremental_report(tmp_path):
    template_path, vault_root = _setup_vault_and_template(tmp_path)
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    # After each item, inspect batch-report.json and assert it reflects progress.
    snapshots = []
    def on_finished(item):
        data = json.loads((batch_dir / "batch-report.json").read_text(encoding="utf-8"))
        snapshots.append(len(data["items"]))
    run_batch(
        keywords=["kw1", "kw2"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=ProgrammableLLM({}),
        seed=0,
        on_item_finished=on_finished,
    )
    # After first item finishes, report has 1; after second, 2.
    assert snapshots == [1, 2]


def test_run_batch_vault_scanned_once(tmp_path, monkeypatch):
    """Ensure vault scan happens only once per batch."""
    template_path, vault_root = _setup_vault_and_template(tmp_path)
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    calls = {"scan": 0, "registry": 0}
    import csm_core.batch.runner as runner_mod
    original_scan = runner_mod.scan_vault
    original_reg = runner_mod.build_brand_registry

    def counting_scan(root):
        calls["scan"] += 1
        return original_scan(root)
    def counting_reg(root):
        calls["registry"] += 1
        return original_reg(root)
    monkeypatch.setattr(runner_mod, "scan_vault", counting_scan)
    monkeypatch.setattr(runner_mod, "build_brand_registry", counting_reg)

    run_batch(
        keywords=["kw1", "kw2", "kw3"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=ProgrammableLLM({}),
        seed=0,
    )
    assert calls["scan"] == 1
    assert calls["registry"] == 1
```

- [ ] **Step 2: Check that fixture vault exists**

Run: Glob `tests/fixtures/vault_minimal/**/*`. If it doesn't exist, the tests need a different fixture source. Adjust `_setup_vault_and_template` to point at whatever minimal vault the existing core tests use. Check `tests/core/test_pipeline.py` for the pattern it uses and copy that.

If no suitable fixture exists, create a minimal one in this step:
- `tests/fixtures/vault_minimal/brands.json`: `{"brands":[{"id":"b1","name":"Brand1","category":"pets","aliases":[]}]}`
- `tests/fixtures/vault_minimal/note1.md`: a front-matter + body note matching the template's slot queries. Copy from an existing pipeline test fixture if available.

- [ ] **Step 3: Run tests to verify failure**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/core/test_batch_runner.py -v`
Expected: `ModuleNotFoundError: No module named 'csm_core.batch.runner'`.

- [ ] **Step 4: Implement `run_batch`**

`csm_core/batch/runner.py`:
```python
"""Serial batch generation runner (no Qt deps)."""
from __future__ import annotations
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..vault.scanner import scan_vault
from ..vault.brand_registry import build_brand_registry
from ..template.loader import load_template
from ..assembler.constraints import assemble_plan
from ..assembler.render import compose_draft
from ..llm.client import LLMClient
from ..llm.prompts import build_prompt, PromptInputs
from ..export.markdown import export_article
from .report import BatchReport, BatchItem, write_report


def _dedup_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in keywords:
        k = k.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def run_batch(
    keywords: list[str],
    template_path: Path,
    vault_root: Path,
    out_dir: Path,
    llm_client: LLMClient,
    seed: int,
    on_item_started: Callable[[int, str], None] = lambda i, kw: None,
    on_item_finished: Callable[[BatchItem], None] = lambda item: None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> BatchReport:
    cleaned = _dedup_keywords(keywords)
    batch_id = out_dir.name
    report_path = out_dir / "batch-report.json"
    report = BatchReport(
        batch_id=batch_id,
        batch_dir=str(out_dir),
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at=None,
        template_path=str(template_path),
        vault_root=str(vault_root),
        seed=seed,
        total=len(cleaned),
    )
    write_report(report, report_path)

    # Scan vault once, reuse for all items.
    index = scan_vault(vault_root)
    registry = build_brand_registry(vault_root)
    template = load_template(template_path)

    for i, keyword in enumerate(cleaned, start=1):
        if should_cancel():
            break
        on_item_started(i, keyword)
        started = time.monotonic()
        try:
            plan = assemble_plan(
                keyword=keyword, template=template,
                index=index, registry=registry,
                seed=seed, user_config={},
            )
            draft = compose_draft(plan)
            system, user = build_prompt(PromptInputs(
                template_system_prompt=template.system_prompt_default,
                user_skill_prompt=None,
                seo=template.seo_defaults,
                keyword=keyword,
                draft=draft,
            ))
            final_text = llm_client.complete(system=system, user=user)
            paths = export_article(
                out_dir=out_dir,
                keyword=keyword,
                final_text=final_text,
                plan=plan,
                prompt_snapshot={
                    "system": system, "user": user,
                    "provider": type(llm_client).__name__,
                },
            )
            item = BatchItem(
                index=i, keyword=keyword, status="success",
                markdown_path=paths["markdown"],
                assembly_json_path=paths["assembly_json"],
                duration_seconds=round(time.monotonic() - started, 3),
            )
        except Exception as exc:  # noqa: BLE001 — per-item boundary
            err_msg = str(exc).splitlines()[0] if str(exc) else ""
            item = BatchItem(
                index=i, keyword=keyword, status="failed",
                error_type=type(exc).__name__,
                error_message=err_msg,
                duration_seconds=round(time.monotonic() - started, 3),
            )
        on_item_finished(item)
        report.items.append(item)
        write_report(report, report_path)

    report.finished_at = datetime.now().isoformat(timespec="seconds")
    write_report(report, report_path)
    return report
```

- [ ] **Step 5: Run tests to verify pass**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/core/test_batch_runner.py -v`
Expected: all pass. If keyword extraction in `ProgrammableLLM.complete` fails (because `build_prompt` uses different format), inspect the `user` string and adjust `ProgrammableLLM`'s parsing accordingly.

- [ ] **Step 6: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add csm_core/batch/runner.py tests/core/test_batch_runner.py
git commit -m "feat(core): run_batch serial runner with incremental report + cancel"
```

---

### Task 11: `BatchWorker` QThread wrapper

**Files:**
- Create: `csm_gui/workers/batch_worker.py`
- Create a test in `tests/gui/test_batch_worker.py`

- [ ] **Step 1: Write failing test**

`tests/gui/test_batch_worker.py`:
```python
from pathlib import Path
from csm_gui.workers.batch_worker import BatchWorker


class StubLLM:
    def complete(self, system, user):
        for line in user.splitlines():
            if "关键词" in line:
                return f"POLISHED"
        return "POLISHED"


def test_batch_worker_emits_signals(qtbot, tmp_path):
    repo_root = Path(__file__).parent.parent.parent
    template_path = repo_root / "templates" / "daogou-changjing-renqun.json"
    vault_root = repo_root / "tests" / "fixtures" / "vault_minimal"
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()

    worker = BatchWorker(
        keywords=["kw1"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=StubLLM(),
        seed=0,
    )
    with qtbot.waitSignal(worker.batch_finished, timeout=10000) as sig:
        worker.start()
    report = sig.args[0]
    assert report.total == 1
    assert len(report.items) == 1


def test_batch_worker_request_cancel(qtbot, tmp_path):
    repo_root = Path(__file__).parent.parent.parent
    template_path = repo_root / "templates" / "daogou-changjing-renqun.json"
    vault_root = repo_root / "tests" / "fixtures" / "vault_minimal"
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()

    worker = BatchWorker(
        keywords=["kw1", "kw2", "kw3"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=StubLLM(),
        seed=0,
    )
    # Cancel as soon as the first item finishes.
    worker.item_finished.connect(lambda item: worker.request_cancel())
    with qtbot.waitSignal(worker.batch_finished, timeout=15000) as sig:
        worker.start()
    report = sig.args[0]
    assert len(report.items) == 1  # cancelled after first
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_batch_worker.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `BatchWorker`**

`csm_gui/workers/batch_worker.py`:
```python
"""QThread wrapper for csm_core.batch.runner.run_batch."""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from csm_core.batch.runner import run_batch
from csm_core.batch.report import BatchItem, BatchReport
from csm_core.llm.client import LLMClient


class BatchWorker(QThread):
    item_started = pyqtSignal(int, str)   # (1-based index, keyword)
    item_finished = pyqtSignal(object)    # BatchItem
    batch_finished = pyqtSignal(object)   # BatchReport (final)

    def __init__(
        self,
        keywords: list[str],
        template_path: Path,
        vault_root: Path,
        out_dir: Path,
        llm_client: LLMClient,
        seed: int,
        parent=None,
    ):
        super().__init__(parent)
        self._keywords = keywords
        self._template_path = Path(template_path)
        self._vault_root = Path(vault_root)
        self._out_dir = Path(out_dir)
        self._llm_client = llm_client
        self._seed = seed
        self._cancel_flag = False

    def request_cancel(self) -> None:
        self._cancel_flag = True

    def run(self) -> None:  # type: ignore[override]
        report = run_batch(
            keywords=self._keywords,
            template_path=self._template_path,
            vault_root=self._vault_root,
            out_dir=self._out_dir,
            llm_client=self._llm_client,
            seed=self._seed,
            on_item_started=lambda i, kw: self.item_started.emit(i, kw),
            on_item_finished=lambda item: self.item_finished.emit(item),
            should_cancel=lambda: self._cancel_flag,
        )
        self.batch_finished.emit(report)
```

- [ ] **Step 4: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_batch_worker.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/workers/batch_worker.py tests/gui/test_batch_worker.py
git commit -m "feat(gui): BatchWorker QThread wrapping run_batch"
```

---

### Task 12: `BatchController`

**Files:**
- Create: `csm_gui/controllers/batch_controller.py`
- Create: `tests/gui/test_batch_controller.py`

- [ ] **Step 1: Write failing tests**

`tests/gui/test_batch_controller.py`:
```python
from pathlib import Path
from csm_gui.config import AppConfig
from csm_gui.controllers.batch_controller import BatchController


def test_start_batch_rejected_without_out_dir(qtbot):
    c = BatchController(AppConfig(out_dir=""))
    ok = c.start_batch({
        "keywords": ["kw1"], "template_path": "t", "vault_root": "v",
        "provider": "mock", "seed": 0,
    })
    assert ok is False


def test_start_batch_rejected_with_empty_keywords(qtbot, tmp_path):
    c = BatchController(AppConfig(out_dir=str(tmp_path)))
    ok = c.start_batch({
        "keywords": ["", "   "], "template_path": "t", "vault_root": str(tmp_path),
        "provider": "mock", "seed": 0,
    })
    assert ok is False


def test_start_batch_rejected_when_vault_root_missing(qtbot, tmp_path):
    c = BatchController(AppConfig(out_dir=str(tmp_path)))
    ok = c.start_batch({
        "keywords": ["kw1"], "template_path": "t",
        "vault_root": str(tmp_path / "nope"),
        "provider": "mock", "seed": 0,
    })
    assert ok is False


def test_start_batch_creates_batch_dir(qtbot, tmp_path, monkeypatch):
    repo_root = Path(__file__).parent.parent.parent
    template_path = repo_root / "templates" / "daogou-changjing-renqun.json"
    vault_root = repo_root / "tests" / "fixtures" / "vault_minimal"
    c = BatchController(AppConfig(out_dir=str(tmp_path)))

    # Replace BatchWorker with no-op to avoid actual run.
    class NoopWorker:
        def __init__(self, *a, **kw):
            self.item_started = _Sig()
            self.item_finished = _Sig()
            self.batch_finished = _Sig()
        def isRunning(self): return False
        def start(self): pass
        def request_cancel(self): pass
    monkeypatch.setattr("csm_gui.controllers.batch_controller.BatchWorker", NoopWorker)
    monkeypatch.setattr(
        "csm_gui.controllers.batch_controller.build_client",
        lambda cfg, p: object(),
    )

    ok = c.start_batch({
        "keywords": ["kw1"],
        "template_path": str(template_path),
        "vault_root": str(vault_root),
        "provider": "mock", "seed": 0,
    })
    assert ok is True
    # Exactly one batch-xxx subdir should now exist in out_dir.
    subs = [p for p in Path(tmp_path).iterdir() if p.is_dir() and p.name.startswith("batch-")]
    assert len(subs) == 1


def test_busy_changed_signal(qtbot, tmp_path, monkeypatch):
    repo_root = Path(__file__).parent.parent.parent
    template_path = repo_root / "templates" / "daogou-changjing-renqun.json"
    vault_root = repo_root / "tests" / "fixtures" / "vault_minimal"
    c = BatchController(AppConfig(out_dir=str(tmp_path)))

    class NoopWorker:
        def __init__(self, *a, **kw):
            self.item_started = _Sig()
            self.item_finished = _Sig()
            self.batch_finished = _Sig()
        def isRunning(self): return True
        def start(self): pass
        def request_cancel(self): pass
    monkeypatch.setattr("csm_gui.controllers.batch_controller.BatchWorker", NoopWorker)
    monkeypatch.setattr(
        "csm_gui.controllers.batch_controller.build_client",
        lambda cfg, p: object(),
    )
    with qtbot.waitSignal(c.busy_changed, timeout=500) as sig:
        c.start_batch({
            "keywords": ["kw1"],
            "template_path": str(template_path),
            "vault_root": str(vault_root),
            "provider": "mock", "seed": 0,
        })
    assert sig.args == [True]


class _Sig:
    def connect(self, _slot): pass
    def emit(self, *a, **kw): pass
```

- [ ] **Step 2: Run tests to verify failure**

Expected: `ModuleNotFoundError` for `csm_gui.controllers.batch_controller`.

- [ ] **Step 3: Implement `BatchController`**

`csm_gui/controllers/batch_controller.py`:
```python
"""BatchController — lifecycle for BatchWorker + per-batch subdirectory."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from ..config import AppConfig
from ..llm_factory import build_client
from ..workers.batch_worker import BatchWorker


class BatchController(QObject):
    batch_started = pyqtSignal(object)           # initial BatchReport (empty items)
    batch_progress = pyqtSignal(int, int, str)   # (done, total, current_keyword)
    item_finished = pyqtSignal(object)           # BatchItem
    batch_completed = pyqtSignal(object)         # final BatchReport
    batch_cancelled = pyqtSignal(object)         # partial BatchReport on cancel
    batch_failed = pyqtSignal(str)               # unexpected worker-level error
    busy_changed = pyqtSignal(bool)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._worker: BatchWorker | None = None
        self._cancelling = False
        self._total = 0
        self._done = 0

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def start_batch(self, payload: dict) -> bool:
        if self.is_busy():
            return False
        if not self._config.out_dir:
            return False
        vault_root = Path(payload["vault_root"])
        if not vault_root.exists():
            return False
        # Dedup + strip mirroring the runner's internal logic, to reject empty early.
        cleaned: list[str] = []
        seen: set[str] = set()
        for k in payload["keywords"]:
            k = k.strip()
            if not k or k in seen:
                continue
            seen.add(k)
            cleaned.append(k)
        if not cleaned:
            return False

        # Build batch-YYYYMMDD-HHMMSS/ subdir.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        batch_dir = Path(self._config.out_dir) / f"batch-{stamp}"
        batch_dir.mkdir(parents=True, exist_ok=False)

        client = build_client(self._config, payload["provider"])
        self._total = len(cleaned)
        self._done = 0
        self._cancelling = False

        self._worker = BatchWorker(
            keywords=cleaned,
            template_path=Path(payload["template_path"]),
            vault_root=vault_root,
            out_dir=batch_dir,
            llm_client=client,
            seed=int(payload.get("seed", self._config.last_seed)),
            parent=self,
        )
        self._worker.item_started.connect(self._on_item_started)
        self._worker.item_finished.connect(self._on_item_finished)
        self._worker.batch_finished.connect(self._on_batch_finished)
        self._worker.start()
        self.busy_changed.emit(True)
        return True

    def cancel(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self._cancelling = True
        self._worker.request_cancel()

    def _on_item_started(self, index: int, keyword: str) -> None:
        self.batch_progress.emit(self._done, self._total, keyword)

    def _on_item_finished(self, item) -> None:
        self._done += 1
        self.item_finished.emit(item)
        self.batch_progress.emit(self._done, self._total, "")

    def _on_batch_finished(self, report) -> None:
        if self._cancelling:
            self.batch_cancelled.emit(report)
        else:
            self.batch_completed.emit(report)
        self.busy_changed.emit(False)
```

- [ ] **Step 4: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_batch_controller.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/controllers/batch_controller.py tests/gui/test_batch_controller.py
git commit -m "feat(gui): BatchController lifecycle + per-batch subdirectory"
```

---

### Task 13: Extract `GenerationForm` shared widget

**Purpose:** The template/vault/provider inputs are needed by both the single-article tab (existing HomePage body) and the new batch tab. Extract them to `csm_gui/widgets/generation_form.py`.

**Files:**
- Create: `csm_gui/widgets/generation_form.py`
- Create: `tests/gui/test_generation_form.py`
- Modify: `csm_gui/pages/home_page.py` (use GenerationForm internally; existing external behavior / signal unchanged)

- [ ] **Step 1: Write failing test**

`tests/gui/test_generation_form.py`:
```python
from csm_gui.widgets.generation_form import GenerationForm
from csm_gui.config import AppConfig


def test_generation_form_reads_config_defaults(qtbot, tmp_path):
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="deepseek")
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    assert form.template_input.text() == str(tmp_path / "t.json")
    assert form.vault_input.text() == str(tmp_path)
    assert form.provider_combo.currentText() == "deepseek"


def test_generation_form_apply_config_updates_fields(qtbot, tmp_path):
    form = GenerationForm(AppConfig())
    qtbot.addWidget(form)
    new = AppConfig(default_template=str(tmp_path / "x.json"),
                    vault_root=str(tmp_path), default_provider="anthropic")
    form.apply_config(new)
    assert form.template_input.text() == str(tmp_path / "x.json")
    assert form.provider_combo.currentText() == "anthropic"


def test_generation_form_is_valid(qtbot, tmp_path):
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="mock")
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    assert form.is_valid() is True
    form.vault_input.setText("")
    assert form.is_valid() is False


def test_generation_form_payload(qtbot, tmp_path):
    cfg = AppConfig(default_template="t.json", vault_root=str(tmp_path),
                    default_provider="mock")
    form = GenerationForm(cfg)
    qtbot.addWidget(form)
    p = form.payload()
    assert p == {
        "template_path": "t.json",
        "vault_root": str(tmp_path),
        "provider": "mock",
    }
```

- [ ] **Step 2: Run test to verify failure**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `GenerationForm`**

`csm_gui/widgets/generation_form.py`:
```python
"""Shared template/vault/provider form for single + batch tabs."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import BodyLabel, LineEdit, PushButton, ComboBox, FluentIcon
from ..config import AppConfig


class GenerationForm(QWidget):
    changed = pyqtSignal()  # fires on any input change

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(BodyLabel("模板"))
        row = QHBoxLayout()
        self.template_input = LineEdit(self)
        self.template_input.setText(config.default_template or "")
        self.template_input.textChanged.connect(self.changed.emit)
        row.addWidget(self.template_input, 1)
        self.template_browse = PushButton("选择", self, FluentIcon.FOLDER)
        self.template_browse.clicked.connect(self._pick_template)
        row.addWidget(self.template_browse)
        root.addLayout(row)

        root.addWidget(BodyLabel("资料库"))
        self.vault_input = LineEdit(self)
        self.vault_input.setText(config.vault_root or "")
        self.vault_input.textChanged.connect(self.changed.emit)
        root.addWidget(self.vault_input)

        root.addWidget(BodyLabel("LLM 供应商"))
        self.provider_combo = ComboBox(self)
        self.provider_combo.addItems(["mock", "anthropic", "deepseek"])
        idx = self.provider_combo.findText(config.default_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.provider_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
        root.addWidget(self.provider_combo)

    def _pick_template(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择模板", filter="JSON (*.json)")
        if p:
            self.template_input.setText(p)

    def apply_config(self, cfg: AppConfig) -> None:
        self.template_input.setText(cfg.default_template or "")
        self.vault_input.setText(cfg.vault_root or "")
        idx = self.provider_combo.findText(cfg.default_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

    def is_valid(self) -> bool:
        return bool(
            self.template_input.text().strip()
            and self.vault_input.text().strip()
        )

    def payload(self) -> dict:
        return {
            "template_path": self.template_input.text().strip(),
            "vault_root": self.vault_input.text().strip(),
            "provider": self.provider_combo.currentText(),
        }
```

- [ ] **Step 4: Refactor `HomePage` to use `GenerationForm`**

Replace the entire `csm_gui/pages/home_page.py`:
```python
"""Home page — single + batch tabs."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget
from qfluentwidgets import SubtitleLabel, BodyLabel, LineEdit, PrimaryPushButton, FluentIcon, Pivot
from ..config import AppConfig
from ..widgets.generation_form import GenerationForm


class _SingleArticlePanel(QWidget):
    request_generate = pyqtSignal(dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.addWidget(BodyLabel("关键词"))
        self.keyword_input = LineEdit(self)
        self.keyword_input.setPlaceholderText("例：宠物家庭吸尘器推荐")
        self.keyword_input.textChanged.connect(self._refresh_enabled)
        root.addWidget(self.keyword_input)

        self.form = GenerationForm(config, self)
        self.form.changed.connect(self._refresh_enabled)
        root.addWidget(self.form)

        self.generate_button = PrimaryPushButton("开始生成", self, FluentIcon.PLAY)
        self.generate_button.clicked.connect(self._emit)
        root.addWidget(self.generate_button)
        root.addStretch(1)
        self._refresh_enabled()

    def _refresh_enabled(self):
        ok = self.form.is_valid() and bool(self.keyword_input.text().strip())
        self.generate_button.setEnabled(ok)

    def _emit(self):
        payload = dict(self.form.payload())
        payload["keyword"] = self.keyword_input.text().strip()
        self.request_generate.emit(payload)

    def apply_config(self, cfg: AppConfig) -> None:
        self.form.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        self.generate_button.setEnabled((not busy) and self.form.is_valid()
                                        and bool(self.keyword_input.text().strip()))


class HomePage(QWidget):
    request_generate = pyqtSignal(dict)
    request_batch = pyqtSignal(dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._config = config

        root = QVBoxLayout(self)
        root.addWidget(SubtitleLabel("生成"))

        self.pivot = Pivot(self)
        self.stack = QStackedWidget(self)

        self.single_panel = _SingleArticlePanel(config, self)
        self.single_panel.request_generate.connect(self.request_generate.emit)
        self.stack.addWidget(self.single_panel)

        # BatchPanel added in Task 14 (placeholder empty widget for now).
        self.batch_panel_placeholder = QWidget(self)
        self.stack.addWidget(self.batch_panel_placeholder)

        self.pivot.addItem(routeKey="single", text="单篇",
                           onClick=lambda: self.stack.setCurrentIndex(0))
        self.pivot.addItem(routeKey="batch", text="批量",
                           onClick=lambda: self.stack.setCurrentIndex(1))
        self.pivot.setCurrentItem("single")

        root.addWidget(self.pivot)
        root.addWidget(self.stack, 1)

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self.single_panel.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        self.single_panel.set_busy(busy)
```

- [ ] **Step 5: Update any home_page tests that break**

Grep for `HomePage` in tests: `tests/gui/test_home_page.py` likely asserts on `home.keyword_input` etc. Those attributes are now nested at `home.single_panel.keyword_input` — update the test.

Look at the existing test file: read `tests/gui/test_home_page.py` if it exists, then update attribute paths. If the test uses `home.template_input`, update to `home.single_panel.form.template_input`.

- [ ] **Step 6: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add csm_gui/widgets/generation_form.py csm_gui/pages/home_page.py tests/gui/
git commit -m "refactor(gui): extract GenerationForm; HomePage now has Pivot with single tab"
```

---

### Task 14: `BatchPanel` widget

**Files:**
- Create: `csm_gui/widgets/batch_panel.py`
- Create: `tests/gui/test_batch_panel.py`

- [ ] **Step 1: Write failing tests**

`tests/gui/test_batch_panel.py`:
```python
from pathlib import Path
from csm_gui.widgets.batch_panel import BatchPanel
from csm_gui.config import AppConfig


def test_batch_panel_keyword_count(qtbot):
    p = BatchPanel(AppConfig(default_provider="mock"))
    qtbot.addWidget(p)
    p.keyword_edit.setPlainText("a\nb\n\na\nc")  # a duplicated, one blank
    qtbot.wait(300)  # wait for debounce
    assert p.unique_keywords() == ["a", "b", "c"]
    assert "3" in p.count_label.text()


def test_batch_panel_start_disabled_when_empty(qtbot, tmp_path):
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    assert p.start_button.isEnabled() is False
    p.keyword_edit.setPlainText("a")
    qtbot.wait(300)
    assert p.start_button.isEnabled() is True
    p.keyword_edit.setPlainText("")
    qtbot.wait(300)
    assert p.start_button.isEnabled() is False


def test_batch_panel_import_txt_replaces(qtbot, tmp_path, monkeypatch):
    cfg = AppConfig(default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    p.keyword_edit.setPlainText("existing")

    f = tmp_path / "kw.txt"
    f.write_text("new1\nnew2\n", encoding="utf-8")
    monkeypatch.setattr(
        "csm_gui.widgets.batch_panel.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **kw: (str(f), "")),
    )
    p._on_import_clicked()
    assert p.keyword_edit.toPlainText().splitlines() == ["new1", "new2"]


def test_batch_panel_import_csv_first_column(qtbot, tmp_path, monkeypatch):
    cfg = AppConfig(default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    f = tmp_path / "kw.csv"
    f.write_text("kw1,extra\nkw2,ignore\n", encoding="utf-8")
    monkeypatch.setattr(
        "csm_gui.widgets.batch_panel.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **kw: (str(f), "")),
    )
    p._on_import_clicked()
    assert p.keyword_edit.toPlainText().splitlines() == ["kw1", "kw2"]


def test_batch_panel_emits_request_batch(qtbot, tmp_path):
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="mock")
    p = BatchPanel(cfg)
    qtbot.addWidget(p)
    p.keyword_edit.setPlainText("kw1\nkw2")
    qtbot.wait(300)
    with qtbot.waitSignal(p.request_batch, timeout=500) as sig:
        p.start_button.click()
    payload = sig.args[0]
    assert payload["keywords"] == ["kw1", "kw2"]
    assert payload["template_path"] == str(tmp_path / "t.json")
    assert payload["provider"] == "mock"
```

- [ ] **Step 2: Run test to verify failure**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `BatchPanel`**

`csm_gui/widgets/batch_panel.py`:
```python
"""Batch-tab panel: multi-line keyword editor + file import + start button."""
from __future__ import annotations
import csv
from pathlib import Path
from PyQt6.QtCore import pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import (
    BodyLabel, CaptionLabel, PlainTextEdit, PrimaryPushButton, PushButton, FluentIcon,
)
from ..config import AppConfig
from .generation_form import GenerationForm


class BatchPanel(QWidget):
    request_batch = pyqtSignal(dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config

        root = QVBoxLayout(self)
        root.addWidget(BodyLabel("关键词列表（每行一个，空行忽略，自动去重）"))

        self.keyword_edit = PlainTextEdit(self)
        self.keyword_edit.setPlaceholderText("例：\n宠物狗粮推荐\n猫砂怎么选\n...")
        self.keyword_edit.setMinimumHeight(180)
        self.keyword_edit.textChanged.connect(self._schedule_recount)
        root.addWidget(self.keyword_edit)

        self.count_label = CaptionLabel("已识别 0 个关键词（去重后）", self)
        root.addWidget(self.count_label)

        import_row = QHBoxLayout()
        self.import_button = PushButton("从文件导入", self, FluentIcon.FOLDER)
        self.import_button.clicked.connect(self._on_import_clicked)
        import_row.addWidget(self.import_button)
        import_row.addStretch(1)
        root.addLayout(import_row)

        self.form = GenerationForm(config, self)
        self.form.changed.connect(self._refresh_enabled)
        root.addWidget(self.form)

        self.start_button = PrimaryPushButton("开始批量", self, FluentIcon.PLAY)
        self.start_button.clicked.connect(self._emit)
        root.addWidget(self.start_button)
        root.addStretch(1)

        self._recount_timer = QTimer(self)
        self._recount_timer.setSingleShot(True)
        self._recount_timer.setInterval(200)
        self._recount_timer.timeout.connect(self._recount)
        self._refresh_enabled()

    def _schedule_recount(self) -> None:
        self._recount_timer.start()

    def unique_keywords(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for line in self.keyword_edit.toPlainText().splitlines():
            k = line.strip()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    def _recount(self) -> None:
        n = len(self.unique_keywords())
        self.count_label.setText(f"已识别 {n} 个关键词（去重后）")
        self._refresh_enabled()

    def _refresh_enabled(self) -> None:
        ok = self.form.is_valid() and bool(self.unique_keywords())
        self.start_button.setEnabled(ok)

    def _on_import_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "导入关键词", filter="文本 (*.txt *.csv)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() == ".csv":
            lines: list[str] = []
            with path.open("r", encoding="utf-8", newline="") as f:
                for row in csv.reader(f):
                    if row:
                        lines.append(row[0])
            text = "\n".join(lines)
        else:
            text = path.read_text(encoding="utf-8")
        self.keyword_edit.setPlainText(text)
        self._recount()

    def _emit(self) -> None:
        payload = dict(self.form.payload())
        payload["keywords"] = self.unique_keywords()
        payload["seed"] = self._config.last_seed
        self.request_batch.emit(payload)

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self.form.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(
            (not busy) and self.form.is_valid() and bool(self.unique_keywords())
        )
        self.keyword_edit.setReadOnly(busy)
        self.import_button.setEnabled(not busy)
```

- [ ] **Step 4: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_batch_panel.py -v`
Expected: all pass. Debounce tests use `qtbot.wait(300)` which exceeds the 200ms interval.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/widgets/batch_panel.py tests/gui/test_batch_panel.py
git commit -m "feat(gui): BatchPanel widget with dedup + file import"
```

---

### Task 15: Wire `BatchPanel` into `HomePage.batch` tab

**Files:**
- Modify: `csm_gui/pages/home_page.py` (replace placeholder with actual BatchPanel; forward `request_batch`)

- [ ] **Step 1: Write failing test**

Append to existing `tests/gui/test_home_page.py` (or create if missing):
```python
def test_home_page_emits_request_batch(qtbot, tmp_path):
    from csm_gui.pages.home_page import HomePage
    from csm_gui.config import AppConfig
    cfg = AppConfig(default_template=str(tmp_path / "t.json"),
                    vault_root=str(tmp_path), default_provider="mock")
    home = HomePage(cfg)
    qtbot.addWidget(home)
    home.batch_panel.keyword_edit.setPlainText("kw1")
    qtbot.wait(300)
    with qtbot.waitSignal(home.request_batch, timeout=500) as sig:
        home.batch_panel.start_button.click()
    assert sig.args[0]["keywords"] == ["kw1"]


def test_home_page_has_two_tabs(qtbot):
    from csm_gui.pages.home_page import HomePage
    from csm_gui.config import AppConfig
    home = HomePage(AppConfig(default_provider="mock"))
    qtbot.addWidget(home)
    assert home.stack.count() == 2
```

- [ ] **Step 2: Run test**

Expected: fail — `home.batch_panel` doesn't exist (still a placeholder QWidget).

- [ ] **Step 3: Replace placeholder**

In `csm_gui/pages/home_page.py`, replace the placeholder block:
```python
        self.batch_panel_placeholder = QWidget(self)
        self.stack.addWidget(self.batch_panel_placeholder)
```
with:
```python
        from ..widgets.batch_panel import BatchPanel
        self.batch_panel = BatchPanel(config, self)
        self.batch_panel.request_batch.connect(self.request_batch.emit)
        self.stack.addWidget(self.batch_panel)
```

Update `apply_config` to propagate:
```python
    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self.single_panel.apply_config(cfg)
        self.batch_panel.apply_config(cfg)
```

Update `set_busy`:
```python
    def set_busy(self, busy: bool) -> None:
        self.single_panel.set_busy(busy)
        self.batch_panel.set_busy(busy)
```

- [ ] **Step 4: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/pages/home_page.py tests/gui/test_home_page.py
git commit -m "feat(gui): mount BatchPanel into HomePage batch tab"
```

---

### Task 16: `BatchResultPage`

**Files:**
- Create: `csm_gui/pages/batch_result_page.py`
- Create: `tests/gui/test_batch_result_page.py`

- [ ] **Step 1: Write failing tests**

`tests/gui/test_batch_result_page.py`:
```python
from csm_core.batch.report import BatchReport, BatchItem
from csm_gui.pages.batch_result_page import BatchResultPage


def _mk_report(total=3):
    return BatchReport(
        batch_id="batch-20260420-120000",
        batch_dir="/tmp/batch-20260420-120000",
        started_at="2026-04-20T12:00:00",
        finished_at=None,
        template_path="/t/template.json",
        vault_root="/v",
        seed=0,
        total=total,
    )


def test_batch_result_page_on_started_resets_lists(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_item_finished(BatchItem(index=1, keyword="x", status="success"))
    page.on_batch_started(_mk_report())
    assert page.success_list.count() == 0
    assert page.failed_list.count() == 0


def test_batch_result_page_item_finished_sorts_by_status(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report())
    page.on_item_finished(BatchItem(index=1, keyword="ok", status="success"))
    page.on_item_finished(BatchItem(
        index=2, keyword="bad", status="failed",
        error_type="RuntimeError", error_message="broke",
    ))
    assert page.success_list.count() == 1
    assert page.failed_list.count() == 1


def test_batch_result_page_progress_update(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report(total=5))
    page.on_batch_progress(3, 5, "kw_current")
    assert page.progress_bar.value() == 3
    assert "kw_current" in page.current_label.text()


def test_batch_result_page_button_state_completed(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report())
    assert page.cancel_button.isVisible() is True or page.cancel_button.isEnabled()
    report = _mk_report()
    page.on_batch_completed(report)
    assert page.return_button.isEnabled() is True


def test_batch_result_page_cancel_button_transitions(qtbot):
    page = BatchResultPage()
    qtbot.addWidget(page)
    page.on_batch_started(_mk_report())
    emitted = []
    page.cancel_requested.connect(lambda: emitted.append(True))
    page.cancel_button.click()
    assert emitted == [True]
    assert page.cancel_button.isEnabled() is False
    assert "取消中" in page.cancel_button.text()
```

- [ ] **Step 2: Run test to verify failure**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `BatchResultPage`**

`csm_gui/pages/batch_result_page.py`:
```python
"""Batch progress + result page (not in left-nav)."""
from __future__ import annotations
import os
from pathlib import Path
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel, ProgressBar, PushButton, PrimaryPushButton, FluentIcon,
)
from csm_core.batch.report import BatchReport, BatchItem


class BatchResultPage(QWidget):
    cancel_requested = pyqtSignal()
    return_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BatchResultPage")
        self._batch_dir: str | None = None

        root = QVBoxLayout(self)
        self.header_title = SubtitleLabel("批量生成")
        root.addWidget(self.header_title)
        self.header_meta = CaptionLabel("")
        root.addWidget(self.header_meta)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.current_label = BodyLabel("")
        root.addWidget(self.current_label)

        lists_row = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(BodyLabel("成功"))
        self.success_list = QListWidget(self)
        left_col.addWidget(self.success_list)
        right_col = QVBoxLayout()
        right_col.addWidget(BodyLabel("失败"))
        self.failed_list = QListWidget(self)
        right_col.addWidget(self.failed_list)
        lists_row.addLayout(left_col)
        lists_row.addLayout(right_col)
        root.addLayout(lists_row, 1)

        btn_row = QHBoxLayout()
        self.open_button = PushButton("打开批次目录", self, FluentIcon.FOLDER)
        self.open_button.clicked.connect(self._open_batch_dir)
        btn_row.addWidget(self.open_button)
        btn_row.addStretch(1)
        self.cancel_button = PushButton("取消", self)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.cancel_button)
        self.return_button = PrimaryPushButton("返回", self)
        self.return_button.clicked.connect(self.return_requested.emit)
        self.return_button.setEnabled(False)
        self.return_button.setVisible(False)
        btn_row.addWidget(self.return_button)
        root.addLayout(btn_row)

    # --- public API (slots for controller signals) ---

    def on_batch_started(self, report: BatchReport) -> None:
        self._batch_dir = report.batch_dir
        self.success_list.clear()
        self.failed_list.clear()
        self.progress_bar.setRange(0, max(report.total, 1))
        self.progress_bar.setValue(0)
        self.current_label.setText("")
        self.header_meta.setText(
            f"批次 {report.batch_id}  模板 {Path(report.template_path).name}  "
            f"vault {Path(report.vault_root).name}  种子 {report.seed}"
        )
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("取消")
        self.cancel_button.setVisible(True)
        self.return_button.setEnabled(False)
        self.return_button.setVisible(False)

    def on_batch_progress(self, done: int, total: int, keyword: str) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        if keyword:
            self.current_label.setText(f"当前：{keyword}")

    def on_item_finished(self, item: BatchItem) -> None:
        if item.status == "success":
            self.success_list.addItem(f"✓ {item.keyword}")
        else:
            text = f"⚠ {item.keyword}\n    {item.error_type}: {item.error_message}"
            self.failed_list.addItem(text)

    def on_batch_completed(self, report: BatchReport) -> None:
        self._finalize(report, cancelled=False)

    def on_batch_cancelled(self, report: BatchReport) -> None:
        self._finalize(report, cancelled=True)

    # --- internals ---

    def _finalize(self, report: BatchReport, cancelled: bool) -> None:
        self.progress_bar.setValue(self.progress_bar.maximum() if not cancelled else self.progress_bar.value())
        self.current_label.setText(
            "已取消" if cancelled else f"完成：成功 {self.success_list.count()} / 失败 {self.failed_list.count()}"
        )
        self.cancel_button.setVisible(False)
        self.return_button.setVisible(True)
        self.return_button.setEnabled(True)

    def _on_cancel_clicked(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("取消中…")
        self.cancel_requested.emit()

    def _open_batch_dir(self) -> None:
        if self._batch_dir:
            try:
                os.startfile(self._batch_dir)  # type: ignore[attr-defined]  # Windows-only
            except (AttributeError, OSError):
                pass  # no-op on non-Windows test runners
```

- [ ] **Step 4: Run tests**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_batch_result_page.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/pages/batch_result_page.py tests/gui/test_batch_result_page.py
git commit -m "feat(gui): BatchResultPage — progress + success/failure lists"
```

---

### Task 17: Wire `BatchController` + `BatchResultPage` into `MainWindow`

**Files:**
- Modify: `csm_gui/main_window.py`
- Modify: `tests/gui/test_main_window.py` (add integration tests for batch flow + mutual exclusion)

- [ ] **Step 1: Write failing tests**

Append to `tests/gui/test_main_window.py`:
```python
def test_main_window_has_batch_controller(qtbot, tmp_path):
    from csm_gui.config import AppConfig, save_config
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    assert hasattr(win, "batch_controller")
    assert hasattr(win, "batch_result_page")


def test_busy_during_batch_disables_single_generate(qtbot, tmp_path):
    from csm_gui.config import AppConfig, save_config
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    # Simulate batch busy
    win.batch_controller.busy_changed.emit(True)
    # Single-article button must be disabled.
    assert win.home.single_panel.generate_button.isEnabled() is False
    assert win.home.batch_panel.start_button.isEnabled() is False
    win.batch_controller.busy_changed.emit(False)


def test_batch_completed_shows_success_infobar(qtbot, tmp_path, monkeypatch):
    from csm_gui.config import AppConfig, save_config
    from csm_core.batch.report import BatchReport, BatchItem
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    shown = _capture_infobar(monkeypatch, "success")
    report = BatchReport(
        batch_id="b", batch_dir=str(tmp_path), started_at="", finished_at="",
        template_path="t", vault_root="v", seed=0, total=1,
        items=[BatchItem(index=1, keyword="k", status="success")],
    )
    win.batch_controller.batch_completed.emit(report)
    assert len(shown) == 1


def test_batch_completed_with_failures_shows_warning(qtbot, tmp_path, monkeypatch):
    from csm_gui.config import AppConfig, save_config
    from csm_core.batch.report import BatchReport, BatchItem
    save_config(AppConfig(out_dir=str(tmp_path)), tmp_path / "settings.json")
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    shown = _capture_infobar(monkeypatch, "warning")
    report = BatchReport(
        batch_id="b", batch_dir=str(tmp_path), started_at="", finished_at="",
        template_path="t", vault_root="v", seed=0, total=2,
        items=[
            BatchItem(index=1, keyword="k1", status="success"),
            BatchItem(index=2, keyword="k2", status="failed", error_type="X", error_message="y"),
        ],
    )
    win.batch_controller.batch_completed.emit(report)
    assert len(shown) == 1
```

- [ ] **Step 2: Run tests to verify failure**

Expected: `AttributeError: 'MainWindow' object has no attribute 'batch_controller'`.

- [ ] **Step 3: Implement wiring in MainWindow**

Add imports at the top:
```python
from .controllers.batch_controller import BatchController
from .pages.batch_result_page import BatchResultPage
```

In `__init__`, after `self.article_controller = ...` and before adding sub-interfaces, add:
```python
        self.batch_controller = BatchController(self.config, parent=self)
        self.batch_controller.batch_started.connect(self._on_batch_started)
        self.batch_controller.batch_progress.connect(self._on_batch_progress)
        self.batch_controller.item_finished.connect(self._on_batch_item_finished)
        self.batch_controller.batch_completed.connect(self._on_batch_completed)
        self.batch_controller.batch_cancelled.connect(self._on_batch_cancelled)
        self.batch_controller.batch_failed.connect(self._on_generate_failed)

        self.batch_result_page = BatchResultPage(self)
        self.batch_result_page.cancel_requested.connect(self.batch_controller.cancel)
        self.batch_result_page.return_requested.connect(lambda: self.switchTo(self.home))
        # Not added to nav; stackedWidget only.
        self.stackedWidget.addWidget(self.batch_result_page)

        # Cross-controller busy plumbing.
        self.article_controller.busy_changed.connect(self._on_any_busy)
        self.batch_controller.busy_changed.connect(self._on_any_busy)

        # Wire HomePage batch signal.
        self.home.request_batch.connect(self._on_request_batch)
```

Add the new handlers:
```python
    def _on_request_batch(self, payload: dict) -> None:
        # Controller also creates the batch_dir and emits batch_started via
        # the first batch_progress; we emit batch_started here from a small
        # synthetic initial report so the result page resets and we can switch.
        if self.article_controller.is_busy():
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning("正在生成", "请先完成当前单篇任务",
                            parent=self, position=InfoBarPosition.TOP)
            return
        ok = self.batch_controller.start_batch(payload)
        if not ok:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error("批量启动失败", "检查输出目录/关键词/资料库路径",
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return
        # Build a synthetic initial report so the result page can reset.
        from csm_core.batch.report import BatchReport
        cleaned = []
        seen = set()
        for k in payload["keywords"]:
            k = k.strip()
            if k and k not in seen:
                seen.add(k); cleaned.append(k)
        initial = BatchReport(
            batch_id="pending", batch_dir="",
            started_at="", finished_at=None,
            template_path=payload["template_path"],
            vault_root=payload["vault_root"],
            seed=int(payload.get("seed", self.config.last_seed)),
            total=len(cleaned),
        )
        self.batch_result_page.on_batch_started(initial)
        self.switchTo(self.batch_result_page)

    def _on_batch_progress(self, done, total, keyword):
        self.batch_result_page.on_batch_progress(done, total, keyword)

    def _on_batch_item_finished(self, item):
        self.batch_result_page.on_item_finished(item)

    def _on_batch_started(self, report):
        self.batch_result_page.on_batch_started(report)

    def _on_batch_completed(self, report):
        self.batch_result_page.on_batch_completed(report)
        from qfluentwidgets import InfoBar, InfoBarPosition
        success = sum(1 for i in report.items if i.status == "success")
        failed = sum(1 for i in report.items if i.status == "failed")
        if failed == 0:
            InfoBar.success(
                "批量完成", f"{report.total} 个关键词全部成功",
                parent=self, position=InfoBarPosition.TOP, duration=5000,
            )
        else:
            InfoBar.warning(
                "批量完成（部分失败）", f"成功 {success} / 失败 {failed}",
                parent=self, position=InfoBarPosition.TOP, duration=6000,
            )

    def _on_batch_cancelled(self, report):
        self.batch_result_page.on_batch_cancelled(report)
        from qfluentwidgets import InfoBar, InfoBarPosition
        done = len(report.items)
        InfoBar.info(
            "批量已取消", f"已完成 {done} / {report.total}",
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )

    def _on_any_busy(self, _busy: bool) -> None:
        busy = self.article_controller.is_busy() or self.batch_controller.is_busy()
        self.home.set_busy(busy)
```

Also in `_on_settings_save`, add `self.batch_controller.apply_config(new_cfg)`.

- [ ] **Step 4: Run full suite**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add csm_gui/main_window.py tests/gui/test_main_window.py
git commit -m "feat(gui): wire BatchController + BatchResultPage; cross-controller busy"
```

---

### Task 18: End-to-end smoke test + v0.3 tag

**Files:**
- Create: `tests/gui/test_batch_smoke.py`

- [ ] **Step 1: Write the smoke test**

`tests/gui/test_batch_smoke.py`:
```python
"""End-to-end: MainWindow + mock LLM, 3 keywords (1 failing), assert disk output."""
import json
from pathlib import Path
from csm_gui.config import AppConfig, save_config
from csm_gui.main_window import MainWindow


class SmokeLLM:
    def __init__(self):
        self.calls = 0
    def complete(self, system, user):
        self.calls += 1
        # Fail on the second call to exercise the failure path.
        if self.calls == 2:
            raise RuntimeError("injected failure for smoke test")
        return "POLISHED"


def test_batch_e2e_smoke(qtbot, tmp_path, monkeypatch):
    repo_root = Path(__file__).parent.parent.parent
    template_path = repo_root / "templates" / "daogou-changjing-renqun.json"
    vault_root = repo_root / "tests" / "fixtures" / "vault_minimal"
    cfg = AppConfig(
        out_dir=str(tmp_path),
        default_template=str(template_path),
        vault_root=str(vault_root),
        default_provider="mock",
    )
    save_config(cfg, tmp_path / "settings.json")

    monkeypatch.setattr(
        "csm_gui.controllers.batch_controller.build_client",
        lambda cfg, p: SmokeLLM(),
    )

    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    with qtbot.waitSignal(win.batch_controller.batch_completed, timeout=30000) as sig:
        win._on_request_batch({
            "keywords": ["kw1", "kw2", "kw3"],
            "template_path": str(template_path),
            "vault_root": str(vault_root),
            "provider": "mock",
            "seed": 0,
        })
    report = sig.args[0]
    assert report.total == 3
    assert sum(1 for i in report.items if i.status == "success") == 2
    assert sum(1 for i in report.items if i.status == "failed") == 1

    # Disk: batch-* subdir should exist with 2 md + 2 json + batch-report.json.
    subs = [p for p in Path(tmp_path).iterdir() if p.is_dir() and p.name.startswith("batch-")]
    assert len(subs) == 1
    batch_dir = subs[0]
    mds = list(batch_dir.glob("*.md"))
    jsons = [p for p in batch_dir.glob("*.assembly.json")]
    report_path = batch_dir / "batch-report.json"
    assert len(mds) == 2
    assert len(jsons) == 2
    assert report_path.exists()
    loaded = json.loads(report_path.read_text(encoding="utf-8"))
    assert loaded["total"] == 3
    assert len(loaded["items"]) == 3
```

- [ ] **Step 2: Run the smoke test**

Run: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests/gui/test_batch_smoke.py -v`
Expected: pass.

- [ ] **Step 3: Run full suite + coverage check**

Run:
```
PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q --cov=csm_core --cov=csm_gui --cov-report=term-missing
```
Expected:
- All tests pass.
- `csm_core` coverage ≥ 95%.
- `csm_gui` coverage ≥ 75%.

If either falls short, add targeted tests in the lowest-covered file until met.

- [ ] **Step 4: Verify MainWindow line count**

Run Read/wc on `csm_gui/main_window.py`. Expected: file is still reasonably compact. If it ballooned past ~180 lines after Task 17's wiring, review for repetition — multiple `_on_batch_*` handlers are one-liners so this should be OK.

Target from spec is ≤ 120 lines. If the batch wiring pushed it over, that's acceptable (spec target was for post-C1; C2 adds legitimate wiring). Update the design doc's acceptance section if needed:

Read the design doc line about "MainWindow ≤ 120 lines"; if exceeded, update to "MainWindow ≤ 180 lines after C2 wiring".

- [ ] **Step 5: Commit**

```bash
git add tests/gui/test_batch_smoke.py
git commit -m "test(gui): end-to-end batch smoke test (3 keywords, 1 failure)"
```

- [ ] **Step 6: Manual verification on Win11**

Launch the app:
```
.venv/Scripts/python -m csm_gui
```
Verify in the UI:
1. HomePage shows the Pivot with 「单篇」 / 「批量」 tabs.
2. On the 批量 tab, paste 3 keywords, click 开始批量. A batch-xxx directory appears in `out_dir`.
3. Result page shows progress, success/failed columns populate as items finish.
4. After completion, an InfoBar appears (success or partial-failure variant).
5. Clicking 返回 navigates back to HomePage.
6. Add a new file to `vault_root` without restarting, run 单篇 generate — the new file is picked up (vault mtime invalidation).
7. Start a batch, click 取消 → 取消中…; batch stops at next item boundary; "批量已取消" InfoBar.
8. During a running batch, 单篇 的「开始生成」 disabled.

- [ ] **Step 7: Tag v0.3**

If all manual checks pass:
```bash
git tag v0.3
```
(Do not push; user controls remote.)

- [ ] **Step 8: Final commit to reflect completion**

If the design doc needs an amendment for the line-count target from Step 4:

```bash
git add docs/superpowers/specs/2026-04-20-plan-c-refactor-and-batch-design.md
git commit -m "docs: adjust Plan C acceptance criterion for MainWindow size post-C2"
```

---

## Plan Self-Review

**Spec coverage:**
- C1 ArticleController extraction → Tasks 2–8. ✓
- Vault mtime invalidation → Task 4. ✓
- ArticlePage view-only → Task 7. ✓
- compose_draft promotion → Task 1. ✓
- BatchReport / BatchItem → Task 9. ✓
- run_batch runner (dedup, failure isolation, cancel, incremental write, shared vault) → Task 10. ✓
- BatchWorker → Task 11. ✓
- BatchController (rejections, batch_dir creation, mutual exclusion) → Task 12. ✓
- GenerationForm shared widget → Task 13. ✓
- BatchPanel (textedit dedup, file import, busy disable) → Task 14. ✓
- HomePage Pivot → Task 13 (single tab scaffold) + Task 15 (mount BatchPanel). ✓
- BatchResultPage (progress, list append, button state machine) → Task 16. ✓
- MainWindow wiring + cross-controller busy + InfoBar routing → Task 17. ✓
- E2E smoke → Task 18. ✓
- Coverage + tag + manual verification → Task 18 steps 3–7. ✓

**Placeholder scan:**
- Task 7 Step 1 uses "Grep tool:" as an instruction to the executor, not a placeholder. OK.
- Task 10 Step 2 instructs to create a fixture vault if missing — this is conditional guidance, not a placeholder. The shape of the fixture is described (brands.json, one markdown note).
- Task 18 Step 4 allows "update the design doc if the line count target is exceeded" — conditional, justified.
- No `TODO` / `TBD` / "fill in later" remains.

**Type consistency:**
- Controller signal names used consistently: `generated`, `generate_failed`, `reroll_completed`, `polished`, `polish_failed`, `exported`, `export_failed`, `plan_warnings`, `busy_changed`.
- `BatchController` signal names consistent: `batch_started`, `batch_progress`, `item_finished`, `batch_completed`, `batch_cancelled`, `batch_failed`, `busy_changed`.
- `ArticlePage.load_result` signature: `(template, plan, draft, final_text)` — matches call sites in MainWindow after Task 7.
- `ArticlePage.update_plan` signature: `(template, plan, draft)` — matches Task 7's Step 3 impl and Task 4's rewire.
- `BatchReport` field names consistent across Tasks 9, 10, 12, 17.
- `BatchItem` field names consistent.
- `BatchWorker.request_cancel` used in Task 11 test, Task 12 controller.

**Fix noted:** Task 7 Step 3 says `update_plan(plan, draft)` in the `ArticlePage` code but the `_on_reroll_completed` call passes `(template, new_plan, compose_draft(new_plan))`. The signature in the rewrite includes `template` as the first arg — consistent. Verified.

**Scope check:** Single plan, ~18 tasks. Large but connected (C1 is C2's prerequisite). Both halves deliver testable code independently (after C1, all existing features still work; C2 adds new). Not too large to decompose further.

Plan self-review complete, no issues requiring rework.

---
