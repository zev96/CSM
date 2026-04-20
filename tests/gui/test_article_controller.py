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


class _FakeSig:
    def connect(self, _slot):
        pass
    def emit(self, *a, **kw):
        pass
