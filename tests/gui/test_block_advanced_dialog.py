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


from csm_gui.widgets.block_advanced_dialog import _SampleSection


def test_sample_section_loads_int_pick(qtbot):
    node = _para_node(pick_notes=3, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w.show()
    assert w._min_spin.value() == 3
    assert w._range_checkbox.isChecked() is False
    assert w._max_spin.isVisible() is False
    assert w._variants_spin.value() == 1
    assert w._unique_checkbox.isChecked() is False


def test_sample_section_loads_random_between(qtbot):
    node = _para_node(
        pick_notes={"random_between": [2, 5]},
        pick_variants=2,
        unique_notes=True,
    )
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w.show()
    assert w._min_spin.value() == 2
    assert w._range_checkbox.isChecked() is True
    assert w._max_spin.isVisible() is True
    assert w._max_spin.value() == 5
    assert w._variants_spin.value() == 2
    assert w._unique_checkbox.isChecked() is True


def test_sample_section_save_int_when_range_disabled(qtbot):
    node = _para_node(pick_notes=1, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w._min_spin.setValue(4)
    w._variants_spin.setValue(2)
    w._unique_checkbox.setChecked(True)
    w.save_to_node()
    assert node.pick_notes == 4
    assert node.pick_variants == 2
    assert node.unique_notes is True


def test_sample_section_save_dict_when_range_enabled(qtbot):
    node = _para_node(pick_notes=1, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w._min_spin.setValue(2)
    w._range_checkbox.setChecked(True)
    w._max_spin.setValue(5)
    w.save_to_node()
    assert node.pick_notes == {"random_between": [2, 5]}


def test_sample_section_save_int_when_range_min_equals_max(qtbot):
    node = _para_node(pick_notes=1, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w._min_spin.setValue(3)
    w._range_checkbox.setChecked(True)
    w._max_spin.setValue(3)
    w.save_to_node()
    assert node.pick_notes == 3


def test_sample_section_toggle_range_shows_and_hides_max(qtbot):
    node = _para_node(pick_notes=2, pick_variants=1, unique_notes=False)
    w = _SampleSection(node, parent=None)
    qtbot.addWidget(w)
    w.show()
    assert w._max_spin.isVisible() is False
    w._range_checkbox.setChecked(True)
    assert w._max_spin.isVisible() is True
    w._range_checkbox.setChecked(False)
    assert w._max_spin.isVisible() is False
