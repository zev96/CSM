"""Tests for TemplateListPanel and _NewTemplateDialog."""
from __future__ import annotations


def test_new_dialog_has_only_name_and_product_inputs(qtbot):
    from PyQt6.QtWidgets import QWidget
    from csm_gui.widgets.template_list_panel import _NewTemplateDialog
    # MessageBoxBase requires a real parent widget to compute geometry.
    parent = QWidget()
    parent.resize(800, 600)
    qtbot.addWidget(parent)
    dlg = _NewTemplateDialog(parent=parent)
    qtbot.addWidget(dlg)
    assert not hasattr(dlg, "id_input")
    assert hasattr(dlg, "name_input")
    assert hasattr(dlg, "product_input")


def test_new_template_auto_generates_timestamp_id(qtbot, tmp_path, monkeypatch):
    """Clicking 创建 with just name+product produces a template with a
    generated id like 'template-<epoch>' and a <id>.json file on disk."""
    import re
    from csm_gui.widgets.template_list_panel import TemplateListPanel
    from csm_gui.widgets import template_list_panel as mod

    panel = TemplateListPanel()
    qtbot.addWidget(panel)
    panel.set_directory(tmp_path)

    class FakeDlg:
        def __init__(self, parent=None):
            self.name_input = type("X", (), {"text": lambda self_: "My Template"})()
            self.product_input = type("X", (), {"text": lambda self_: "吸尘器"})()
        def exec(self): return True

    monkeypatch.setattr(mod, "_NewTemplateDialog", FakeDlg)
    panel._on_new()

    jsons = list(tmp_path.glob("*.json"))
    assert len(jsons) == 1
    assert re.match(r"^template-\d{9,11}\.json$", jsons[0].name)
