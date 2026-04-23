"""Tests for BlockAdvancedDialog and its section widgets."""
from __future__ import annotations
from csm_gui.widgets.slot_tree_widget import _BlockNode
from csm_gui.widgets.block_advanced_dialog import _FilterSection


def _para_node(**kw) -> _BlockNode:
    n = _BlockNode(kind="paragraph")
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def test_filter_section_loads_existing_dict(qtbot):
    node = _para_node(filter_cond={"素材类型": ["引言痛点", "引言期待"], "难度": "简单"})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    rows = w.rows_for_test()
    assert len(rows) == 2
    assert rows[0]["key"] == "素材类型"
    assert rows[0]["value"] == "引言痛点, 引言期待"
    assert rows[1]["key"] == "难度"
    assert rows[1]["value"] == "简单"


def test_filter_section_add_row_appends_blank_entry(qtbot):
    node = _para_node(filter_cond={})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    assert len(w.rows_for_test()) == 0
    w._on_add_row()
    rows = w.rows_for_test()
    assert len(rows) == 1
    assert rows[0]["key"] == ""
    assert rows[0]["value"] == ""


def test_filter_section_save_roundtrips_list_and_scalar(qtbot):
    node = _para_node(filter_cond={})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    w._on_add_row()
    w._on_add_row()
    rows = w.rows_for_test()
    rows[0]["key_edit"].setText("素材类型")
    rows[0]["value_edit"].setText("引言痛点, 引言期待")
    rows[1]["key_edit"].setText("难度")
    rows[1]["value_edit"].setText("简单")
    w.save_to_node()
    assert node.filter_cond == {
        "素材类型": ["引言痛点", "引言期待"],
        "难度": "简单",
    }


def test_filter_section_save_drops_empty_values_and_keys(qtbot):
    node = _para_node(filter_cond={"旧键": "旧值"})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    rows = w.rows_for_test()
    rows[0]["value_edit"].setText("")
    w._on_add_row()
    new_row = w.rows_for_test()[1]
    new_row["key_edit"].setText("另一键")
    new_row["value_edit"].setText("")
    w.save_to_node()
    assert node.filter_cond == {}


def test_filter_section_remove_row(qtbot):
    node = _para_node(filter_cond={"a": "1", "b": "2"})
    w = _FilterSection(node, fm_candidates={}, parent=None)
    qtbot.addWidget(w)
    assert len(w.rows_for_test()) == 2
    w._remove_row(0)
    assert len(w.rows_for_test()) == 1
    assert w.rows_for_test()[0]["key"] == "b"
