"""Center-doc preview — paragraph cards + polished + source-compare tabs.

Matches the ``workspace.jsx`` prototype:

* **初稿 · 可重抽** — paragraphs rendered as labeled cards. The gutter holds
  the block label (开头 / 数据 / 行业意义 / …); the body is read-only prose;
  hover reveals a toolbar (refresh / sparkle / copy / trash) on the right.
  A dashed "+ 在此处补一段" button sits at the bottom.
* **成稿预览** — the polished markdown, typographic QTextEdit render.
* **对照原文** — two side-by-side cards (原文 / 洗稿后). Placeholder for
  now — the original source is filled when available, otherwise a hint.

Public API preserved for main_window / article_page:

* ``set_draft(md)``, ``get_draft_text()`` — drafting markdown round-trip
* ``set_polished(md)``
* ``paragraph_reroll_requested(int, str)``, ``paragraph_delete_requested(str)``
* ``_pivot.setCurrentItem("draft" | "polished" | "source")`` — used by
  ``article_page.clear``.

``set_draft_plan(template, plan, md)`` is the richer entry point — it
builds the per-paragraph card list from the plan. ``set_draft(md)`` alone
renders a simpler single-block card, for environments that don't have a
plan yet (e.g. tests).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QEvent, QObject, pyqtSignal
from PyQt6.QtGui import QTextCursor, QTextBlockFormat, QTextCharFormat
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QStackedWidget, QFrame, QWidget, QLabel,
    QSizePolicy, QGridLayout, QPushButton, QButtonGroup,
)
from qfluentwidgets import (
    TextEdit, ToolButton, FluentIcon, SingleDirectionScrollArea,
)


# ── Design tokens ───────────────────────────────────────────────────────────
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT        = "#2f6f5e"
_ACCENT_SOFTER = "#ecf2ee"
_DANGER        = "#c25c4d"

_BODY_PT = 13
_LINE_HEIGHT_PCT = 170


# ── Helpers ─────────────────────────────────────────────────────────────────
def _build_label_map(template) -> dict[str, str]:
    result: dict[str, str] = {}
    if template is None:
        return result

    def walk(items):
        for b in items:
            kind = getattr(b, "kind", "")
            bid = getattr(b, "id", "")
            if kind in ("paragraph", "numbered_list"):
                label = getattr(b, "label", "") or bid
            elif kind == "heading":
                label = getattr(b, "text", "") or bid
            elif kind == "hero_brand":
                label = getattr(b, "title", "") or bid
            elif kind == "literal":
                txt = getattr(b, "text", "") or bid
                label = txt[:16] + ("…" if len(txt) > 16 else "")
            elif kind == "competitor_pool":
                label = "竞品"
            else:
                label = bid
            result[bid] = label
            if kind == "paragraph":
                walk(getattr(b, "children", []) or [])

    walk(getattr(template, "blocks", []) or [])
    return result


def _hover_btn(icon, tip: str, danger: bool = False, parent=None) -> ToolButton:
    from PyQt6.QtCore import QSize
    btn = ToolButton(icon, parent)
    btn.setFixedSize(22, 22)
    btn.setIconSize(QSize(12, 12))
    btn.setToolTip(tip)
    color = _DANGER if danger else _INK_2
    hover = "rgba(194,92,77,0.12)" if danger else _ACCENT_SOFTER
    btn.setStyleSheet(
        "ToolButton { background: #ffffff; border-radius: 6px;"
        f" border: 1px solid {_INK_5}; color: {color}; }}"
        f"ToolButton:hover {{ background: {hover}; border-color: {color}; }}"
    )
    return btn


# ── Segmented tabs (replaces Pivot) ────────────────────────────────────────
class _SegmentedTabs(QFrame):
    """Rounded gray container with a white-pill active segment.

    API mirrors qfluentwidgets' ``Pivot``:

    * ``addItem(routeKey, text)`` — register a segment
    * ``setCurrentItem(routeKey)`` — programmatic switch
    * ``currentItemChanged(str)`` — emitted on switch
    """

    currentItemChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentedTabs")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#SegmentedTabs { background: rgba(30,28,25,0.05);"
            " border: 1px solid rgba(30,28,25,0.06); border-radius: 10px; }"
        )
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._keys: list[str] = []
        self._buttons: dict[str, QPushButton] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self._lay = lay

        self._btn_qss = (
            "QPushButton { background: transparent; border: none;"
            f" color: {_INK_2}; padding: 6px 14px; border-radius: 7px;"
            " font-size: 13px; }"
            f"QPushButton:hover {{ color: {_INK}; }}"
            "QPushButton:checked { background: #ffffff;"
            f" color: {_INK}; font-weight: 600;"
            " border: 1px solid rgba(30,28,25,0.08); }"
        )

    def addItem(self, routeKey: str, text: str) -> None:  # noqa: N802
        btn = QPushButton(text, self)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(self._btn_qss)
        btn.clicked.connect(lambda _=False, k=routeKey: self._on_clicked(k))
        self._group.addButton(btn)
        self._lay.addWidget(btn)
        self._keys.append(routeKey)
        self._buttons[routeKey] = btn
        if len(self._keys) == 1:
            btn.setChecked(True)

    def setCurrentItem(self, key: str) -> None:  # noqa: N802
        btn = self._buttons.get(key)
        if btn and not btn.isChecked():
            btn.setChecked(True)
            self.currentItemChanged.emit(key)
        elif btn:
            self.currentItemChanged.emit(key)

    def _on_clicked(self, key: str) -> None:
        self._buttons[key].setChecked(True)
        self.currentItemChanged.emit(key)


# ── Paragraph card ──────────────────────────────────────────────────────────
class _ParagraphCard(QFrame):
    """One row in the draft view: left-gutter label + body text + hover tools."""

    reroll_clicked = pyqtSignal(str, int)   # (block_id, pick_index)
    delete_clicked = pyqtSignal(str)        # block_id

    def __init__(self, block_id: str, pick_index: int, label: str, text: str,
                 parent=None):
        super().__init__(parent)
        self._block_id = block_id
        self._pick_index = pick_index
        self.setObjectName("ParagraphCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._apply_style(False)
        self.setMinimumHeight(88)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 22, 12, 22)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(0)

        # Left-gutter label — small, wrapped, right-aligned, vertically centered
        self._label = QLabel(label, self)
        self._label.setFixedWidth(60)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._label.setStyleSheet(
            f"color: {_INK_3}; font-size: 10px; letter-spacing: 0.4px;"
            "font-weight: 600; background: transparent;"
        )
        grid.addWidget(self._label, 0, 0, Qt.AlignmentFlag.AlignVCenter)

        # Body text
        self._body = QLabel(text, self)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._body.setStyleSheet(
            f"color: {_INK}; font-size: 14px; line-height: 1.9;"
            "background: transparent;"
        )
        self._body.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )
        grid.addWidget(self._body, 0, 1)
        grid.setColumnStretch(1, 1)

        # Reserve the right-hand tools column so card width doesn't change on
        # hover. Actual buttons float as an overlay so they never contribute to
        # the row height — short paragraphs would otherwise grow on hover.
        grid.setColumnMinimumWidth(2, 36)

        self._tools = QWidget(self)
        self._tools.setStyleSheet("background: transparent;")
        t_lay = QVBoxLayout(self._tools)
        t_lay.setContentsMargins(0, 0, 0, 0); t_lay.setSpacing(6)
        self._btn_reroll = _hover_btn(FluentIcon.SYNC, "重抽这一段", parent=self._tools)
        self._btn_sparkle = _hover_btn(FluentIcon.ROBOT, "AI 润色", parent=self._tools)
        for b in (self._btn_reroll, self._btn_sparkle):
            t_lay.addWidget(b)
        self._tools.setVisible(False)
        self._tools.raise_()

        self._btn_reroll.clicked.connect(
            lambda: self.reroll_clicked.emit(self._block_id, self._pick_index))

    # ── Hover affordance ────────────────────────────────────────────────
    def enterEvent(self, ev):  # noqa: N802
        self._position_tools()
        self._tools.setVisible(True)
        self._tools.raise_()
        self._apply_style(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev):  # noqa: N802
        self._tools.setVisible(False)
        self._apply_style(False)
        super().leaveEvent(ev)

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self._position_tools()

    def _position_tools(self) -> None:
        self._tools.adjustSize()
        tw = self._tools.sizeHint().width()
        th = self._tools.sizeHint().height()
        x = max(0, self.width() - tw - 12)
        y = max(0, (self.height() - th) // 2)
        self._tools.move(x, y)

    def _apply_style(self, hover: bool) -> None:
        bg = "#fafaf7" if hover else "transparent"
        border = _INK_5 if hover else "transparent"
        self.setStyleSheet(
            "#ParagraphCard { background: " + bg + ";"
            " border: 1px solid " + border + "; border-radius: 10px; }"
        )

    def _on_copy(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._body.text())


# ── Add-block button ────────────────────────────────────────────────────────
class _AddBlockButton(QFrame):
    clicked = pyqtSignal()

    def __init__(self, text: str = "+ 在此处补一段", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setStyleSheet(
            "QFrame { background: transparent;"
            f" border: 1px dashed {_INK_5}; border-radius: 10px; }}"
            f"QFrame:hover {{ border-color: {_ACCENT}; background: {_ACCENT_SOFTER}; }}"
        )
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(text, self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color: {_INK_3}; font-size: 12px; background: transparent;"
            "border: none;"
        )
        lay.addWidget(lbl)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ── Main view ───────────────────────────────────────────────────────────────
class MarkdownView(QFrame):
    paragraph_reroll_requested = pyqtSignal(int, str)     # back-compat
    paragraph_pick_reroll_requested = pyqtSignal(str, int)  # (block_id, pick)
    # Alias matching the old PickListPanel signal signature so main_window
    # wiring (``self.article.pick_list_panel.reroll_requested``) is preserved
    # after the left pick-list column was removed — an ArticlePage-level
    # alias forwards this signal.
    reroll_requested = pyqtSignal(str, int)
    paragraph_delete_requested = pyqtSignal(str)
    add_paragraph_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MarkdownView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#MarkdownView { background: transparent; border: none; }")
        self.setFrameShape(QFrame.Shape.NoFrame)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Pivot tabs ─────────────────────────────────────────────────
        pivot_wrap = QWidget(self)
        pivot_wrap.setStyleSheet(
            "QWidget { background: transparent; }"
        )
        pw_lay = QHBoxLayout(pivot_wrap)
        pw_lay.setContentsMargins(0, 0, 0, 10)
        pw_lay.setSpacing(0)
        self._pivot = _SegmentedTabs(pivot_wrap)
        self._pivot.addItem(routeKey="draft", text="组装")
        self._pivot.addItem(routeKey="polished", text="初稿")
        self._pivot.addItem(routeKey="source", text="成稿")
        self._pivot.currentItemChanged.connect(self._on_tab)
        pw_lay.addWidget(self._pivot)
        pw_lay.addStretch(1)
        root.addWidget(pivot_wrap)

        # ── Stack ──────────────────────────────────────────────────────
        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("background: transparent;")
        root.addWidget(self._stack, 1)

        # Pages
        self._draft_page = self._build_draft_page()
        self._polished_page, self.polished_edit = self._build_md_page()
        self._source_page, self.final_edit = self._build_final_page()

        self._stack.addWidget(self._draft_page)
        self._stack.addWidget(self._polished_page)
        self._stack.addWidget(self._source_page)

        self._pivot.setCurrentItem("draft")

        # Cached state
        self._cards: list[_ParagraphCard] = []
        self._card_texts: dict[tuple[str, int], str] = {}
        self._label_map: dict[str, str] = {}
        self._raw_draft_md: str = ""
        self._raw_polished_md: str = ""
        self._title: str = ""
        # Track whether the user has hand-edited the 初稿 text. If they have,
        # rerolls should patch individual paragraphs in place rather than
        # blowing away their custom layout.
        self._polished_dirty = False
        self._updating_polished = False
        self.polished_edit.textChanged.connect(self._on_polished_changed)
        # Kept so old tests that poke ``.draft_edit`` still resolve.
        self.draft_edit = self.polished_edit  # harmless alias

    # ── Tab / page builders ─────────────────────────────────────────────
    def _build_draft_page(self) -> QWidget:
        page = QWidget(self._stack)
        page.setStyleSheet("background: transparent;")

        scroll = SingleDirectionScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "SingleDirectionScrollArea, QScrollArea "
            "{ background: transparent; border: none; }"
        )
        scroll.viewport().setStyleSheet("background: transparent;")

        inner = QWidget(scroll); inner.setStyleSheet("background: transparent;")
        self._draft_lay = QVBoxLayout(inner)
        self._draft_lay.setContentsMargins(16, 8, 40, 24)
        self._draft_lay.setSpacing(6)

        self._empty_hint = QLabel("尚未生成文章 — 从工作台发起一次生成。", inner)
        self._empty_hint.setStyleSheet(
            f"color: {_INK_3}; font-size: 12.5px; padding: 40px 0;"
            "background: transparent;"
        )
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._draft_lay.addWidget(self._empty_hint)

        self._draft_lay.addStretch(1)

        scroll.setWidget(inner)
        p_lay = QVBoxLayout(page)
        p_lay.setContentsMargins(0, 0, 0, 0)
        p_lay.addWidget(scroll)
        return page

    def _build_md_page(self) -> tuple[QWidget, TextEdit]:
        """Editable rich-text page — doubles as polished preview. Content is
        auto-populated from draft cards; the user can touch up inline.
        """
        page = QWidget(self._stack); page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        card = QFrame(page)
        card.setObjectName("PolishedCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#PolishedCard {{ background: #ffffff;"
            f" border: 1px solid {_INK_5}; border-radius: 12px; }}"
        )
        c_lay = QVBoxLayout(card); c_lay.setContentsMargins(12, 10, 12, 16); c_lay.setSpacing(0)
        edit = TextEdit(card)
        edit.setReadOnly(False)
        edit.setFrameShape(QFrame.Shape.NoFrame)
        edit.setStyleSheet(
            "TextEdit { border: none; background: transparent;"
            " padding: 12px 24px; }"
        )
        edit.document().setDocumentMargin(8)
        c_lay.addWidget(edit)
        lay.addWidget(card)
        return page, edit

    def _build_final_page(self) -> tuple[QWidget, TextEdit]:
        """成稿 tab — AI-polished output. Same white-card shell as 初稿."""
        page = QWidget(self._stack); page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        card = QFrame(page)
        card.setObjectName("FinalCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#FinalCard {{ background: #ffffff;"
            f" border: 1px solid {_INK_5}; border-radius: 12px; }}"
        )
        c_lay = QVBoxLayout(card); c_lay.setContentsMargins(12, 10, 12, 16); c_lay.setSpacing(0)
        edit = TextEdit(card)
        edit.setReadOnly(False)
        edit.setFrameShape(QFrame.Shape.NoFrame)
        edit.setStyleSheet(
            "TextEdit { border: none; background: transparent;"
            " padding: 12px 24px; }"
        )
        edit.document().setDocumentMargin(8)
        edit.setPlaceholderText("尚未润色 — 在右侧点击『润色』按钮生成成稿。")
        c_lay.addWidget(edit)
        lay.addWidget(card)
        return page, edit

    # ── Tab routing ─────────────────────────────────────────────────────
    def _on_tab(self, key: str) -> None:
        idx = {"draft": 0, "polished": 1, "source": 2}.get(key, 0)
        self._stack.setCurrentIndex(idx)

    # ── Public API ──────────────────────────────────────────────────────
    def set_draft(self, md: str) -> None:
        """Set draft markdown. If no plan has been loaded, render as a single
        card; callers with a plan should prefer ``set_draft_plan``.
        """
        self._raw_draft_md = md or ""
        self._raw_polished_md = ""
        self._clear_cards()
        if md and md.strip():
            self._empty_hint.hide()
            card = _ParagraphCard("__draft__", 0, "正文", md.strip(), parent=self)
            card.delete_clicked.connect(self._on_card_delete)
            self._mount_card(card)
        else:
            self._empty_hint.show()
        self._sync_polished_view()

    def set_draft_plan(self, template, plan, md: str) -> None:
        """Rich draft rendering — one card per pick across all block kinds.

        组装 shows the picked text without structural decoration (numbering,
        headings, hero titles) — that's reserved for the 初稿 view, which
        uses the full ``compose_draft`` output.
        """
        prev_texts = dict(self._card_texts)
        self._raw_draft_md = md or ""
        self._raw_polished_md = ""
        self._label_map = _build_label_map(template)
        self._clear_cards()
        results = list(getattr(plan, "results", []) or [])
        any_card = False
        for r in self._iter_content_blocks(results):
            kind = getattr(r, "kind", "")
            base_label = (self._label_map.get(r.block_id)
                          or getattr(r, "block_id", "") or "段")
            if kind == "hero_brand":
                title = getattr(r, "text", "") or base_label
                if title.strip():
                    card = _ParagraphCard(r.block_id, 0, "主推", title.strip(),
                                          parent=self)
                    card.reroll_clicked.connect(self._on_card_reroll)
                    card.delete_clicked.connect(self._on_card_delete)
                    self._mount_card(card)
                    any_card = True
                continue
            if kind == "competitor_pool":
                for i, pv in enumerate(getattr(r, "picks", []) or []):
                    text = getattr(pv, "text", "")
                    meta = getattr(pv, "meta", {}) or {}
                    title = meta.get("title") or getattr(pv, "note_id", "")
                    body = f"{title}\n{text}".strip() if title else text.strip()
                    if not body:
                        continue
                    card = _ParagraphCard(r.block_id, i, "竞品", body,
                                          parent=self)
                    card.reroll_clicked.connect(self._on_card_reroll)
                    card.delete_clicked.connect(self._on_card_delete)
                    self._mount_card(card)
                    any_card = True
                continue
            # paragraph / numbered_list — one card per pick
            for i, pv in enumerate(getattr(r, "picks", []) or []):
                text = getattr(pv, "text", "")
                if not text.strip():
                    continue
                card = _ParagraphCard(r.block_id, i, base_label, text.strip(),
                                      parent=self)
                card.reroll_clicked.connect(self._on_card_reroll)
                card.delete_clicked.connect(self._on_card_delete)
                self._mount_card(card)
                any_card = True
        if any_card:
            self._empty_hint.hide()
        elif md and md.strip():
            self.set_draft(md)
            return
        else:
            self._empty_hint.show()
        new_texts = {(c._block_id, c._pick_index): c._body.text()
                     for c in self._cards}
        self._card_texts = new_texts
        if self._polished_dirty and prev_texts:
            self._patch_polished(prev_texts, new_texts)
        else:
            self._sync_polished_view()

    def get_draft_text(self) -> str:
        """Return the current 初稿 text — user-edited composed markdown if any,
        else the composed card text, else the raw draft the pipeline handed us.
        """
        edited = self.polished_edit.toPlainText().strip()
        if edited:
            return self.polished_edit.toMarkdown().strip()
        composed = self._compose_from_cards()
        return composed or self._raw_draft_md

    def reset_polished_edits(self) -> None:
        """Clear the user-edit flag so the next plan refresh rebuilds 初稿."""
        self._polished_dirty = False

    def _on_polished_changed(self) -> None:
        if self._updating_polished:
            return
        self._polished_dirty = True

    def _patch_polished(
        self, prev: dict[tuple[str, int], str],
        new: dict[tuple[str, int], str],
    ) -> None:
        """Replace individual paragraph bodies in polished_edit in-place.

        Preserves the user's custom layout (merged / reordered paragraphs)
        by doing targeted find-replace for each card whose text changed.
        """
        doc = self.polished_edit.document()
        self._updating_polished = True
        try:
            for key, old_text in prev.items():
                new_text = new.get(key)
                if not new_text or new_text == old_text:
                    continue
                old_s = (old_text or "").strip()
                new_s = new_text.strip()
                if not old_s:
                    continue
                cursor = doc.find(old_s)
                if cursor.isNull():
                    continue
                cursor.insertText(new_s)
        finally:
            self._updating_polished = False

    def set_title(self, title: str) -> None:
        """Update the H1 prepended to the 初稿 composed text."""
        new_title = (title or "").strip()
        if new_title == self._title:
            return
        old_title = self._title
        self._title = new_title
        if self._polished_dirty:
            # Patch the H1 in place so the user's reorganized body survives.
            doc = self.polished_edit.document()
            self._updating_polished = True
            try:
                if old_title:
                    cur = doc.find(f"# {old_title}")
                    if not cur.isNull():
                        cur.insertText(f"# {new_title}" if new_title else "")
                else:
                    first = doc.firstBlock()
                    if first.isValid() and first.blockFormat().headingLevel() > 0:
                        cursor = QTextCursor(first)
                        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                        cursor.insertText(new_title)
            finally:
                self._updating_polished = False
        else:
            self._sync_polished_view()

    def set_polished(self, md: str) -> None:
        """Set AI-polished output. Renders into the 成稿 tab and flips there."""
        self._raw_polished_md = md or ""
        if md and md.strip():
            self.final_edit.setMarkdown(md)
            self._apply_final_typography()
            self._pivot.setCurrentItem("source")
        else:
            self.final_edit.clear()

    def set_busy(self, busy: bool) -> None:
        """Disable per-card reroll/sparkle buttons during a reroll/polish."""
        for c in self._cards:
            c._btn_reroll.setEnabled(not busy)
            c._btn_sparkle.setEnabled(not busy)

    # ── Internals ───────────────────────────────────────────────────────
    def _iter_paragraph_blocks(self, results):
        for r in results:
            kind = getattr(r, "kind", "")
            if kind in ("paragraph", "numbered_list") and getattr(r, "picks", None):
                yield r
            yield from self._iter_paragraph_blocks(getattr(r, "children", []) or [])

    def _iter_content_blocks(self, results):
        """Walk plan results yielding blocks that have user-visible content
        in the 组装 view: paragraphs, numbered lists, hero titles, and
        competitor-pool picks. Headings / literals are skipped — those are
        framework chrome that belongs in 初稿 only.
        """
        for r in results:
            kind = getattr(r, "kind", "")
            if kind == "hero_brand":
                yield r
            elif kind == "competitor_pool" and getattr(r, "picks", None):
                yield r
            elif kind in ("paragraph", "numbered_list") and getattr(r, "picks", None):
                yield r
            yield from self._iter_content_blocks(getattr(r, "children", []) or [])

    def _clear_cards(self) -> None:
        for c in self._cards:
            self._draft_lay.removeWidget(c)
            c.setParent(None); c.deleteLater()
        self._cards.clear()

    def _mount_card(self, card: _ParagraphCard) -> None:
        # Insert above the trailing stretch (always last item).
        insert_at = max(0, self._draft_lay.count() - 1)
        self._draft_lay.insertWidget(insert_at, card)
        self._cards.append(card)

    # ── Card event handlers ─────────────────────────────────────────────
    def _on_card_reroll(self, block_id: str, pick_index: int) -> None:
        # Re-emit on both the new and legacy signal names.
        self.paragraph_pick_reroll_requested.emit(block_id, pick_index)
        self.reroll_requested.emit(block_id, pick_index)

    def _on_card_delete(self, block_id: str) -> None:
        for c in list(self._cards):
            if c._block_id == block_id:
                self._draft_lay.removeWidget(c)
                c.setParent(None); c.deleteLater()
                self._cards.remove(c)
                break
        self.paragraph_delete_requested.emit(block_id)
        self._sync_polished_view()
        if not self._cards:
            self._empty_hint.show()

    # ── Draft → polished / source sync ──────────────────────────────────
    def _compose_from_cards(self) -> str:
        """Join card body text into a single markdown document."""
        parts: list[str] = []
        for c in self._cards:
            t = c._body.text().strip()
            if t:
                parts.append(t)
        return "\n\n".join(parts)

    def _sync_polished_view(self) -> None:
        """Refresh the 初稿 editor.

        Prefers the fully-formatted draft markdown from ``compose_draft``
        (which carries numbering, headings, hero cards, 推荐理由 prefix
        and competitor-pool formatting). Falls back to composed card text
        for environments without a plan.
        """
        body = self._raw_draft_md.strip() or self._compose_from_cards()
        if self._title and body:
            md = f"# {self._title}\n\n{body}"
        elif self._title:
            md = f"# {self._title}"
        else:
            md = body
        # Escape "N. " list markers so Qt renders them inline with the text
        # rather than auto-indenting them as a QTextList. Keep them visually
        # left-aligned with surrounding paragraphs.
        import re as _re
        md = _re.sub(r"(?m)^(\d+)\.\s", r"\1\. ", md)
        self._updating_polished = True
        try:
            self.polished_edit.setMarkdown(md)
            self._apply_polished_typography()
        finally:
            self._updating_polished = False

    _sync_polished_from_cards = _sync_polished_view  # legacy alias

    def _apply_polished_typography(self) -> None:
        self._apply_typography(self.polished_edit)

    def _apply_final_typography(self) -> None:
        self._apply_typography(self.final_edit)

    @staticmethod
    def _apply_typography(edit) -> None:
        doc = edit.document()
        line_type = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
        # Strip markdown-list indentation — the picked content already carries
        # its own "1." / "一、" prefix from compose_draft, so Qt's auto-list
        # indent just double-nests it.
        block = doc.firstBlock()
        while block.isValid():
            tl = block.textList()
            if tl is not None:
                lfmt = tl.format()
                lfmt.setIndent(0)
                tl.setFormat(lfmt)
            cursor = QTextCursor(block)
            bfmt = block.blockFormat()
            bfmt.setLineHeight(_LINE_HEIGHT_PCT, line_type)
            bfmt.setIndent(0)
            bfmt.setLeftMargin(0)
            bfmt.setTextIndent(0)
            cursor.setBlockFormat(bfmt)
            size_fmt = QTextCharFormat()
            size_fmt.setFontPointSize(
                _BODY_PT if bfmt.headingLevel() == 0 else 16
            )
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.mergeCharFormat(size_fmt)
            block = block.next()
