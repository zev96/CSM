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


from csm_gui.widgets.block_advanced_dialog import _DependsSection


def test_depends_section_excludes_self_and_descendants(qtbot):
    parent = _BlockNode(kind="paragraph", label="父")
    child_a = _BlockNode(kind="paragraph", label="子A")
    grand = _BlockNode(kind="paragraph", label="孙")
    child_a.children = [grand]
    parent.children = [child_a]
    sibling = _BlockNode(kind="paragraph", label="兄弟")
    all_blocks = [
        ("block_1", "父", parent),
        ("block_1_1", "子A", child_a),
        ("block_1_1_1", "孙", grand),
        ("block_2", "兄弟", sibling),
    ]
    w = _DependsSection(parent, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    labels = [c.text() for c in w.checkboxes_for_test()]
    assert labels == ["block_2 — 兄弟"]


def test_depends_section_checks_existing_depends_on(qtbot):
    self_node = _BlockNode(kind="paragraph", label="我")
    self_node.depends_on = ["block_2"]
    other_a = _BlockNode(kind="paragraph", label="A")
    other_b = _BlockNode(kind="paragraph", label="B")
    all_blocks = [
        ("block_1", "我", self_node),
        ("block_2", "A", other_a),
        ("block_3", "B", other_b),
    ]
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    boxes = w.checkboxes_for_test()
    assert boxes[0].isChecked() is True    # block_2
    assert boxes[1].isChecked() is False   # block_3


def test_depends_section_save_preserves_order(qtbot):
    self_node = _BlockNode(kind="paragraph")
    a = _BlockNode(kind="paragraph")
    b = _BlockNode(kind="paragraph")
    c = _BlockNode(kind="paragraph")
    all_blocks = [
        ("block_1", "self", self_node),
        ("block_2", "A", a),
        ("block_3", "B", b),
        ("block_4", "C", c),
    ]
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    boxes = w.checkboxes_for_test()
    boxes[0].setChecked(True)   # block_2
    boxes[2].setChecked(True)   # block_4
    w.save_to_node()
    assert self_node.depends_on == ["block_2", "block_4"]


def test_depends_section_search_box_hidden_when_few_candidates(qtbot):
    self_node = _BlockNode(kind="paragraph")
    all_blocks = [
        ("block_1", "self", self_node),
        ("block_2", "A", _BlockNode(kind="paragraph")),
    ]
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    w.show()
    assert w._search_edit.isHidden() is True


def test_depends_section_search_box_filters_candidates(qtbot):
    self_node = _BlockNode(kind="paragraph")
    all_blocks = [("block_1", "self", self_node)]
    for i in range(2, 13):
        all_blocks.append((f"block_{i}", f"标签{i}", _BlockNode(kind="paragraph")))
    w = _DependsSection(self_node, all_blocks, parent_widget=None)
    qtbot.addWidget(w)
    w.show()
    assert w._search_edit.isHidden() is False
    w._search_edit.setText("5")
    visible = [cb for cb in w.checkboxes_for_test() if cb.isVisible()]
    assert len(visible) == 1
    assert "标签5" in visible[0].text()


from csm_gui.widgets.block_advanced_dialog import BlockAdvancedDialog


def test_dialog_accept_writes_all_sections_back(qtbot):
    from PyQt6.QtWidgets import QWidget
    node = _BlockNode(
        kind="paragraph", label="test",
        filter_cond={}, pick_notes=1, pick_variants=1, unique_notes=False,
    )
    other = _BlockNode(kind="paragraph", label="other")
    all_blocks = [("block_1", "test", node), ("block_2", "other", other)]
    parent_w = QWidget()
    parent_w.resize(800, 600)
    qtbot.addWidget(parent_w)
    dlg = BlockAdvancedDialog(
        node=node, all_blocks=all_blocks, vault_root=None, parent=parent_w,
    )
    qtbot.addWidget(dlg)
    dlg._filter_section._on_add_row()
    row = dlg._filter_section.rows_for_test()[0]
    row["key_edit"].setText("素材类型")
    row["value_edit"].setText("引言痛点")
    dlg._sample_section._min_spin.setValue(2)
    dlg._sample_section._range_checkbox.setChecked(True)
    dlg._sample_section._max_spin.setValue(5)
    dlg._sample_section._variants_spin.setValue(2)
    dlg._sample_section._unique_checkbox.setChecked(True)
    dlg._depends_section.checkboxes_for_test()[0].setChecked(True)

    dlg.accept()

    assert node.filter_cond == {"素材类型": "引言痛点"}
    assert node.pick_notes == {"random_between": [2, 5]}
    assert node.pick_variants == 2
    assert node.unique_notes is True
    assert node.depends_on == ["block_2"]


def test_dialog_reject_leaves_node_unchanged(qtbot):
    from PyQt6.QtWidgets import QWidget
    node = _BlockNode(
        kind="paragraph",
        filter_cond={"key": "val"},
        pick_notes=2, pick_variants=1, unique_notes=False,
        depends_on=["block_9"],
    )
    all_blocks = [("block_1", "self", node)]
    parent_w = QWidget()
    parent_w.resize(800, 600)
    qtbot.addWidget(parent_w)
    dlg = BlockAdvancedDialog(
        node=node, all_blocks=all_blocks, vault_root=None, parent=parent_w,
    )
    qtbot.addWidget(dlg)
    dlg._filter_section._on_add_row()
    dlg._filter_section.rows_for_test()[-1]["key_edit"].setText("新键")
    dlg._sample_section._min_spin.setValue(9)
    dlg._sample_section._unique_checkbox.setChecked(True)

    dlg.reject()

    assert node.filter_cond == {"key": "val"}
    assert node.pick_notes == 2
    assert node.pick_variants == 1
    assert node.unique_notes is False
    assert node.depends_on == ["block_9"]


def test_dialog_title_shows_block_identity(qtbot):
    from PyQt6.QtWidgets import QWidget
    node = _BlockNode(kind="paragraph", label="我的段落")
    parent_w = QWidget()
    parent_w.resize(800, 600)
    qtbot.addWidget(parent_w)
    dlg = BlockAdvancedDialog(
        node=node, all_blocks=[("block_1", "我的段落", node)],
        vault_root=None, parent=parent_w,
    )
    qtbot.addWidget(dlg)
    assert "我的段落" in dlg.titleLabel.text()
