"""Home page — Hero input + auxiliary tile grid + recent docs.

Layout mirrors the Claude-Design prototype (组合方案 ②B):

* Eyebrow with today's date
* Large greeting + stats sub-line
* Hero card: keyword input (+ template combo) on the left, 2×2 tile grid
  on the right. Primary CTA is the ink-green "开始生成" button.
* Recent-docs list card below

The page exposes two route-out signals — ``request_navigate`` emits a key
("templates" / "skills" / "batch" / "wizard") and the main window decides
where to send the user. ``request_show_batch`` pops the internal batch
panel (kept to preserve the single/batch flow without a navigation jump).
"""
from __future__ import annotations
from datetime import datetime
from PyQt6.QtCore import pyqtSignal, Qt, QEvent
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QFrame, QLabel, QSizePolicy, QPushButton,
)
from qfluentwidgets import (
    BodyLabel, LineEdit, PrimaryPushButton, PushButton, FluentIcon,
    CardWidget, SimpleCardWidget, ComboBox,
)
from ..config import AppConfig
from ..widgets.generation_form import GenerationForm
from ..widgets.batch_panel import BatchPanel
from ..recent_docs import RecentDoc, load_recent, relative_when


# ── Shared style fragments ──────────────────────────────────────────────

_HERO_CARD_QSS = """
#heroCard {
    background-color: #ffffff;
    border: 1px solid rgba(30,28,25,0.08);
    border-radius: 14px;
}
#heroCard QLineEdit {
    border: none;
    background: transparent;
    font-size: 15px;
    padding: 10px 4px;
}
#heroEyebrow, #pageEyebrow {
    color: rgba(30,28,25,0.38);
    font-size: 11px;
    letter-spacing: 1.2px;
}
#pageTitle {
    font-size: 28px;
    font-weight: 600;
    color: #1e1c19;
    letter-spacing: -0.4px;
}
#pageSub {
    color: rgba(30,28,25,0.62);
    font-size: 13px;
}
#sectionTitle {
    font-size: 15px;
    font-weight: 600;
    color: #1e1c19;
}
"""

_TILE_QSS = """
CardTile {
    background-color: #faf8f3;
    border: 1px solid rgba(30,28,25,0.06);
    border-radius: 12px;
}
CardTile:hover {
    background-color: #ecf2ee;
    border: 1px solid rgba(47,111,94,0.35);
}
CardTile QLabel#tileTitle {
    font-size: 13px;
    font-weight: 600;
    color: #1e1c19;
}
CardTile QLabel#tileDesc {
    font-size: 11.5px;
    color: rgba(30,28,25,0.62);
}
CardTile QLabel#tileIco {
    background-color: #dde9e3;
    border-radius: 9px;
    min-width: 30px;
    min-height: 30px;
    max-width: 30px;
    max-height: 30px;
    qproperty-alignment: AlignCenter;
}
"""

_RECENT_QSS = """
#recentCard {
    background-color: #ffffff;
    border: 1px solid rgba(30,28,25,0.08);
    border-radius: 12px;
}
RecentRow {
    background-color: transparent;
    border-radius: 8px;
}
RecentRow:hover {
    background-color: #faf8f3;
}
RecentRow QLabel#recentTitle {
    font-size: 13px;
    color: #1e1c19;
}
RecentRow QLabel#recentMeta {
    font-size: 11.5px;
    color: rgba(30,28,25,0.62);
}
"""


class _Chip(QLabel):
    """Small rounded tag for template / status badges."""

    def __init__(self, text: str, variant: str = "", parent=None):
        super().__init__(text, parent)
        colors = {
            "":        ("rgba(30,28,25,0.06)", "rgba(30,28,25,0.62)"),
            "accent":  ("#dde9e3",             "#2f6f5e"),
            "warn":    ("#f4e8cf",             "#8f6a18"),
            "outline": ("transparent",         "rgba(30,28,25,0.62)"),
        }
        bg, fg = colors.get(variant, colors[""])
        border = "1px solid rgba(30,28,25,0.12)" if variant == "outline" else "none"
        self.setStyleSheet(
            f"padding: 2px 8px; border-radius: 6px;"
            f"background-color: {bg}; color: {fg}; font-size: 11px;"
            f"border: {border};"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class CardTile(QFrame):
    """2×2 auxiliary tile in the hero grid."""

    clicked = pyqtSignal()

    def __init__(self, icon: FluentIcon, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setObjectName("cardTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        self._ico_label = QLabel(self)
        self._ico_label.setObjectName("tileIco")
        pm = icon.icon().pixmap(16, 16)
        self._ico_label.setPixmap(pm)
        root.addWidget(self._ico_label)

        title_label = QLabel(title, self)
        title_label.setObjectName("tileTitle")
        root.addWidget(title_label)

        desc_label = QLabel(desc, self)
        desc_label.setObjectName("tileDesc")
        desc_label.setWordWrap(True)
        root.addWidget(desc_label)
        root.addStretch(1)

    def mousePressEvent(self, ev):  # noqa: N802 — Qt signature
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class RecentRow(QFrame):
    """Single row in the recent-documents list."""

    clicked = pyqtSignal()

    def __init__(self, title: str, tpl: str, when: str, status: str, parent=None):
        super().__init__(parent)
        self.setObjectName("recentRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(12)

        title_label = QLabel(title, self)
        title_label.setObjectName("recentTitle")
        title_label.setMinimumWidth(320)
        row.addWidget(title_label, 1)

        row.addWidget(_Chip(tpl, "outline", self))

        meta = QLabel(when, self)
        meta.setObjectName("recentMeta")
        row.addWidget(meta)

        variant = {"已发布": "accent", "归档": "", "草稿": "warn"}.get(status, "")
        row.addWidget(_Chip(status, variant, self))

        chev = QLabel("›", self)
        chev.setStyleSheet("color: rgba(30,28,25,0.38); font-size: 16px;")
        row.addWidget(chev)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class _HeroView(QWidget):
    """Hero + tile grid + recent docs — primary home view."""

    request_generate = pyqtSignal(dict)
    request_navigate = pyqtSignal(str)  # 'templates' | 'skills' | 'batch' | 'wizard' | 'recents'

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self.setStyleSheet(_HERO_CARD_QSS + _TILE_QSS + _RECENT_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        # Eyebrow + title + stats
        today = datetime.now()
        weekday = "一二三四五六日"[today.weekday()]
        eyebrow = QLabel(f"工作台 · {today.month}月{today.day}日 星期{weekday}", self)
        eyebrow.setObjectName("pageEyebrow")
        root.addWidget(eyebrow)

        title = QLabel(self._greeting(), self)
        title.setObjectName("pageTitle")
        root.addWidget(title)

        sub = QLabel("用关键词起一篇，或从模板 / Skill 开始。", self)
        sub.setObjectName("pageSub")
        root.addWidget(sub)

        root.addSpacing(18)

        # Hero card
        hero = QFrame(self)
        hero.setObjectName("heroCard")
        hero_outer = QHBoxLayout(hero)
        hero_outer.setContentsMargins(22, 20, 22, 20)
        hero_outer.setSpacing(22)

        # Left — input column
        left = QVBoxLayout()
        left.setSpacing(10)
        left_eyebrow = QLabel("最常用 · 写一篇", self)
        left_eyebrow.setObjectName("heroEyebrow")
        left.addWidget(left_eyebrow)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.keyword_input = LineEdit(hero)
        self.keyword_input.setPlaceholderText("输入关键词 / 粘贴链接 / 描述一个选题…")
        self.keyword_input.setMinimumHeight(42)
        f = self.keyword_input.font()
        f.setPointSize(max(f.pointSize() + 1, 11))
        self.keyword_input.setFont(f)
        self.keyword_input.textChanged.connect(self._refresh_enabled)
        self.keyword_input.returnPressed.connect(self._emit_generate)
        input_row.addWidget(self.keyword_input, 1)

        self.generate_button = PrimaryPushButton("开始生成", hero, FluentIcon.PLAY)
        self.generate_button.setMinimumHeight(42)
        self.generate_button.clicked.connect(self._emit_generate)
        input_row.addWidget(self.generate_button)
        left.addLayout(input_row)

        # Compact template selector — keeps the functional contract.
        self.form = GenerationForm(config, hero)
        self.form.changed.connect(self._refresh_enabled)
        self.form.layout().setContentsMargins(0, 0, 0, 0)
        self.form.layout().setSpacing(6)
        left.addWidget(self.form)

        left.addStretch(1)
        hero_outer.addLayout(left, 3)

        # Right — 2×2 tile grid
        tile_grid = QGridLayout()
        tile_grid.setSpacing(10)
        tile_grid.setContentsMargins(0, 0, 0, 0)
        tiles = [
            (FluentIcon.EDIT,      "粘贴原文洗稿", "粘贴一段 → 选 Skill → 生成候选", "paste"),
            (FluentIcon.MENU,      "批量跑一批",   "上传 CSV 或关键词列表 · 一次跑 10+", "batch"),
            (FluentIcon.LIBRARY,   "用模板起稿",   "产品测评 · 节点梳理 · 投放文", "templates"),
            (FluentIcon.DICTIONARY, "自定义 Skill", "把个人风格做成可复用的 Skill", "skills"),
        ]
        for i, (icon, title_text, desc, key) in enumerate(tiles):
            tile = CardTile(icon, title_text, desc, hero)
            tile.clicked.connect(lambda _=None, k=key: self._on_tile(k))
            tile_grid.addWidget(tile, i // 2, i % 2)
        tile_grid.setRowStretch(0, 1)
        tile_grid.setRowStretch(1, 1)
        tile_grid.setColumnStretch(0, 1)
        tile_grid.setColumnStretch(1, 1)

        grid_wrap = QWidget(hero)
        grid_wrap.setLayout(tile_grid)
        grid_wrap.setMinimumWidth(320)
        grid_wrap.setMaximumWidth(420)
        hero_outer.addWidget(grid_wrap, 2)

        root.addWidget(hero)
        root.addSpacing(18)

        # Recent docs header
        recent_hdr = QHBoxLayout()
        recent_title = QLabel("最近的文档", self)
        recent_title.setObjectName("sectionTitle")
        recent_hdr.addWidget(recent_title)
        recent_hdr.addStretch(1)
        all_link = QLabel(
            "<a href='#' style='color:rgba(30,28,25,0.62);text-decoration:none;'>全部 →</a>", self)
        all_link.linkActivated.connect(lambda _=None: self.request_navigate.emit("recents"))
        recent_hdr.addWidget(all_link)
        root.addLayout(recent_hdr)

        self._recent_card = QFrame(self)
        self._recent_card.setObjectName("recentCard")
        self._recent_vbox = QVBoxLayout(self._recent_card)
        self._recent_vbox.setContentsMargins(6, 6, 6, 6)
        self._recent_vbox.setSpacing(2)
        root.addWidget(self._recent_card)
        root.addStretch(1)
        self._render_recents()

        self._refresh_enabled()

    def set_recents(self, docs: list[RecentDoc]) -> None:
        self._recents = list(docs)
        self._render_recents()

    def _render_recents(self) -> None:
        # Clear existing rows.
        while self._recent_vbox.count():
            item = self._recent_vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None); w.deleteLater()
        docs = getattr(self, "_recents", [])
        if not docs:
            empty = QLabel(
                "尚无导出记录 — 在创作区生成并导出一篇即可。", self._recent_card)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                "color: rgba(30,28,25,0.38); font-size: 12px;"
                " padding: 18px 0; background: transparent;"
            )
            self._recent_vbox.addWidget(empty)
            return
        for doc in docs[:5]:
            tpl_label = "Markdown" if doc.fmt == "markdown" else "Word"
            row = RecentRow(doc.title, tpl_label, relative_when(doc.exported_dt),
                            doc.status, self._recent_card)
            self._recent_vbox.addWidget(row)

    def _greeting(self) -> str:
        h = datetime.now().hour
        if h < 6:
            return "夜深了，休息吧"
        if h < 11:
            return "早上好，今天写点什么"
        if h < 14:
            return "午安，好好吃饭"
        if h < 18:
            return "下午好，继续创作"
        return "晚上好，继续创作"

    def _refresh_enabled(self):
        ok = self.form.is_valid() and bool(self.keyword_input.text().strip())
        self.generate_button.setEnabled(ok)

    def _emit_generate(self):
        if not self.generate_button.isEnabled():
            return
        payload = dict(self.form.payload())
        payload["keyword"] = self.keyword_input.text().strip()
        self.request_generate.emit(payload)

    def _on_tile(self, key: str) -> None:
        if key == "paste":
            self.keyword_input.setFocus()
            return
        self.request_navigate.emit(key)

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self.form.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        if busy:
            self.generate_button.setEnabled(False)
        else:
            self._refresh_enabled()


class HomePage(QWidget):
    """Home page — Hero view by default, batch panel pops on demand."""

    request_generate = pyqtSignal(dict)
    request_batch = pyqtSignal(dict)
    # 'templates' | 'skills' | 'wizard' — main window handles these.
    request_navigate = pyqtSignal(str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget(self)

        self._hero = _HeroView(config, self)
        self._hero.request_generate.connect(self.request_generate.emit)
        self._hero.request_navigate.connect(self._on_navigate)
        self.stack.addWidget(self._hero)

        self.batch_panel = BatchPanel(config, self)
        self.batch_panel.request_batch.connect(self.request_batch.emit)
        batch_wrap = QWidget(self)
        batch_box = QVBoxLayout(batch_wrap)
        batch_box.setContentsMargins(28, 22, 28, 24)
        batch_box.setSpacing(10)
        back_row = QHBoxLayout()
        back_btn = PushButton("← 返回工作台", batch_wrap, FluentIcon.RETURN)
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        back_row.addWidget(back_btn)
        back_row.addStretch(1)
        batch_box.addLayout(back_row)
        batch_header = QLabel("批量跑一批", batch_wrap)
        batch_header.setStyleSheet("font-size: 22px; font-weight: 600; color: #1e1c19;")
        batch_box.addWidget(batch_header)
        batch_box.addWidget(self.batch_panel, 1)
        self.stack.addWidget(batch_wrap)

        root.addWidget(self.stack, 1)

    # Alias for legacy callers that expected ``single_panel`` / ``batch_panel``
    @property
    def single_panel(self):
        return self._hero

    def _on_navigate(self, key: str) -> None:
        if key == "batch":
            self.stack.setCurrentIndex(1)
            return
        self.request_navigate.emit(key)

    def apply_config(self, cfg: AppConfig) -> None:
        self._config = cfg
        self._hero.apply_config(cfg)
        self.batch_panel.apply_config(cfg)

    def set_busy(self, busy: bool) -> None:
        self._hero.set_busy(busy)
        self.batch_panel.set_busy(busy)

    def set_recents(self, docs) -> None:
        self._hero.set_recents(docs)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._hero.form.refresh_templates()
        self.batch_panel.form.refresh_templates()
