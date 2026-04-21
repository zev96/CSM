"""Display a single slot's picks with a reroll button."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from qfluentwidgets import CardWidget, BodyLabel, StrongBodyLabel, PushButton, FluentIcon
from csm_core.template.schema import Slot
from csm_core.assembler.plan import SlotAssignment

_TEXT_PREVIEW_LEN = 80


class SlotCard(CardWidget):
    reroll_requested = pyqtSignal(str)

    def __init__(self, slot: Slot, assignment: SlotAssignment, parent=None, index: int | None = None):
        super().__init__(parent)
        self._slot_id = slot.id

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = f"{index}. {slot.label}" if index is not None else slot.label
        self.title_label = StrongBodyLabel(title, self)
        self.count_label = BodyLabel(f"{len(assignment.picks)} 条", self)
        self.reroll_button = PushButton("重新抽", self, FluentIcon.SYNC)
        self.reroll_button.clicked.connect(lambda: self.reroll_requested.emit(self._slot_id))
        header.addWidget(self.title_label, 1)
        header.addWidget(self.count_label)
        header.addWidget(self.reroll_button)
        root.addLayout(header)

        for p in assignment.picks:
            preview = p.text.replace("\n", " ")
            if len(preview) > _TEXT_PREVIEW_LEN:
                preview = preview[:_TEXT_PREVIEW_LEN] + "…"
            label = BodyLabel(f"· {p.note_id}: {preview}", self)
            label.setWordWrap(True)
            root.addWidget(label)

        if assignment.note:
            warn = BodyLabel(f"⚠ {assignment.note}", self)
            warn.setStyleSheet("color: #B45309;")
            root.addWidget(warn)
