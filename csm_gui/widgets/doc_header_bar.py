"""Header bar above the article preview.

Mirrors the ``workspace.jsx`` center-doc top strip: edit chip + version chip
on the left, "N 秒前已自动保存" hint on the right, then a large h1 title and
a muted meta line ("原文 … 字 · 洗稿 … 字 · 重复度 … · 约需阅读 … 分钟").

The widget is data-agnostic — call ``update_doc(template, plan, draft,
polished)`` from ``article_page`` after every load/resample.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QLineEdit


# Design tokens (shared with workspace_side_panel)
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT        = "#2f6f5e"
_ACCENT_SOFTER = "#ecf2ee"


def _chip(text: str, variant: str = "outline", parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    if variant == "accent":
        style = (
            f"background: {_ACCENT_SOFTER}; color: {_ACCENT};"
            f" border: 1px solid {_ACCENT_SOFTER};"
        )
    else:
        style = (
            f"background: #ffffff; color: {_INK_2};"
            f" border: 1px solid {_INK_5};"
        )
    lbl.setStyleSheet(
        f"{style} padding: 2px 10px; border-radius: 999px; font-size: 11.5px;"
    )
    lbl.setFixedHeight(22)
    return lbl


class DocHeaderBar(QWidget):
    """Title + meta strip rendered above MarkdownView."""

    title_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DocHeaderBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#DocHeaderBar { background: transparent; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 10)
        lay.setSpacing(10)

        # ── Chip row ────────────────────────────────────────────────────
        row = QHBoxLayout(); row.setSpacing(8); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_chip("● 正在编辑", "accent", self))
        self._version_chip = _chip("—", "outline", self)
        row.addWidget(self._version_chip)
        row.addStretch(1)
        self._save_hint = QLabel("✓ 自动保存已开启", self)
        self._save_hint.setStyleSheet(
            f"color: {_INK_3}; font-size: 11.5px; background: transparent;")
        row.addWidget(self._save_hint)
        lay.addLayout(row)

        # ── Title (editable) ────────────────────────────────────────────
        self._title = QLineEdit(self)
        self._title.setPlaceholderText("尚未生成文章")
        self._title.setFrame(False)
        self._title.setCursor(Qt.CursorShape.IBeamCursor)
        self._title.setStyleSheet(
            f"QLineEdit {{ color: {_INK}; font-size: 24px; font-weight: 700;"
            "background: transparent; border: none;"
            f" border-bottom: 1px dashed transparent; padding: 2px 0; }}"
            f"QLineEdit:hover {{ border-bottom: 1px dashed {_INK_5}; }}"
            f"QLineEdit:focus {{ background: {_ACCENT_SOFTER};"
            f" border: none; border-radius: 6px; padding: 2px 6px; }}"
        )
        self._title_dirty = False
        self._title.textEdited.connect(self._on_title_edited)
        lay.addWidget(self._title)

        # ── Meta ────────────────────────────────────────────────────────
        self._meta = QLabel("—", self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet(
            f"color: {_INK_3}; font-size: 12px; background: transparent;"
        )
        lay.addWidget(self._meta)

        # ── Separator ───────────────────────────────────────────────────
        sep = QFrame(self); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {_INK_5}; border: none; max-height: 1px;")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

    # ── Public API ──────────────────────────────────────────────────────
    def update_doc(self, template=None, plan=None, draft: str = "",
                   polished: str = "") -> None:
        # Title priority: polished heading → draft heading → template literal,
        # with {keyword} substituted from the plan. User-edited titles stick.
        keyword = getattr(plan, "keyword", "") if plan else ""
        title = self._derive_title(template, plan, draft, polished, keyword)
        if not self._title_dirty:
            self._title.blockSignals(True)
            self._title.setText(title)
            self._title.blockSignals(False)

        # Version chip — template name + " · v1" (version is aspirational for now).
        tpl_name = getattr(template, "name", "") if template else ""
        self._version_chip.setText(f"{tpl_name or '未选择模板'} · v1")

        # Meta line. Counts are rough — stripped chars, not words.
        draft_chars = len(draft or "")
        polished_chars = len(polished or "")
        read_minutes = max(1, round((polished_chars or draft_chars) / 350))
        parts = []
        if draft_chars:
            parts.append(f"初稿 {draft_chars:,} 字")
        if polished_chars:
            parts.append(f"成稿 {polished_chars:,} 字")
        if not parts:
            parts.append("暂无正文")
        parts.append(f"约需阅读 {read_minutes} 分钟")
        self._meta.setText(" · ".join(parts))

    def set_save_hint(self, text: str) -> None:
        self._save_hint.setText(text)

    def current_title(self) -> str:
        return self._title.text().strip()

    def reset_title_dirty(self) -> None:
        """Clear the user-edited flag so the next update_doc may overwrite."""
        self._title_dirty = False

    def _on_title_edited(self, text: str) -> None:
        self._title_dirty = True
        self.title_changed.emit(text)

    # ── Helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _derive_title(template, plan, draft: str, polished: str,
                      keyword: str) -> str:
        # When polish output exists, prefer its first heading so the title
        # follows the final article's wording.
        if polished:
            for line in polished.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    s = stripped.lstrip("#").strip()
                    if s:
                        return s
        # Otherwise default to the raw keyword — the template title is kept
        # for the version chip, not here (user doesn't want the full template
        # heading baked in automatically).
        return keyword or ""
