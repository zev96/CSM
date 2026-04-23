"""Article workspace — two-column layout.

Left: pick-list panel (per-pick reroll buttons).
Right-top: markdown preview (large).
Right-bottom: action bar (compact) — polish-skill + 重新随机/润色/导出 buttons.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from ..widgets.markdown_view import MarkdownView
from ..widgets.controls_panel import ControlsPanel
from ..widgets.pick_list_panel import PickListPanel


class ArticlePage(QWidget):

    def __init__(self, skill_dir=None, default_provider="mock", parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")

        # Outer horizontal splitter: left placeholder | right column
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.pick_list_panel = PickListPanel(self.splitter)
        self.pick_list_panel.setMinimumWidth(260)
        # Back-compat alias (existing tests and callers reference ``slot_panel``).
        self.slot_panel = self.pick_list_panel

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

        self.splitter.addWidget(self.pick_list_panel)
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
        # After set_polished() the view auto-jumped to 成文; flip back to 初稿
        # so a fresh generate lands on the draft tab.
        self.markdown_view._pivot.setCurrentItem("draft")
        from csm_core.assembler.plan import AssemblyPlan
        self.pick_list_panel.load_plan(
            AssemblyPlan(keyword="", template_id="", seed=0, results=[])
        )

    def load_result(self, template, plan, draft: str, final_text: str) -> None:
        """Render a generated article. All inputs are plain data."""
        self.markdown_view.set_draft(draft)
        self.markdown_view.set_polished(final_text)
        self.pick_list_panel.load_plan(plan, template)
        self.controls.set_preferred_skill(getattr(template, "default_skill_id", None))

    def update_plan(self, template, plan, draft: str) -> None:
        """Refresh draft after resampling (polished text unchanged)."""
        self.markdown_view.set_draft(draft)
        self.pick_list_panel.load_plan(plan, template)

    def apply_config(self, cfg):
        self.controls.set_skill_dir(Path(cfg.skill_dir) if cfg.skill_dir else None)
        self.controls.set_provider_default(cfg.default_provider)
