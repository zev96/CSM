"""Skill directory picker + list + new/delete actions.

Mirrors TemplateListPanel's visual language: CardWidget rows, soft-delete
to <dir>/.trash/, InfoBar feedback. Skill files are plain .md; the panel
knows nothing about their contents.
"""
from __future__ import annotations
import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel,
    LineEdit, PrimaryPushButton, PushButton, FluentIcon,
    ListWidget, CardWidget, MessageBox, MessageBoxBase,
    InfoBar, InfoBarPosition,
)

from .skill_skeleton import SKILL_SKELETON


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
    skill_selected(Path): fired when the user clicks a .md file.
    skill_dir_changed(Path): fired when the scanned directory changes.
    """

    skill_selected = pyqtSignal(Path)
    skill_dir_changed = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir: Path | None = None
        self._paths: list[Path] = []

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
        list_lay.addWidget(BodyLabel("Skill 列表"))
        self.list_widget = ListWidget(list_card)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        list_lay.addWidget(self.list_widget, 1)
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
        self.list_widget.clear()
        self._paths = []
        self.delete_btn.setEnabled(False)
        if self._dir is None or not self._dir.is_dir():
            return
        for p in sorted(self._dir.glob("*.md")):
            self.list_widget.addItem(p.stem)
            self._paths.append(p)

    def current_path(self) -> Path | None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._paths):
            return self._paths[row]
        return None

    def _pick_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择 Skill 目录")
        if p:
            self.set_directory(Path(p))

    def _on_item_clicked(self) -> None:
        path = self.current_path()
        if path:
            self.delete_btn.setEnabled(True)
            self.skill_selected.emit(path)

    def _prompt_new_name(self) -> str | None:
        """Show new-skill dialog. Returns stem, or None on cancel. Override
        in tests via monkeypatch."""
        dlg = _NewSkillDialog(self.window())
        if not dlg.exec():
            return None
        return dlg.name_input.text().strip()

    def _on_new(self) -> None:
        if self._dir is None:
            InfoBar.warning("未选择目录", "请先选择 Skill 目录",
                            parent=self.window(), position=InfoBarPosition.TOP)
            return
        name = self._prompt_new_name()
        if not name:
            return
        target = self._dir / f"{name}.md"
        if target.exists():
            InfoBar.error("已存在", f"「{name}」已存在，请换个名字",
                          parent=self.window(), position=InfoBarPosition.TOP)
            return
        target.write_text(SKILL_SKELETON, encoding="utf-8")
        self.refresh()
        for i, p in enumerate(self._paths):
            if p == target:
                self.list_widget.setCurrentRow(i)
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
