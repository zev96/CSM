from pathlib import Path

from fastapi.testclient import TestClient

VAULT = "营销资料库/产品模块/吸尘器"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _vault(root: Path) -> None:
    _w(root / VAULT / "产品参数/CEWEYDS18-产品参数.md",
       "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
       "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 220 |\n\n"
       "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 认证检测 | CE、FCC |\n")
    _w(root / VAULT / "希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md",
       "---\n产品: 吸尘器\n素材类型: 动力系统\n核心关键词: x\n---\n① 220AW强劲吸力。\n")


def test_list_returns_models(client: TestClient, tmp_path):
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    r = client.get("/api/brand-memory")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    cewey = next(m for m in body["models"] if m["model"] == "CEWEYDS18")
    assert cewey["role"] == "主推"
    assert cewey["coverage"]["has_specs"] is True


def test_detail_returns_memory_and_preview(client: TestClient, tmp_path):
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    r = client.get("/api/brand-memory/CEWEYDS18")
    assert r.status_code == 200
    d = r.json()
    assert d["specs"]["吸力(AW)"]["numbers"] == [220.0]
    assert "220" in d["inject_preview"]


def test_detail_unknown_404(client: TestClient, tmp_path):
    _vault(tmp_path)
    client.patch("/api/config", json={"vault_root": str(tmp_path)})
    assert client.get("/api/brand-memory/杂牌X9").status_code == 404


def test_list_without_vault_root_400(client: TestClient, tmp_path):
    client.patch("/api/config", json={"vault_root": ""})
    assert client.get("/api/brand-memory").status_code == 400
