"""Article workspace — 3-column layout. View-only: no workflow state."""
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

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.slot_list = SlotList(self.splitter)
        self.slot_list.setMinimumWidth(300)
        self.slot_list.reroll_requested.connect(self.reroll_slot_requested.emit)
        self.slot_panel = self.slot_list

        self.markdown_view = MarkdownView(self.splitter)
        self.markdown_view.setMinimumWidth(480)
        self.preview_panel = self.markdown_view

        self.controls = ControlsPanel(
            skill_dir=skill_dir,
            provider_default=default_provider,
            parent=self.splitter,
        )
        self.controls.setMinimumWidth(280)
        self.controls_panel = self.controls

        self.splitter.addWidget(self.slot_list)
        self.splitter.addWidget(self.markdown_view)
        self.splitter.addWidget(self.controls_panel)
        self.splitter.setSizes([320, 720, 300])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.markdown_view.set_draft("")
        self.markdown_view.set_polished("")

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
