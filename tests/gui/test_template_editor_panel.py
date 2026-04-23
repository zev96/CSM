"""Tests for TemplateEditorPanel — block-based template editing."""
from __future__ import annotations


def test_template_editor_loads_all_block_kinds(qtbot, tmp_path):
    import json
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    tpl_path = tmp_path / "t.json"
    tpl_path.write_text(json.dumps({
        "id": "t", "name": "T", "product": "吸尘器",
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
        "id": "t", "name": "T", "product": "x",
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


def test_info_tab_has_no_version_prompt_seo_fields(qtbot):
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    assert not hasattr(panel, "version_spin")
    assert not hasattr(panel, "prompt_edit")
    assert not hasattr(panel, "wc_min_spin")
    assert not hasattr(panel, "kd_min_spin")
    assert not hasattr(panel, "tone_input")
    assert not hasattr(panel, "force_h2_switch")
    assert not hasattr(panel, "long_tail_input")


def test_info_tab_has_default_skill_combo(qtbot, tmp_path):
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    (skill_dir / "alpha.md").write_text("a", encoding="utf-8")
    (skill_dir / "beta.md").write_text("b", encoding="utf-8")
    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.set_skill_dir(skill_dir)
    items = [panel.default_skill_combo.itemText(i)
             for i in range(panel.default_skill_combo.count())]
    assert items == ["（无）", "alpha", "beta"]


def test_set_skill_dir_preserves_current_selection(qtbot, tmp_path):
    """Rescanning the skill directory after the user added a new skill
    in the Skills page must not wipe the currently selected default
    skill. Previously set_skill_dir rebuilt the combo and left the
    first item ("（无）") selected, silently flipping the template's
    default_skill_id."""
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    (skill_dir / "alpha.md").write_text("a", encoding="utf-8")
    (skill_dir / "beta.md").write_text("b", encoding="utf-8")
    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.set_skill_dir(skill_dir)
    # Simulate the user selecting beta
    idx = panel.default_skill_combo.findText("beta")
    panel.default_skill_combo.setCurrentIndex(idx)
    # New skill appears (as if the Skills page just created it)
    (skill_dir / "gamma.md").write_text("g", encoding="utf-8")
    panel.set_skill_dir(skill_dir)
    items = [panel.default_skill_combo.itemText(i)
             for i in range(panel.default_skill_combo.count())]
    assert items == ["（无）", "alpha", "beta", "gamma"]
    assert panel.default_skill_combo.currentText() == "beta"


def test_set_skill_dir_drops_selection_when_skill_deleted(qtbot, tmp_path):
    """If the previously selected skill no longer exists on disk
    (renamed / deleted in the Skills page), fall back to '（无）'."""
    from csm_gui.widgets.template_editor_panel import TemplateEditorPanel
    skill_dir = tmp_path / "s"; skill_dir.mkdir()
    (skill_dir / "alpha.md").write_text("a", encoding="utf-8")
    panel = TemplateEditorPanel()
    qtbot.addWidget(panel)
    panel.set_skill_dir(skill_dir)
    idx = panel.default_skill_combo.findText("alpha")
    panel.default_skill_combo.setCurrentIndex(idx)
    (skill_dir / "alpha.md").unlink()
    panel.set_skill_dir(skill_dir)
    assert panel.default_skill_combo.currentText() == "（无）"
