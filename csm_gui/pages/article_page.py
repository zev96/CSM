"""Article workspace — two-column layout.

Left:  center doc (header card + markdown/paragraph-card preview + tabs)
Right: workspace side panel — Skill list + 微调 + 检查 + 整篇重新生成 / 导出.

The old left-hand pick-list column was folded into the draft tab of
``MarkdownView``: each paragraph is now a hover-tools card with its own
reroll/copy/delete buttons. A compatibility alias ``pick_list_panel`` is
exposed so ``main_window`` wiring for reroll + busy states keeps working
without changes.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from ..widgets.markdown_view import MarkdownView
from ..widgets.workspace_side_panel import WorkspaceSidePanel
from ..widgets.doc_header_bar import DocHeaderBar


class ArticlePage(QWidget):

    def __init__(self, skill_dir=None, default_provider="mock", parent=None):
        super().__init__(parent)
        self.setObjectName("ArticlePage")

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(0)

        # ── Left: header card + markdown preview ─────────────────────────
        center = QWidget(self.splitter)
        center.setStyleSheet("background: transparent;")
        c_lay = QVBoxLayout(center)
        c_lay.setContentsMargins(18, 14, 18, 14)
        c_lay.setSpacing(10)
        self.header_bar = DocHeaderBar(center)
        c_lay.addWidget(self.header_bar)
        self.header_bar.title_changed.connect(self._on_title_changed)
        self.markdown_view = MarkdownView(center)
        self.markdown_view.setMinimumWidth(560)
        c_lay.addWidget(self.markdown_view, 1)
        self._center = center
        self.preview_panel = self.markdown_view
        # Back-compat: main_window.py wires reroll + set_busy via
        # ``article.pick_list_panel``. After removing the left column, the
        # per-paragraph cards inside MarkdownView play that role — expose
        # MarkdownView under the old name (it provides ``reroll_requested``
        # and ``set_busy`` with matching signatures).
        self.pick_list_panel = self.markdown_view
        self.slot_panel = self.markdown_view

        # ── Right: workspace side panel (owns hidden ControlsPanel) ──────
        self.controls = WorkspaceSidePanel(
            skill_dir=skill_dir,
            provider_default=default_provider,
            parent=self.splitter,
        )
        self.controls.setMinimumWidth(300)
        self.controls_panel = self.controls
        self._last_polished: str = ""

        self.splitter.addWidget(self._center)
        self.splitter.addWidget(self.controls)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([900, 340])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.splitter)

    def clear(self) -> None:
        self.markdown_view.reset_polished_edits()
        self.markdown_view.set_draft("")
        self.markdown_view.set_polished("")
        self._last_polished = ""
        self._current_template = None
        self._current_plan = None
        self._current_draft = ""
        self.header_bar.reset_title_dirty()
        self.header_bar.update_doc(None, None, "", "")
        self.markdown_view.set_title(self.header_bar.current_title())
        self.markdown_view._pivot.setCurrentItem("draft")

    def _on_title_changed(self, text: str) -> None:
        self.markdown_view.set_title(text)

    def load_result(self, template, plan, draft: str, final_text: str) -> None:
        """Render a generated article. All inputs are plain data."""
        self.markdown_view.reset_polished_edits()
        self.markdown_view.set_draft_plan(template, plan, draft)
        self.markdown_view.set_polished(final_text)
        self.controls.set_preferred_skill(getattr(template, "default_skill_id", None))
        self._last_polished = final_text
        self._current_template = template
        self._current_plan = plan
        self._current_draft = draft
        self.header_bar.reset_title_dirty()
        self.header_bar.update_doc(template, plan, draft, final_text)
        self.markdown_view.set_title(self.header_bar.current_title())

    def update_plan(self, template, plan, draft: str) -> None:
        """Refresh draft after resampling (polished text unchanged)."""
        self.markdown_view.set_draft_plan(template, plan, draft)
        self._current_template = template
        self._current_plan = plan
        self._current_draft = draft
        self.header_bar.update_doc(template, plan, draft, self._last_polished)
        self.markdown_view.set_title(self.header_bar.current_title())

    def sync_title_to_polished(self, polished: str) -> None:
        """After AI polish lands, sync the title from the polished heading."""
        self._last_polished = polished
        self.header_bar.update_doc(
            getattr(self, "_current_template", None),
            getattr(self, "_current_plan", None),
            getattr(self, "_current_draft", ""),
            polished,
        )
        self.markdown_view.set_title(self.header_bar.current_title())

    def apply_config(self, cfg):
        self.controls.set_skill_dir(Path(cfg.skill_dir) if cfg.skill_dir else None)
        self.controls.set_provider_default(cfg.default_provider)

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        self.controls.refresh_skills()
