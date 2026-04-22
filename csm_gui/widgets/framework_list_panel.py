"""Left panel of the Framework tab — directory-bound list of frameworks."""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QHBoxLayout
from qfluentwidgets import BodyLabel, ToolButton, FluentIcon as FIF

from csm_core.framework.loader import list_frameworks


class FrameworkListPanel(QWidget):
    framework_selected = pyqtSignal(Path)
    new_requested = pyqtSignal()
    delete_requested = pyqtSignal(Path)

    def __init__(self, parent=None, directory: Path | None = None):
        super().__init__(parent)
        self._dir: Path = directory or Path("frameworks")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        header.addWidget(BodyLabel("框架"))
        header.addStretch(1)
        self.new_btn = ToolButton(FIF.ADD, self)
        self.new_btn.setToolTip("新建框架")
        self.new_btn.clicked.connect(self.new_requested.emit)
        header.addWidget(self.new_btn)
        self.delete_btn = ToolButton(FIF.DELETE, self)
        self.delete_btn.setToolTip("删除当前框架")
        self.delete_btn.clicked.connect(self._emit_delete)
        header.addWidget(self.delete_btn)
        root.addLayout(header)

        self.list = QListWidget(self)
        self.list.itemClicked.connect(self._emit_selected)
        root.addWidget(self.list)

        self.refresh()

    def set_directory(self, d: Path) -> None:
        self._dir = Path(d)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for name, path in list_frameworks(self._dir):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list.addItem(item)

    def select_by_path(self, path: Path) -> None:
        target = str(path)
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == target:
                self.list.setCurrentItem(it)
                return

    def current_path(self) -> Path | None:
        it = self.list.currentItem()
        if not it:
            return None
        return Path(it.data(Qt.ItemDataRole.UserRole))

    def _emit_selected(self, item: QListWidgetItem) -> None:
        self.framework_selected.emit(Path(item.data(Qt.ItemDataRole.UserRole)))

    def _emit_delete(self) -> None:
        p = self.current_path()
        if p is not None:
            self.delete_requested.emit(p)
