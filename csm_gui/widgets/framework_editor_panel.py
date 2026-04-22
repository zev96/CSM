"""Right panel of the Framework tab — edit a single framework."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea,
    QMenu, QMessageBox,
)
from qfluentwidgets import BodyLabel, LineEdit, ComboBox, PushButton

from csm_core.framework.loader import load_framework, save_framework
from csm_core.framework.schema import Framework
from csm_core.template.loader import list_templates, load_template

from .framework_block_card import FrameworkBlockCard


class FrameworkEditorPanel(QWidget):
    saved = pyqtSignal(Path)
    dirty_changed = pyqtSignal(bool)

    def __init__(self, parent=None, templates_dir: Path | None = None):
        super().__init__(parent)
        self._path: Path | None = None
        self._data: dict[str, Any] = {}
        self._dirty: bool = False
        self._templates_dir: Path = templates_dir or Path("templates")
        self._slot_choices: list[str] = []
        self._cards: list[FrameworkBlockCard] = []

        root = QVBoxLayout(self)

        header = QFormLayout()
        self.id_edit = LineEdit(self)
        self.id_edit.setReadOnly(True)
        header.addRow("id", self.id_edit)
        self.name_edit = LineEdit(self)
        self.name_edit.textChanged.connect(lambda _t: self._mark_dirty())
        header.addRow("name", self.name_edit)
        self.desc_edit = LineEdit(self)
        self.desc_edit.textChanged.connect(lambda _t: self._mark_dirty())
        header.addRow("description", self.desc_edit)
        self.ref_template_combo = ComboBox(self)
        self.ref_template_combo.setPlaceholderText("参考模板（仅用于 slot 下拉）")
        for name, path in list_templates(self._templates_dir):
            self.ref_template_combo.addItem(name, userData=str(path))
        self.ref_template_combo.currentIndexChanged.connect(
            self._on_ref_template_changed
        )
        header.addRow("参考模板", self.ref_template_combo)
        root.addLayout(header)

        self.blocks_container = QWidget(self)
        self.blocks_layout = QVBoxLayout(self.blocks_container)
        self.blocks_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.blocks_container)
        root.addWidget(scroll, 1)

        bar = QHBoxLayout()
        self.add_btn = PushButton("+ 添加块", self)
        self.add_btn.clicked.connect(self._show_add_menu)
        bar.addWidget(self.add_btn)
        bar.addStretch(1)
        self.save_btn = PushButton("保存", self)
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        root.addLayout(bar)

    def current_path(self) -> Path | None:
        return self._path

    def is_dirty(self) -> bool:
        return self._dirty

    def load_framework(self, path: Path) -> None:
        fw = load_framework(path)
        self._path = path
        self._data = fw.model_dump()
        self.id_edit.setText(fw.id)
        self.name_edit.blockSignals(True)
        self.name_edit.setText(fw.name)
        self.name_edit.blockSignals(False)
        self.desc_edit.blockSignals(True)
        self.desc_edit.setText(fw.description)
        self.desc_edit.blockSignals(False)
        self._rebuild_cards()
        self._set_dirty(False)

    def add_block(self, block: dict[str, Any]) -> None:
        self._data.setdefault("blocks", []).append(block)
        self._rebuild_cards()
        self._mark_dirty()

    def delete_block(self, index: int) -> None:
        blocks = self._data.get("blocks", [])
        if 0 <= index < len(blocks):
            blocks.pop(index)
            self._rebuild_cards()
            self._mark_dirty()

    def move_block(self, src: int, dst: int) -> None:
        blocks = self._data.get("blocks", [])
        if 0 <= src < len(blocks) and 0 <= dst < len(blocks):
            blocks.insert(dst, blocks.pop(src))
            self._rebuild_cards()
            self._mark_dirty()

    def save(self) -> bool:
        if self._path is None:
            return False
        self._data["blocks"] = [c.to_dict() for c in self._cards]
        self._data["name"] = self.name_edit.text()
        self._data["description"] = self.desc_edit.text()
        try:
            fw = Framework.model_validate(self._data)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"框架校验失败：{e}")
            return False
        save_framework(fw, self._path)
        self._set_dirty(False)
        self.saved.emit(self._path)
        return True

    def _rebuild_cards(self) -> None:
        while self.blocks_layout.count():
            item = self.blocks_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()
        for i, b in enumerate(self._data.get("blocks", [])):
            card = FrameworkBlockCard(b, self._slot_choices, self.blocks_container)
            card.changed.connect(self._mark_dirty)
            card.delete_requested.connect(lambda _i=i: self.delete_block(_i))
            card.move_up_requested.connect(lambda _i=i: self.move_block(_i, max(0, _i - 1)))
            card.move_down_requested.connect(
                lambda _i=i: self.move_block(
                    _i, min(len(self._data.get("blocks", [])) - 1, _i + 1)
                )
            )
            self.blocks_layout.addWidget(card)
            self._cards.append(card)

    def _on_ref_template_changed(self) -> None:
        p = self.ref_template_combo.currentData()
        if not p:
            self._slot_choices = []
        else:
            try:
                tpl = load_template(Path(p))
                self._slot_choices = [s.id for s in tpl.slots]
            except Exception:
                self._slot_choices = []
        self._rebuild_cards()

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        defaults = {
            "paragraph":        {"kind": "paragraph", "slot": ""},
            "heading":          {"kind": "heading", "level": 2, "index": "", "text": "标题"},
            "numbered_list":    {"kind": "numbered_list", "slot": ""},
            "brand_reason_list":{"kind": "brand_reason_list", "slots": [], "reason_label": "推荐理由："},
            "literal":          {"kind": "literal", "text": "..."},
        }
        for kind, tmpl in defaults.items():
            act = menu.addAction(kind)
            act.triggered.connect(lambda _c, b=dict(tmpl): self.add_block(b))
        menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

    def _mark_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, v: bool) -> None:
        if self._dirty != v:
            self._dirty = v
            self.dirty_changed.emit(v)
