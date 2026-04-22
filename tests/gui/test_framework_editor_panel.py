import json
from pathlib import Path


def test_editor_loads_and_saves_framework(qtbot, tmp_path):
    from csm_gui.widgets.framework_editor_panel import FrameworkEditorPanel
    fw_path = tmp_path / "fx.json"
    fw_path.write_text(json.dumps({
        "id": "fx", "name": "FX", "variables": ["keyword"],
        "blocks": [
            {"kind": "heading", "level": 2, "index": "一", "text": "{keyword}"},
            {"kind": "paragraph", "slot": "s1"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = FrameworkEditorPanel()
    qtbot.addWidget(panel)
    panel.load_framework(fw_path)
    assert panel.current_path() == fw_path
    assert not panel.is_dirty()

    panel.add_block({"kind": "literal", "text": "完。"})
    assert panel.is_dirty()

    assert panel.save() is True
    saved = json.loads(fw_path.read_text(encoding="utf-8"))
    assert saved["blocks"][-1] == {"kind": "literal", "text": "完。"}


def test_editor_delete_block(qtbot, tmp_path):
    from csm_gui.widgets.framework_editor_panel import FrameworkEditorPanel
    fw_path = tmp_path / "fx.json"
    fw_path.write_text(json.dumps({
        "id": "fx", "name": "FX", "variables": [],
        "blocks": [
            {"kind": "paragraph", "slot": "s1"},
            {"kind": "paragraph", "slot": "s2"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = FrameworkEditorPanel()
    qtbot.addWidget(panel)
    panel.load_framework(fw_path)
    panel.delete_block(0)
    assert panel.save() is True
    saved = json.loads(fw_path.read_text(encoding="utf-8"))
    assert saved["blocks"] == [{"kind": "paragraph", "slot": "s2"}]


def test_editor_move_block(qtbot, tmp_path):
    from csm_gui.widgets.framework_editor_panel import FrameworkEditorPanel
    fw_path = tmp_path / "fx.json"
    fw_path.write_text(json.dumps({
        "id": "fx", "name": "FX", "variables": [],
        "blocks": [
            {"kind": "paragraph", "slot": "a"},
            {"kind": "paragraph", "slot": "b"},
            {"kind": "paragraph", "slot": "c"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    panel = FrameworkEditorPanel()
    qtbot.addWidget(panel)
    panel.load_framework(fw_path)
    panel.move_block(0, 2)
    assert panel.save() is True
    saved = json.loads(fw_path.read_text(encoding="utf-8"))
    assert [b["slot"] for b in saved["blocks"]] == ["b", "c", "a"]
