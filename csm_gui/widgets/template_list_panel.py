"""Left-side template list panel — directory picker + template list + new/delete.

Matches the existing project layout conventions:
- outer QWidget with transparent background
- CardWidget for each logical section
- StrongBodyLabel for card titles, BodyLabel for labels
- PrimaryPushButton(icon, text, parent) for primary actions
- Soft-delete: files moved to  <dir>/.trash/  instead of os.remove
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
    QGridLayout, QFrame, QLabel, QSizePolicy,
)
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel,
    LineEdit, PrimaryPushButton, PushButton, FluentIcon,
    ListWidget, CardWidget, MessageBoxBase, MessageBox,
    InfoBar, InfoBarPosition, ScrollArea,
)

from csm_core.template.loader import list_templates, load_template, save_template
from csm_core.template.schema import Template, LiteralBlock


# ---------------------------------------------------------------------------
# Block-type thumbnail — paints a small visual representation of a template
# based on its block sequence so users can scan the grid by structure rather
# than by name alone.
# ---------------------------------------------------------------------------

# Maps block class-names to a (height-px, color, label) triple. Heights stack
# vertically inside the thumbnail; colors come from the palette.
_BLOCK_VIZ = {
    "HeadingBlock":        (8,  "#2f6f5e", "H"),
    "ParagraphBlock":      (16, "#dde9e3", "¶"),
    "NumberedListBlock":   (22, "#ecf2ee", "≡"),
    "HeroBrandBlock":      (24, "#c96442", "★"),
    "CompetitorPoolBlock": (20, "#f4e0d5", "▦"),
    "LiteralBlock":        (12, "#faf8f3", "•"),
}


class _ThumbCanvas(QFrame):
    """Custom-painted thumbnail showing the template's block sequence."""

    def __init__(self, blocks: list, parent=None):
        super().__init__(parent)
        self._blocks = blocks or []
        self.setFixedHeight(96)
        self.setStyleSheet(
            "border-radius: 8px; background-color: #faf8f3;"
            "border: 1px solid rgba(30,28,25,0.06);"
        )

    def paintEvent(self, ev):  # noqa: N802
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        if not self._blocks:
            p.setPen(QColor(30, 28, 25, 80))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "（空模板）")
            return
        y = rect.top()
        for blk in self._blocks[:5]:
            cls = type(blk).__name__
            h, color, _ = _BLOCK_VIZ.get(cls, (10, "#dde9e3", "·"))
            if y + h > rect.bottom():
                break
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(color)))
            p.drawRoundedRect(rect.left(), y, rect.width(), h, 3, 3)
            y += h + 4


class _TplCard(QFrame):
    """Single template card: thumbnail + name + product chip."""

    clicked = pyqtSignal()

    def __init__(self, name: str, product: str, blocks: list, selected: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("tplCard")
        self.setProperty("selected", selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(184)
        self.setMinimumWidth(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(self._qss(selected))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        lay.addWidget(_ThumbCanvas(blocks, self))

        title = QLabel(name, self)
        title.setStyleSheet(
            "font-size: 12.5px; font-weight: 600; color: #1e1c19; background: transparent;")
        title.setWordWrap(False)
        lay.addWidget(title)

        meta_row = QHBoxLayout()
        chip = QLabel(product or "—", self)
        chip.setStyleSheet(
            "padding: 1px 6px; border-radius: 5px; font-size: 10.5px;"
            "background: rgba(30,28,25,0.06); color: rgba(30,28,25,0.62);")
        meta_row.addWidget(chip)
        meta_row.addStretch(1)
        count = QLabel(f"{len(blocks)} 模块", self)
        count.setStyleSheet("font-size: 10.5px; color: rgba(30,28,25,0.38);")
        meta_row.addWidget(count)
        lay.addLayout(meta_row)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.setStyleSheet(self._qss(selected))

    @staticmethod
    def _qss(selected: bool) -> str:
        if selected:
            return ("#tplCard { background: #ffffff; border: 1.5px solid #2f6f5e;"
                    " border-radius: 12px; }")
        return ("#tplCard { background: #ffffff; border: 1px solid rgba(30,28,25,0.08);"
                " border-radius: 12px; }"
                "#tplCard:hover { border: 1px solid rgba(47,111,94,0.45); background: #faf8f3; }")

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ---------------------------------------------------------------------------
# Internal dialog: create a new template skeleton
# ---------------------------------------------------------------------------

class _NewTemplateDialog(MessageBoxBase):
    """Two-field dialog (name + product). Template id is auto-generated by
    the caller using a unix timestamp."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(400)
        self.titleLabel = SubtitleLabel("新建模板", self)
        self.viewLayout.addWidget(self.titleLabel)

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
        for name, field in [
            ("模板名称", self.name_input),
            ("产品类别", self.product_input),
        ]:
            if not field.text().strip():
                InfoBar.error(
                    "验证失败", f"{name} 不能为空",
                    parent=self, position=InfoBarPosition.TOP,
                )
                return False
        return True


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class TemplateListPanel(QWidget):
    """Left-side panel: directory selector + template list + new/delete buttons.

    Signals
    -------
    template_selected(Path):
        Emitted when the user clicks a template in the list.
    template_dir_changed(Path):
        Emitted when the scanned directory changes.
    """

    template_selected = pyqtSignal(Path)
    template_dir_changed = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir: Path | None = None
        # maps list-row → Path
        self._paths: list[Path] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 目录选择卡片 ──────────────────────────────────────────────────
        dir_card = CardWidget(self)
        dir_lay = QVBoxLayout(dir_card)
        dir_lay.setContentsMargins(16, 12, 16, 12)
        dir_lay.setSpacing(6)
        dir_lay.addWidget(StrongBodyLabel("模板目录"))
        dir_row = QHBoxLayout()
        self.dir_input = LineEdit(dir_card)
        self.dir_input.setPlaceholderText("选择模板目录 …")
        self.dir_input.setReadOnly(True)
        dir_row.addWidget(self.dir_input, 1)
        self.browse_btn = PushButton("浏览", dir_card, FluentIcon.FOLDER)
        self.browse_btn.clicked.connect(self._pick_dir)
        dir_row.addWidget(self.browse_btn)
        dir_lay.addLayout(dir_row)
        root.addWidget(dir_card)

        # ── 模板卡片网格 ──────────────────────────────────────────────────
        list_card = CardWidget(self)
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(12, 10, 12, 10)
        list_lay.setSpacing(8)
        list_lay.addWidget(BodyLabel("模板列表"))

        self._scroll = ScrollArea(list_card)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("ScrollArea { background: transparent; border: none; }")
        self._grid_host = QWidget(self._scroll)
        self._grid_host.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)
        self._scroll.setWidget(self._grid_host)
        list_lay.addWidget(self._scroll, 1)

        # Hidden ListWidget kept for backward compatibility — some callers
        # still reach into self.list_widget for currentItem(). It mirrors
        # the cards but is never shown.
        self.list_widget = ListWidget(self)
        self.list_widget.hide()

        self._cards: list[_TplCard] = []
        self._selected_idx: int = -1
        root.addWidget(list_card, 1)

        # ── 操作按钮 ──────────────────────────────────────────────────────
        btn_card = CardWidget(self)
        btn_lay = QHBoxLayout(btn_card)
        btn_lay.setContentsMargins(12, 8, 12, 8)
        btn_lay.setSpacing(8)
        self.new_btn = PrimaryPushButton(FluentIcon.ADD, "新建模板", btn_card)
        self.new_btn.clicked.connect(self._on_new)
        btn_lay.addWidget(self.new_btn)
        self.delete_btn = PushButton(FluentIcon.DELETE, "删除模板", btn_card)
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.setEnabled(False)
        btn_lay.addWidget(self.delete_btn)
        root.addWidget(btn_card)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_directory(self, path: Path) -> None:
        """Set the templates directory and scan it."""
        self._dir = Path(path)
        self.dir_input.setText(str(self._dir))
        self.refresh()
        self.template_dir_changed.emit(self._dir)

    def refresh(self) -> None:
        """Re-scan the current directory and rebuild the card grid."""
        # Wipe both representations.
        self.list_widget.clear()
        for card in self._cards:
            card.setParent(None)
        self._cards.clear()
        self._paths = []
        self._selected_idx = -1
        self.delete_btn.setEnabled(False)
        # Drop any stretch leftover from a previous fill.
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        if self._dir is None:
            return
        cols = 2
        for i, (name, p) in enumerate(list_templates(self._dir)):
            self.list_widget.addItem(name)
            self._paths.append(p)
            blocks: list = []
            product = ""
            try:
                tpl = load_template(p)
                blocks = list(tpl.blocks)
                product = tpl.product or ""
            except Exception:
                # Corrupt / unreadable template — render an empty placeholder
                # rather than failing the whole grid refresh.
                pass
            card = _TplCard(name, product, blocks, parent=self._grid_host)
            card.clicked.connect(lambda idx=i: self._on_card_clicked(idx))
            self._grid.addWidget(card, i // cols, i % cols)
            self._cards.append(card)
        # Push everything to the top.
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    def select_by_path(self, path: Path) -> None:
        """Programmatically select the row matching *path*."""
        try:
            idx = self._paths.index(path)
        except ValueError:
            return
        self._highlight(idx)
        self.list_widget.setCurrentRow(idx)
        self.delete_btn.setEnabled(True)

    def current_path(self) -> Path | None:
        """Return the path of the currently selected template, or None."""
        if 0 <= self._selected_idx < len(self._paths):
            return self._paths[self._selected_idx]
        return None

    def _highlight(self, idx: int) -> None:
        for i, c in enumerate(self._cards):
            c.set_selected(i == idx)
        self._selected_idx = idx

    def _on_card_clicked(self, idx: int) -> None:
        self._highlight(idx)
        self.list_widget.setCurrentRow(idx)
        self.delete_btn.setEnabled(True)
        self.template_selected.emit(self._paths[idx])

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _pick_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择模板目录")
        if p:
            self.set_directory(Path(p))

    def _on_item_clicked(self) -> None:
        path = self.current_path()
        if path:
            self.delete_btn.setEnabled(True)
            self.template_selected.emit(path)

    def _on_new(self) -> None:
        if self._dir is None:
            InfoBar.warning(
                "未选择目录", "请先选择模板目录，再新建模板",
                parent=self.window(), position=InfoBarPosition.TOP, duration=4000,
            )
            return

        # parent = window so the dialog centers on the main window instead
        # of this narrow left-side panel (which used to obscure the editor).
        dlg = _NewTemplateDialog(self.window())
        if not dlg.exec():
            return

        tpl_name = dlg.name_input.text().strip()
        tpl_product = dlg.product_input.text().strip()

        # Auto-generated id: template-<epoch>. Collision is effectively
        # impossible within one second; retain the -N suffix fallback as
        # a belt-and-braces guard.
        import time
        tpl_id = f"template-{int(time.time())}"
        target = self._dir / f"{tpl_id}.json"
        suffix = 1
        while target.exists():
            target = self._dir / f"{tpl_id}-{suffix}.json"
            suffix += 1
        actual_id = target.stem

        skeleton = Template(
            id=actual_id,
            name=tpl_name,
            product=tpl_product,
            blocks=[LiteralBlock(id="intro", text="引言")],
        )
        save_template(skeleton, target)

        self.refresh()
        self.select_by_path(target)
        self.template_selected.emit(target)
        InfoBar.success(
            "创建成功", f"模板「{tpl_name}」已创建",
            parent=self.window(), position=InfoBarPosition.TOP, duration=3000,
        )

    def _on_delete(self) -> None:
        path = self.current_path()
        if path is None:
            return
        name = self.list_widget.currentItem().text() if self.list_widget.currentItem() else path.name

        dlg = MessageBox(
            "删除模板",
            f"确认删除「{name}」？\n删除后文件将移入 .trash/ 目录，可手动恢复。",
            self,
        )
        dlg.yesButton.setText("删除")
        dlg.cancelButton.setText("取消")
        if not dlg.exec():
            return

        trash = path.parent / ".trash"
        trash.mkdir(exist_ok=True)
        dest = trash / path.name
        # handle name collision in trash
        n = 1
        while dest.exists():
            dest = trash / f"{path.stem}-{n}{path.suffix}"
            n += 1
        shutil.move(str(path), str(dest))

        self.refresh()
        InfoBar.success(
            "模板已删除", f"「{name}」已移入 .trash/",
            parent=self.window(), position=InfoBarPosition.TOP, duration=3000,
        )
