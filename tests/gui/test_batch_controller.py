from pathlib import Path
from csm_gui.config import AppConfig
from csm_gui.controllers.batch_controller import BatchController


_REPO = Path(__file__).parent.parent.parent
_TEMPLATE = _REPO / "templates" / "daogou-changjing-renqun.json"
_VAULT = _REPO / "tests" / "fixtures" / "mini_vault" / "营销资料库"


class _Sig:
    def connect(self, _slot): pass
    def emit(self, *a, **kw): pass


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
    c = BatchController(AppConfig(out_dir=str(tmp_path)))

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
        "template_path": str(_TEMPLATE),
        "vault_root": str(_VAULT),
        "provider": "mock", "seed": 0,
    })
    assert ok is True
    subs = [p for p in Path(tmp_path).iterdir() if p.is_dir() and p.name.startswith("batch-")]
    assert len(subs) == 1


def test_busy_changed_signal(qtbot, tmp_path, monkeypatch):
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
            "template_path": str(_TEMPLATE),
            "vault_root": str(_VAULT),
            "provider": "mock", "seed": 0,
        })
    assert sig.args == [True]
