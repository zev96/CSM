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
