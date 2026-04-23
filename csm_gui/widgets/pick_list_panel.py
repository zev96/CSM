"""Left-panel widget: list sampled picks with per-pick reroll buttons."""
from __future__ import annotations
from typing import Iterator
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QSizePolicy, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ToolButton, FluentIcon, CardWidget,
)
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


def _build_label_map(template) -> dict[str, str]:
    """Map block_id -> display label for pick-list titles.

    Paragraph / numbered_list use ``label`` (falling back to id).
    Heading/literal use ``text``; hero_brand uses ``title``; competitor_pool
    has no user-set label so falls back to a generic "竞品".
    """
    result: dict[str, str] = {}
    if template is None:
        return result

    def walk(items):
        for b in items:
            kind = getattr(b, "kind", "")
            bid = getattr(b, "id", "")
            if kind in ("paragraph", "numbered_list"):
                label = getattr(b, "label", "") or bid
            elif kind == "heading":
                label = getattr(b, "text", "") or bid
            elif kind == "hero_brand":
                label = getattr(b, "title", "") or bid
            elif kind == "literal":
                txt = getattr(b, "text", "") or bid
                label = txt[:16] + ("…" if len(txt) > 16 else "")
            elif kind == "competitor_pool":
                label = "竞品"
            else:
                label = bid
            result[bid] = label
            if kind == "paragraph":
                walk(getattr(b, "children", []) or [])

    walk(getattr(template, "blocks", []) or [])
    return result


class _PickRow(QFrame):
    def __init__(self, block_id: str, pick_index: int, preview: str,
                 display_label: str, parent=None):
        super().__init__(parent)
        self.block_id = block_id
        self.pick_index = pick_index
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)

        label_col = QVBoxLayout()
        label_col.setSpacing(2)
        self.title = CaptionLabel(f"{display_label}[{pick_index}]", self)
        self.body = BodyLabel(preview, self)
        self.body.setWordWrap(True)
        label_col.addWidget(self.title)
        label_col.addWidget(self.body)
        lay.addLayout(label_col, 1)

        self.button = ToolButton(FluentIcon.SYNC, self)
        self.button.setToolTip("重抽这条")
        self.button.setFixedSize(28, 28)
        lay.addWidget(self.button)


class PickListPanel(CardWidget):
    reroll_requested = pyqtSignal(str, int)  # (block_id, pick_index)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(BodyLabel("采样结果（点击重抽单条）", self))

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._container = QWidget(self._scroll)
        self._container.setStyleSheet("background: transparent;")
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
        self._label_map: dict[str, str] = {}

    def load_plan(self, plan: AssemblyPlan, template=None) -> None:
        for row in self._rows:
            self._container_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        self._label_map = _build_label_map(template)

        for block_id, pick_index, preview in _flatten_picks(plan.results):
            # Child blocks get the same label as their paragraph ancestor by
            # walking back through the id prefix ("block_1_1" -> "block_1").
            label = self._label_map.get(block_id) or _fallback_label(
                block_id, self._label_map,
            )
            row = _PickRow(
                block_id, pick_index, preview, label, self._container,
            )
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


def _fallback_label(block_id: str, label_map: dict[str, str]) -> str:
    """If block_id isn't directly in the label map (e.g. nested child id
    wasn't discovered through template walk), fall back to the closest
    prefix match, then to block_id itself.
    """
    cur = block_id
    while "_" in cur:
        cur = cur.rsplit("_", 1)[0]
        if cur in label_map:
            return label_map[cur]
    return block_id
