"""vault_atomize 路由测试。复用 conftest 的 client（已带 token）+ tmp 库。"""
from __future__ import annotations

import json
from pathlib import Path

from csm_sidecar.services import config_service, vault_service


def _seed_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    d = root / "科普模块/吸尘器/挑选攻略"
    d.mkdir(parents=True, exist_ok=True)
    (d / "吸尘器-吸力选购.md").write_text(
        "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n",
        encoding="utf-8")
    return root


def _use_vault(root: Path) -> None:
    config_service.patch({"vault_root": str(root)})
    vault_service.invalidate()


def test_atomize_200(client, tmp_path, monkeypatch):
    _use_vault(_seed_vault(tmp_path))
    config_service.patch({"default_provider": "mock"})
    from csm_sidecar.routes import vault_atomize as va

    class _Rec:
        def complete(self, *, system, user, temperature=None):
            return json.dumps([{"正文": "看吸力", "建议文件夹": "科普模块/吸尘器/挑选攻略",
                                "置信度": "high"}], ensure_ascii=False)

    monkeypatch.setattr(va.atomize_service.llm_factory, "build_client", lambda **kw: _Rec())
    r = client.post("/api/vault/atomize", json={"text": "资料"})
    assert r.status_code == 200
    assert r.json()["atoms"][0]["rel_folder"] == "科普模块/吸尘器/挑选攻略"


def test_atomize_503_no_provider(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    config_service.patch({"default_provider": None})
    assert client.post("/api/vault/atomize", json={"text": "资料"}).status_code == 503


def test_atomize_400_no_vault(client):
    config_service.patch({"vault_root": None})
    assert client.post("/api/vault/atomize", json={"text": "资料"}).status_code == 400


def test_atomize_422_missing_text(client):
    assert client.post("/api/vault/atomize", json={}).status_code == 422
