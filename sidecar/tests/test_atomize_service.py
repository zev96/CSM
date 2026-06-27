"""atomize_service 测试。Mock 策略同 xhs_ai_service：recording fake client +
monkeypatch build_client；503 分支不打 patch 让真 build_client 抛 LLMConfigError。
vault 走 tmp_path，绝不碰真实库。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from csm_sidecar.services import atomize_service, config_service, vault_service
from csm_sidecar.services.llm_factory import LLMConfigError


def _seed_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    d = root / "科普模块/吸尘器/挑选攻略"
    d.mkdir(parents=True, exist_ok=True)
    (d / "吸尘器-吸力选购.md").write_text(
        "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n",
        encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _cfg(tmp_path: Path):
    config_service.init(tmp_path / "settings.json")
    yield
    config_service.init(None)
    vault_service.invalidate()


class _Rec:
    def __init__(self, resp: str = ""):
        self.resp = resp
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.resp


@pytest.fixture
def fake(monkeypatch):
    c = _Rec()
    monkeypatch.setattr(atomize_service.llm_factory, "build_client", lambda **kw: c)
    return c


def test_atomize_returns_grounded(tmp_path, fake):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path)), "default_provider": "mock"})
    fake.resp = json.dumps([{"正文": "看吸力", "建议文件夹": "科普模块/吸尘器/挑选攻略",
                             "素材类型": "科普选购", "产品": "通用", "核心关键词": "吸力",
                             "建议文件名": "吸力", "置信度": "high"}], ensure_ascii=False)
    atoms = atomize_service.atomize("一段关于吸力的资料")
    assert len(atoms) == 1
    assert atoms[0]["rel_folder"] == "科普模块/吸尘器/挑选攻略"
    assert atoms[0]["filename"].endswith(".md")
    assert atoms[0]["confidence"] == "high"
    assert "科普模块/吸尘器/挑选攻略" in fake.calls[0]["user"]   # 菜单注入
    assert fake.calls[0]["temperature"] == 0.2


def test_atomize_empty_no_llm(tmp_path, fake):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path)), "default_provider": "mock"})
    assert atomize_service.atomize("   ") == []
    assert fake.calls == []


def test_atomize_offmenu_folder_blanked(tmp_path, fake):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path)), "default_provider": "mock"})
    fake.resp = json.dumps([{"正文": "x", "建议文件夹": "不存在/文件夹", "置信度": "med"}], ensure_ascii=False)
    atoms = atomize_service.atomize("资料")
    assert atoms[0]["rel_folder"] is None
    assert any("不在素材库" in w for w in atoms[0]["warnings"])


def test_atomize_no_provider_raises(tmp_path):
    config_service.patch({"vault_root": str(_seed_vault(tmp_path))})   # 不设 provider
    with pytest.raises(LLMConfigError):
        atomize_service.atomize("资料")


def test_atomize_long_input_truncated_and_logged(tmp_path, fake, caplog):
    import logging
    config_service.patch({"vault_root": str(_seed_vault(tmp_path)), "default_provider": "mock"})
    fake.resp = "[]"
    with caplog.at_level(logging.WARNING):
        atomize_service.atomize("字" * 9000)
    assert any("截断" in r.message or "truncat" in r.message.lower() for r in caplog.records)
    # 截断后真正喂给 LLM 的原文长度 ≤ 8000（+200 余量给菜单+提示词包裹）
    assert len(fake.calls[0]["user"]) <= 8000 + 200
