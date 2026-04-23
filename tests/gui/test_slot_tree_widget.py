"""Tests for SlotTreeWidget helpers and row behaviors."""
from __future__ import annotations
from csm_gui.widgets.slot_tree_widget import SlotTreeWidget, _BlockNode


def _paragraph(bid: str, label: str, children=()) -> _BlockNode:
    n = _BlockNode(kind="paragraph", block_id=bid, label=label)
    n.children = list(children)
    return n


def test_collect_all_blocks_returns_flat_list_in_tree_order(qtbot):
    w = SlotTreeWidget()
    qtbot.addWidget(w)
    child1 = _paragraph("", "孩子A")
    child2 = _paragraph("", "孩子B")
    root1 = _paragraph("", "根1", children=[child1, child2])
    root2 = _paragraph("", "根2")
    w._roots = [root1, root2]

    collected = w._collect_all_blocks()
    assert [(bid, label) for bid, label, _ in collected] == [
        ("block_1", "根1"),
        ("block_1_1", "孩子A"),
        ("block_1_2", "孩子B"),
        ("block_2", "根2"),
    ]
    assert collected[0][2] is root1
    assert collected[1][2] is child1
    assert collected[3][2] is root2


import pytest


def _make_widget_with_root(qtbot, kind: str = "paragraph"):
    w = SlotTreeWidget()
    qtbot.addWidget(w)
    w.load_blocks([])
    w._roots = [_BlockNode(kind=kind, label="根")]
    w._rebuild()
    return w


def test_paragraph_row_shows_gear_and_add_child(qtbot):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    w.show()
    row = w._all_rows_for_test()[0]
    assert row._gear_btn.isVisible() is True
    assert row._add_child_btn.isVisible() is True


def test_non_paragraph_row_hides_gear_and_add_child(qtbot):
    w = _make_widget_with_root(qtbot, kind="heading")
    row = w._all_rows_for_test()[0]
    assert row._gear_btn.isVisible() is False
    assert row._add_child_btn.isVisible() is False


def test_kind_switch_to_paragraph_reveals_gear_and_add_child(qtbot):
    w = _make_widget_with_root(qtbot, kind="heading")
    w.show()
    row = w._all_rows_for_test()[0]
    row._kind_combo.setCurrentIndex(0)  # BLOCK_KINDS[0] == "paragraph"
    assert row._gear_btn.isVisible() is True
    assert row._add_child_btn.isVisible() is True


def test_click_add_child_appends_child_and_expands(qtbot):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    root_node = w._roots[0]
    assert root_node.children == []
    assert root_node.expanded is False
    row = w._all_rows_for_test()[0]
    row._add_child_btn.click()
    assert len(root_node.children) == 1
    assert root_node.children[0].kind == "paragraph"
    assert root_node.expanded is True


def test_gear_opens_dialog_and_writes_back_on_accept(qtbot, monkeypatch):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    row = w._all_rows_for_test()[0]
    root_node = w._roots[0]

    from csm_gui.widgets import block_advanced_dialog as mod
    real_init = mod.BlockAdvancedDialog.__init__
    def fake_init(self, *, node, all_blocks, vault_root=None, parent=None):
        real_init(
            self, node=node, all_blocks=all_blocks,
            vault_root=vault_root, parent=parent,
        )
        self._sample_section._min_spin.setValue(7)
        self._sample_section._unique_checkbox.setChecked(True)
    monkeypatch.setattr(mod.BlockAdvancedDialog, "__init__", fake_init)
    monkeypatch.setattr(mod.BlockAdvancedDialog, "exec", lambda self: self.accept() or 1)

    row._gear_btn.click()
    assert root_node.pick_notes == 7
    assert root_node.unique_notes is True


def test_gear_cancel_leaves_node_untouched(qtbot, monkeypatch):
    w = _make_widget_with_root(qtbot, kind="paragraph")
    w._roots[0].pick_notes = 3
    w._roots[0].unique_notes = False
    row = w._all_rows_for_test()[0]

    from csm_gui.widgets import block_advanced_dialog as mod
    real_init = mod.BlockAdvancedDialog.__init__
    def fake_init(self, *, node, all_blocks, vault_root=None, parent=None):
        real_init(
            self, node=node, all_blocks=all_blocks,
            vault_root=vault_root, parent=parent,
        )
        self._sample_section._min_spin.setValue(9)
        self._sample_section._unique_checkbox.setChecked(True)
    monkeypatch.setattr(mod.BlockAdvancedDialog, "__init__", fake_init)
    monkeypatch.setattr(mod.BlockAdvancedDialog, "exec", lambda self: self.reject() or 0)

    row._gear_btn.click()
    assert w._roots[0].pick_notes == 3
    assert w._roots[0].unique_notes is False
