"""Template library panel — full-page card grid matching prototype design.

Replaces the narrow left-side TemplateListPanel for the library view.
The page header has a title + 新建模板 button; below sits a tabs/search/
tag toolbar; the body is an auto-fill card grid where each card paints
a tiny wireframe thumbnail of the template's structure.

Selection emits ``template_selected(Path)``; the page swaps to the editor.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog,
    QFrame, QLabel, QSizePolicy,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel,
    LineEdit, PushButton, PrimaryPushButton, FluentIcon,
    ScrollArea, MessageBox, MessageBoxBase, InfoBar, InfoBarPosition,
)

from csm_core.template.loader import list_templates, load_template, save_template
from csm_core.template.schema import Template, LiteralBlock


# ── Design tokens (mirroring theme.css) ──────────────────────────────────────
_INK     = QColor(30, 28, 25)
_INK_2   = QColor(30, 28, 25, int(255 * 0.62))
_INK_3   = QColor(30, 28, 25, int(255 * 0.38))
_INK_4   = QColor(30, 28, 25, int(255 * 0.18))
_INK_5   = QColor(30, 28, 25, int(255 * 0.08))
_ACCENT       = QColor(47, 111, 94)
_ACCENT_SOFT  = QColor(221, 233, 227)
_ACCENT_SOFTER= QColor(236, 242, 238)
_EXPORT       = QColor(201, 100, 66)
_EXPORT_SOFT  = QColor(244, 224, 213)
_WARN         = QColor(217, 159, 60)
_SURFACE      = QColor(255, 255, 255)


def _qss_color(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()/255:.3f})"


# ── Block → kind heuristic ───────────────────────────────────────────────────
def _kind_for_blocks(blocks: list) -> str:
    if not blocks:
        return "review"
    names = [type(b).__name__ for b in blocks]
    if "HeroBrandBlock" in names:
        return "grass"
    if "CompetitorPoolBlock" in names:
        return "review"
    if names.count("NumberedListBlock") >= 2:
        return "promo"
    if names.count("HeadingBlock") >= 2:
        return "news"
    if names.count("ParagraphBlock") >= 3:
        return "trained"
    return "analysis"


# ── Wireframe thumbnail ──────────────────────────────────────────────────────
class _TplThumb(QFrame):
    """Paints a small structural wireframe per ``kind``."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(110)
        self.setStyleSheet(
            f"background: #faf8f3; border: 1px solid {_qss_color(_INK_5)};"
            f"border-radius: 8px;"
        )

    # ---- helpers ---------------------------------------------------------
    def _bar(self, p: QPainter, x: int, y: int, w: int, h: int, color: QColor, r: int = 2) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(x, y, w, h, r, r)

    def paintEvent(self, ev):  # noqa: N802
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(12, 12, -12, -12)
        x0, y0, w0 = r.left(), r.top(), r.width()
        getattr(self, f"_paint_{self._kind}", self._paint_default)(p, x0, y0, w0, r)
        p.end()

    # ---- per-kind --------------------------------------------------------
    def _paint_default(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.78), 8, _INK)
        self._bar(p, x, y+14, int(w*0.44), 4, _INK_3)
        self._bar(p, x, y+24, int(w*0.96), 4, _INK_4)
        self._bar(p, x, y+34, int(w*0.88), 4, _INK_4)
        self._bar(p, x, y+44, int(w*0.72), 4, _INK_4)

    def _paint_review(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.78), 8, _INK)
        self._bar(p, x, y+14, int(w*0.44), 4, _INK_3)
        # data chips
        cy = y + 24
        cw = (w - 8) // 3
        self._bar(p, x, cy, cw, 8, _ACCENT_SOFT)
        self._bar(p, x+cw+4, cy, cw, 8, _EXPORT_SOFT)
        self._bar(p, x+(cw+4)*2, cy, cw, 8, _INK_5)
        self._bar(p, x, y+38, int(w*0.96), 4, _INK_4)
        self._bar(p, x, y+48, int(w*0.88), 4, _INK_4)
        # accent block
        self._bar(p, x, y+58, w, 18, _ACCENT_SOFTER, r=4)
        p.setBrush(QBrush(_ACCENT))
        p.drawRect(x, y+58, 2, 18)

    def _paint_news(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.88), 10, _INK)
        self._bar(p, x, y+16, int(w*0.44), 4, _INK_3)
        self._bar(p, x, y+26, w, 18, _ACCENT_SOFTER, r=4)
        p.setBrush(QBrush(_ACCENT)); p.drawRect(x, y+26, 2, 18)
        for i, frac in enumerate((0.96, 0.96, 0.88, 0.72)):
            self._bar(p, x, y+50+i*8, int(w*frac), 4, _INK_4)

    def _paint_grass(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.55), 8, _INK)
        self._bar(p, x, y+14, int(w*0.44), 4, _INK_3)
        # left small block + right two lines
        self._bar(p, x, y+24, 36, 30, _INK_5, r=4)
        self._bar(p, x+42, y+30, w-42, 4, _INK_4)
        self._bar(p, x+42, y+42, int((w-42)*0.88), 4, _INK_4)
        self._bar(p, x, y+60, int(w*0.88), 4, _INK_4)
        self._bar(p, x, y+70, int(w*0.72), 4, _INK_4)
        # CTA pill
        self._bar(p, x, y+80, int(w*0.40), 6, _EXPORT_SOFT, r=3)

    def _paint_video(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.30), 4, _INK_3)
        p.setFont(QFont("Consolas", 7))
        for i, t in enumerate(("00:00", "00:20", "00:45")):
            yy = y + 14 + i * 16
            p.setPen(_INK_3)
            p.drawText(QRect(x, yy, 30, 8), Qt.AlignmentFlag.AlignLeft, t)
            self._bar(p, x+34, yy+2, w-34, 4, _INK_4)
        self._bar(p, x, y+62, int(w*0.72), 6, _ACCENT_SOFTER, r=3)

    def _paint_timeline(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.60), 8, _INK)
        # vertical line
        p.setPen(QPen(_INK_4, 2))
        p.drawLine(x+6, y+22, x+6, y+86)
        widths = (0.80, 0.60, 0.70, 0.50)
        for i, frac in enumerate(widths):
            yy = y + 22 + i * 16
            color = _ACCENT if i == 0 else _INK_4
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(color))
            p.drawEllipse(x+2, yy, 8, 8)
            self._bar(p, x+18, yy+2, int(w*frac), 4, _INK_4)

    def _paint_promo(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.70), 8, _INK)
        self._bar(p, x, y+14, int(w*0.44), 4, _INK_3)
        for i in range(3):
            yy = y + 26 + i * 10
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(_ACCENT))
            p.drawEllipse(x, yy+1, 4, 4)
            self._bar(p, x+10, yy+1, int(w*0.88), 4, _INK_4)
        cw = (w - 4) // 2
        self._bar(p, x, y+62, cw, 8, _EXPORT_SOFT)
        self._bar(p, x+cw+4, y+62, cw, 8, _EXPORT_SOFT)

    def _paint_analysis(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.68), 8, _INK)
        self._bar(p, x, y+14, int(w*0.44), 4, _INK_3)
        # bar chart
        heights = [12, 24, 18, 28, 20, 14, 22]
        bw = (w - 6 * 4) // 7
        base = y + 76
        for i, h in enumerate(heights):
            color = _ACCENT if i == 3 else _INK_4
            self._bar(p, x + i * (bw + 4), base - h, bw, h, color, r=1)
        self._bar(p, x, y+84, int(w*0.88), 4, _INK_4)

    def _paint_trained(self, p, x, y, w, r):
        self._bar(p, x, y, int(w*0.50), 8, _INK)
        self._bar(p, x, y+14, int(w*0.44), 4, _INK_3)
        for i, frac in enumerate((0.96, 0.88, 0.72)):
            self._bar(p, x, y+24+i*10, int(w*frac), 4, _INK_4)
        # chips
        self._bar(p, x, y+62, 56, 12, _ACCENT_SOFTER, r=6)
        self._bar(p, x+62, y+62, 36, 12, _INK_5, r=6)
        p.setFont(QFont("", 7))
        p.setPen(_ACCENT); p.drawText(QRect(x+4, y+62, 56, 12), Qt.AlignmentFlag.AlignCenter, "样本")
        p.setPen(_INK_2);  p.drawText(QRect(x+62, y+62, 36, 12), Qt.AlignmentFlag.AlignCenter, "我的")


# ── Card ─────────────────────────────────────────────────────────────────────
_SPINE_COLORS = {
    "":       None,
    "accent": _ACCENT,
    "orange": _EXPORT,
    "warn":   _WARN,
    "ink":    _INK,
}


class _TplCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, name: str, desc: str, tag: str, blocks: int,
                 used: int, date: str, kind: str, spine: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("TplCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(258)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spine_color = _SPINE_COLORS.get(spine)
        self.setStyleSheet(
            f"#TplCard {{ background: #ffffff;"
            f" border: 1px solid {_qss_color(_INK_5)}; border-radius: 14px; }}"
            f"#TplCard:hover {{ border-color: {_qss_color(_INK_4)}; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 14)
        lay.setSpacing(10)

        lay.addWidget(_TplThumb(kind, self))

        title = QLabel(name, self)
        title.setStyleSheet(
            f"color: {_qss_color(_INK)}; font-size: 15px; font-weight: 600;"
            "letter-spacing: -0.2px; background: transparent;")
        title.setWordWrap(True)
        lay.addWidget(title)

        chip = QLabel(f"{tag} · {blocks} 块", self)
        chip.setStyleSheet(
            f"padding: 2px 8px; border-radius: 999px;"
            f"border: 1px solid {_qss_color(_INK_4)};"
            f"font-size: 11px; color: {_qss_color(_INK_2)};"
            "background: transparent;")
        chip.setMaximumWidth(160)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        chip_row = QHBoxLayout(); chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.addWidget(chip); chip_row.addStretch(1)
        lay.addLayout(chip_row)

        desc_lbl = QLabel(desc or " ", self)
        desc_lbl.setStyleSheet(
            f"color: {_qss_color(_INK_2)}; font-size: 12.5px;"
            "background: transparent;")
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl, 1)

        foot = QFrame(self)
        foot.setStyleSheet(
            f"QFrame {{ border: none; border-top: 1px dashed {_qss_color(_INK_5)}; }}")
        foot.setFixedHeight(24)
        foot_lay = QHBoxLayout(foot)
        foot_lay.setContentsMargins(0, 4, 0, 0); foot_lay.setSpacing(6)
        used_lbl = QLabel(f"已用 {used} 次", foot)
        used_lbl.setStyleSheet(
            f"color: {_qss_color(_INK_3)}; font-size: 11.5px; background: transparent; border: none;")
        date_lbl = QLabel(date, foot)
        date_lbl.setStyleSheet(used_lbl.styleSheet())
        foot_lay.addWidget(used_lbl); foot_lay.addStretch(1); foot_lay.addWidget(date_lbl)
        lay.addWidget(foot)

    def paintEvent(self, ev):  # noqa: N802
        super().paintEvent(ev)
        if self._spine_color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._spine_color))
        # Spine clipped to top-left and bottom-left rounded corners
        p.drawRoundedRect(0, 0, 4, self.height(), 2, 2)
        p.drawRect(2, 0, 2, self.height())
        p.end()

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class _NewTplCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NewTplCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(258)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            f"#NewTplCard {{ background: transparent;"
            f" border: 1.5px dashed {_qss_color(_INK_3)}; border-radius: 14px; }}"
            f"#NewTplCard:hover {{ border-color: {_qss_color(_ACCENT)};"
            f" background: {_qss_color(_ACCENT_SOFTER)}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(8)
        lay.addStretch(1)
        plus = QLabel("+", self)
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus.setStyleSheet(
            f"color: {_qss_color(_INK_2)}; font-size: 28px; font-weight: 300;"
            "background: transparent; border: none;")
        lay.addWidget(plus)
        title = QLabel("新建模板", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {_qss_color(_INK_2)}; font-size: 13px; font-weight: 500;"
            "background: transparent; border: none;")
        lay.addWidget(title)
        sub = QLabel("从 0 开始 · 或从现有文档生成", self)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(
            f"color: {_qss_color(_INK_3)}; font-size: 11.5px;"
            "background: transparent; border: none;")
        lay.addWidget(sub)
        lay.addStretch(1)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ── New-template dialog (kept compatible with the old call site) ─────────────
class _NewTemplateDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(420)
        self.viewLayout.addWidget(SubtitleLabel("新建模板", self))
        self.viewLayout.addWidget(BodyLabel("模板名称"))
        self.name_input = LineEdit(self)
        self.name_input.setPlaceholderText("如：导购文-场景人群型")
        self.viewLayout.addWidget(self.name_input)
        self.viewLayout.addWidget(BodyLabel("产品类别"))
        self.product_input = LineEdit(self)
        self.product_input.setPlaceholderText("如：吸尘器")
        self.viewLayout.addWidget(self.product_input)
        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")

    def validate(self) -> bool:
        for label, field in (("模板名称", self.name_input), ("产品类别", self.product_input)):
            if not field.text().strip():
                InfoBar.error("验证失败", f"{label} 不能为空",
                              parent=self, position=InfoBarPosition.TOP)
                return False
        return True


# ── Library panel ────────────────────────────────────────────────────────────
class TemplateLibraryPanel(QWidget):
    template_selected = pyqtSignal(Path)
    template_dir_changed = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TemplateLibraryPanel")
        self.setStyleSheet(
            "#TemplateLibraryPanel { background: transparent; }")

        self._dir: Path | None = None
        self._entries: list[tuple[str, Path, list, str]] = []  # name,path,blocks,product
        self._cards: list[QFrame] = []
        self._search: str = ""
        self._cols_cache: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(0)

        # ── Header row ────────────────────────────────────────────────────
        header = QHBoxLayout(); header.setSpacing(10)
        title = QLabel("模板库", self)
        title.setStyleSheet(
            f"color: {_qss_color(_INK)}; font-size: 26px; font-weight: 600;"
            "letter-spacing: -0.3px; background: transparent;")
        header.addWidget(title)
        header.addStretch(1)
        self._new_btn = PrimaryPushButton(FluentIcon.ADD, "新建模板", self)
        self._new_btn.clicked.connect(self._on_new)
        header.addWidget(self._new_btn)
        root.addLayout(header)

        self._sub = QLabel("—", self)
        self._sub.setStyleSheet(
            f"color: {_qss_color(_INK_2)}; font-size: 13.5px;"
            "background: transparent; margin-top: 4px;")
        root.addWidget(self._sub)

        # ── Toolbar (search + tag) ────────────────────────────────────────
        bar = QHBoxLayout(); bar.setSpacing(10); bar.setContentsMargins(0, 18, 0, 14)
        try:
            from qfluentwidgets import SearchLineEdit  # nicer glyph if available
            self._search_input = SearchLineEdit(self)
        except Exception:
            self._search_input = LineEdit(self)
        self._search_input.setPlaceholderText("搜模板名称 / 描述…")
        self._search_input.setFixedWidth(280)
        self._search_input.textChanged.connect(self._on_search_changed)
        bar.addStretch(1)
        bar.addWidget(self._search_input)
        self._tag_btn = PushButton(FluentIcon.TAG, "标签", self)
        self._tag_btn.setEnabled(False)
        bar.addWidget(self._tag_btn)
        root.addLayout(bar)

        # ── Grid ──────────────────────────────────────────────────────────
        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self._grid_host = QWidget(self._scroll)
        self._grid_host.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._scroll.setWidget(self._grid_host)
        root.addWidget(self._scroll, 1)

    # ── Public API ────────────────────────────────────────────────────────
    def set_directory(self, path: Path) -> None:
        self._dir = Path(path)
        self.refresh()
        self.template_dir_changed.emit(self._dir)

    def refresh(self) -> None:
        self._entries.clear()
        if self._dir is not None:
            for name, p in list_templates(self._dir):
                blocks: list = []
                product = ""
                try:
                    tpl = load_template(p)
                    blocks = list(tpl.blocks)
                    product = tpl.product or ""
                except Exception:
                    pass
                self._entries.append((name, p, blocks, product))
        if self._dir is None:
            self._sub.setText("未配置模板目录 · 请先在「设置 / 路径」中指定")
        else:
            self._sub.setText(f"{len(self._entries)} 个模板")
        self._rebuild_cards()

    def select_by_path(self, path: Path) -> None:
        # Library is stateless; selection just emits the signal so the
        # outer page swaps to the editor.
        return

    # ── Private ───────────────────────────────────────────────────────────
    def _pick_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择模板目录")
        if p:
            self.set_directory(Path(p))

    def _on_search_changed(self, text: str) -> None:
        self._search = text.strip().lower()
        self._rebuild_cards()

    def _filter(self) -> list[tuple[str, Path, list, str]]:
        if not self._search:
            return list(self._entries)
        q = self._search
        return [e for e in self._entries
                if q in e[0].lower() or q in (e[3] or "").lower()]

    def _columns_for_width(self, w: int) -> int:
        # Mirrors `repeat(auto-fill, minmax(280px, 1fr))` with 14px gaps.
        if w <= 0:
            return 1
        col = max(1, (w + 14) // (280 + 14))
        return col

    def _rebuild_cards(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        self._cards.clear()

        cols = max(1, self._columns_for_width(self._scroll.viewport().width()))
        self._cols_cache = cols

        new_card = _NewTplCard(self._grid_host)
        new_card.clicked.connect(self._on_new)
        self._grid.addWidget(new_card, 0, 0)
        self._cards.append(new_card)

        idx = 1
        for name, path, blocks, product in self._filter():
            kind = _kind_for_blocks(blocks)
            tag = product or "未分类"
            try:
                date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%m月%d日")
            except OSError:
                date = "—"
            desc = self._make_desc(blocks)
            card = _TplCard(
                name=name, desc=desc, tag=tag, blocks=len(blocks),
                used=0, date=date, kind=kind, spine=self._spine_for(kind),
                parent=self._grid_host,
            )
            card.clicked.connect(lambda p=path: self.template_selected.emit(p))
            self._grid.addWidget(card, idx // cols, idx % cols)
            self._cards.append(card)
            idx += 1
        self._grid.setRowStretch(self._grid.rowCount(), 1)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

    @staticmethod
    def _spine_for(kind: str) -> str:
        return {
            "grass": "orange", "promo": "orange",
            "video": "warn",
            "news": "ink", "analysis": "ink",
        }.get(kind, "")

    @staticmethod
    def _make_desc(blocks: list) -> str:
        if not blocks:
            return "空模板 · 待编辑"
        labels = {
            "HeadingBlock": "标题",
            "ParagraphBlock": "段落",
            "NumberedListBlock": "清单",
            "HeroBrandBlock": "主推",
            "CompetitorPoolBlock": "对比",
            "LiteralBlock": "文本",
        }
        parts = [labels.get(type(b).__name__, "块") for b in blocks[:6]]
        return f"{len(blocks)} 块：" + " · ".join(parts)

    # Re-flow grid on resize to match the design's auto-fill behavior.
    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        if not self._cards:
            return
        cols = max(1, self._columns_for_width(self._scroll.viewport().width()))
        if cols != self._cols_cache:
            self._rebuild_cards()

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        # On first show the scroll viewport hasn't been laid out yet, so the
        # initial _rebuild_cards ran with width≈0 → single column. Reflow once
        # the real geometry is known.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._reflow_if_needed)

    def _reflow_if_needed(self) -> None:
        if not self._cards:
            return
        cols = max(1, self._columns_for_width(self._scroll.viewport().width()))
        if cols != self._cols_cache:
            self._rebuild_cards()

    # ── New template (mirrors old TemplateListPanel behavior) ────────────
    def _on_new(self) -> None:
        if self._dir is None:
            InfoBar.warning(
                "未选择目录", "请先选择模板目录，再新建模板",
                parent=self.window(), position=InfoBarPosition.TOP, duration=4000,
            )
            return
        dlg = _NewTemplateDialog(self.window())
        if not dlg.exec():
            return
        tpl_name = dlg.name_input.text().strip()
        tpl_product = dlg.product_input.text().strip()

        import time
        tpl_id = f"template-{int(time.time())}"
        target = self._dir / f"{tpl_id}.json"
        suffix = 1
        while target.exists():
            target = self._dir / f"{tpl_id}-{suffix}.json"
            suffix += 1

        skeleton = Template(
            id=target.stem, name=tpl_name, product=tpl_product,
            blocks=[LiteralBlock(id="intro", text="引言")],
        )
        save_template(skeleton, target)
        self.refresh()
        self.template_selected.emit(target)
        InfoBar.success(
            "创建成功", f"模板「{tpl_name}」已创建",
            parent=self.window(), position=InfoBarPosition.TOP, duration=3000,
        )

    # Soft-delete kept here so the page can wire a delete button if it wants.
    def delete_template(self, path: Path) -> None:
        trash = path.parent / ".trash"
        trash.mkdir(exist_ok=True)
        dest = trash / path.name
        n = 1
        while dest.exists():
            dest = trash / f"{path.stem}-{n}{path.suffix}"; n += 1
        shutil.move(str(path), str(dest))
        self.refresh()
