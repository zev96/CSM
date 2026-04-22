"""Per-block edit card for the framework editor.

One card handles all 5 kinds via a kind switch. Keeping them in one file
avoids 5 near-identical tiny widgets.
"""
from __future__ import annotations
from typing import Any
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QListWidget,
    QAbstractItemView,
)
from qfluentwidgets import (
    BodyLabel, LineEdit, SpinBox, ComboBox, TextEdit, ToolButton,
    FluentIcon as FIF,
)


class FrameworkBlockCard(QWidget):
    changed = pyqtSignal()
    delete_requested = pyqtSignal()
    move_up_requested = pyqtSignal()
    move_down_requested = pyqtSignal()

    def __init__(self, block: dict[str, Any], slot_choices: list[str], parent=None):
        super().__init__(parent)
        self._kind: str = block["kind"]
        self._slot_choices = slot_choices

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(BodyLabel(f"[{self._kind}]"))
        header.addStretch(1)
        up = ToolButton(FIF.UP, self)
        up.clicked.connect(self.move_up_requested.emit)
        header.addWidget(up)
        down = ToolButton(FIF.DOWN, self)
        down.clicked.connect(self.move_down_requested.emit)
        header.addWidget(down)
        rm = ToolButton(FIF.DELETE, self)
        rm.clicked.connect(self.delete_requested.emit)
        header.addWidget(rm)
        root.addLayout(header)

        form = QFormLayout()
        root.addLayout(form)
        self._widgets: dict[str, QWidget] = {}

        if self._kind in ("paragraph", "numbered_list"):
            combo = ComboBox(self)
            effective_choices = list(slot_choices)
            existing_slot = block.get("slot", "")
            if existing_slot and existing_slot not in effective_choices:
                effective_choices.insert(0, existing_slot)
            for s in effective_choices:
                combo.addItem(s, userData=s)
            idx = combo.findData(existing_slot)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
            form.addRow("slot", combo)
            self._widgets["slot"] = combo

        elif self._kind == "heading":
            level = SpinBox(self)
            level.setRange(1, 3)
            level.setValue(int(block.get("level", 2)))
            level.valueChanged.connect(lambda _v: self.changed.emit())
            form.addRow("level", level)
            self._widgets["level"] = level

            index_edit = LineEdit(self)
            index_edit.setText(str(block.get("index", "")))
            index_edit.textChanged.connect(lambda _t: self.changed.emit())
            form.addRow("index", index_edit)
            self._widgets["index"] = index_edit

            text_edit = LineEdit(self)
            text_edit.setText(str(block.get("text", "")))
            text_edit.setPlaceholderText("支持 {keyword}")
            text_edit.textChanged.connect(lambda _t: self.changed.emit())
            form.addRow("text", text_edit)
            self._widgets["text"] = text_edit

        elif self._kind == "brand_reason_list":
            lst = QListWidget(self)
            lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
            for s in slot_choices:
                lst.addItem(s)
            preselect = set(block.get("slots", []))
            for i in range(lst.count()):
                if lst.item(i).text() in preselect:
                    lst.item(i).setSelected(True)
            lst.itemSelectionChanged.connect(self.changed.emit)
            form.addRow("slots", lst)
            self._widgets["slots"] = lst

            label_edit = LineEdit(self)
            label_edit.setText(str(block.get("reason_label", "推荐理由：")))
            label_edit.textChanged.connect(lambda _t: self.changed.emit())
            form.addRow("reason_label", label_edit)
            self._widgets["reason_label"] = label_edit

        elif self._kind == "literal":
            text_edit = TextEdit(self)
            text_edit.setPlainText(str(block.get("text", "")))
            text_edit.textChanged.connect(self.changed.emit)
            form.addRow("text", text_edit)
            self._widgets["text"] = text_edit

    def to_dict(self) -> dict[str, Any]:
        w = self._widgets
        if self._kind in ("paragraph", "numbered_list"):
            return {"kind": self._kind, "slot": w["slot"].currentData() or ""}
        if self._kind == "heading":
            return {
                "kind": "heading",
                "level": int(w["level"].value()),
                "index": w["index"].text(),
                "text": w["text"].text(),
            }
        if self._kind == "brand_reason_list":
            lst: QListWidget = w["slots"]  # type: ignore[assignment]
            slots = [lst.item(i).text() for i in range(lst.count())
                     if lst.item(i).isSelected()]
            return {
                "kind": "brand_reason_list",
                "slots": slots,
                "reason_label": w["reason_label"].text(),
            }
        if self._kind == "literal":
            return {"kind": "literal", "text": w["text"].toPlainText()}
        raise ValueError(f"unknown kind {self._kind}")
