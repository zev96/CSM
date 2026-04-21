"""Scrollable stack of SlotCards for the current plan."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea
from csm_core.template.schema import Template
from csm_core.assembler.plan import AssemblyPlan
from .slot_card import SlotCard


class SlotList(ScrollArea):
    reroll_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.addStretch(1)
        self.setWidget(self._inner)
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea{background: transparent; border: none;}")
        self._inner.setStyleSheet("background: transparent;")
        self.viewport().setStyleSheet("background: transparent;")

    def load(self, template: Template, plan: AssemblyPlan) -> None:
        # Clear all cards, preserving the trailing stretch
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        slot_map = {s.id: s for s in template.slots}
        idx = 0
        for assignment in plan.slots:
            slot = slot_map.get(assignment.slot_id)
            if slot is None:
                continue
            idx += 1
            card = SlotCard(slot=slot, assignment=assignment, parent=self._inner, index=idx)
            card.reroll_requested.connect(self.reroll_requested.emit)
            self._layout.insertWidget(self._layout.count() - 1, card)
