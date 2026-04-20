from pathlib import Path
from csm_gui.workers.generate_worker import GenerateWorker
from csm_core.pipeline import GenerateRequest, STAGES
from csm_core.llm.providers.mock import MockClient


def _request(mini_vault_path, tmp_path) -> GenerateRequest:
    tpl = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    return GenerateRequest(
        keyword="test",
        vault_root=mini_vault_path,
        template_path=tpl,
        out_dir=tmp_path,
        llm_client=MockClient(response="# done"),
        seed=1,
        user_config={"brand_competitors": 2},
    )


def test_generate_worker_emits_finished(qtbot, mini_vault_path, tmp_path):
    req = _request(mini_vault_path, tmp_path)
    worker = GenerateWorker(req)
    with qtbot.waitSignal(worker.finished, timeout=10_000) as sig:
        worker.start()
    result = sig.args[0]
    assert Path(result.markdown_path).exists()


def test_generate_worker_emits_failed_on_exception(qtbot, mini_vault_path, tmp_path):
    req = _request(mini_vault_path, tmp_path)
    req.template_path = tmp_path / "nope.json"
    worker = GenerateWorker(req)
    with qtbot.waitSignal(worker.failed, timeout=10_000) as sig:
        worker.start()
    assert len(sig.args[0]) > 0


def test_generate_worker_emits_stage(qtbot, mini_vault_path, tmp_path):
    req = _request(mini_vault_path, tmp_path)
    worker = GenerateWorker(req)
    stages = []
    worker.stage_changed.connect(stages.append)
    with qtbot.waitSignal(worker.finished, timeout=10_000):
        worker.start()
    assert stages == list(STAGES)
