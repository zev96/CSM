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
    vault_root = repo_root / "tests" / "fixtures" / "mini_vault" / "营销资料库"
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
