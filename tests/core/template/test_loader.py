import json
from pathlib import Path
from csm_core.template.loader import load_template, save_template, list_templates


def _fixture_dict():
    return {
        "id": "t1", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": [
            {"kind": "literal", "id": "l1", "text": "hello"},
        ],
    }


def test_load_and_save_roundtrip(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_fixture_dict()), encoding="utf-8")
    tpl = load_template(p)
    assert tpl.id == "t1"
    assert tpl.blocks[0].kind == "literal"
    out = tmp_path / "out.json"
    save_template(tpl, out)
    round = load_template(out)
    assert round.id == tpl.id


def test_list_templates_returns_display_names(tmp_path):
    d = tmp_path / "tpls"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({**_fixture_dict(), "name": "第二"}), encoding="utf-8")
    (d / "b.json").write_text(json.dumps({**_fixture_dict(), "name": "第一"}), encoding="utf-8")
    items = list_templates(d)
    assert [n for n, _ in items] == ["第一", "第二"]


def test_load_migrates_competitor_pool_brand_pool_to_notes_query(tmp_path):
    """旧模板 competitor_pool 默认 brand_pool 会撞 sampler 断言；
    loader 应该静默迁移成 notes_query（empty 模块/筛选），让用户能打开
    并通过 UI 填回真实参数。"""
    data = {
        **_fixture_dict(),
        "blocks": [
            {"kind": "literal", "id": "lit1", "text": "x"},
            {
                "kind": "competitor_pool",
                "id": "competitor_pool_pier",
                "source": {"type": "brand_pool", "exclude_brands": []},
                "pick_notes": 2,
                "reason_label": "推荐理由：",
            },
        ],
    }
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    tpl = load_template(p)
    cp = tpl.blocks[1]
    assert cp.source.type == "notes_query"
    assert cp.source.module == ""
    assert cp.source.filter == {}
