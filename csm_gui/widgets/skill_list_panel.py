"""Skill directory picker + card list + new/delete actions.

Mirrors TemplateListPanel's visual language: CardWidget rows, soft-delete
to <dir>/.trash/, InfoBar feedback. Skill files are plain .md; the panel
reads each file's first non-frontmatter prose lines for the hover preview.

Cards expand on hover to show ~3 sample lines from the skill body so the
user can scan style without opening every file. The legacy ``list_widget``
attribute is preserved (hidden) so external callers that still poke at
``currentRow()`` keep working.
"""
from __future__ import annotations
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
    QFrame, QLabel, QScrollArea, QSizePolicy,
)
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel,
    LineEdit, PrimaryPushButton, PushButton, FluentIcon,
    ListWidget, CardWidget, MessageBox, MessageBoxBase,
    InfoBar, InfoBarPosition,
)

from .skill_skeleton import SKILL_SKELETON
from .skill_wizard import SkillWizard


def _read_skill_sample(path: Path, max_lines: int = 3) -> tuple[str, list[str]]:
    """Return (one_line_summary, sample_lines) from a skill .md file.

    Strips YAML frontmatter and Markdown heading prefixes; keeps the first
    few non-empty prose lines. Falls back gracefully if the file is missing
    or unreadable — the panel must never crash on a bad skill.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ("", [])
    lines = text.splitlines()
    # Skip leading YAML frontmatter (--- ... ---)
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines = lines[i + 1:]
                break
    cleaned: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        # Drop Markdown heading hashes for a cleaner preview.
        while s.startswith("#"):
            s = s[1:].lstrip()
        if not s:
            continue
        cleaned.append(s)
        if len(cleaned) >= max_lines:
            break
    summary = cleaned[0] if cleaned else ""
    return (summary, cleaned)


class _SkillCard(QFrame):
    """Hover-expanding skill card.

    Collapsed: name + 1-line preview (~64px tall).
    Hovered:   name + up to 3-line preview (~108px tall).
    Selection state paints a 1.5px ink-green border so users can see the
    active skill at a glance.
    """

    clicked = pyqtSignal(object)  # emits the wrapped Path

    _COLLAPSED = 64
    _EXPANDED = 112

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self._path = path
        self._selected = False
        self.setObjectName("SkillCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._COLLAPSED)
        self.setMaximumHeight(self._COLLAPSED)
        self._apply_style()

        summary, sample = _read_skill_sample(path)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        self.name_label = QLabel(path.stem, self)
        self.name_label.setStyleSheet(
            "color: #1e1c19; font-weight: 600; font-size: 13px; background: transparent;"
        )
        lay.addWidget(self.name_label)

        preview_text = "\n".join(sample) if sample else "（空 Skill — 点击编辑）"
        self.preview_label = QLabel(preview_text, self)
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet(
            "color: rgba(30,28,25,0.62); font-size: 12px; background: transparent;"
        )
        # Collapsed view shows only the first line.
        self.preview_label.setMaximumHeight(18)
        lay.addWidget(self.preview_label, 1)

        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._preview_anim = QPropertyAnimation(self.preview_label, b"maximumHeight", self)
        self._preview_anim.setDuration(140)
        self._preview_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self._apply_style()

    def path(self) -> Path:
        return self._path

    def _apply_style(self) -> None:
        border = "1.5px solid #2f6f5e" if self._selected else "1px solid rgba(30,28,25,0.08)"
        bg = "#faf8f3" if self._selected else "#ffffff"
        self.setStyleSheet(
            f"#SkillCard {{ background: {bg}; border: {border}; border-radius: 10px; }}"
            f"#SkillCard:hover {{ background: #faf8f3; }}"
        )

    def enterEvent(self, event: QEnterEvent) -> None:  # type: ignore[override]
        self._anim.stop()
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(self._EXPANDED)
        self._anim.start()
        self._preview_anim.stop()
        self._preview_anim.setStartValue(self.preview_label.maximumHeight())
        self._preview_anim.setEndValue(64)
        self._preview_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._anim.stop()
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(self._COLLAPSED)
        self._anim.start()
        self._preview_anim.stop()
        self._preview_anim.setStartValue(self.preview_label.maximumHeight())
        self._preview_anim.setEndValue(18)
        self._preview_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path)
        super().mousePressEvent(event)


class _NewSkillDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(400)
        self.viewLayout.addWidget(SubtitleLabel("新建 Skill", self))
        self.viewLayout.addWidget(BodyLabel("Skill 名称（将作为文件名）"))
        self.name_input = LineEdit(self)
        self.name_input.setPlaceholderText("如：xiaohongshu-polish")
        self.viewLayout.addWidget(self.name_input)
        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")

    def validate(self) -> bool:
        if not self.name_input.text().strip():
            InfoBar.error("验证失败", "名称不能为空",
                          parent=self, position=InfoBarPosition.TOP)
            return False
        return True


class SkillListPanel(QWidget):
    """Left-side list panel.

    Signals
    -------
    skill_selected(Path): fired when the user clicks a skill card.
    skill_dir_changed(Path): fired when the scanned directory changes.
    """

    skill_selected = pyqtSignal(Path)
    skill_dir_changed = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir: Path | None = None
        self._paths: list[Path] = []
        self._cards: list[_SkillCard] = []
        self._selected_idx: int = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        dir_card = CardWidget(self)
        dir_lay = QVBoxLayout(dir_card)
        dir_lay.setContentsMargins(16, 12, 16, 12)
        dir_lay.setSpacing(6)
        dir_lay.addWidget(StrongBodyLabel("Skill 目录"))
        row = QHBoxLayout()
        self.dir_input = LineEdit(dir_card)
        self.dir_input.setPlaceholderText("选择 Skill 目录 …")
        self.dir_input.setReadOnly(True)
        row.addWidget(self.dir_input, 1)
        self.browse_btn = PushButton("浏览", dir_card, FluentIcon.FOLDER)
        self.browse_btn.clicked.connect(self._pick_dir)
        row.addWidget(self.browse_btn)
        dir_lay.addLayout(row)
        root.addWidget(dir_card)

        list_card = CardWidget(self)
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(12, 8, 12, 8)
        list_lay.setSpacing(6)

        self._scroll = QScrollArea(list_card)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_host = QWidget()
        self._cards_lay = QVBoxLayout(self._scroll_host)
        self._cards_lay.setContentsMargins(2, 2, 2, 2)
        self._cards_lay.setSpacing(8)
        self._cards_lay.addStretch(1)
        self._scroll.setWidget(self._scroll_host)
        list_lay.addWidget(self._scroll, 1)

        # Hidden compat shim — older callers may still call list_widget.currentItem()
        # or .currentRow(). We keep it in sync with card selection but never show it.
        self.list_widget = ListWidget(list_card)
        self.list_widget.hide()
        list_lay.addWidget(self.list_widget)

        root.addWidget(list_card, 1)

        btn_card = CardWidget(self)
        btn_lay = QHBoxLayout(btn_card)
        btn_lay.setContentsMargins(12, 8, 12, 8)
        btn_lay.setSpacing(8)
        self.new_btn = PrimaryPushButton(FluentIcon.ADD, "新建 Skill", btn_card)
        self.new_btn.clicked.connect(self._on_new)
        btn_lay.addWidget(self.new_btn)
        self.delete_btn = PushButton(FluentIcon.DELETE, "删除", btn_card)
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.setEnabled(False)
        btn_lay.addWidget(self.delete_btn)
        root.addWidget(btn_card)

    def set_directory(self, path: Path) -> None:
        self._dir = Path(path)
        self.dir_input.setText(str(self._dir))
        self.refresh()
        self.skill_dir_changed.emit(self._dir)

    def refresh(self) -> None:
        # Tear down existing cards.
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards = []
        self._paths = []
        self._selected_idx = -1
        self.list_widget.clear()
        self.delete_btn.setEnabled(False)

        if self._dir is None or not self._dir.is_dir():
            return

        for p in sorted(self._dir.glob("*.md")):
            self._paths.append(p)
            self.list_widget.addItem(p.stem)
            card = _SkillCard(p, self._scroll_host)
            card.clicked.connect(self._on_card_clicked)
            # Insert before the trailing stretch.
            self._cards_lay.insertWidget(self._cards_lay.count() - 1, card)
            self._cards.append(card)

    def current_path(self) -> Path | None:
        if 0 <= self._selected_idx < len(self._paths):
            return self._paths[self._selected_idx]
        # Fallback to list widget for legacy callers that mutated it.
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._paths):
            return self._paths[row]
        return None

    def select_by_path(self, path: Path) -> None:
        for i, p in enumerate(self._paths):
            if p == path:
                self._highlight(i)
                return

    def _highlight(self, idx: int) -> None:
        if not (0 <= idx < len(self._cards)):
            return
        if self._selected_idx >= 0 and self._selected_idx < len(self._cards):
            self._cards[self._selected_idx].set_selected(False)
        self._selected_idx = idx
        self._cards[idx].set_selected(True)
        self.list_widget.setCurrentRow(idx)
        self.delete_btn.setEnabled(True)

    def _on_card_clicked(self, path: Path) -> None:
        for i, p in enumerate(self._paths):
            if p == path:
                self._highlight(i)
                self.skill_selected.emit(path)
                return

    def _on_item_clicked(self) -> None:
        """Legacy compat — drive the selection flow from ``list_widget``.

        Older callers (and tests) interact with the hidden ListWidget via
        ``setCurrentRow`` then expect us to fire ``skill_selected``. The
        card-based UI renders into the gallery; this shim keeps the
        ListWidget-driven path working.
        """
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._paths):
            self._on_card_clicked(self._paths[row])

    def _pick_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择 Skill 目录")
        if p:
            self.set_directory(Path(p))

    def _prompt_new_name(self) -> str | None:
        """Legacy single-name prompt. Kept so existing tests that monkeypatch
        this method still drive the create flow; the production path now
        uses the multi-step wizard via ``_prompt_new_skill``."""
        dlg = _NewSkillDialog(self.window())
        if not dlg.exec():
            return None
        return dlg.name_input.text().strip()

    def _prompt_new_skill(self) -> tuple[str, str] | None:
        """Show the wizard and return (name, body) or None on cancel."""
        dlg = SkillWizard(self.window())
        if not dlg.exec():
            return None
        return (dlg.result_name(), dlg.result_body())

    def _on_new(self) -> None:
        if self._dir is None:
            InfoBar.warning("未选择目录", "请先选择 Skill 目录",
                            parent=self.window(), position=InfoBarPosition.TOP)
            return
        result = self._prompt_new_skill()
        if not result:
            return
        name, body = result
        if not name:
            return
        target = self._dir / f"{name}.md"
        if target.exists():
            InfoBar.error("已存在", f"「{name}」已存在，请换个名字",
                          parent=self.window(), position=InfoBarPosition.TOP)
            return
        target.write_text(body or SKILL_SKELETON, encoding="utf-8")
        self.refresh()
        for i, p in enumerate(self._paths):
            if p == target:
                self._highlight(i)
                self.skill_selected.emit(p)
                break
        InfoBar.success("已创建", f"「{name}.md」",
                        parent=self.window(), position=InfoBarPosition.TOP)

    def _confirm_delete(self, name: str) -> bool:
        dlg = MessageBox(
            "删除 Skill",
            f"确认删除「{name}」？\n删除后文件将移入 .trash/ 目录。",
            self.window(),
        )
        dlg.yesButton.setText("删除")
        dlg.cancelButton.setText("取消")
        return bool(dlg.exec())

    def _on_delete(self) -> None:
        path = self.current_path()
        if path is None:
            return
        if not self._confirm_delete(path.stem):
            return
        trash = path.parent / ".trash"
        trash.mkdir(exist_ok=True)
        dest = trash / path.name
        n = 1
        while dest.exists():
            dest = trash / f"{path.stem}-{n}{path.suffix}"
            n += 1
        shutil.move(str(path), str(dest))
        self.refresh()
        InfoBar.success("已删除", f"「{path.stem}」已移入 .trash/",
                        parent=self.window(), position=InfoBarPosition.TOP)
