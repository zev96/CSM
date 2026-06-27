import pytest
from csm_core.config import AppConfig, LintConfig
from csm_sidecar.services import lint_service


@pytest.fixture
def patch_cfg(monkeypatch):
    def _set(lint: LintConfig):
        monkeypatch.setattr(lint_service.config_service, "load",
                            lambda: AppConfig(lint=lint))
    return _set


def test_scan_text_hits(patch_cfg):
    patch_cfg(LintConfig())
    out = lint_service.scan_text("业内最佳，加微信😀")
    cats = {h["category"] for h in out["hits"]}
    assert {"absolute", "traffic", "emoji"} <= cats
    assert "😀" not in out["fixed_text"]


def test_scan_text_disabled_returns_empty(patch_cfg):
    patch_cfg(LintConfig(enabled=False))
    out = lint_service.scan_text("业内最佳😀")
    assert out == {"hits": [], "fixed_text": "业内最佳😀"}


def test_scan_text_config_extra_applies(patch_cfg):
    patch_cfg(LintConfig(extra_traffic=["私我哦"]))
    out = lint_service.scan_text("有事私我哦")
    assert any(h["category"] == "traffic" and h["text"] == "私我哦" for h in out["hits"])
