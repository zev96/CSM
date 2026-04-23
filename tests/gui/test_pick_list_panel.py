"""Tests for the PickListPanel widget."""
from __future__ import annotations
from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_gui.widgets.pick_list_panel import PickListPanel


def _plan_with_picks():
    return AssemblyPlan(
        keyword="kw", template_id="t", seed=1,
        results=[
            BlockResult(
                block_id="nl", kind="numbered_list",
                picks=[
                    PickedVariant(note_id="n1", variant_index=0, text="first pick text"),
                    PickedVariant(note_id="n2", variant_index=0, text="second pick text"),
                ],
                meta={"number_style": "1.", "item_separator": "\n\n"},
            ),
            BlockResult(
                block_id="h1", kind="heading", text="题",
                meta={"level": 2, "index": "一"},
            ),
            BlockResult(
                block_id="par", kind="paragraph",
                picks=[PickedVariant(note_id="p1", variant_index=0, text="par text")],
                children=[BlockResult(
                    block_id="child", kind="paragraph",
                    picks=[PickedVariant(note_id="c1", variant_index=0, text="child text")],
                )],
            ),
        ],
    )


def test_pick_list_panel_renders_one_row_per_pick_including_children(qtbot):
    panel = PickListPanel()
    qtbot.addWidget(panel)
    panel.load_plan(_plan_with_picks())
    assert panel.row_count() == 4


def test_pick_list_panel_emits_request_on_button_click(qtbot):
    panel = PickListPanel()
    qtbot.addWidget(panel)
    panel.load_plan(_plan_with_picks())
    with qtbot.waitSignal(panel.reroll_requested, timeout=500) as sig:
        panel.click_row(0)
    assert sig.args == ["nl", 0]


def test_pick_list_panel_set_busy_disables_buttons(qtbot):
    panel = PickListPanel()
    qtbot.addWidget(panel)
    panel.load_plan(_plan_with_picks())
    panel.set_busy(True)
    assert all(not btn.isEnabled() for btn in panel.iter_buttons())
    panel.set_busy(False)
    assert all(btn.isEnabled() for btn in panel.iter_buttons())


def test_pick_list_panel_load_plan_replaces_previous_rows(qtbot):
    panel = PickListPanel()
    qtbot.addWidget(panel)
    panel.load_plan(_plan_with_picks())
    assert panel.row_count() == 4
    empty = AssemblyPlan(keyword="kw", template_id="t", seed=1, results=[])
    panel.load_plan(empty)
    assert panel.row_count() == 0
