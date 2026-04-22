import json, shutil
from pathlib import Path
from scripts.migrate_framework_to_blocks import migrate


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_migrate_bundles_paragraph_slots_into_blocks(tmp_path):
    tpl_dir = tmp_path / "templates"
    fw_dir = tmp_path / "frameworks"
    _write(tpl_dir / "t1.json", {
        "id": "t1", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "slots": [
            {"id": "s1", "label": "痛点",
             "source": {"type": "notes_query", "module": "A"},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
            {"id": "s2", "label": "科普",
             "source": {"type": "notes_query", "module": "B"},
             "pick_notes": 3, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
        ],
        "render_order": ["s1", "s2"],
        "default_framework": "fw1",
    })
    _write(fw_dir / "fw1.json", {
        "id": "fw1", "name": "F", "variables": [],
        "blocks": [
            {"kind": "paragraph", "slot": "s1"},
            {"kind": "heading", "level": 2, "index": "一", "text": "标题"},
            {"kind": "numbered_list", "slot": "s2"},
        ],
    })

    report = migrate(tpl_dir, fw_dir)
    assert report["migrated"] == ["t1.json"]
    assert report["skipped"] == []
    data = json.loads((tpl_dir / "t1.json").read_text(encoding="utf-8"))
    kinds = [b["kind"] for b in data["blocks"]]
    assert kinds == ["paragraph", "heading", "numbered_list"]
    assert data["blocks"][0]["id"] == "s1"
    assert data["blocks"][0]["source"]["module"] == "A"
    assert data["blocks"][2]["pick_notes"] == 3
    assert "slots" not in data and "render_order" not in data
    assert (tpl_dir / "_migrated_backup" / "t1.json").exists()


def test_migrate_skips_brand_reason_list(tmp_path):
    tpl_dir = tmp_path / "templates"
    fw_dir = tmp_path / "frameworks"
    _write(tpl_dir / "t1.json", {
        "id": "t1", "name": "T", "product": "x", "version": 1,
        "system_prompt_default": "", "seo_defaults": {},
        "slots": [
            {"id": "s1", "label": "品牌",
             "source": {"type": "notes_query", "module": "A"},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
        ],
        "render_order": ["s1"],
        "default_framework": "fw1",
    })
    _write(fw_dir / "fw1.json", {
        "id": "fw1", "name": "F", "variables": [],
        "blocks": [
            {"kind": "brand_reason_list", "slots": ["s1"], "reason_label": "r:"},
        ],
    })
    report = migrate(tpl_dir, fw_dir)
    assert "t1.json" in report["skipped"]
    assert "slots" in json.loads((tpl_dir / "t1.json").read_text(encoding="utf-8"))


def test_migrate_idempotent_on_already_new_schema(tmp_path):
    tpl_dir = tmp_path / "templates"
    fw_dir = tmp_path / "frameworks"
    _write(tpl_dir / "t1.json", {
        "id": "t1", "name": "T", "product": "x", "version": 1,
        "system_prompt_default": "", "seo_defaults": {},
        "blocks": [{"kind": "literal", "id": "l1", "text": "x"}],
    })
    fw_dir.mkdir()
    report = migrate(tpl_dir, fw_dir)
    assert report["skipped_already_new"] == ["t1.json"]
