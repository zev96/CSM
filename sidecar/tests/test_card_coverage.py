"""竞品卡覆盖度检查接口 —— 写模板时就能看到谁缺料、型号写歪没有。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

_SECTIONS = [
    {"label": "市场口碑数据", "required": True},
    {"label": "品牌赛道定位", "required": True},
    {"label": "横评总结点评", "required": False},
]


def _card(root: Path, rel: str, *, brand: str, model: str,
          sections: dict[str, str], tier: str = "热门品牌") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(f"## {h}\n① {t}" for h, t in sections.items())
    p.write_text(
        f"---\n品牌: {brand}\n型号: {model}\n素材类型: 竞品卡\n"
        f"层级标签: {tier}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _setup(client: TestClient, tmp_path: Path) -> None:
    client.patch("/api/config", json={"vault_root": str(tmp_path)})


def _probe(client: TestClient, sections=None) -> dict:
    return client.post("/api/vault/card_coverage", json={
        "module": "竞品",
        "filter": {"素材类型": "竞品卡"},
        "sections": sections or _SECTIONS,
    }).json()


def test_reports_eligible_and_missing(client: TestClient, tmp_path: Path):
    _setup(client, tmp_path)
    _card(tmp_path, "竞品/竞品卡-欧瑞达X9.md", brand="欧瑞达", model="欧瑞达X9",
          sections={"市场口碑数据": "甲", "品牌赛道定位": "乙",
                    "横评总结点评": "丙"})
    _card(tmp_path, "竞品/竞品卡-半残X.md", brand="半残", model="半残X1",
          sections={"市场口碑数据": "只有口碑"})

    data = _probe(client)
    assert data["note_count"] == 2
    assert data["eligible_count"] == 1
    by_title = {c["title"]: c for c in data["competitors"]}
    assert by_title["欧瑞达X9"]["eligible"] is True
    # 型号已含品牌前缀时标题不重复拼品牌
    assert by_title["半残X1"]["eligible"] is False
    bad = next(r for r in data["rows"] if "半残" in r["path"])
    assert bad["missing_required"] == ["品牌赛道定位"]


def test_reports_matched_h2_原文(client: TestClient, tmp_path: Path):
    """小节名与 H2 不逐字一致时，要能看出实际绑到了哪个 H2。"""
    _setup(client, tmp_path)
    _card(tmp_path, "竞品/竞品卡-欧瑞达X9.md", brand="欧瑞达", model="欧瑞达X9",
          sections={"口碑": "甲", "品牌赛道定位与人群": "乙"})
    row = _probe(client, [{"label": "市场口碑数据", "required": True},
                          {"label": "品牌赛道定位", "required": True}])["rows"][0]
    assert row["matched"]["市场口碑数据"] == "口碑"
    assert row["matched"]["品牌赛道定位"] == "品牌赛道定位与人群"


def test_missing_frontmatter_listed_with_path(client: TestClient, tmp_path: Path):
    _setup(client, tmp_path)
    p = tmp_path / "竞品" / "竞品卡-无名.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\n素材类型: 竞品卡\n---\n\n## 市场口碑数据\n① 甲\n",
                 encoding="utf-8")
    data = _probe(client)
    assert any("竞品卡-无名.md" in x for x in data["notes_missing_identity"])


def test_stem_conflicts_flagged(client: TestClient, tmp_path: Path):
    """文件名 stem 撞车 —— 重随会串到别家竞品、反馈权重合桶。"""
    _setup(client, tmp_path)
    for sub in ("A", "B"):
        _card(tmp_path, f"竞品/{sub}/口碑.md", brand=f"品{sub}", model=f"{sub}1",
              sections={"市场口碑数据": "甲", "品牌赛道定位": "乙"})
    data = _probe(client)
    assert any(c["stem"] == "口碑" for c in data["stem_conflicts"])
    assert all(r["stem_conflict"] for r in data["rows"])


def test_near_duplicate_models_flagged(client: TestClient, tmp_path: Path):
    _setup(client, tmp_path)
    for model in ("欧瑞达X9", "欧瑞达X-9"):
        _card(tmp_path, f"竞品/竞品卡-{model}.md", brand="欧瑞达", model=model,
              sections={"市场口碑数据": "甲", "品牌赛道定位": "乙"})
    data = _probe(client)
    assert data["near_duplicates"] and len(data["near_duplicates"][0]) == 2


def test_multiple_cards_per_competitor_counted(client: TestClient, tmp_path: Path):
    _setup(client, tmp_path)
    for suffix in ("A", "B"):
        _card(tmp_path, f"竞品/竞品卡-欧瑞达X9-{suffix}.md",
              brand="欧瑞达", model="欧瑞达X9",
              sections={"市场口碑数据": f"{suffix} 甲", "品牌赛道定位": f"{suffix} 乙"})
    data = _probe(client)
    assert len(data["competitors"]) == 1
    assert data["competitors"][0]["card_count"] == 2
    assert data["competitors"][0]["eligible_card_count"] == 2


def test_tier_conflict_visible(client: TestClient, tmp_path: Path):
    _setup(client, tmp_path)
    for i, tier in enumerate(("热门品牌", "性价比之选")):
        _card(tmp_path, f"竞品/竞品卡-欧瑞达X9-{i}.md", brand="欧瑞达",
              model="欧瑞达X9", tier=tier,
              sections={"市场口碑数据": "甲", "品牌赛道定位": "乙"})
    data = _probe(client)
    assert data["competitors"][0]["tiers"] == ["性价比之选", "热门品牌"]


# ── 入参守卫 ────────────────────────────────────────────────────────
def test_empty_module_rejected(client: TestClient, tmp_path: Path):
    """空 module 在 VaultIndex.query 里等于整个资料库 —— 几千篇逐篇解析
    再全量回传，界面会卡死且结论全是噪音。"""
    _setup(client, tmp_path)
    r = client.post("/api/vault/card_coverage", json={
        "module": "", "filter": {}, "sections": _SECTIONS,
    })
    assert r.status_code == 400
    assert "选目录" in r.json()["detail"]


def test_blank_section_label_rejected(client: TestClient, tmp_path: Path):
    """「+ 添加小节」推的是空名小节，直接送检以前会 500。"""
    _setup(client, tmp_path)
    r = client.post("/api/vault/card_coverage", json={
        "module": "竞品", "filter": {},
        "sections": [{"label": "市场口碑数据"}, {"label": "  "}],
    })
    assert r.status_code == 400
    assert "还没填名字" in r.json()["detail"]


def test_no_sections_rejected(client: TestClient, tmp_path: Path):
    _setup(client, tmp_path)
    r = client.post("/api/vault/card_coverage", json={
        "module": "竞品", "filter": {}, "sections": [],
    })
    assert r.status_code == 400


def test_stem_conflicts_scoped_to_this_pool(client: TestClient, tmp_path: Path):
    """全仓同名的 README 之类不该刷进竞品池的红字告警。"""
    _setup(client, tmp_path)
    _card(tmp_path, "竞品/竞品卡-欧瑞达X9.md", brand="欧瑞达", model="欧瑞达X9",
          sections={"市场口碑数据": "甲", "品牌赛道定位": "乙"})
    for sub in ("甲", "乙"):
        p = tmp_path / "别的目录" / sub / "README.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\n产品: x\n---\n\n正文\n", encoding="utf-8")
    data = _probe(client)
    assert data["stem_conflicts"] == []
