"""fact_service.detect_changes/drain/diff —— 首建不报/变更报 diff/基线更新/跳过失败。tmp DB。"""
import pytest

from csm_core.brand_memory.fingerprint import spec_fingerprint
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.config import AppConfig
from csm_core.feedback import storage as fb
from csm_core.feedback.model import CreationRecord, FactSnapshot
from csm_sidecar.services import config_service, fact_service


def _mem(model, specs):
    sv = {f: SpecValue(field=f, raw=r) for f, r in specs.items()}
    return BrandModelMemory(brand="B", model=model, category="", role="竞品", specs=sv)


class _Reg:
    def __init__(self, models):
        self._m = list(models)

    def all_models(self):
        return list(self._m)

    def brand_of(self, m):
        return "B" if m in self._m else None


@pytest.fixture(autouse=True)
def _reset():
    fact_service.reset_for_test()
    yield
    fact_service.reset_for_test()


def _patch(monkeypatch, mems):
    monkeypatch.setattr(fact_service, "resolve_memory",
                        lambda brand, model, cat, index, **k: mems[model])
    monkeypatch.setattr(config_service, "load", lambda: AppConfig())


def test_first_build_no_report(monitor_db, monkeypatch):
    _patch(monkeypatch, {"A": _mem("A", {"吸力": "150AW"}), "B": _mem("B", {"续航": "60min"})})
    assert fact_service.detect_changes(None, _Reg(["A", "B"])) == []
    assert set(fb.get_model_fingerprints()) == {"A", "B"}


def test_change_reports_diff_and_updates_baseline(monitor_db, monkeypatch):
    mems = {"A": _mem("A", {"吸力": "150AW"})}
    _patch(monkeypatch, mems)
    fact_service.detect_changes(None, _Reg(["A"]))          # 建基线
    mems["A"] = _mem("A", {"吸力": "230AW"})                 # vault 改了
    changes = fact_service.detect_changes(None, _Reg(["A"]))
    assert len(changes) == 1 and changes[0]["model"] == "A"
    assert {"field": "吸力", "old": "150AW", "new": "230AW"} in changes[0]["changed"]
    assert "230AW" in fb.get_model_fingerprints()["A"][1]   # 基线已更新


def test_no_change_second_run(monitor_db, monkeypatch):
    _patch(monkeypatch, {"A": _mem("A", {"吸力": "150AW"})})
    fact_service.detect_changes(None, _Reg(["A"]))
    assert fact_service.detect_changes(None, _Reg(["A"])) == []


def test_skips_failed_resolve(monitor_db, monkeypatch):
    good = _mem("A", {"吸力": "150AW"})

    def _rm(brand, model, cat, index, **k):
        if model == "BAD":
            raise RuntimeError("resolve boom")
        return good

    monkeypatch.setattr(fact_service, "resolve_memory", _rm)
    monkeypatch.setattr(config_service, "load", lambda: AppConfig())
    fact_service.detect_changes(None, _Reg(["A", "BAD"]))
    base = fb.get_model_fingerprints()
    assert "A" in base and "BAD" not in base  # 单型号失败不塌全局


def test_drain_clears(monitor_db, monkeypatch):
    mems = {"A": _mem("A", {"吸力": "150AW"})}
    _patch(monkeypatch, mems)
    fact_service.detect_changes(None, _Reg(["A"]))   # 建基线，无 pending
    assert fact_service.drain_changes() == []
    mems["A"] = _mem("A", {"吸力": "230AW"})
    fact_service.detect_changes(None, _Reg(["A"]))   # 1 变更 → pending
    assert len(fact_service.drain_changes()) == 1
    assert fact_service.drain_changes() == []         # 已清空


def test_diff_for_model(monitor_db, monkeypatch):
    old_fp, old_canon = spec_fingerprint(_mem("M", {"吸力": "150AW"}))
    rec = CreationRecord(
        job_id="j", mode="normal", keyword=None, template_id=None, title=None,
        angle_json=None, skill_chain_json=None, models_json=None, contract_mode=None,
        document_path="/o.md", format="markdown", edit_ratio=None, lint_unresolved=0,
        factcheck_blocked=0, score=None, score_json=None, created_at="t", exported_at="t")
    fb.record_creation(rec, [], [FactSnapshot("M", old_fp, old_canon)])
    cur = _mem("M", {"吸力": "230AW"})
    monkeypatch.setattr(fact_service, "resolve_memory", lambda brand, model, cat, index, **k: cur)
    monkeypatch.setattr(config_service, "load", lambda: AppConfig())
    d = fact_service.diff_for_model("M", None, _Reg(["M"]))
    assert {"field": "吸力", "old": "150AW", "new": "230AW"} in d


def test_diff_for_model_no_snapshot(monitor_db, monkeypatch):
    monkeypatch.setattr(config_service, "load", lambda: AppConfig())
    assert fact_service.diff_for_model("Nope", None, _Reg(["Nope"])) == []
