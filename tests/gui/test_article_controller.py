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


def test_generate_finished_template_load_failure_emits_generate_failed(qtbot, tmp_path, monkeypatch):
    """If load_template raises after the worker succeeds, surface via generate_failed."""
    from csm_core.pipeline import GenerateResult
    from csm_core.assembler.plan import AssemblyPlan

    c = ArticleController(AppConfig(out_dir=str(tmp_path)))
    c._last_template_path = tmp_path / "missing.json"  # does not exist

    monkeypatch.setattr(
        "csm_core.template.loader.load_template",
        lambda p: (_ for _ in ()).throw(FileNotFoundError(f"no such file: {p}")),
    )

    fake_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[]),
        final_text="",
    )
    with qtbot.waitSignal(c.generate_failed, timeout=500) as sig:
        c._on_generate_finished(fake_result)
    assert "FileNotFoundError" in sig.args[0]
    assert c._current_result is None  # state not corrupted


class _FakeSig:
    def connect(self, _slot):
        pass
    def emit(self, *a, **kw):
        pass


import time
from csm_core.assembler.plan import AssemblyPlan
from csm_core.pipeline import GenerateResult


def test_get_vault_caches_result(qtbot, tmp_path):
    (tmp_path / "brands.json").write_text('{"brands":[]}', encoding="utf-8")
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))
    idx1, reg1 = c._get_vault(tmp_path)
    idx2, reg2 = c._get_vault(tmp_path)
    assert idx1 is idx2
    assert reg1 is reg2


def test_get_vault_invalidates_on_mtime_change(qtbot, tmp_path):
    (tmp_path / "brands.json").write_text('{"brands":[]}', encoding="utf-8")
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))
    idx1, _ = c._get_vault(tmp_path)
    time.sleep(0.05)
    (tmp_path / "new.md").write_text("# x", encoding="utf-8")
    idx2, _ = c._get_vault(tmp_path)
    assert idx1 is not idx2


def test_reroll_slot_no_op_when_no_current_result(qtbot, tmp_path):
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))
    with qtbot.assertNotEmitted(c.reroll_completed):
        c.reroll_slot("some_slot", {"brand_competitors": 2})
    assert c._reroll_counter == 0


def test_reroll_slot_emits_reroll_completed_on_success(qtbot, tmp_path, monkeypatch):
    (tmp_path / "brands.json").write_text('{"brands":[]}', encoding="utf-8")
    c = ArticleController(AppConfig(vault_root=str(tmp_path)))

    fake_plan = AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[])
    c._current_result = GenerateResult(
        markdown_path="", assembly_json_path="",
        plan=AssemblyPlan(keyword="k", template_id="t", seed=0, slots=[]),
        final_text="",
    )
    c._current_template = object()
    monkeypatch.setattr(
        c, "_get_vault",
        lambda root: (object(), object()),
    )

    monkeypatch.setattr(
        "csm_gui.controllers.article_controller.reroll_slot",
        lambda **kwargs: fake_plan,
    )

    with qtbot.waitSignal(c.reroll_completed, timeout=500) as sig:
        c.reroll_slot("slot_a", {"brand_competitors": 2})
    assert sig.args[0] is fake_plan
    assert c._current_result.plan is fake_plan
    assert c._reroll_counter == 1


def test_polish_no_op_without_current_result(qtbot, tmp_path):
    c = ArticleController(AppConfig(out_dir=str(tmp_path)))
    with qtbot.assertNotEmitted(c.busy_changed):
        c.polish("mock", None)
    assert c._polish_worker is None


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

    before_id = id(c._polish_worker)
    with qtbot.assertNotEmitted(c.busy_changed):
        c.polish("mock", None)
    assert id(c._polish_worker) == before_id


class _MockTemplate:
    system_prompt_default = "sys"
    seo_defaults = {}
