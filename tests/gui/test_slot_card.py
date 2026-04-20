from csm_core.assembler.plan import SlotAssignment, PickedVariant
from csm_core.template.schema import Slot, NotesQuerySource
from csm_gui.widgets.slot_card import SlotCard


def _slot(slot_id="intro", label="引言"):
    return Slot(id=slot_id, label=label,
                source=NotesQuerySource(module="m"), pick_notes=1)


def test_slot_card_shows_label_and_pick_count(qtbot):
    assignment = SlotAssignment(slot_id="intro", picks=[
        PickedVariant(note_id="n1", variant_index=0, text="hello world " * 20),
    ])
    card = SlotCard(slot=_slot(), assignment=assignment)
    qtbot.addWidget(card)
    assert "引言" in card.title_label.text()
    assert "1" in card.count_label.text()


def test_slot_card_emits_reroll(qtbot):
    assignment = SlotAssignment(slot_id="intro", picks=[])
    card = SlotCard(slot=_slot(), assignment=assignment)
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.reroll_requested, timeout=500) as sig:
        card.reroll_button.click()
    assert sig.args[0] == "intro"
