"""Tests for TemplateEditorPanel — block-based template editing."""
from __future__ import annotations


def test_template_editor_loads_all_block_kinds(qtbot, tmp_path):
    import json
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    tpl_path = tmp_path / "t.json"
    tpl_path.write_text(json.dumps({
        "id": "t", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": [
            {"kind": "paragraph", "id": "p1", "label": "痛点",
             "source": {"type": "notes_query", "module": "A"}},
            {"kind": "heading", "id": "h1", "level": 2, "index": "一", "text": "题"},
            {"kind": "hero_brand", "id": "hb1", "title": "CEWEY"},
            {"kind": "competitor_pool", "id": "cp1",
             "source": {"type": "notes_query", "module": "竞品"},
             "pick_notes": {"random_between": [2, 2]}},
            {"kind": "literal", "id": "l1", "text": "end"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.load_template(tpl_path)
    blocks = panel.slots_page.get_blocks()
    assert [b.kind for b in blocks] == [
        "paragraph", "heading", "hero_brand", "competitor_pool", "literal",
    ]


def test_template_editor_saves_round_trip(qtbot, tmp_path):
    import json
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    tpl_path = tmp_path / "t.json"
    original = {
        "id": "t", "name": "T", "product": "x", "version": 1,
        "system_prompt_default": "", "seo_defaults": {},
        "blocks": [
            {"kind": "literal", "id": "l1", "text": "hello"},
            {"kind": "heading", "id": "h1", "level": 2, "index": "", "text": "T"},
        ],
    }
    tpl_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.load_template(tpl_path)
    assert panel.save() is True
    saved = json.loads(tpl_path.read_text(encoding="utf-8"))
    assert [b["kind"] for b in saved["blocks"]] == ["literal", "heading"]
