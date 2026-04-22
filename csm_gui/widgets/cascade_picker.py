"""CascadePickerButton — hierarchical vault-directory selection widget.

Replaces flat ComboBox dropdowns with a cascading RoundMenu tree
organized by the vault's folder hierarchy. Only leaf directories
(those returned by _scan_vault_dirs after the leaf-only filter) appear
as selectable actions; intermediate folders become sub-menus.

Usage::

    picker = CascadePickerButton(vault_dirs, current_path, parent)
    picker.path_selected.connect(lambda p: ...)
    picker.set_path("some/relative/path")
    path = picker.get_path()
    picker.update_dirs(new_list)
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QSizePolicy, QPushButton

from qfluentwidgets import RoundMenu, Action, FluentIcon, isDarkTheme, qconfig


class CascadePickerButton(QPushButton):
    """A Fluent Design-style button that opens a cascading folder-tree menu.

    Inherits from plain ``QPushButton`` (NOT qfluentwidgets PushButton) to
    avoid the qfluentwidgets ``@overload`` mechanism that re-calls
    ``__init__(parent=parent)`` and breaks custom required arguments.

    Signals
    -------
    path_selected(str)
        Emitted whenever the user selects a directory path.
    """

    path_selected = pyqtSignal(str)

    _PLACEHOLDER = "选择数据库文件夹"

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self.setText(self._PLACEHOLDER)
        self._vault_dirs: list[str] = []
        self._current: str = ""

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(33)
        self.setIcon(FluentIcon.FOLDER.icon())
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        # Apply Fluent-style theme and track theme changes
        self._apply_fluent_style()
        try:
            qconfig.themeChanged.connect(self._apply_fluent_style)
        except Exception:
            pass  # older qfluentwidgets versions may differ

        self.clicked.connect(self._show_menu)

    def setup(self, vault_dirs: list[str], current: str = "") -> None:
        self._vault_dirs = vault_dirs
        if current:
            self.set_path(current)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_path(self, path: str) -> None:
        """Set the currently selected path (does NOT emit path_selected)."""
        self._current = path
        self._update_display()

    def get_path(self) -> str:
        """Return the currently selected path (empty string if none)."""
        return self._current

    def update_dirs(self, vault_dirs: list[str]) -> None:
        """Replace the vault directory list (e.g. after refresh)."""
        self._vault_dirs = vault_dirs

    # ── Styling ─────────────────────────────────────────────────────────────

    def _apply_fluent_style(self) -> None:
        """Apply a qfluentwidgets-ComboBox-compatible stylesheet."""
        if isDarkTheme():
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.06);
                    color: rgba(255, 255, 255, 0.90);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-bottom: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 5px;
                    padding: 4px 10px;
                    text-align: left;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.10);
                }
                QPushButton:pressed {
                    background-color: rgba(255, 255, 255, 0.04);
                    color: rgba(255, 255, 255, 0.63);
                    border-bottom-color: rgba(255, 255, 255, 0.08);
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.70);
                    color: rgba(0, 0, 0, 0.90);
                    border: 1px solid rgba(0, 0, 0, 0.073);
                    border-bottom: 1px solid rgba(0, 0, 0, 0.183);
                    border-radius: 5px;
                    padding: 4px 10px;
                    text-align: left;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: rgba(249, 249, 249, 0.80);
                }
                QPushButton:pressed {
                    background-color: rgba(249, 249, 249, 0.50);
                    color: rgba(0, 0, 0, 0.63);
                    border-bottom-color: rgba(0, 0, 0, 0.073);
                }
            """)

    # ── Private helpers ─────────────────────────────────────────────────────

    def _update_display(self) -> None:
        if self._current:
            parts = self._current.split("/")
            # Show last 2 segments for compactness; full path in tooltip
            display = " / ".join(parts[-2:]) if len(parts) > 1 else self._current
            self.setText(display)
            self.setToolTip(self._current)
        else:
            self.setText(self._PLACEHOLDER)
            self.setToolTip("")

    def _build_tree(self) -> dict:
        """Convert flat path list into nested dict tree.

        Each node is a ``dict``.  Leaf nodes (selectable dirs) carry a
        ``"__path__"`` key whose value is the full relative path string.
        """
        root: dict = {}
        for path in self._vault_dirs:
            node = root
            for part in path.split("/"):
                node = node.setdefault(part, {})
            node["__path__"] = path
        return root

    def _show_menu(self) -> None:
        tree = self._build_tree()
        if not tree:
            return
        menu = RoundMenu(parent=self.window())
        self._populate_menu(menu, tree)
        menu.exec(QCursor.pos())

    def _populate_menu(self, menu: RoundMenu, node: dict) -> None:
        """Recursively add actions / sub-menus from *node*."""
        for key in sorted(k for k in node if k != "__path__"):
            child = node[key]
            child_data_keys = {k for k in child if k != "__path__"}
            is_leaf = "__path__" in child

            if is_leaf and not child_data_keys:
                # Pure leaf → selectable Action
                path = child["__path__"]
                act = Action(FluentIcon.FOLDER, key)
                act.triggered.connect(
                    lambda _checked=False, p=path: self._select(p)
                )
                menu.addAction(act)
            else:
                # Intermediate or hybrid → sub-menu
                submenu = RoundMenu(key, parent=menu)
                if is_leaf:
                    # Hybrid: also selectable itself
                    path = child["__path__"]
                    self_act = Action(FluentIcon.ACCEPT, f"选择「{key}」")
                    self_act.triggered.connect(
                        lambda _checked=False, p=path: self._select(p)
                    )
                    submenu.addAction(self_act)
                    submenu.addSeparator()
                self._populate_menu(submenu, child)
                menu.addMenu(submenu)

    def _select(self, path: str) -> None:
        self._current = path
        self._update_display()
        self.path_selected.emit(path)
