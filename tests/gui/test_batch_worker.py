from pathlib import Path
from csm_gui.workers.batch_worker import BatchWorker


class StubLLM:
    def complete(self, system, user):
        return "POLISHED"


_REPO = Path(__file__).parent.parent.parent
_TEMPLATE = _REPO / "templates" / "daogou-changjing-renqun.json"
_VAULT = _REPO / "tests" / "fixtures" / "mini_vault" / "营销资料库"


def test_batch_worker_emits_signals(qtbot, tmp_path):
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    worker = BatchWorker(
        keywords=["kw1"],
        template_path=_TEMPLATE,
        vault_root=_VAULT,
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
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    worker = BatchWorker(
        keywords=["kw1", "kw2", "kw3"],
        template_path=_TEMPLATE,
        vault_root=_VAULT,
        out_dir=batch_dir,
        llm_client=StubLLM(),
        seed=0,
    )
    worker.item_finished.connect(lambda item: worker.request_cancel())
    with qtbot.waitSignal(worker.batch_finished, timeout=15000) as sig:
        worker.start()
    report = sig.args[0]
    assert len(report.items) == 1
