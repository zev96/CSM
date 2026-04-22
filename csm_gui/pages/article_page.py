"""Article workspace — L-shape layout.

Left: slot list (full height).
Right-top: markdown preview (large).
Right-bottom: action bar (compact) — polish-skill + 重新随机/润色/导出 buttons.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from ..widgets.slot_list import SlotList
from ..widgets.markdown_view import MarkdownView
from ..widgets.controls_panel import ControlsPanel


class ArticlePage(QWidget):
    reroll_slot_requested = pyqtSignal(str)

    def __init__(self, skill_dir=None, default_provider="mock", parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")

        # Outer horizontal splitter: slot list | right column
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.slot_list = SlotList(self.splitter)
        self.slot_list.setMinimumWidth(260)
        self.slot_list.reroll_requested.connect(self.reroll_slot_requested.emit)
        self.slot_panel = self.slot_list

        # Right column: vertical splitter with markdown preview on top and a
        # compact action bar pinned below. Using a splitter (not a fixed
        # layout) so users can drag the divider if they want more preview
        # room, but we seed the sizes so the controls bar stays small.
        self.right_splitter = QSplitter(Qt.Orientation.Vertical, self.splitter)

        self.markdown_view = MarkdownView(self.right_splitter)
        self.markdown_view.setMinimumWidth(480)
        self.markdown_view.setMinimumHeight(320)
        self.preview_panel = self.markdown_view

        self.controls = ControlsPanel(
            skill_dir=skill_dir,
            provider_default=default_provider,
            parent=self.right_splitter,
        )
        self.controls.setMaximumHeight(72)
        self.controls.setMinimumHeight(56)
        self.controls_panel = self.controls

        self.right_splitter.addWidget(self.markdown_view)
        self.right_splitter.addWidget(self.controls)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 0)
        self.right_splitter.setCollapsible(0, False)
        self.right_splitter.setCollapsible(1, False)
        self.right_splitter.setSizes([680, 64])

        self.splitter.addWidget(self.slot_list)
        self.splitter.addWidget(self.right_splitter)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([320, 980])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.markdown_view.set_draft("")
        self.markdown_view.set_polished("")
        # Drop every SlotCard so the left column returns to its empty state.
        lay = self.slot_list._layout
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        # After set_polished() the view auto-jumped to 成文; flip back to 初稿
        # so a fresh generate lands on the draft tab.
        self.markdown_view._pivot.setCurrentItem("draft")

    def load_result(self, template, plan, draft: str, final_text: str) -> None:
        """Render a generated article. All inputs are plain data."""
        self.slot_list.load(template, plan)
        self.markdown_view.set_draft(draft)
        self.markdown_view.set_polished(final_text)

    def update_plan(self, template, plan, draft: str) -> None:
        """Refresh slot list + draft after a reroll (polished text unchanged)."""
        self.slot_list.load(template, plan)
        self.markdown_view.set_draft(draft)

    def apply_config(self, cfg):
        self.controls.set_skill_dir(Path(cfg.skill_dir) if cfg.skill_dir else None)
        self.controls.set_provider_default(cfg.default_provider)
