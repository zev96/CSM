"""Two-tab markdown preview: draft + polished."""
from __future__ import annotations
import re
from PyQt6.QtGui import (
    QTextFrameFormat, QTextBlockFormat, QTextCharFormat, QTextListFormat,
    QTextCursor, QFont,
)

# Typography — Chinese print-size conventions. 小四 ≈ 12pt, 小三 ≈ 15pt.
# Line height is expressed as a percentage of the font's natural line
# height (ProportionalHeight type), so 150 == 1.5×.
_BODY_PT = 12
_HEADING_PT = 15
_LINE_HEIGHT_PCT = 150
# Extra breathing room inside the white document card. Combined with
# ``QTextDocument.setDocumentMargin`` below this gives the text a
# comfortable margin on all four sides.
_DOC_MARGIN_PX = 12
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QStackedWidget, QFrame, QWidget
from qfluentwidgets import (
    Pivot, TextEdit, CardWidget, TransparentPushButton, TransparentToolButton,
    FluentIcon,
)


# The editor sits inside a white rounded container so the text has a
# document-like surface against the page's tinted background. Padding
# keeps the text away from the edges.
_MD_STYLESHEET = """
TextEdit {
    border: none;
    background: white;
    padding: 28px 32px;
}
"""


# Matches an ordered-list marker at the start of a line: one-or-more
# digits, a dot, a space. ``compose_draft`` emits these as *literal
# prefixes* ("1. CEWEY DS18…") — they are not meant to be parsed as
# markdown ordered lists. Without escaping, ``setMarkdown`` turns them
# into ``QTextList`` items whose markers sit at a fixed indent that
# can't be flattened to the paragraph left edge. Escaping the dot
# (``1\. ``) tells markdown "this is literal text", so the paragraph
# renders flush-left like any other paragraph.
_ORDERED_LIST_PREFIX_RE = re.compile(r"(?m)^(\d+)\. ")


def _escape_ordered_list_prefixes(md: str) -> str:
    """Prevent ``setMarkdown`` from materialising leading "N. " as a list.

    The renderer already bakes the index into the text (see
    ``csm_core.assembler.render._prefix_join``). Treating those as
    list markers only hurts alignment — they should display as
    ordinary paragraph text.
    """
    return _ORDERED_LIST_PREFIX_RE.sub(r"\1\\. ", md)


class _DraftToolbar(QWidget):
    """Fluent-style formatting toolbar driving a QTextEdit's rich-text API.

    Buttons mutate the current selection / cursor position; the TextEdit
    stays editable, and ``toMarkdown()`` round-trips the result back to
    markdown source for the polish stage.
    """

    _HEADING_SIZES = {1: 20, 2: 16, 3: 14}

    def __init__(self, edit: "TextEdit", parent: QWidget | None = None):
        super().__init__(parent)
        self._edit = edit
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(2)

        self._add_text_btn(lay, "B", "加粗 (Ctrl+B)", self._toggle_bold, bold=True)
        self._add_text_btn(lay, "I", "斜体 (Ctrl+I)", self._toggle_italic,
                           italic=True)
        self._add_text_btn(lay, "U", "下划线 (Ctrl+U)", self._toggle_underline,
                           underline=True)
        lay.addSpacing(10)
        for lvl in (1, 2, 3):
            self._add_text_btn(lay, f"H{lvl}", f"{lvl} 级标题",
                               lambda _=False, L=lvl: self._set_heading(L))
        self._add_text_btn(lay, "正文", "恢复为正文段落",
                           lambda _=False: self._set_heading(0))
        lay.addSpacing(10)
        self._add_icon_btn(lay, FluentIcon.MENU, "无序列表", self._bullet_list)
        self._add_text_btn(lay, "1.", "有序列表", self._ordered_list)
        lay.addSpacing(10)
        self._add_icon_btn(lay, FluentIcon.BROOM, "清除格式", self._clear_format)
        lay.addStretch(1)

    # ── Button factories ─────────────────────────────────────────────
    def _add_text_btn(self, lay, text, tip, cb, *,
                      bold=False, italic=False, underline=False):
        btn = TransparentPushButton(text, self)
        btn.setFixedHeight(28)
        btn.setMinimumWidth(32)
        font = btn.font()
        font.setBold(bold)
        font.setItalic(italic)
        font.setUnderline(underline)
        btn.setFont(font)
        btn.setToolTip(tip)
        btn.clicked.connect(cb)
        lay.addWidget(btn)
        return btn

    def _add_icon_btn(self, lay, icon, tip, cb):
        btn = TransparentToolButton(icon, self)
        btn.setFixedSize(28, 28)
        btn.setToolTip(tip)
        btn.clicked.connect(cb)
        lay.addWidget(btn)
        return btn

    # ── Formatting actions ───────────────────────────────────────────
    def _toggle_bold(self) -> None:
        e = self._edit
        weight = (QFont.Weight.Normal
                  if e.fontWeight() > QFont.Weight.Normal
                  else QFont.Weight.Bold)
        e.setFontWeight(weight)

    def _toggle_italic(self) -> None:
        e = self._edit
        e.setFontItalic(not e.fontItalic())

    def _toggle_underline(self) -> None:
        e = self._edit
        e.setFontUnderline(not e.fontUnderline())

    def _set_heading(self, level: int) -> None:
        """Apply heading level 1-3 to the current block, or 0 to reset.

        Both the block format (QTextBlockFormat.heading_level — what
        toMarkdown reads to emit '##') and the char format (size/weight,
        so it looks right in the editor) get updated.
        """
        cursor = self._edit.textCursor()
        block_fmt = QTextBlockFormat()
        char_fmt = QTextCharFormat()
        if level == 0:
            base = self._edit.font().pointSizeF() or 11.0
            char_fmt.setFontPointSize(base)
            char_fmt.setFontWeight(QFont.Weight.Normal)
            block_fmt.setHeadingLevel(0)
        else:
            char_fmt.setFontPointSize(self._HEADING_SIZES[level])
            char_fmt.setFontWeight(QFont.Weight.Bold)
            block_fmt.setHeadingLevel(level)
        cursor.mergeBlockFormat(block_fmt)
        # Extend selection to whole block so the size change covers it.
        cursor.movePosition(cursor.MoveOperation.StartOfBlock)
        cursor.movePosition(cursor.MoveOperation.EndOfBlock,
                            cursor.MoveMode.KeepAnchor)
        cursor.mergeCharFormat(char_fmt)

    def _bullet_list(self) -> None:
        self._edit.textCursor().createList(QTextListFormat.Style.ListDisc)

    def _ordered_list(self) -> None:
        self._edit.textCursor().createList(QTextListFormat.Style.ListDecimal)

    def _clear_format(self) -> None:
        cursor = self._edit.textCursor()
        cursor.setCharFormat(QTextCharFormat())
        cursor.setBlockFormat(QTextBlockFormat())


def _strip_block_borders(edit) -> None:
    """Remove the root QTextFrame border that Qt draws around each block
    after ``setMarkdown`` / ``setHtml``. This is the source of the thin
    rectangular outline the user sees around every paragraph.
    """
    doc = edit.document()
    fmt = QTextFrameFormat()
    fmt.setBorder(0)
    fmt.setPadding(0)
    fmt.setMargin(0)
    doc.rootFrame().setFrameFormat(fmt)


def _apply_typography(edit) -> None:
    """Apply 小四 body / 小三 heading sizes + 1.5× line spacing to every block.

    ``setMarkdown`` bakes its own font sizes (Qt's defaults: 24/18/14 for
    H1/H2/H3, plus whatever the widget's base font is for prose) and no
    line-height at all. Walk every block after markdown parse and:

    * force body paragraphs to 小四 (12pt), headings to 小三 (15pt)
    * set a 1.5× proportional line height so paragraphs breathe
    * flatten list indentation so numbered / bulleted items sit at the
      same left edge as regular paragraphs (the markers render inline
      via the list format — they aren't lost, just un-indented)
    """
    doc = edit.document()
    line_type = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value

    block = doc.firstBlock()
    while block.isValid():
        cursor = QTextCursor(block)

        bfmt = block.blockFormat()
        bfmt.setLineHeight(_LINE_HEIGHT_PCT, line_type)

        text_list = block.textList()
        if text_list is not None:
            # Flatten the block-level indent so list content sits near the
            # paragraph left edge, but leave ``QTextListFormat.indent`` at
            # its default (≥ 1). Setting the list-format indent to 0 makes
            # Qt draw the "1." / "•" marker at a negative x-offset, which
            # clips it outside the viewport — list numbers silently
            # disappear. Keeping the list indent preserves the marker
            # while the block indent flatten keeps items left-aligned.
            bfmt.setIndent(0)
            bfmt.setLeftMargin(0)
            bfmt.setTextIndent(0)

        cursor.setBlockFormat(bfmt)

        # Size override: keep existing bold/italic runs (mergeCharFormat
        # with only pointSize set doesn't touch weight/italic).
        size_fmt = QTextCharFormat()
        size_fmt.setFontPointSize(
            _HEADING_PT if bfmt.headingLevel() > 0 else _BODY_PT,
        )
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.mergeCharFormat(size_fmt)

        block = block.next()


class MarkdownView(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QStackedWidget(self)
        self._pivot = Pivot(self)

        # Draft tab renders markdown for display (H1/H2 styled, lists, etc.)
        # AND stays editable — ``QTextEdit.toMarkdown()`` converts the
        # current rich-text document back to markdown for the polish stage,
        # so user edits round-trip cleanly through set_draft -> edit ->
        # get_draft_text.
        self.draft_edit = TextEdit(self)
        self.draft_edit.setReadOnly(False)
        self.polished_edit = TextEdit(self)
        self.polished_edit.setReadOnly(True)

        for edit in (self.draft_edit, self.polished_edit):
            edit.setFrameShape(QFrame.Shape.NoFrame)
            edit.setStyleSheet(_MD_STYLESHEET)
            # Give the document itself a breathing margin so the text
            # doesn't hug the left edge of the viewport.
            edit.document().setDocumentMargin(_DOC_MARGIN_PX)
            _strip_block_borders(edit)
            _apply_typography(edit)

        self._stack.addWidget(self.draft_edit)
        self._stack.addWidget(self.polished_edit)

        self._toolbar = _DraftToolbar(self.draft_edit, self)

        self._pivot.addItem(routeKey="draft", text="初稿")
        self._pivot.addItem(routeKey="polished", text="成文")
        self._pivot.currentItemChanged.connect(self._on_tab)
        self._pivot.setCurrentItem("draft")

        root = QVBoxLayout(self)
        root.addWidget(self._pivot)
        root.addWidget(self._toolbar)
        root.addWidget(self._stack, 1)

    def _on_tab(self, key: str):
        self._stack.setCurrentIndex(0 if key == "draft" else 1)
        # Toolbar only applies to the editable draft tab; hide it when
        # viewing the read-only polished output so there's no dead UI.
        self._toolbar.setVisible(key == "draft")

    def set_draft(self, md: str):
        # Render markdown for display; Qt keeps an internal rich-text
        # document that's editable, and ``toMarkdown`` reproduces the
        # markdown source on demand.
        self.draft_edit.setMarkdown(_escape_ordered_list_prefixes(md))
        _strip_block_borders(self.draft_edit)
        _apply_typography(self.draft_edit)

    def get_draft_text(self) -> str:
        return self.draft_edit.toMarkdown()

    def set_polished(self, md: str):
        # Only auto-switch to the 成文 tab when there's actual polished
        # content to show — otherwise a fresh generate that preloads an
        # empty polished string would leave the user on a blank tab.
        self.polished_edit.setMarkdown(_escape_ordered_list_prefixes(md))
        _strip_block_borders(self.polished_edit)
        _apply_typography(self.polished_edit)
        if md.strip():
            self._pivot.setCurrentItem("polished")
        else:
            self._pivot.setCurrentItem("draft")
