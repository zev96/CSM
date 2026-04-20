from pathlib import Path
import json
from csm_core.batch.runner import run_batch
from csm_core.batch.report import read_report


class ProgrammableLLM:
    """Mock client: reactions maps keyword -> text OR Exception."""
    def __init__(self, reactions: dict):
        self._reactions = reactions

    def complete(self, system: str, user: str) -> str:
        kw = ""
        for line in user.splitlines():
            if "【关键词】" in line:
                kw = line.split("【关键词】", 1)[-1].strip()
                break
            if line.startswith("关键词"):
                kw = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                break
        reaction = self._reactions.get(kw, f"POLISHED({kw})")
        if isinstance(reaction, Exception):
            raise reaction
        return reaction


def _setup_vault_and_template(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = Path(__file__).parent.parent.parent
    template_path = repo_root / "templates" / "daogou-changjing-renqun.json"
    vault_root = repo_root / "tests" / "fixtures" / "mini_vault" / "营销资料库"
    assert template_path.exists(), "fixture template missing"
    assert vault_root.exists(), "fixture vault missing"
    return template_path, vault_root


def test_run_batch_dedup_and_empty_skip(tmp_path):
    template_path, vault_root = _setup_vault_and_template(tmp_path)
    batch_dir = tmp_path / "batch-test"
    batch_dir.mkdir()
    client = ProgrammableLLM({})
    report = run_batch(
        keywords=["kw1", "", "  ", "kw1", "kw2"],
        template_path=template_path,
        vault_root=vault_root,
        out_dir=batch_dir,
        llm_client=client,
        seed=0,
    )
    assert report.total == 2
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
    assert snapshots == [1, 2]


def test_run_batch_vault_scanned_once(tmp_path, monkeypatch):
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
