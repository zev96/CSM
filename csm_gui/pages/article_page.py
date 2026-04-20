"""Article workspace — 3-column layout: slots / markdown / controls."""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from ..widgets.slot_list import SlotList
from ..widgets.markdown_view import MarkdownView
from ..widgets.controls_panel import ControlsPanel


class ArticlePage(QWidget):
    def __init__(self, skill_dir=None, default_provider="mock", parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")
        self.current_result = None
        self._template = None

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.slot_list = SlotList(self.splitter)
        self.slot_list.setMinimumWidth(300)
        # Keep attribute alias for backward compatibility with earlier tasks.
        self.slot_panel = self.slot_list

        self.markdown_view = MarkdownView(self.splitter)
        self.markdown_view.setMinimumWidth(480)
        self.preview_panel = self.markdown_view  # alias for compat

        self.controls = ControlsPanel(
            skill_dir=skill_dir,
            provider_default=default_provider,
            parent=self.splitter,
        )
        self.controls.setMinimumWidth(280)
        self.controls_panel = self.controls  # alias

        self.splitter.addWidget(self.slot_list)
        self.splitter.addWidget(self.markdown_view)
        self.splitter.addWidget(self.controls_panel)
        self.splitter.setSizes([320, 720, 300])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.current_result = None
        self._template = None
        self.markdown_view.set_draft("")
        self.markdown_view.set_polished("")

    def load_result(self, template, result) -> None:
        """Populate from a Template + GenerateResult."""
        self.current_result = result
        self._template = template
        self.slot_list.load(template, result.plan)
        draft = "\n\n".join(
            "\n\n".join(p.text for p in s.picks) for s in result.plan.slots if s.picks
        )
        self.markdown_view.set_draft(draft)
        self.markdown_view.set_polished(result.final_text)

    def apply_config(self, cfg):
        self.controls.set_skill_dir(Path(cfg.skill_dir) if cfg.skill_dir else None)
        self.controls.set_provider_default(cfg.default_provider)
