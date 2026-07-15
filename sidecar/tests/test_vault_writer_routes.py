from pathlib import Path
from csm_sidecar.services import config_service, vault_service


def _seed_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "科普模块/吸尘器/挑选攻略").mkdir(parents=True, exist_ok=True)
    (root / "科普模块/吸尘器/挑选攻略/吸尘器-吸力选购.md").write_text(
        "---\n产品: 吸尘器\n素材类型: 科普选购\n核心关键词:\n  - 吸力\n---\n\n① 看吸力\n\n② 看真空\n",
        encoding="utf-8")
    (root / "科普模块/吸尘器/吸尘器科普内容索引.md").write_text(
        "---\n产品: 吸尘器\n---\n\n# 索引\n\n旧内容\n", encoding="utf-8")
    return root


def _use_vault(root: Path) -> None:
    config_service.patch({"vault_root": str(root)})
    vault_service.invalidate()


def test_writable_folders(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    r = client.get("/api/vault/writable-folders")
    assert r.status_code == 200
    rels = [f["rel_folder"] for f in r.json()["folders"]]
    assert "科普模块/吸尘器/挑选攻略" in rels


def test_plan_then_commit_then_undo(client, tmp_path):
    root = _seed_vault(tmp_path)
    _use_vault(root)
    body = {
        "rel_folder": "科普模块/吸尘器/挑选攻略",
        "filename": "吸尘器-噪音选购.md",
        "frontmatter": {"产品": "吸尘器", "素材类型": "科普选购", "核心关键词": ["噪音"]},
        "body_shape": "variants",
        "variants": ["看分贝", "看降噪"],
    }
    plan = client.post("/api/vault/plan", json=body).json()
    assert plan["conflict"] is False
    assert "① 看分贝" in plan["full_text"]

    commit = client.post("/api/vault/commit", json=body)
    assert commit.status_code == 200
    receipt = commit.json()
    assert (root / "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md").exists()

    undo = client.post("/api/vault/undo", json=receipt)
    assert undo.status_code == 200
    assert not (root / "科普模块/吸尘器/挑选攻略/吸尘器-噪音选购.md").exists()


def test_commit_conflict_409(client, tmp_path):
    root = _seed_vault(tmp_path)
    _use_vault(root)
    body = {
        "rel_folder": "科普模块/吸尘器/挑选攻略", "filename": "吸尘器-吸力选购.md",
        "frontmatter": {"产品": "吸尘器"}, "body_shape": "variants", "variants": ["x"],
    }
    assert client.post("/api/vault/commit", json=body).status_code == 409


def test_bad_filename_400(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    body = {
        "rel_folder": "科普模块/吸尘器/挑选攻略", "filename": "有 空格.txt",
        "frontmatter": {}, "body_shape": "variants", "variants": ["x"],
    }
    assert client.post("/api/vault/commit", json=body).status_code == 400


def test_path_escape_400(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    body = {
        "rel_folder": "../..", "filename": "evil.md",
        "frontmatter": {}, "body_shape": "variants", "variants": ["x"],
    }
    assert client.post("/api/vault/plan", json=body).status_code == 400


def test_no_vault_root_400(client):
    config_service.patch({"vault_root": None})
    assert client.get("/api/vault/writable-folders").status_code == 400


def test_oserror_maps_to_503(client, tmp_path, monkeypatch):
    _use_vault(_seed_vault(tmp_path))
    from csm_sidecar.routes import vault_writer as vw
    def boom(**kwargs):
        raise OSError("share offline")
    monkeypatch.setattr(vw.vault_writer_service, "commit", boom)
    body = {"rel_folder": "科普模块/吸尘器/挑选攻略", "filename": "吸尘器-y.md",
            "frontmatter": {"产品": "吸尘器"}, "body_shape": "variants", "variants": ["x"]}
    assert client.post("/api/vault/commit", json=body).status_code == 503


def test_unknown_body_shape_422(client, tmp_path):
    _use_vault(_seed_vault(tmp_path))
    body = {"rel_folder": "科普模块/吸尘器/挑选攻略", "filename": "吸尘器-x.md",
            "frontmatter": {"产品": "吸尘器"}, "body_shape": "banana", "variants": ["x"]}
    assert client.post("/api/vault/commit", json=body).status_code == 422


def test_writable_folders_includes_empty_with_borrowed_template(client, tmp_path):
    root = _seed_vault(tmp_path)
    (root / "科普模块/空气净化器/挑选攻略").mkdir(parents=True, exist_ok=True)
    _use_vault(root)
    folders = {f["rel_folder"]: f for f in
               client.get("/api/vault/writable-folders").json()["folders"]}
    empty = folders["科普模块/空气净化器/挑选攻略"]
    assert empty["sample_count"] == 0
    assert empty["template_from"] == "科普模块/吸尘器/挑选攻略"
    assert empty["defaults"]["产品"] == "空气净化器"
    assert "科普模块/空气净化器" in folders          # 中间层也在树里
