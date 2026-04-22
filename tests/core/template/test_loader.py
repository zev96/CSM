from pathlib import Path
import json
import pytest
from csm_core.template.loader import load_template, save_template
from csm_core.template.schema import Template

TEMPLATE_PATH = Path(__file__).parent.parent.parent.parent / "templates" / "daogou-changjing-renqun.json"


def test_load_template_returns_model():
    tpl = load_template(TEMPLATE_PATH)
    assert isinstance(tpl, Template)
    assert tpl.id == "daogou-changjing-renqun"
    assert len(tpl.slots) == 14


def test_save_template_roundtrip(tmp_path: Path):
    original = load_template(TEMPLATE_PATH)
    out = tmp_path / "out.json"
    save_template(original, out)
    reloaded = load_template(out)
    assert reloaded.model_dump() == original.model_dump()


def test_load_invalid_json_raises(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_template(bad)


def test_load_schema_violation_raises(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "id": "x", "name": "X", "product": "吸尘器",
        "slots": [], "render_order": ["missing"]
    }), encoding="utf-8")
    with pytest.raises(Exception):  # pydantic ValidationError
        load_template(bad)
