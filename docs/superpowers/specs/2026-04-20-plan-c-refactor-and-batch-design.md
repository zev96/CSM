# Plan C Design — Controller Refactor + Batch Mode

**Status:** Approved (2026-04-20)
**Successor to:** Plan B (v0.2)
**Target tag:** v0.3

## Goal

Ship two things, in order:

1. **C1 — Controller refactor.** Extract an `ArticleController` from `MainWindow` so UI orchestration state and workflow logic live separately from the window shell. Fix the `vault_cache` mtime-blindness that ships in v0.2. No user-visible change.
2. **C2 — Batch mode.** Let users generate N articles from a list of keywords in one unattended run, with per-item failure isolation, a per-batch output subdirectory, and a persisted batch report.

Plan C deliberately excludes: keyring migration, fine-grained progress stages, template management UI, .docx export, framework→template import, concurrent batch, cross-batch queue. Those are Plan D candidates.

## Non-Goals

- Parallel batch execution. Serial only. If users ask for parallelism later, add it in Plan D — don't pre-build hooks for it.
- "Resume a crashed batch." Crash recovery is implicit via the incrementally-written `batch-report.json`, but there's no UI to continue a partial batch. User reruns the failed subset manually.
- Editing keywords mid-batch. Once a batch starts, the keyword list is frozen.

## Architecture Overview

### C1 — Controller layer

New package `csm_gui/controllers/`. `ArticleController(QObject)` owns the article workflow state (current result, template, reroll counter, vault cache, generate/polish workers) and exposes a signal-based API. `MainWindow` keeps only: window shell, three-page navigation, config load/save, and InfoBar routing on controller signals.

`ArticlePage` loses its private workflow state (`_template`, `_compose_draft`, `_reroll_counter`, `current_result`) — the page becomes a pure view that renders whatever the controller hands it.

`compose_draft(plan) -> str` promotes from a private `ArticlePage` method to a public function in `csm_core/assembler/render.py`, because C2's batch runner also needs it (indirectly, via `run_generate`, but the function is a natural core API).

### C2 — Batch layer

Split across core and gui to preserve Plan A/B's layering:

- `csm_core/batch/report.py` — `BatchReport` / `BatchItem` dataclasses + atomic read/write.
- `csm_core/batch/runner.py` — `run_batch(...)` pure function, no Qt imports. Iterates keywords, reuses `csm_core.pipeline.run_generate`, catches per-item exceptions, writes `batch-report.json` incrementally, respects `should_cancel()`.
- `csm_gui/workers/batch_worker.py` — `BatchWorker(QThread)` wraps `run_batch`, translates runner callbacks into Qt signals, exposes `request_cancel()`.
- `csm_gui/controllers/batch_controller.py` — `BatchController(QObject)` owns the worker lifecycle, builds `batch-YYYYMMDD-HHMMSS/` dir, enforces mutual exclusion with `ArticleController`.
- `csm_gui/pages/batch_result_page.py` — progress page (not in left-nav; only shown via `switchTo` during/after a batch).
- `csm_gui/widgets/generation_form.py` — shared form (template / vault / seed / provider) extracted from the current single-article HomePage, reused by both single and batch tabs.
- `csm_gui/widgets/batch_panel.py` — batch-only panel (keyword textarea + file import + start button), embeds `GenerationForm`.
- `csm_gui/pages/home_page.py` — adds a `Pivot` with two tabs: "单篇" (existing UI) / "批量" (new `BatchPanel`).

## Tech Stack

- PyQt6 + PyQt6-Fluent-Widgets 1.11.2 (already in use)
- pytest-qt's built-in `qtbot` fixture
- Test command: `PYTEST_QT_API=pyqt6 .venv/Scripts/python -m pytest tests -q`

## Detailed Design

### ArticleController contract

```python
class ArticleController(QObject):
    # Signals
    generated = pyqtSignal(object)           # GenerateResult
    generate_failed = pyqtSignal(str)
    reroll_completed = pyqtSignal(object)    # AssemblyPlan
    polished = pyqtSignal(str)
    polish_failed = pyqtSignal(str)
    exported = pyqtSignal(dict)              # {"markdown": path, "assembly_json": path}
    export_failed = pyqtSignal(str)
    plan_warnings = pyqtSignal(list)         # list[str]
    busy_changed = pyqtSignal(bool)

    # Internal state (all private)
    _config: AppConfig
    _current_result: GenerateResult | None
    _current_template: Template | None
    _last_template_path: Path | None
    _reroll_counter: int
    _vault_cache: tuple[Path, float, Index, Registry] | None  # (root, mtime, index, registry)
    _generate_worker: GenerateWorker | None
    _polish_worker: PolishWorker | None

    # Public API
    def apply_config(self, cfg: AppConfig) -> None
    def request_generate(self, payload: dict) -> bool        # False = rejected
    def reroll_slot(self, slot_id: str, user_config: dict) -> None
    def polish(self, provider: str, skill_path: Path | None) -> None
    def export(self) -> None
    def is_busy(self) -> bool
```

Rejection reasons (return `False` and emit nothing):
- `request_generate` when `_generate_worker` is running.
- `request_generate` when `config.out_dir` is empty. *(MainWindow catches the False, shows the InfoBar.)*

Controller does NOT:
- Import `ArticlePage` or any widget.
- Call `InfoBar.*` directly.
- Call `switchTo(...)`.
- Hold references to UI objects beyond the `parent` passed at construction (used only for `QThread` parent ownership).

### Vault cache with mtime

```python
def _get_vault(self, vault_root: Path) -> tuple[Index, Registry]:
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

**Known limit:** `dir.stat().st_mtime` tracks directory-entry changes (add/remove files), not in-place edits to existing files. Acceptable because vault editing flow is add/delete-file, not in-place. If in-place edits become common, add `watchdog` later — don't pre-build.

### ArticlePage view-only interface

Before (v0.2):
```python
class ArticlePage:
    current_result: GenerateResult | None
    _template: Template | None
    _reroll_counter: int
    def _compose_draft(self, plan) -> str
    def load_result(self, template, result) -> None
```

After (Plan C):
```python
class ArticlePage:
    # No workflow state. Pure view.
    def load_result(self, template: Template, plan: AssemblyPlan, draft: str, final_text: str) -> None
    def update_plan(self, plan: AssemblyPlan, draft: str) -> None  # reroll refresh path
    def set_polished(self, text: str) -> None
    def clear(self) -> None
```

MainWindow wires:
- `controller.generated` → computes draft via `compose_draft`, calls `article.load_result(...)`, emits plan_warnings routing, `switchTo(article)`.
- `controller.reroll_completed` → `article.update_plan(plan, compose_draft(plan))`.
- `controller.polished` → `article.set_polished(text)`.

### BatchReport / BatchItem

```python
@dataclass(frozen=True)
class BatchItem:
    index: int                       # 1-based position in the batch
    keyword: str
    status: Literal["success", "failed"]
    markdown_path: str | None = None
    assembly_json_path: str | None = None
    error_type: str | None = None    # e.g. "EmptyPoolError"
    error_message: str | None = None # first line only
    duration_seconds: float = 0.0

@dataclass
class BatchReport:
    batch_id: str                    # "batch-YYYYMMDD-HHMMSS"
    batch_dir: str                   # abs path
    started_at: str                  # ISO8601
    finished_at: str | None          # None while running
    template_path: str
    vault_root: str
    seed: int
    total: int                       # len(keywords) after dedup
    items: list[BatchItem]           # append-only during run

def write_report(report: BatchReport, path: Path) -> None  # atomic via temp+rename
def read_report(path: Path) -> BatchReport
```

JSON uses `dataclasses.asdict`. `BatchReport` is mutable so the runner can append items; `BatchItem` is frozen so items can't be mutated after creation.

### run_batch runner

```python
def run_batch(
    keywords: list[str],
    template_path: Path,
    vault_root: Path,
    out_dir: Path,                       # already the batch-xxx subdir, caller's responsibility
    llm_client: LLMClient,
    seed: int,
    on_item_started: Callable[[int, str], None] = lambda i, kw: None,
    on_item_finished: Callable[[BatchItem], None] = lambda item: None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> BatchReport:
    """
    Serial execution. Dedups keywords (preserves order). Catches every
    per-item exception and records it as a failed BatchItem. Calls
    on_item_finished BEFORE appending to report.items, so observers see
    items in the same order as the report. Writes batch-report.json
    incrementally after each item. Checks should_cancel() at the top of
    each iteration; if True, returns the partial report immediately
    (remaining keywords not recorded as failed).
    """
```

Keyword preprocessing:
- `k.strip()` each; drop empties.
- Dedupe preserving order (first occurrence wins).

On cancel or natural completion, `report.finished_at` is set to the current ISO8601 timestamp and the final `write_report` is called before returning.

Per-item flow:
1. `should_cancel()` → if True, finalize `finished_at`, write report, return.
2. `on_item_started(i, keyword)`.
3. Build `GenerateRequest`, call `run_generate(...)`, which returns `GenerateResult` with written paths.
4. Build `BatchItem(status="success", ...)`.
5. On any `Exception`: build `BatchItem(status="failed", error_type=type(exc).__name__, error_message=str(exc).splitlines()[0] if str(exc) else "")`. Never re-raise.
6. `on_item_finished(item)`.
7. `report.items.append(item)`.
8. `write_report(report, batch_report_path)` (atomic).

Vault scan (`scan_vault`, `build_brand_registry`) runs ONCE at the start of the batch, shared across all items.

### BatchController contract

```python
class BatchController(QObject):
    batch_started = pyqtSignal(object)           # BatchReport (initial, empty items)
    batch_progress = pyqtSignal(int, int, str)   # (done, total, current_keyword)
    item_finished = pyqtSignal(object)           # BatchItem
    batch_completed = pyqtSignal(object)         # BatchReport (final)
    batch_cancelled = pyqtSignal(object)         # BatchReport (partial)
    batch_failed = pyqtSignal(str)               # worker-level unexpected error
    busy_changed = pyqtSignal(bool)

    def apply_config(self, cfg: AppConfig) -> None
    def start_batch(self, payload: dict) -> bool  # False = rejected
    def cancel(self) -> None
    def is_busy(self) -> bool
```

`payload` schema:
```python
{
    "keywords": list[str],         # raw, pre-dedup
    "template_path": str,
    "vault_root": str,
    "provider": str,
    "seed": int,
}
```

Rejection reasons (return False):
- Already busy.
- `config.out_dir` empty.
- `keywords` is empty after strip+dedup.
- `vault_root` does not exist.

### MainWindow cross-controller mutual exclusion

MainWindow holds `self.article_controller` and `self.batch_controller`. On either `busy_changed(True)`, the other controller's `start_*` would reject anyway, but MainWindow additionally:
- Sets `home.set_busy(True)` (disables both "开始生成" and "开始批量" buttons).
- Sets `article.controls.set_busy(True)` (disables polish/reroll/export during batch).

On `busy_changed(False)`, restore. If both controllers could somehow end up busy (they can't, but defensively), `set_busy(True)` wins.

### HomePage Pivot

```python
class HomePage(QWidget):
    request_generate = pyqtSignal(dict)       # single-article, existing
    request_batch = pyqtSignal(dict)          # new

    def __init__(self, config, parent=None):
        ...
        self.pivot = Pivot(self)              # qfluentwidgets
        self.stack = QStackedWidget(self)
        self.single_panel = SingleArticlePanel(...)   # existing UI, refactored to use GenerationForm
        self.batch_panel = BatchPanel(...)
        self.stack.addWidget(self.single_panel)
        self.stack.addWidget(self.batch_panel)
        self.pivot.addItem(routeKey="single", text="单篇", onClick=lambda: self.stack.setCurrentIndex(0))
        self.pivot.addItem(routeKey="batch",  text="批量",  onClick=lambda: self.stack.setCurrentIndex(1))
        self.pivot.setCurrentItem("single")
```

`set_busy(bool)` disables both panels' start buttons and both `Pivot` items (switching tabs mid-batch is fine actually — leave tab switch enabled; only disable start buttons).

### BatchPanel

```
┌ keyword QTextEdit (multi-line) ──────────────┐
│                                              │
└──────────────────────────────────────────────┘
  已识别 <N> 个关键词（去重后）  ← QLabel, debounced
[ 从文件导入 ]  (.txt or .csv)
─────────────────────────────────────────────
GenerationForm (template / vault / seed / provider)
─────────────────────────────────────────────
[ 开始批量 ]   ← disabled when N == 0 or busy
```

- `textChanged` → 200ms `QTimer.singleShot` debounce → recompute keyword count.
- "从文件导入": `QFileDialog.getOpenFileName` with filter `*.txt *.csv`; on .txt, split by lines; on .csv, `csv.reader` and take first column; **replace** textedit contents.
- Signal: `request_batch.emit({"keywords": [...], "template_path": ..., ...})`.

### BatchResultPage

Two-column result view, no left-nav entry. MainWindow calls `switchTo(batch_result_page)` when `batch_started` fires, and keeps it as the current page until the user clicks "返回".

Elements:
- Header: batch_id, template path, vault root, seed (read from `BatchReport`).
- Progress bar: `ProgressBar` (qfluentwidgets), 0..total.
- Current keyword label.
- Success `ListWidget` (left) — one row per success, showing `✓ <keyword>`.
- Failed `ListWidget` (right) — one row per failure, two lines: `⚠ <keyword>` and `<error_type>: <error_message>`.
- Buttons row:
  - "打开批次目录" — `os.startfile(batch_dir)`, always enabled.
  - "取消" — visible while running; click transitions to "取消中…" + disabled; after `batch_cancelled`, replaced by "返回".
  - "返回" — visible only after `batch_completed` or `batch_cancelled`; `switchTo(home)`.

Slots:
- `on_batch_started(report)` → clear lists, set header, progress = (0, total).
- `on_item_finished(item)` → append to appropriate list, increment progress.
- `on_batch_progress(done, total, keyword)` → update progress bar + current label.
- `on_batch_completed(report)` / `on_batch_cancelled(report)` → swap buttons.

### InfoBar routing (MainWindow-level)

Single-article flow (unchanged from v0.2, now triggered by `ArticleController` signals):
- `generate_failed` → EmptyPoolError → warning; else → error.
- `plan_warnings` (non-empty) → warning.
- `polish_failed` → error.
- `exported` → success + "打开文件夹" button.
- `export_failed` → error.

Batch flow (new, triggered by `BatchController.batch_completed` / `batch_cancelled`):
- `batch_completed(report)`, all success → `InfoBar.success("批量完成", f"{total} 个关键词全部成功")`.
- `batch_completed(report)`, some failed → `InfoBar.warning("批量完成（部分失败）", f"成功 {s} / 失败 {f}")`.
- `batch_cancelled(report)` → `InfoBar.info("批量已取消", f"已完成 {done} / {total}")`.
- `batch_failed(msg)` → `InfoBar.error("批量失败", first_line)` (worker-level bug, shouldn't happen).

**Critical:** per-item `EmptyPoolError` during a batch does NOT fire an `InfoBar`. It's recorded as a failed `BatchItem` and surfaces in the result page. Only batch-level completion fires InfoBar, exactly once.

## Testing Strategy

### Layers

| Layer | File | Focus |
|---|---|---|
| core | `tests/core/test_batch_report.py` | dataclass serialization/deserialization, atomic write |
| core | `tests/core/test_batch_runner.py` | dedup, empty-line skip, per-item failure → BatchItem, callback ordering, should_cancel honored, incremental report write, shared vault scan |
| core | `tests/core/test_compose_draft.py` | promoted pure function |
| gui | `tests/gui/test_article_controller.py` | C1 core: generate/reroll/polish/export signal emission, worker reentrancy reject, vault mtime invalidation, apply_config |
| gui | `tests/gui/test_batch_controller.py` | start_batch rejection conditions (no out_dir / empty / busy / bad vault), busy_changed signal, batch_dir naming, mutual exclusion with ArticleController |
| gui | `tests/gui/test_batch_panel.py` | textedit dedup count, file import replaces content, start button disabled when N==0 |
| gui | `tests/gui/test_batch_result_page.py` | item_finished appends to correct list, cancel button state machine, return button appears after completion |
| gui | `tests/gui/test_main_window.py` | **slimmed**: only shell, navigation, config load, cross-controller mutual exclusion, InfoBar routing on signals |

Tests currently in `test_main_window.py` that exercise generate/reroll/polish/export → **migrated** to `test_article_controller.py`.

### LLM mocking

`run_batch` tests use a programmable `MockLLMClient` that decides per-keyword whether to return text or raise (e.g. `EmptyPoolError` on keyword "稀有长尾词"). Extend the existing `csm_core/llm/mock_client.py` to support a `reactions: dict[str, str | Exception]` parameter, or use a test-local subclass — pick during implementation based on cleanliness.

### Coverage targets

- `csm_core` ≥ 95% (maintain current bar).
- `csm_gui` ≥ 75% (slight relaxation from current ~77%; batch UI details are hard to cover fully and not worth painful asserts).

## Task Phasing

Plan document will break these into step-level tasks with exact code. High-level outline:

**C1 (refactor, ~6-8 tasks):**
1. Promote `compose_draft` to `csm_core/assembler/render.py` + test.
2. Create `ArticleController` skeleton with signals + empty methods + initial test file.
3. Migrate generate path: `request_generate` + tests (move from `test_main_window.py`).
4. Migrate reroll path + vault mtime check + tests.
5. Migrate polish path + tests.
6. Migrate export path + tests.
7. Slim `ArticlePage` to view-only: remove workflow state, change `load_result` signature, add `update_plan`.
8. Slim `MainWindow`, rewire to controller signals, full test suite green.

**C2 (batch, ~8-10 tasks):**
9. `BatchReport`/`BatchItem` + atomic write + tests.
10. `run_batch` runner + full coverage (cancel, failure, incremental write, shared vault).
11. `BatchWorker` + qtbot signal tests.
12. `BatchController` + rejection/busy tests + mutual-exclusion plumbing.
13. Extract `GenerationForm` widget; refactor single-article HomePage to use it.
14. `BatchPanel` widget + tests (dedup count, file import, busy disable).
15. HomePage `Pivot` + two tabs + tests.
16. `BatchResultPage` + tests (progress, list append, button state machine).
17. MainWindow wiring: BatchController + BatchResultPage + cross-controller mutual exclusion + InfoBar routing + tests.
18. End-to-end smoke test: mock LLM, 3 keywords (2 success, 1 failure), assert batch_dir contents + report round-trip.

## Acceptance (v0.3 tag conditions)

- All C1 + C2 tests pass.
- `csm_core` coverage ≥ 95%, `csm_gui` coverage ≥ 75%.
- `MainWindow` ≤ 270 lines (C1 target was ≤120; C2 batch wiring + InfoBar routing for 6 batch-lifecycle signals adds legitimate surface area).
- `ArticlePage` contains no `_template`, `_compose_draft`, or `_reroll_counter`.
- Manual verification on Win11:
  - Adding/removing a .md file in the vault takes effect without restart.
  - Batch of 20 keywords (2 known to trigger `EmptyPoolError`) produces `batch-YYYYMMDD-HHMMSS/` with 18 md+json pairs, a `batch-report.json` listing all 20 items, and exactly one "部分失败" InfoBar at the end (not 2 EmptyPool popups mid-batch).
  - Starting a single-article generation while a batch is running is rejected with an InfoBar.
  - Cancelling a batch stops at the next item boundary; already-produced files remain; a "批量已取消" InfoBar fires.

## Deferred to Plan D (explicit list)

- Concurrent batch execution.
- `retry_failed` convenience action (manual re-paste is fine for v0.3).
- API key keyring migration.
- Fine-grained generate progress stages (`stage_changed`).
- Template management UI.
- `.docx` export.
- Framework→template import.
- Cross-batch queue / batch history UI.
- `watchdog`-based vault change detection (mtime dir-level is enough for now).
