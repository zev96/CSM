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
from datetime import datetime, timedelta
from pathlib import Path
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

    def __init__(self, config: AppConfig, config_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self._config = config
        self._config_dir: Path | None = Path(config_dir) if config_dir else None
        self._yesterday_count_cached: int = 0
        self.setStyleSheet(_HERO_CARD_QSS + _TILE_QSS + _RECENT_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        # Eyebrow + title + stats — simple vertical stack. (The rotating
        # quote that briefly lived in the top-right was removed per
        # 用户反馈，简洁优先。)
        today = datetime.now()
        weekday = "一二三四五六日"[today.weekday()]

        eyebrow = QLabel(f"工作台 · {today.month}月{today.day}日 星期{weekday}", self)
        eyebrow.setObjectName("pageEyebrow")
        root.addWidget(eyebrow)

        self._greeting_label = QLabel(self._greeting(config.user_name), self)
        self._greeting_label.setObjectName("pageTitle")
        root.addWidget(self._greeting_label)

        self._sub_label = QLabel(self._stats_sub(), self)
        self._sub_label.setObjectName("pageSub")
        root.addWidget(self._sub_label)

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
        self.keyword_input.textChanged.connect(self._on_keyword_changed)
        self.keyword_input.returnPressed.connect(self._emit_generate)
        input_row.addWidget(self.keyword_input, 1)

        self.generate_button = PrimaryPushButton("开始生成", hero, FluentIcon.PLAY)
        self.generate_button.setMinimumHeight(42)
        self.generate_button.clicked.connect(self._emit_generate)
        input_row.addWidget(self.generate_button)
        left.addLayout(input_row)

        # ── Core-keyword chip ────────────────────────────────────────
        # Sits one line below the keyword input. Auto-syncs to whatever
        # the extractor pulls from the keyword; user can click 修改 to
        # override (e.g. "无线吸尘器哪款好用" → core "无线吸尘器", but
        # the user might want "吸尘器" instead). Hidden until the user
        # actually types something.
        core_row = QHBoxLayout()
        core_row.setSpacing(6)
        core_row.setContentsMargins(2, 0, 0, 0)
        self._core_label = QLabel("核心词：", hero)
        self._core_label.setStyleSheet(
            "color: rgba(30,28,25,0.45); font-size: 11.5px; background: transparent;"
        )
        core_row.addWidget(self._core_label)

        self._core_value = QLabel("—", hero)
        self._core_value.setStyleSheet(
            "color: rgba(30,28,25,0.78); font-size: 11.5px; font-weight: 500;"
            " background: transparent;"
        )
        core_row.addWidget(self._core_value)

        self._core_input = LineEdit(hero)
        self._core_input.setMaximumWidth(180)
        self._core_input.setFixedHeight(22)
        self._core_input.setPlaceholderText("覆盖核心词…")
        self._core_input.editingFinished.connect(self._on_core_edit_finished)
        self._core_input.hide()
        core_row.addWidget(self._core_input)

        self._core_edit_btn = QPushButton("✏️ 修改", hero)
        self._core_edit_btn.setFlat(True)
        self._core_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._core_edit_btn.setStyleSheet(
            "QPushButton { color: rgba(30,28,25,0.45); font-size: 11px;"
            " background: transparent; border: none; padding: 0 4px; }"
            "QPushButton:hover { color: #2f6f5e; }"
        )
        self._core_edit_btn.clicked.connect(self._enter_core_edit)
        core_row.addWidget(self._core_edit_btn)
        core_row.addStretch(1)

        # Wrap so we can hide the entire row at once before user types.
        self._core_row_widget = QWidget(hero)
        self._core_row_widget.setStyleSheet("background: transparent;")
        self._core_row_widget.setLayout(core_row)
        self._core_row_widget.hide()
        # Track whether the user has manually overridden the auto extraction —
        # keeps `_on_keyword_changed` from clobbering the override.
        self._core_user_override: str | None = None
        left.addWidget(self._core_row_widget)

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

    def _greeting(self, name: str | None) -> str:
        h = datetime.now().hour
        if h < 6:
            base, suffix = "夜深了", "休息吧"
        elif h < 11:
            base, suffix = "早上好", "今天写点什么"
        elif h < 14:
            base, suffix = "午安", "好好吃饭"
        elif h < 18:
            base, suffix = "下午好", "继续创作"
        else:
            base, suffix = "晚上好", "继续创作"
        if name:
            return f"{base}，{name}，{suffix}"
        return f"{base}，{suffix}"

    def _yesterday_count(self) -> int:
        """Count exports from ``recent_docs.json`` whose date == yesterday."""
        if self._config_dir is None:
            return 0
        try:
            from ..recent_docs import load_recent
            docs = load_recent(self._config_dir)
        except Exception:
            return 0
        yesterday = (datetime.now() - timedelta(days=1)).date()
        return sum(1 for d in docs if d.exported_dt.date() == yesterday)

    def _stats_sub(self) -> str:
        n = self._yesterday_count()
        self._yesterday_count_cached = n
        if n == 0:
            return "昨天还没动笔 — 今天起一篇吧。"
        return f"昨天处理了 {n} 篇文章，继续保持节奏。"

    def apply_user(self, name: str | None) -> None:
        """Refresh greeting + stats sub-line. Called whenever the local
        account name changes (first-run dialog, settings edit, avatar edit)."""
        self._greeting_label.setText(self._greeting(name))
        self._sub_label.setText(self._stats_sub())

    def _refresh_enabled(self):
        ok = self.form.is_valid() and bool(self.keyword_input.text().strip())
        self.generate_button.setEnabled(ok)

    def _emit_generate(self):
        if not self.generate_button.isEnabled():
            return
        payload = dict(self.form.payload())
        payload["keyword"] = self.keyword_input.text().strip()
        payload["core_keyword"] = self._current_core_keyword()
        self.request_generate.emit(payload)

    # ── Core-keyword chip behaviour ────────────────────────────────────
    def _current_core_keyword(self) -> str:
        """Return whatever core keyword should be used for body substitution.

        User override wins; otherwise auto-extract from the live keyword.
        """
        if self._core_user_override is not None:
            return self._core_user_override
        from csm_core.keyword import extract_core
        return extract_core(self.keyword_input.text().strip())

    def _on_keyword_changed(self, text: str) -> None:
        """Sync the core-keyword chip whenever the keyword input changes.

        Manual overrides are dropped on every keystroke — typing a new
        keyword reverts the chip to auto-extraction. (If we kept the
        override sticky, switching from "无线吸尘器哪款好用" to "扫地机器人"
        would still show 无线吸尘器 as the override.)
        """
        kw = (text or "").strip()
        if not kw:
            self._core_row_widget.hide()
            self._core_user_override = None
            return

        from csm_core.keyword import extract_core
        auto_core = extract_core(kw)
        # Drop any prior manual override on a fresh keystroke.
        self._core_user_override = None
        self._core_value.setText(auto_core)
        self._core_value.show()
        self._core_input.hide()
        self._core_edit_btn.show()
        self._core_row_widget.show()

    def _enter_core_edit(self) -> None:
        """Switch the chip into edit mode."""
        self._core_input.setText(self._core_value.text())
        self._core_value.hide()
        self._core_edit_btn.hide()
        self._core_input.show()
        self._core_input.setFocus()
        self._core_input.selectAll()

    def _on_core_edit_finished(self) -> None:
        """User finished editing the core keyword — commit or cancel."""
        new_value = self._core_input.text().strip()
        if not new_value:
            # Empty input → revert to auto.
            from csm_core.keyword import extract_core
            new_value = extract_core(self.keyword_input.text().strip())
            self._core_user_override = None
        else:
            self._core_user_override = new_value
        self._core_value.setText(new_value)
        self._core_input.hide()
        self._core_value.show()
        self._core_edit_btn.show()

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

    def __init__(self, config: AppConfig, config_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget(self)

        self._hero = _HeroView(config, config_dir, self)
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
        # Recents drives the "昨天处理 N 篇" sub-line — refresh after every
        # update (export, history clear, etc.) so the count stays honest.
        self._hero.apply_user(self._config.user_name)

    def apply_user(self, name: str | None) -> None:
        """Push the current local account name into the home greeting."""
        self._config.user_name = name  # keep cached config in sync
        self._hero.apply_user(name)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._hero.form.refresh_templates()
        self.batch_panel.form.refresh_templates()
