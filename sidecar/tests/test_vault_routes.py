"""Tests for /api/vault/scan and /api/vault/notes."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _write_note(p: Path, *, frontmatter: dict | None = None, body: str = "") -> None:
    """Write a vault note. ``scan_vault`` drops notes with empty frontmatter,
    so tests that expect a note to appear in the index must pass non-empty
    frontmatter."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = frontmatter or {"module": "default"}  # ensure non-empty for scan_vault
    parts = ["---"]
    for k, v in fm.items():
        parts.append(f"{k}: {v}")
    parts.append("---")
    parts.append(body)
    p.write_text("\n".join(parts), encoding="utf-8")


def test_scan_404_when_root_missing(client: TestClient, tmp_path):
    resp = client.post("/api/vault/scan", json={"root": str(tmp_path / "does-not-exist")})
    assert resp.status_code == 404


def test_scan_400_when_no_root_anywhere(client: TestClient):
    # vault_root unset in config and no override → 400
    resp = client.post("/api/vault/scan", json={})
    assert resp.status_code == 400


def test_scan_returns_summary(client: TestClient, tmp_path):
    vault = tmp_path / "vault"
    _write_note(vault / "营销资料库" / "标题模块" / "test.md",
                frontmatter={"module": "标题"}, body="① first\n② second")
    _write_note(vault / "其他" / "blank.md", body="just text, no variants")

    resp = client.post("/api/vault/scan", json={"root": str(vault)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["root"] == str(vault)
    assert data["note_count"] == 2


def test_list_notes_409_without_prior_scan(client: TestClient):
    resp = client.get("/api/vault/notes")
    assert resp.status_code == 409


def test_list_notes_after_scan(client: TestClient, tmp_path):
    vault = tmp_path / "vault"
    _write_note(vault / "营销资料库" / "标题模块" / "a.md", frontmatter={"x": 1}, body="① one")
    _write_note(vault / "营销资料库" / "标题模块" / "b.md", body="② two\n③ three")
    _write_note(vault / "其他" / "c.md", body="no variants")

    client.post("/api/vault/scan", json={"root": str(vault)})

    all_resp = client.get("/api/vault/notes")
    assert all_resp.status_code == 200
    assert all_resp.json()["count"] == 3

    filtered = client.get("/api/vault/notes", params={"module": "营销资料库/标题模块"})
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["count"] == 2
    assert {n["id"] for n in body["notes"]} == {"a", "b"}


def test_scan_uses_config_vault_root_when_no_override(client: TestClient, tmp_path):
    vault = tmp_path / "configured-vault"
    _write_note(vault / "x.md", body="hi")
    client.patch("/api/config", json={"vault_root": str(vault)})

    resp = client.post("/api/vault/scan", json={})
    assert resp.status_code == 200
    assert resp.json()["note_count"] == 1


# ── /api/vault/card_sections ────────────────────────────────────────────
# 「从目录识别小节」的数据源。关键契约：篇数分「有此小节」与「有内容」两栏、
# 顺序按文档序、同篇重复 H2 不重复计数。


def _card(p: Path, sections: list[tuple[str, str]]) -> None:
    """写一张竞品卡：sections = [(H2 名, 正文), ...]，正文空串 = 空标题。"""
    body = "\n\n".join(f"## {t}\n{b}".rstrip() for t, b in sections)
    _write_note(p, frontmatter={"素材类型": "竞品卡", "品牌": "小米"}, body=body)


def test_card_sections_400_without_module(client: TestClient, tmp_path):
    client.patch("/api/config", json={"vault_root": str(tmp_path / "v")})
    resp = client.post("/api/vault/card_sections", json={"module": "  "})
    assert resp.status_code == 400


def test_card_sections_counts_bodies_separately(client: TestClient, tmp_path):
    """空骨架笔记有 H2 也进不了名册 —— 两栏必须分开，否则以为素材齐了。"""
    vault = tmp_path / "vault"
    pool = vault / "竞品位"
    _card(pool / "a.md", [("核心定位", "① 有内容"), ("净化性能", "① 有内容")])
    _card(pool / "b.md", [("核心定位", ""), ("净化性能", "")])
    client.patch("/api/config", json={"vault_root": str(vault)})

    resp = client.post("/api/vault/card_sections", json={"module": "竞品位"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["note_count"] == 2
    by_title = {s["title"]: s for s in data["sections"]}
    assert by_title["核心定位"]["note_count"] == 2
    assert by_title["核心定位"]["with_body"] == 1


def test_card_sections_document_order_not_alphabetical(client: TestClient, tmp_path):
    """识别结果直接拿去当小节顺序，字母序导进去排版就乱了。"""
    vault = tmp_path / "vault"
    order = ["核心定位", "净化性能", "静音与安全", "成本与维护"]
    _card(vault / "竞品位" / "a.md", [(t, "① x") for t in order])
    _card(vault / "竞品位" / "b.md", [(t, "① y") for t in order])
    client.patch("/api/config", json={"vault_root": str(vault)})

    resp = client.post("/api/vault/card_sections", json={"module": "竞品位"})
    assert [s["title"] for s in resp.json()["sections"]] == order


def test_card_sections_dedupes_repeated_h2_in_one_note(client: TestClient, tmp_path):
    """同篇重复 H2 只算一次，否则 note_count 会超过总篇数。"""
    vault = tmp_path / "vault"
    _card(vault / "竞品位" / "a.md", [("核心定位", "① x"), ("核心定位", "① 又一段")])
    client.patch("/api/config", json={"vault_root": str(vault)})

    resp = client.post("/api/vault/card_sections", json={"module": "竞品位"})
    data = resp.json()
    assert data["note_count"] == 1
    assert [(s["title"], s["note_count"]) for s in data["sections"]] == [("核心定位", 1)]


def test_card_sections_respects_filter(client: TestClient, tmp_path):
    """筛选要真生效 —— 否则同目录的旧格式笔记会把 H2 列表搅浑。"""
    vault = tmp_path / "vault"
    _card(vault / "竞品位" / "card.md", [("核心定位", "① x")])
    _write_note(vault / "竞品位" / "old.md",
                frontmatter={"素材类型": "旧格式"}, body="## 品牌实力\n① 旧的")
    client.patch("/api/config", json={"vault_root": str(vault)})

    resp = client.post("/api/vault/card_sections",
                       json={"module": "竞品位", "filter": {"素材类型": "竞品卡"}})
    data = resp.json()
    assert data["note_count"] == 1
    assert [s["title"] for s in data["sections"]] == ["核心定位"]


def test_card_sections_attributes_empty_match(client: TestClient, tmp_path):
    """一篇都没捞到 → 要说清是目录错还是筛选错，不能只回一张空表。"""
    vault = tmp_path / "vault"
    _card(vault / "竞品位" / "a.md", [("核心定位", "① x")])
    client.patch("/api/config", json={"vault_root": str(vault)})

    resp = client.post("/api/vault/card_sections",
                       json={"module": "竞品位", "filter": {"推荐位": "竞品"}})
    data = resp.json()
    assert data["note_count"] == 0
    assert data["sections"] == []
    assert "推荐位" in data["hint"]


def test_card_endpoints_400_when_vault_root_unreachable(client: TestClient, tmp_path):
    """共享盘掉线要报「目录不可访问」，不能报成「检查目录名是否写错」。

    Path.rglob 对不存在的目录静默产出空序列、IncrementalIndexer 也不抛，
    所以没有前置 is_dir 检查时整盘断连会被归因成模块路径写错 —— 运营会去
    改一个本来正确的路径。
    """
    gone = tmp_path / "断连的共享盘"
    client.patch("/api/config", json={"vault_root": str(gone)})

    r1 = client.post("/api/vault/card_sections", json={"module": "竞品位"})
    assert r1.status_code == 400
    assert "不可访问" in r1.json()["detail"]

    r2 = client.post("/api/vault/card_coverage", json={
        "module": "竞品位", "sections": [{"label": "核心定位"}],
    })
    assert r2.status_code == 400
    assert "不可访问" in r2.json()["detail"]


# ── /api/vault/note_sections（主推卡「从目录识别」）────────────────────────
# 主推卡是「一篇笔记 = 一个小节」，靠 frontmatter 字段区分，正文里没有 H2 ——
# 拿 card_sections 那套去扫只会得到 0 个小节，而用户明明看得见目录里躺着 11 篇。
def _hero(p: Path, *, module: str, order: int | None = None,
          body: str = "① 正文", brand: str = "DARZ") -> None:
    fm: dict = {"素材类型": "产品推荐格式", "模块": module, "品牌": brand}
    if order is not None:
        fm["模块序号"] = order
    _write_note(p, frontmatter=fm, body=body)


def test_note_sections_400_without_module(client: TestClient, tmp_path):
    client.patch("/api/config", json={"vault_root": str(tmp_path / "v")})
    assert client.post("/api/vault/note_sections", json={"module": " "}).status_code == 400


def test_note_sections_groups_by_inferred_field_in_order(client: TestClient, tmp_path):
    """推断出 `模块` 当分组字段、`模块序号` 当排序 —— 顺序直接是小节顺序。

    并列的候选里刻意选**取值不是纯数字**的那个：`模块` 和 `模块序号` 都能
    一篇一值，拿序号当小节名等于给用户一排「0/1/2」。
    """
    vault = tmp_path / "vault"
    d = vault / "主推位"
    _hero(d / "c.md", module="核心参数", order=3)
    _hero(d / "a.md", module="品牌实力", order=1)
    _hero(d / "b.md", module="核心技术", order=2)
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={"module": "主推位"}).json()
    assert data["field"] == "模块"
    assert data["note_count"] == 3
    assert [v["value"] for v in data["values"]] == ["品牌实力", "核心技术", "核心参数"]
    assert all(v["note_count"] == 1 and v["with_body"] == 1 for v in data["values"])
    assert "模块序号" in data["field_candidates"]


def test_note_sections_respects_explicit_field(client: TestClient, tmp_path):
    """前端把当前小节用的字段回传，识别就跟着用户已有的口径走。"""
    vault = tmp_path / "vault"
    _hero(vault / "主推位" / "a.md", module="品牌实力", order=1)
    _hero(vault / "主推位" / "b.md", module="核心技术", order=2)
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={
        "module": "主推位", "field": "模块序号",
    }).json()
    assert data["field"] == "模块序号"
    assert [v["value"] for v in data["values"]] == ["1", "2"]


def test_note_sections_flags_empty_body(client: TestClient, tmp_path):
    """空骨架笔记筛得到，但抽出来是空段 —— 面板要能标出来。"""
    vault = tmp_path / "vault"
    _hero(vault / "主推位" / "a.md", module="品牌实力", order=1)
    _hero(vault / "主推位" / "b.md", module="核心技术", order=2, body="")
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={"module": "主推位"}).json()
    by_val = {v["value"]: v for v in data["values"]}
    assert by_val["品牌实力"]["with_body"] == 1
    assert by_val["核心技术"]["with_body"] == 0


def test_note_sections_empty_pool_carries_attribution(client: TestClient, tmp_path):
    """一篇都没捞到时给归因，与竞品池空池报错同一套口径。"""
    vault = tmp_path / "vault"
    _hero(vault / "主推位" / "a.md", module="品牌实力", order=1)
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={
        "module": "主推位", "filter": {"推荐位": "主推"},
    }).json()
    assert data["note_count"] == 0
    assert data["values"] == []
    assert "推荐位" in data["hint"]


def test_note_sections_no_discriminating_field(client: TestClient, tmp_path):
    """全同字段分不开笔记 —— 返回空 values 而不是瞎选一个字段。"""
    vault = tmp_path / "vault"
    for name in ("a", "b"):
        _write_note(vault / "主推位" / f"{name}.md",
                    frontmatter={"品牌": "DARZ", "产品": "空气净化器"}, body="正文")
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={"module": "主推位"}).json()
    assert data["note_count"] == 2
    assert data["field"] == ""
    assert data["values"] == []


def test_note_sections_400_when_vault_root_unreachable(client: TestClient, tmp_path):
    client.patch("/api/config", json={"vault_root": str(tmp_path / "断连的共享盘")})
    r = client.post("/api/vault/note_sections", json={"module": "主推位"})
    assert r.status_code == 400
    assert "不可访问" in r.json()["detail"]


def test_note_sections_rejects_field_that_cannot_split(client: TestClient, tmp_path):
    """前端回传的字段分不开笔记时必须回落，不能照它拆。

    `field` 取的是「小节 filter 里出现最多的键」，用户只要有一节的筛选字段
    选错（下拉里 素材类型/品牌/产品 全在列），坏字段就会被回传。照它拆只有
    1 个组 → 「按目录替换」把整张卡塌成一节，且那一节命中整个目录随机抽 ——
    正是这次要修的病，由修复按钮本人制造，而且 lint 和 sampler 两道告警都
    拦不住（filter 非空）。
    """
    vault = tmp_path / "vault"
    for i, m in enumerate(["品牌实力", "核心技术", "核心参数"], start=1):
        _hero(vault / "主推位" / f"{i}.md", module=m, order=i)
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={
        "module": "主推位", "field": "素材类型",     # 三篇全是「产品推荐格式」
    }).json()
    assert data["field_rejected"] == "素材类型"
    assert data["field"] == "模块"
    assert [v["value"] for v in data["values"]] == ["品牌实力", "核心技术", "核心参数"]


def test_note_sections_rejects_list_valued_field(client: TestClient, tmp_path):
    """列表字段一篇会落进多个组，当不了「一篇 = 一节」的分组键。"""
    vault = tmp_path / "vault"
    for i, m in enumerate(["品牌实力", "核心技术"], start=1):
        p = vault / "主推位" / f"{i}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"---\n模块: {m}\n模块序号: {i}\n核心关键词:\n  - 模板二\n  - {m}\n---\n① 正文\n",
            encoding="utf-8")
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={
        "module": "主推位", "field": "核心关键词",
    }).json()
    assert data["field_rejected"] == "核心关键词"
    assert data["field"] == "模块"
    assert len(data["values"]) == 2


def test_note_sections_keeps_valid_explicit_field(client: TestClient, tmp_path):
    """能分开就照用户的字段拆，不自作主张（零回归）。"""
    vault = tmp_path / "vault"
    _hero(vault / "主推位" / "a.md", module="甲", order=1)
    _hero(vault / "主推位" / "b.md", module="乙", order=2)
    client.patch("/api/config", json={"vault_root": str(vault)})

    data = client.post("/api/vault/note_sections", json={
        "module": "主推位", "field": "模块序号",
    }).json()
    assert data["field_rejected"] == ""
    assert data["field"] == "模块序号"
