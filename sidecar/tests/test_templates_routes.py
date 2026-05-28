"""Tests for /api/templates CRUD."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _minimal_template_body(template_id: str = "demo") -> dict:
    """Smallest Template payload that passes csm_core schema validation.

    A HeadingBlock only needs id + text (no source/picks), so it's the
    cheapest way to satisfy ``blocks: list[Block] = Field(min_length=1)``.
    """
    return {
        "id": template_id,
        "name": "演示模板",
        "product": "无线吸尘器",
        "template_type": "导购文",
        "default_skill_id": None,
        "blocks": [
            {"kind": "heading", "id": "h1", "level": 2, "text": "标题"},
        ],
    }


def test_list_templates_empty(client: TestClient, tmp_path: Path):
    # Point default_template at a non-existent file; the parent dir doesn't
    # exist either → list returns empty rather than 404.
    client.patch("/api/config", json={"default_template": str(tmp_path / "missing" / "x.json")})
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "templates": []}


def test_default_template_directory_is_used_directly(client: TestClient, tmp_path: Path):
    """Regression: 设置页「默认模板目录」选择器存的是文件夹路径（directory:true），
    不是 .json 文件。resolve_dir 之前无条件 .parent，把用户选的文件夹截成上级
    目录，导致选了文件夹却扫不到里面的模板。模板必须落在所选文件夹本身。"""
    tdir = tmp_path / "my_templates"
    tdir.mkdir()
    # default_template 指向目录本身（folder picker 的实际行为）。
    client.patch("/api/config", json={"default_template": str(tdir)})

    body = _minimal_template_body("in_folder")
    create_resp = client.post("/api/templates", json=body)
    assert create_resp.status_code == 201, create_resp.text

    # 模板 .json 落在所选文件夹里，而不是被 .parent 甩到上级目录。
    assert (tdir / "in_folder.json").exists()
    assert not (tmp_path / "in_folder.json").exists()

    list_resp = client.get("/api/templates")
    assert list_resp.json()["count"] == 1
    assert list_resp.json()["templates"][0]["id"] == "in_folder"


def test_create_then_get_then_delete(client: TestClient, tmp_path: Path):
    tdir = tmp_path / "tpls"
    tdir.mkdir()
    client.patch("/api/config", json={"default_template": str(tdir / "anchor.json")})

    body = _minimal_template_body("demo1")
    create_resp = client.post("/api/templates", json=body)
    if create_resp.status_code != 201:
        # Surface the validation error so the test message is useful.
        raise AssertionError(f"create failed: {create_resp.status_code} {create_resp.text}")

    list_resp = client.get("/api/templates")
    assert list_resp.json()["count"] == 1
    assert list_resp.json()["templates"][0]["id"] == "demo1"

    get_resp = client.get("/api/templates/demo1")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == "demo1"

    del_resp = client.delete("/api/templates/demo1")
    assert del_resp.status_code == 204
    assert client.get("/api/templates").json()["count"] == 0


def test_create_duplicate_id_returns_409(client: TestClient, tmp_path: Path):
    tdir = tmp_path / "tpls"
    tdir.mkdir()
    client.patch("/api/config", json={"default_template": str(tdir / "anchor.json")})

    body = _minimal_template_body("dup")
    client.post("/api/templates", json=body)
    resp2 = client.post("/api/templates", json=body)
    assert resp2.status_code == 409


def test_get_unknown_template_returns_404(client: TestClient, tmp_path: Path):
    tdir = tmp_path / "tpls"
    tdir.mkdir()
    client.patch("/api/config", json={"default_template": str(tdir / "anchor.json")})
    assert client.get("/api/templates/nope").status_code == 404


def test_patch_path_id_mismatch_returns_400(client: TestClient, tmp_path: Path):
    tdir = tmp_path / "tpls"
    tdir.mkdir()
    client.patch("/api/config", json={"default_template": str(tdir / "anchor.json")})
    body = _minimal_template_body("a")
    client.post("/api/templates", json=body)
    # Path says 'a' but body says 'b' → 400
    body_b = _minimal_template_body("b")
    resp = client.patch("/api/templates/a", json=body_b)
    assert resp.status_code == 400
