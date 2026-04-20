from csm_gui.workers.polish_worker import PolishWorker
from csm_core.llm.providers.mock import MockClient


def test_polish_worker_returns_text(qtbot):
    client = MockClient(response="# 润色结果")
    worker = PolishWorker(client=client, system="sys", user="usr")
    with qtbot.waitSignal(worker.finished, timeout=5000) as sig:
        worker.start()
    assert sig.args[0] == "# 润色结果"


def test_polish_worker_emits_failed(qtbot):
    class Boom:
        def complete(self, *, system, user):
            raise RuntimeError("boom")
    worker = PolishWorker(client=Boom(), system="s", user="u")
    with qtbot.waitSignal(worker.failed, timeout=5000) as sig:
        worker.start()
    assert "boom" in sig.args[0]
