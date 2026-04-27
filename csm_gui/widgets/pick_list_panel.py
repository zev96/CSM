"""Left-panel widget: sampled picks with per-pick reroll.

Mirrors the ``workspace.jsx`` left rail:

* **Collapsed** — narrow strip with a pin-right toggle, vertical "初稿" label,
  column of dots (one accent heading dot + two regular dots per pick).
* **Expanded** — wider card list with eyebrow "初稿 · N 条卡片", pin-left
  toggle, each pick as a clickable card with a reroll button.

Public API preserved for ``article_page`` / ``main_window`` wiring:

* ``reroll_requested(block_id: str, pick_index: int)`` signal
* ``load_plan(plan, template=None)``
* ``set_busy(busy)``
* ``row_count()``, ``iter_buttons()``, ``click_row(index)``
"""
from __future__ import annotations
from typing import Iterator
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy, QWidget, QLabel,
    QStackedWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ToolButton, FluentIcon,
    SingleDirectionScrollArea,
)
from csm_core.assembler.plan import AssemblyPlan, BlockResult


# ── Design tokens (shared with workspace_side_panel) ────────────────────────
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT        = "#2f6f5e"
_ACCENT_SOFTER = "#ecf2ee"


_PREVIEW_MAX = 40


def _preview(text: str) -> str:
    t = text.strip().replace("\n", " ")
    if len(t) <= _PREVIEW_MAX:
        return t
    return t[:_PREVIEW_MAX] + "…"


def _flatten_picks(results: list[BlockResult]) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for r in results:
        for i, p in enumerate(r.picks):
            rows.append((r.block_id, i, _preview(p.text)))
        if r.children:
            rows.extend(_flatten_picks(r.children))
    return rows


def _build_label_map(template) -> dict[str, str]:
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


def _fallback_label(block_id: str, label_map: dict[str, str]) -> str:
    cur = block_id
    while "_" in cur:
        cur = cur.rsplit("_", 1)[0]
        if cur in label_map:
            return label_map[cur]
    return block_id


# ── Pick card (expanded mode) ───────────────────────────────────────────────
class _PickRow(QFrame):
    def __init__(self, block_id: str, pick_index: int, preview: str,
                 display_label: str, parent=None):
        super().__init__(parent)
        self.block_id = block_id
        self.pick_index = pick_index
        self.setObjectName("pickRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "#pickRow { background: #ffffff;"
            f" border: 1px solid {_INK_5}; border-radius: 10px; }}"
            "#pickRow:hover { border-color: rgba(30,28,25,0.18); }"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(8)

        label_col = QVBoxLayout()
        label_col.setSpacing(3)
        label_col.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(f"{display_label}[{pick_index}]", self)
        self.title.setStyleSheet(
            f"color: {_INK_3}; font-size: 10.5px; letter-spacing: 0.4px;"
            "background: transparent;")
        self.body = QLabel(preview, self)
        self.body.setWordWrap(True)
        self.body.setStyleSheet(
            f"color: {_INK}; font-size: 12.5px; background: transparent;")
        label_col.addWidget(self.title)
        label_col.addWidget(self.body)
        lay.addLayout(label_col, 1)

        self.button = ToolButton(FluentIcon.SYNC, self)
        self.button.setToolTip("换一版")
        self.button.setFixedSize(24, 24)
        self.button.setIconSize(QSize(12, 12))
        self.button.setStyleSheet(
            "ToolButton { background: transparent; border-radius: 6px;"
            f" border: 1px solid {_INK_5}; }}"
            f"ToolButton:hover {{ background: {_ACCENT_SOFTER};"
            f" border-color: {_ACCENT}; }}"
        )
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)


# ── Dot column (collapsed mode) ─────────────────────────────────────────────
class _RailDot(QFrame):
    def __init__(self, heading: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(10 if heading else 6, 10 if heading else 6)
        self.setStyleSheet(
            f"background: {_ACCENT if heading else _INK_3};"
            " border-radius: 3px;" if not heading else "border-radius: 5px;"
        )


class PickListPanel(QFrame):
    """Left rail: collapsed dots vs expanded cards.

    Default is **collapsed** — matches the prototype's first-glance feel of a
    slim strip, with the big canvas reserved for the draft itself.
    """

    reroll_requested = pyqtSignal(str, int)  # (block_id, pick_index)

    _COLLAPSED_WIDTH = 48
    _EXPANDED_WIDTH  = 288

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PickListPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#PickListPanel {{ background: #ffffff;"
            f" border: 1px solid {_INK_5}; border-radius: 12px; }}"
        )

        self._collapsed = True
        self._rows: list[_PickRow] = []
        self._label_map: dict[str, str] = {}
        self._pick_count: int = 0

        self._stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._build_collapsed()
        self._build_expanded()

        self._apply_mode()

    # ── Collapsed mode ──────────────────────────────────────────────────
    def _build_collapsed(self) -> None:
        page = QWidget(self._stack)
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 12, 10, 12)
        lay.setSpacing(8)

        self._collapsed_toggle = ToolButton(FluentIcon.MENU, page)
        self._collapsed_toggle.setFixedSize(28, 28)
        self._collapsed_toggle.setToolTip("展开初稿卡片")
        self._collapsed_toggle.setStyleSheet(
            "ToolButton { background: transparent; border: none;"
            f" color: {_INK_2}; }} ToolButton:hover {{ background: {_ACCENT_SOFTER}; border-radius: 6px; }}"
        )
        self._collapsed_toggle.clicked.connect(lambda: self.set_collapsed(False))
        lay.addWidget(self._collapsed_toggle, 0, Qt.AlignmentFlag.AlignHCenter)

        self._collapsed_label = QLabel("初\n稿", page)
        self._collapsed_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._collapsed_label.setStyleSheet(
            f"color: {_INK_3}; font-size: 10.5px; letter-spacing: 2px;"
            "background: transparent;"
        )
        lay.addWidget(self._collapsed_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._dot_host = QWidget(page)
        self._dot_host.setStyleSheet("background: transparent;")
        self._dot_lay = QVBoxLayout(self._dot_host)
        self._dot_lay.setContentsMargins(0, 6, 0, 0)
        self._dot_lay.setSpacing(6)
        self._dot_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._dot_host, 0, Qt.AlignmentFlag.AlignHCenter)

        lay.addStretch(1)
        self._stack.addWidget(page)

    # ── Expanded mode ───────────────────────────────────────────────────
    def _build_expanded(self) -> None:
        page = QWidget(self._stack)
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # Header row
        head = QHBoxLayout(); head.setContentsMargins(4, 0, 0, 4); head.setSpacing(8)
        self._expanded_eyebrow = QLabel("初稿 · 0 条卡片", page)
        self._expanded_eyebrow.setStyleSheet(
            f"color: {_INK_3}; font-size: 11px; font-weight: 600;"
            "letter-spacing: 0.6px; background: transparent;"
        )
        head.addWidget(self._expanded_eyebrow)
        head.addStretch(1)
        self._expanded_toggle = ToolButton(FluentIcon.LEFT_ARROW, page)
        self._expanded_toggle.setFixedSize(24, 24)
        self._expanded_toggle.setIconSize(QSize(12, 12))
        self._expanded_toggle.setToolTip("收起")
        self._expanded_toggle.setStyleSheet(
            "ToolButton { background: transparent; border: none;"
            f" color: {_INK_2}; }} ToolButton:hover {{ background: {_ACCENT_SOFTER}; border-radius: 6px; }}"
        )
        self._expanded_toggle.clicked.connect(lambda: self.set_collapsed(True))
        head.addWidget(self._expanded_toggle)
        lay.addLayout(head)

        self._scroll = SingleDirectionScrollArea(page)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "SingleDirectionScrollArea, QScrollArea { background: transparent; border: none; }"
        )
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._container = QWidget(self._scroll)
        self._container.setStyleSheet("background: transparent;")
        self._container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum,
        )
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 4, 0)
        self._container_layout.setSpacing(6)
        self._container_layout.addStretch(1)
        self._scroll.setWidget(self._container)
        lay.addWidget(self._scroll, 1)

        self._stack.addWidget(page)

    # ── Mode switching ──────────────────────────────────────────────────
    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._apply_mode()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _apply_mode(self) -> None:
        if self._collapsed:
            self._stack.setCurrentIndex(0)
            self.setFixedWidth(self._COLLAPSED_WIDTH)
        else:
            self._stack.setCurrentIndex(1)
            # Let the splitter govern width — don't pin it.
            self.setMinimumWidth(self._EXPANDED_WIDTH)
            self.setMaximumWidth(16777215)

    # ── Data loading ────────────────────────────────────────────────────
    def load_plan(self, plan: AssemblyPlan, template=None) -> None:
        self._label_map = _build_label_map(template)
        picks = _flatten_picks(plan.results)
        self._pick_count = len(picks)

        # Rebuild expanded cards
        for row in self._rows:
            self._container_layout.removeWidget(row)
            row.setParent(None); row.deleteLater()
        self._rows.clear()

        for block_id, pick_index, preview in picks:
            label = self._label_map.get(block_id) or _fallback_label(
                block_id, self._label_map,
            )
            row = _PickRow(block_id, pick_index, preview, label, self._container)
            row.button.clicked.connect(
                lambda _=False, b=block_id, i=pick_index:
                self.reroll_requested.emit(b, i)
            )
            count = self._container_layout.count()
            self._container_layout.insertWidget(count - 1, row)
            self._rows.append(row)

        self._expanded_eyebrow.setText(f"初稿 · {self._pick_count} 条卡片")

        # Rebuild collapsed dots — one heading dot + the picks for that block.
        while self._dot_lay.count():
            it = self._dot_lay.takeAt(0)
            if (w := it.widget()):
                w.setParent(None); w.deleteLater()
        for r in plan.results:
            self._dot_lay.addWidget(_RailDot(True, self._dot_host))
            for _ in r.picks:
                self._dot_lay.addWidget(_RailDot(False, self._dot_host))

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
