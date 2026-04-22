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
