"""Left-panel widget: list sampled picks with per-pick reroll buttons."""
from __future__ import annotations
from typing import Iterator
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QSizePolicy,
)
from qfluentwidgets import BodyLabel, CaptionLabel, ToolButton, FluentIcon
from csm_core.assembler.plan import AssemblyPlan, BlockResult


_PREVIEW_MAX = 40


def _preview(text: str) -> str:
    t = text.strip().replace("\n", " ")
    if len(t) <= _PREVIEW_MAX:
        return t
    return t[:_PREVIEW_MAX] + "…"


def _flatten_picks(results: list[BlockResult]) -> list[tuple[str, int, str]]:
    """Return [(block_id, pick_index, preview_text)] including children."""
    rows: list[tuple[str, int, str]] = []
    for r in results:
        for i, p in enumerate(r.picks):
            rows.append((r.block_id, i, _preview(p.text)))
        if r.children:
            rows.extend(_flatten_picks(r.children))
    return rows


class _PickRow(QFrame):
    def __init__(self, block_id: str, pick_index: int, preview: str, parent=None):
        super().__init__(parent)
        self.block_id = block_id
        self.pick_index = pick_index
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)

        label_col = QVBoxLayout()
        label_col.setSpacing(2)
        self.title = CaptionLabel(f"{block_id}[{pick_index}]", self)
        self.body = BodyLabel(preview, self)
        self.body.setWordWrap(True)
        label_col.addWidget(self.title)
        label_col.addWidget(self.body)
        lay.addLayout(label_col, 1)

        self.button = ToolButton(FluentIcon.SYNC, self)
        self.button.setToolTip("重抽这条")
        self.button.setFixedSize(28, 28)
        lay.addWidget(self.button)


class PickListPanel(QWidget):
    reroll_requested = pyqtSignal(str, int)  # (block_id, pick_index)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(BodyLabel("采样结果（点击重抽单条）", self))

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._container = QWidget(self._scroll)
        self._container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum,
        )
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(6)
        self._container_layout.addStretch(1)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self._rows: list[_PickRow] = []

    def load_plan(self, plan: AssemblyPlan) -> None:
        for row in self._rows:
            self._container_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        for block_id, pick_index, preview in _flatten_picks(plan.results):
            row = _PickRow(block_id, pick_index, preview, self._container)
            row.button.clicked.connect(
                lambda _=False, b=block_id, i=pick_index:
                self.reroll_requested.emit(b, i)
            )
            count = self._container_layout.count()
            self._container_layout.insertWidget(count - 1, row)
            self._rows.append(row)

    def set_busy(self, busy: bool) -> None:
        for row in self._rows:
            row.button.setEnabled(not busy)

    def row_count(self) -> int:
        return len(self._rows)

    def iter_buttons(self) -> Iterator[ToolButton]:
        for row in self._rows:
            yield row.button

    def click_row(self, index: int) -> None:
        """Test helper: invoke the button on row ``index``."""
        self._rows[index].button.click()
