"""Skill 库 — gallery view + editor view (stacked).

Mirrors the prototype in ``cms/project/prototype/skills.jsx``:

* Header — title + sub + 查看文档 / 新建 Skill primary action.
* Filter row — 我的 · 团队 · 官方 · 全部 pills + name search.
* Card grid — one tile per ``.md`` file in ``cfg.skill_dir``. Each tile
  shows an avatar, name, an ownership chip, a 1-line description, and a
  footer with usage + last-edited mtime.

Clicking a card switches the page to the editor view (the existing
``SkillEditorPanel``) with a "← 返回" button to come back to the gallery.

The hidden ``self.list_panel`` is preserved as a data backing store + the
legacy test surface (``list_widget.setCurrentRow`` / ``_on_item_clicked``).
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QFrame, QLabel, QScrollArea, QButtonGroup, QSizePolicy,
)
from qfluentwidgets import (
    LineEdit, PushButton, PrimaryPushButton, ToolButton, FluentIcon,
    MessageBox, InfoBar, InfoBarPosition,
)

from ..config import AppConfig
from ..widgets.skill_list_panel import SkillListPanel, _read_skill_sample
from ..widgets.skill_editor_panel import SkillEditorPanel


# ── Design tokens ───────────────────────────────────────────────────────────
_INK    = "#1e1c19"
_INK_2  = "rgba(30,28,25,0.62)"
_INK_3  = "rgba(30,28,25,0.38)"
_INK_5  = "rgba(30,28,25,0.08)"
_ACCENT        = "#2f6f5e"
_ACCENT_SOFTER = "#ecf2ee"

# Avatar palette — picked deterministically from the skill stem so each
# tile keeps the same color across reloads. Soft pastels so the dot
# doesn't fight the card content for attention.
_AVATAR_PALETTE = [
    ("#2f6f5e", "#e6f1ec"),
    ("#a26a3a", "#f4e6d6"),
    ("#5b6cad", "#e3e6f4"),
    ("#a04b6b", "#f4e0e8"),
    ("#5d7b2c", "#e8efd9"),
    ("#7a4f9c", "#ece2f4"),
]


def _avatar_colors(stem: str) -> tuple[str, str]:
    h = int(hashlib.md5(stem.encode("utf-8")).hexdigest(), 16)
    return _AVATAR_PALETTE[h % len(_AVATAR_PALETTE)]


def _relative_mtime(path: Path) -> str:
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return ""
    now = datetime.now()
    delta = now - ts
    if delta < timedelta(minutes=1):
        return "刚刚"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} 分钟前"
    if now.date() == ts.date():
        return "今天"
    if now.date() - ts.date() == timedelta(days=1):
        return "昨天"
    if delta < timedelta(days=30):
        return f"{delta.days} 天前"
    if delta < timedelta(days=365):
        return f"{delta.days // 30} 个月前"
    return ts.strftime("%Y-%m")


# ── Gallery card ────────────────────────────────────────────────────────────
class _GalleryCard(QFrame):
    """One skill tile in the gallery grid."""

    from PyQt6.QtCore import pyqtSignal as _Signal
    clicked = _Signal(object)  # emits Path

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self._path = path
        self.setObjectName("SkillGalleryCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(116)
        self.setMaximumHeight(140)
        self._apply_style(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(8)

        # Header: avatar · name · 我的 chip
        head = QHBoxLayout(); head.setSpacing(10); head.setContentsMargins(0, 0, 0, 0)
        fg, bg = _avatar_colors(path.stem)
        avatar = QLabel(path.stem[:1].upper() if path.stem else "·", self)
        avatar.setFixedSize(28, 28)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 14px;"
            " font-weight: 700; font-size: 12px;"
        )
        head.addWidget(avatar)

        name = QLabel(path.stem, self)
        name.setStyleSheet(
            f"color: {_INK}; font-size: 13.5px; font-weight: 600; background: transparent;"
        )
        head.addWidget(name)

        chip = QLabel("我的", self)
        chip.setStyleSheet(
            f"color: {_ACCENT}; background: {_ACCENT_SOFTER};"
            " border-radius: 4px; padding: 1px 6px; font-size: 10.5px;"
        )
        head.addWidget(chip)
        head.addStretch(1)
        outer.addLayout(head)

        # Description — first prose line of the skill body.
        summary, _ = _read_skill_sample(path, max_lines=1)
        desc = QLabel(summary or "（空 Skill — 点击编辑）", self)
        desc.setWordWrap(True)
        desc.setMaximumHeight(36)
        desc.setStyleSheet(
            f"color: {_INK_2}; font-size: 12px; background: transparent;"
        )
        outer.addWidget(desc, 1)

        # Footer — usage + last-edited
        foot = QHBoxLayout(); foot.setSpacing(8); foot.setContentsMargins(0, 0, 0, 0)
        usage = QLabel("✏️ 已用 —", self)
        usage.setStyleSheet(f"color: {_INK_3}; font-size: 11px; background: transparent;")
        foot.addWidget(usage)
        foot.addStretch(1)
        edited = QLabel(f"🕐 {_relative_mtime(path)}", self)
        edited.setStyleSheet(f"color: {_INK_3}; font-size: 11px; background: transparent;")
        foot.addWidget(edited)
        outer.addLayout(foot)

    def path(self) -> Path:
        return self._path

    def enterEvent(self, ev):  # noqa: N802
        self._apply_style(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev):  # noqa: N802
        self._apply_style(False)
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path)
        super().mousePressEvent(ev)

    def _apply_style(self, hover: bool) -> None:
        bg = "#fafaf7" if hover else "#ffffff"
        border = _ACCENT if hover else _INK_5
        self.setStyleSheet(
            f"#SkillGalleryCard {{ background: {bg};"
            f" border: 1px solid {border}; border-radius: 12px; }}"
        )


# ── Filter pill ─────────────────────────────────────────────────────────────
class _FilterPill(PushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setStyleSheet(
            "PushButton { padding: 2px 14px; border-radius: 8px;"
            f" border: 1px solid {_INK_5}; background: #ffffff;"
            f" color: {_INK_2}; font-size: 12px; }}"
            "PushButton:checked {"
            f" background: {_INK}; color: #ffffff; border: 1px solid {_INK}; }}"
            "PushButton:hover:!checked {"
            f" border-color: rgba(30,28,25,0.18); }}"
        )


# ── Page ────────────────────────────────────────────────────────────────────
class SkillsPage(QWidget):
    """Gallery + editor stacked view."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("skillsPage")
        self._config = config
        self._gallery_cards: list[_GalleryCard] = []
        self._current_filter = "mine"
        self._search_text = ""

        # Hidden data + legacy compat — the new gallery cards mirror
        # ``list_panel._paths`` so test code that drives the ListWidget
        # (``setCurrentRow`` + ``_on_item_clicked``) keeps working.
        self.list_panel = SkillListPanel(self)
        self.list_panel.hide()
        self.list_panel.skill_selected.connect(self._on_skill_selected)
        self.list_panel.skill_dir_changed.connect(lambda _: self._rebuild_gallery())

        # Editor — same widget as before, hosted in the second stack page.
        self.editor_panel = SkillEditorPanel(self)
        self.editor_panel.saved.connect(self._on_saved)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_gallery_page())
        self._stack.addWidget(self._build_editor_page())
        root.addWidget(self._stack)

        if config.skill_dir:
            self.list_panel.set_directory(Path(config.skill_dir))

    # ── View construction ──────────────────────────────────────────────
    def _build_gallery_page(self) -> QWidget:
        page = QWidget(self)
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)

        # Header row
        head = QHBoxLayout(); head.setSpacing(10)
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        title = QLabel("Skill 库", page)
        title.setStyleSheet(f"color: {_INK}; font-size: 22px; font-weight: 600; background: transparent;")
        title_col.addWidget(title)
        sub = QLabel(
            "Skill 是复用写作风格的最小单元 · 可以基于样本训练，也可以从零配置 · hover 看示例输出",
            page,
        )
        sub.setStyleSheet(f"color: {_INK_2}; font-size: 12.5px; background: transparent;")
        title_col.addWidget(sub)
        head.addLayout(title_col, 1)

        self.docs_btn = PushButton(FluentIcon.DOCUMENT, "查看文档", page)
        self.docs_btn.setFixedHeight(30)
        head.addWidget(self.docs_btn)
        self.new_btn = PrimaryPushButton(FluentIcon.ADD, "新建 Skill", page)
        self.new_btn.setFixedHeight(30)
        # Reuse the existing wizard flow on the hidden list panel.
        self.new_btn.clicked.connect(self.list_panel._on_new)
        head.addWidget(self.new_btn)
        lay.addLayout(head)

        # Filter row — pills + search input
        filt = QHBoxLayout(); filt.setSpacing(8)
        self._pill_group = QButtonGroup(page); self._pill_group.setExclusive(True)
        self._pills: dict[str, _FilterPill] = {}
        for key, label in (("mine", "我的"), ("team", "团队"),
                           ("official", "官方"), ("all", "全部")):
            p = _FilterPill(label, page)
            self._pills[key] = p
            self._pill_group.addButton(p)
            p.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            filt.addWidget(p)
        self._pills["mine"].setChecked(True)

        self.search_input = LineEdit(page)
        self.search_input.setPlaceholderText("🔍  搜 Skill 名称…")
        self.search_input.setFixedHeight(28)
        self.search_input.setMaximumWidth(280)
        self.search_input.textChanged.connect(self._on_search_changed)
        filt.addWidget(self.search_input)
        filt.addStretch(1)
        lay.addLayout(filt)

        # Card grid (scrollable)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        host = QWidget(); host.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(host)
        self._grid.setContentsMargins(0, 4, 0, 4)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._grid_host = host

        self._empty_label = QLabel(
            "尚未配置 Skill 目录 — 在「设置 · 存储路径」中选择目录后即可创建。",
            host,
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {_INK_3}; font-size: 12.5px; padding: 40px 0; background: transparent;"
        )
        self._grid.addWidget(self._empty_label, 0, 0, 1, 3)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)
        self._scroll = scroll

        return page

    def _build_editor_page(self) -> QWidget:
        page = QWidget(self)
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 18, 28, 22)
        lay.setSpacing(10)

        # Top bar — back button + breadcrumb
        bar = QHBoxLayout(); bar.setSpacing(8)
        self.back_btn = PushButton(FluentIcon.LEFT_ARROW, "返回 Skill 库", page)
        self.back_btn.setFixedHeight(30)
        self.back_btn.clicked.connect(self._back_to_gallery)
        bar.addWidget(self.back_btn)
        bar.addStretch(1)
        lay.addLayout(bar)

        lay.addWidget(self.editor_panel, 1)
        return page

    # ── Gallery rendering ──────────────────────────────────────────────
    def _rebuild_gallery(self) -> None:
        # Tear down existing cards.
        for c in self._gallery_cards:
            c.setParent(None); c.deleteLater()
        self._gallery_cards = []
        # Clear all grid items (keep the empty label as a known item).
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is self._empty_label:
                continue
            if w is not None:
                w.setParent(None)

        paths = self._filtered_paths()
        # Update pill counts
        all_count = len(self.list_panel._paths)
        self._pills["mine"].setText(f"我的 · {all_count}")
        self._pills["team"].setText("团队 · 0")
        self._pills["official"].setText("官方 · 0")
        self._pills["all"].setText(f"全部 · {all_count}")

        if not paths:
            self._empty_label.setText(
                "未配置 Skill 目录 — 在「设置 · 存储路径」中选择目录后即可创建。"
                if self._config.skill_dir is None
                else "没有匹配的 Skill — 调整筛选条件或新建一个。"
            )
            self._grid.addWidget(self._empty_label, 0, 0, 1, 3)
            self._empty_label.show()
            return
        self._empty_label.hide()

        cols = max(1, self._columns_for_width(self._scroll.viewport().width()))
        for i, p in enumerate(paths):
            card = _GalleryCard(p, self._grid_host)
            card.clicked.connect(self._on_card_clicked)
            self._gallery_cards.append(card)
            self._grid.addWidget(card, i // cols, i % cols)
        # Keep the last row from stretching by adding a stretch on the next row
        self._grid.setRowStretch(len(paths) // cols + 1, 1)

    def _columns_for_width(self, w: int) -> int:
        # Mirror the prototype: ~280px tile minimum, gap 14px.
        if w < 640:
            return 1
        if w < 960:
            return 2
        return 3

    def _filtered_paths(self) -> list[Path]:
        paths = list(self.list_panel._paths)
        if self._current_filter in ("team", "official"):
            # No ownership metadata yet — these tiers are placeholders so
            # the filter UI matches the prototype, but show nothing.
            return []
        if self._search_text:
            q = self._search_text.lower()
            paths = [p for p in paths if q in p.stem.lower()]
        return paths

    def _set_filter(self, key: str) -> None:
        self._current_filter = key
        self._rebuild_gallery()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        self._rebuild_gallery()

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        # Re-flow grid columns when the viewport width changes.
        QTimer.singleShot(0, self._rebuild_gallery)

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        QTimer.singleShot(0, self._rebuild_gallery)

    # ── Event wiring ───────────────────────────────────────────────────
    def _on_card_clicked(self, path: Path) -> None:
        # Drive the same flow as the legacy list panel so the dirty
        # confirmation and select-by-path behaviours stay consistent.
        self.list_panel._on_card_clicked(path)

    def _on_skill_selected(self, path: Path) -> None:
        if self.editor_panel.is_dirty():
            decision = self._resolve_dirty()
            if decision == "save":
                if not self.editor_panel.save():
                    return
        self.editor_panel.load_skill(path)
        self._stack.setCurrentIndex(1)

    def _on_saved(self, path: Path) -> None:
        self.list_panel.refresh()
        self._rebuild_gallery()

    def _back_to_gallery(self) -> None:
        if self.editor_panel.is_dirty():
            decision = self._resolve_dirty()
            if decision == "save":
                if not self.editor_panel.save():
                    return
        self._stack.setCurrentIndex(0)
        self._rebuild_gallery()

    def _resolve_dirty(self) -> str:
        """Prompt on unsaved changes. Returns 'save' or 'discard'.
        Override in tests via monkeypatch."""
        dlg = MessageBox(
            "未保存的更改",
            "当前 Skill 有未保存的改动。是否保存？",
            self.window(),
        )
        dlg.yesButton.setText("保存")
        dlg.cancelButton.setText("丢弃")
        if dlg.exec():
            return "save"
        return "discard"

    # ── Public API ─────────────────────────────────────────────────────
    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        if cfg.skill_dir:
            self.list_panel.set_directory(Path(cfg.skill_dir))
        else:
            self.editor_panel.clear()
            self._stack.setCurrentIndex(0)
        self._rebuild_gallery()
