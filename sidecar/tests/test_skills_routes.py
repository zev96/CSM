"""Tests for /api/skills and /api/skills/{id}."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from csm_sidecar.services import skills_service


def _write_skill(p: Path, *, name: str, desc: str = "", tone: str = "", body: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---", f"name: {name}"]
    if desc:
        fm_lines.append(f"desc: {desc}")
    if tone:
        fm_lines.append(f"tone: {tone}")
    fm_lines.append("---")
    fm_lines.append(body)
    p.write_text("\n".join(fm_lines), encoding="utf-8")


def test_list_skills_returns_empty_when_dir_unset(client: TestClient):
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "skills": []}


def test_list_skills_returns_empty_when_dir_missing(client: TestClient, tmp_path):
    client.patch("/api/config", json={"skill_dir": str(tmp_path / "does-not-exist")})
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_list_skills_parses_frontmatter(client: TestClient, tmp_path):
    skill_dir = tmp_path / "skills"
    _write_skill(skill_dir / "rational.md",
                 name="克制理性", desc="短句、低饱和", tone="rational",
                 body="prompt body here")
    _write_skill(skill_dir / "warm.md",
                 name="温暖感性", body="another body")  # no desc/tone

    client.patch("/api/config", json={"skill_dir": str(skill_dir)})

    resp = client.get("/api/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    by_id = {s["id"]: s for s in data["skills"]}
    assert by_id["rational"]["name"] == "克制理性"
    assert by_id["rational"]["desc"] == "短句、低饱和"
    assert by_id["rational"]["tone"] == "rational"
    assert by_id["rational"]["uses"] == 0  # always 0 per A2 decision
    # Body is NOT included in list response (避免列表返回过大)
    assert "body" not in by_id["rational"]
    # Falls back to id when name missing — but we set name, so check warm fallback.
    assert by_id["warm"]["name"] == "温暖感性"
    assert by_id["warm"]["desc"] == ""


def test_get_single_skill_includes_body(client: TestClient, tmp_path):
    skill_dir = tmp_path / "skills"
    _write_skill(skill_dir / "rational.md", name="克制理性", body="this is the prompt fragment")
    client.patch("/api/config", json={"skill_dir": str(skill_dir)})

    resp = client.get("/api/skills/rational")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "rational"
    assert data["name"] == "克制理性"
    assert "this is the prompt fragment" in data["body"]


def test_get_single_skill_404(client: TestClient, tmp_path):
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    client.patch("/api/config", json={"skill_dir": str(skill_dir)})

    resp = client.get("/api/skills/nope")
    assert resp.status_code == 404


def test_skill_falls_back_to_filename_when_name_missing(client: TestClient, tmp_path):
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    # Write a file with NO frontmatter at all — name should fall back to stem.
    (skill_dir / "anonymous.md").write_text("just markdown, no frontmatter", encoding="utf-8")
    client.patch("/api/config", json={"skill_dir": str(skill_dir)})

    resp = client.get("/api/skills/anonymous")
    assert resp.status_code == 200
    assert resp.json()["name"] == "anonymous"


def test_skill_role_defaults_persona_when_absent(tmp_path):
    (tmp_path / "x.md").write_text("# 无 frontmatter\n本体", encoding="utf-8")
    sk = skills_service.get_skill(tmp_path, "x")
    assert sk is not None
    assert sk.role == "persona"
    assert sk.to_dict()["role"] == "persona"


def test_skill_role_parsed_from_frontmatter(tmp_path):
    (tmp_path / "y.md").write_text(
        "---\nname: 去AI味\nrole: humanize\n---\n本体", encoding="utf-8")
    sk = skills_service.get_skill(tmp_path, "y")
    assert sk is not None
    assert sk.role == "humanize"
    assert sk.to_dict()["role"] == "humanize"


def test_create_skill_persists_role(tmp_path):
    skills_service.create_skill(
        tmp_path, "hz", name="去AI味", desc="", tone="", role="humanize", body="正文")
    assert skills_service.get_skill(tmp_path, "hz").role == "humanize"


def test_update_skill_preserves_role_when_omitted(tmp_path):
    skills_service.create_skill(
        tmp_path, "hz", name="去AI味", desc="", tone="", role="humanize", body="正文")
    # 模拟现有前端 PATCH：不带 role
    skills_service.update_skill(
        tmp_path, "hz", name="去AI味2", desc="d", tone="", body="新正文")
    sk = skills_service.get_skill(tmp_path, "hz")
    assert sk.role == "humanize"      # 关键：保留，不回退 persona
    assert sk.name == "去AI味2" and sk.body.strip() == "新正文"


def test_update_skill_changes_role_when_given(tmp_path):
    skills_service.create_skill(
        tmp_path, "p", name="人设", desc="", tone="", role="humanize", body="x")
    skills_service.update_skill(
        tmp_path, "p", name="人设", desc="", tone="", body="x", role="persona")
    assert skills_service.get_skill(tmp_path, "p").role == "persona"


def test_route_create_and_get_round_trips_role(client: TestClient, tmp_path):
    skill_dir = tmp_path / "skills"
    client.patch("/api/config", json={"skill_dir": str(skill_dir)})
    r = client.post("/api/skills", json={
        "id": "去AI味", "name": "去AI味", "role": "humanize", "body": "正文"})
    assert r.status_code == 201
    assert r.json()["role"] == "humanize"
    g = client.get("/api/skills/去AI味")
    assert g.json()["role"] == "humanize"


def test_route_patch_without_role_preserves(client: TestClient, tmp_path):
    skill_dir = tmp_path / "skills"
    client.patch("/api/config", json={"skill_dir": str(skill_dir)})
    client.post("/api/skills", json={
        "id": "hz2", "name": "去AI味", "role": "humanize", "body": "a"})
    r = client.patch("/api/skills/hz2", json={"name": "去AI味", "body": "b"})
    assert r.status_code == 200
    assert r.json()["role"] == "humanize"   # PATCH 不带 role → 保留
