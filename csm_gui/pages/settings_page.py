"""Settings page — 2-column layout matching the Claude Design handoff.

Left: vertical icon+label nav (groups). Right: scrollable column of
``SettingsCard``s; each card has a header (title + sub) and a body of
``SettingsRow``s — left side is a label + hint, right side holds the
control. Mirrors ``cms/project/prototype/settings.jsx``.

The actual config schema is smaller than the prototype's (no team /
account / cloud sync yet), so the 通用 / 导出 / 账号 sections render as
read-only placeholders — wired only when those features land.
"""
from __future__ import annotations
import hashlib
import os
import sys
import subprocess
from typing import Callable, Literal, cast


def _provider_signature(api_key: str, model: str, base_url: str) -> str:
    """Stable hash of (key, model, base_url).

    Used as the "this triplet tested OK" marker. We compare hashes (not
    plaintext) so a settings.json reader can't trivially recover working
    api_key + model + custom-url combinations from this field — the
    api_key is already in the file, but no need to duplicate it.
    """
    payload = f"{api_key}\n{model}\n{base_url}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QStackedWidget,
    QScrollArea, QFrame, QLabel, QButtonGroup, QSizePolicy,
)


class _AdaptiveStack(QWidget):
    """Stacked container that ONLY reports the current page's size.

    ``QStackedWidget`` uses ``QStackedLayout``, whose ``minimumSize()``
    is the max of ALL children regardless of visibility. That forces the
    enclosing scroll-area host to the height of the tallest page (模型),
    so a short page (通用 / 关于) renders inside an over-tall host and
    QScrollArea draws a phantom vertical scrollbar.

    Replacement: a plain ``QVBoxLayout`` plus manual show/hide. Hidden
    children contribute zero to a QBoxLayout's minimum/preferred size,
    so the host shrinks to the actual current page and the scrollbar
    only appears when the page genuinely overflows.

    Exposes the small subset of ``QStackedWidget`` API the rest of the
    file uses: ``addWidget``, ``setCurrentIndex``, ``currentIndex``,
    ``currentWidget``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._pages: list[QWidget] = []
        self._current: int = -1

    def addWidget(self, w: QWidget) -> int:  # type: ignore[override]
        idx = len(self._pages)
        self._lay.addWidget(w)
        self._pages.append(w)
        if self._current < 0:
            self._current = idx
            w.setVisible(True)
        else:
            w.setVisible(False)
        return idx

    def setCurrentIndex(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._pages) or idx == self._current:
            return
        self._current = idx
        for i, w in enumerate(self._pages):
            w.setVisible(i == idx)
        self.updateGeometry()

    def currentIndex(self) -> int:
        return self._current

    def currentWidget(self) -> QWidget | None:
        if 0 <= self._current < len(self._pages):
            return self._pages[self._current]
        return None
from qfluentwidgets import (
    ComboBox, SpinBox, DoubleSpinBox, LineEdit, PasswordLineEdit,
    PrimaryPushButton, PushButton, ToolButton, FluentIcon,
    SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel, CardWidget,
    SwitchButton,
)

from ..config import AppConfig, MonitorConfig, Provider


# ── Color tokens (mirrors theme.css `--ink-*`) ───────────────────────────────
_INK = "#1e1c19"
_INK_2 = "rgba(30,28,25,0.62)"
_INK_3 = "rgba(30,28,25,0.38)"
_INK_5 = "rgba(30,28,25,0.08)"
_SURFACE = "#ffffff"
_ACCENT = "#2f6f5e"


# ── Building blocks ──────────────────────────────────────────────────────────

class _SettingsRow(QWidget):
    """Two-column row: 220px label/hint + flexible control area."""

    def __init__(self, label: str, hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsRow")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 12)
        outer.setSpacing(18)

        left = QWidget(self)
        left.setFixedWidth(220)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(3)
        title = QLabel(label, left)
        title.setStyleSheet(
            f"color: {_INK}; font-size: 13px; font-weight: 500; background: transparent;"
        )
        left_lay.addWidget(title)
        if hint:
            sub = QLabel(hint, left)
            sub.setWordWrap(True)
            sub.setStyleSheet(
                f"color: {_INK_3}; font-size: 11px; line-height: 1.5; background: transparent;"
            )
            left_lay.addWidget(sub)
        outer.addWidget(left, 0, Qt.AlignmentFlag.AlignTop)

        self._right = QWidget(self)
        self._right_lay = QHBoxLayout(self._right)
        self._right_lay.setContentsMargins(0, 0, 0, 0)
        self._right_lay.setSpacing(8)
        outer.addWidget(self._right, 1)

    def set_control(self, *widgets: QWidget) -> None:
        for w in widgets:
            self._right_lay.addWidget(w)
        self._right_lay.addStretch(1)


class _SettingsCard(QFrame):
    """Card with a title header and body slot for SettingsRows."""

    def __init__(self, title: str, sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsCard")
        self.setStyleSheet(
            f"#SettingsCard {{ background: {_SURFACE}; border: 1px solid {_INK_5};"
            f" border-radius: 12px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header.setStyleSheet(f"border-bottom: 1px solid {_INK_5};")
        head_lay = QVBoxLayout(header)
        head_lay.setContentsMargins(22, 18, 22, 14)
        head_lay.setSpacing(4)
        h = QLabel(title, header)
        h.setStyleSheet(
            f"color: {_INK}; font-size: 15px; font-weight: 600; background: transparent;"
            " border: none;"
        )
        head_lay.addWidget(h)
        if sub:
            s = QLabel(sub, header)
            s.setWordWrap(True)
            s.setStyleSheet(
                f"color: {_INK_2}; font-size: 12px; background: transparent; border: none;"
            )
            head_lay.addWidget(s)
        outer.addWidget(header)

        self._body = QWidget(self)
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(22, 4, 22, 14)
        self._body_lay.setSpacing(0)
        outer.addWidget(self._body)

    def add_row(self, row: _SettingsRow) -> None:
        # Dashed divider between rows — matches prototype's `border-bottom: 1px dashed`
        if self._body_lay.count() > 0:
            sep = QFrame(self._body)
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {_INK_5}; background: transparent; border: none;"
                              f" border-top: 1px dashed {_INK_5};")
            sep.setFixedHeight(1)
            self._body_lay.addWidget(sep)
        self._body_lay.addWidget(row)


class _PathField(QFrame):
    """Folder icon + monospaced path label + 选择 / 打开 buttons.

    Mirrors ``.path-field`` in the prototype. Emits no signals; callers
    read ``text()`` after the user picks a path.
    """

    def __init__(self, mode: str = "dir", parent=None):
        super().__init__(parent)
        self._mode = mode  # 'dir' or 'file'
        self.setObjectName("PathField")
        self.setStyleSheet(
            f"#PathField {{ background: {_SURFACE}; border: 1px solid {_INK_5};"
            f" border-radius: 8px; }}"
        )
        self.setFixedHeight(38)
        self.setMinimumWidth(360)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(8)

        ico = ToolButton(FluentIcon.FOLDER, self)
        ico.setEnabled(False)
        ico.setFixedSize(20, 20)
        ico.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(ico)

        self._value_label = QLabel("（未设置）", self)
        self._value_label.setStyleSheet(
            f"color: {_INK}; font-size: 12px; background: transparent;"
            " font-family: 'Consolas','Cascadia Mono','SF Mono',monospace;"
        )
        self._value_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Preferred)
        lay.addWidget(self._value_label, 1)

        self._choose_btn = PushButton("选择…", self)
        self._choose_btn.setFixedHeight(26)
        self._choose_btn.clicked.connect(self._pick)
        lay.addWidget(self._choose_btn)

        self._open_btn = ToolButton(FluentIcon.LINK, self)
        self._open_btn.setFixedSize(26, 26)
        self._open_btn.setToolTip("在文件管理器中打开")
        self._open_btn.clicked.connect(self._open_in_explorer)
        lay.addWidget(self._open_btn)

        # Hidden plain LineEdit so legacy tests / callers can still read
        # the underlying string via ``self.input.text()``.
        self.input = LineEdit(self)
        self.input.hide()

    # Public API mirroring the old _PathRow used in tests.
    def text(self) -> str:
        return self.input.text()

    def setText(self, s: str) -> None:
        s = s or ""
        self.input.setText(s)
        self._value_label.setText(s if s else "（未设置）")
        self._value_label.setToolTip(s)

    def _pick(self) -> None:
        if self._mode == "dir":
            p = QFileDialog.getExistingDirectory(self, "选择目录", self.text() or "")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "选择文件", self.text() or "",
                                               filter="JSON (*.json)")
        if p:
            self.setText(p)

    def _open_in_explorer(self) -> None:
        path = self.text()
        if not path:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass


class _NavButton(QFrame):
    """Sidebar entry: icon + label, full-width, dark when active.

    Built as a QFrame (not a QPushButton) so we have full control over
    icon-left + label-right ordering — Qt's PushButton ignores layout
    direction once a custom ``text-align`` QSS rule is applied, which is
    why the previous version drew the icon flush to the right edge.
    """

    from PyQt6.QtCore import pyqtSignal as _Signal
    clicked = _Signal()

    def __init__(self, label: str, icon: FluentIcon, parent=None):
        super().__init__(parent)
        self._checked = False
        self.setObjectName("NavButton")
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._icon = QLabel(self)
        self._icon.setFixedSize(16, 16)
        self._icon_enum = icon
        self._paint_icon(_INK)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel(label, self)
        self._label.setStyleSheet(
            f"color: {_INK}; font-size: 13px; background: transparent;"
        )
        lay.addWidget(self._label, 1, Qt.AlignmentFlag.AlignVCenter)

        self._apply_style()

    def _paint_icon(self, color: str) -> None:
        from PyQt6.QtGui import QPixmap, QPainter, QColor
        pm = QPixmap(16, 16)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        try:
            self._icon_enum.icon(color=QColor(color)).paint(painter, 0, 0, 16, 16)
        finally:
            painter.end()
        self._icon.setPixmap(pm)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        self._apply_style()

    def _apply_style(self) -> None:
        if self._checked:
            self.setStyleSheet(
                f"#NavButton {{ background: {_INK}; border-radius: 8px; }}"
            )
            self._label.setStyleSheet(
                "color: white; font-size: 13px; font-weight: 500; background: transparent;"
            )
            self._paint_icon("#ffffff")
        else:
            self.setStyleSheet(
                f"#NavButton {{ background: transparent; border-radius: 8px; }}"
                f"#NavButton:hover {{ background: {_INK_5}; }}"
            )
            self._label.setStyleSheet(
                f"color: {_INK}; font-size: 13px; background: transparent;"
            )
            self._paint_icon(_INK)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ── Provider registry (display metadata) ────────────────────────────────────

# Per-provider presets: display name, badge (2-char), dot color, base url,
# curated model list, and default context / output limits. The model list is
# editable (EditableComboBox) so users can type a custom model id too.
_PROVIDER_META: list[dict] = [
    {
        "key": "anthropic",
        "name": "Claude",
        "vendor": "Anthropic",
        "badge": "C4",
        "badge_bg": "#efd9c7",
        "base_url": "api.anthropic.com",
        "default_base_url": "https://api.anthropic.com",
        "api_style": "Anthropic",
        "default_model": "claude-sonnet-4-6",
        "key_placeholder": "sk-ant-...",
    },
    {
        "key": "deepseek",
        "name": "DeepSeek",
        "vendor": "DeepSeek",
        "badge": "DS",
        "badge_bg": "#d8e4f0",
        "base_url": "api.deepseek.com",
        "default_base_url": "https://api.deepseek.com/v1",
        "api_style": "OpenAI",
        # See https://api-docs.deepseek.com/zh-cn/ — model names are free-text
        # so the user can pick whichever variant their account has access to.
        "default_model": "deepseek-chat",
        "key_placeholder": "sk-...",
    },
    {
        "key": "openai",
        "name": "GPT",
        "vendor": "OpenAI",
        "badge": "G4",
        "badge_bg": "#d4ead9",
        "base_url": "api.openai.com",
        "default_base_url": "https://api.openai.com/v1",
        "api_style": "OpenAI",
        "default_model": "gpt-4o",
        "key_placeholder": "sk-...",
    },
    {
        "key": "gemini",
        "name": "Gemini",
        "vendor": "Google",
        "badge": "GE",
        "badge_bg": "#dde7f4",
        "base_url": "generativelanguage.googleapis.com",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_style": "OpenAI",
        "default_model": "gemini-2.5-pro",
        "key_placeholder": "AIza...",
    },
    {
        "key": "qwen",
        "name": "通义千问",
        "vendor": "Alibaba",
        "badge": "QW",
        "badge_bg": "#f4e0d6",
        "base_url": "dashscope.aliyuncs.com",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_style": "OpenAI",
        "default_model": "qwen-max",
        "key_placeholder": "sk-...",
    },
]


class _ProviderCard(QFrame):
    """Single model card — matches the settings.jsx 已连接模型 grid tile."""

    from PyQt6.QtCore import pyqtSignal as _Signal
    test_clicked = _Signal(str)     # provider key
    default_clicked = _Signal(str)  # provider key

    def __init__(self, meta: dict, parent=None):
        super().__init__(parent)
        self._meta = meta
        self._placeholder = bool(meta.get("placeholder", False))
        self.setObjectName("ProviderCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._is_default = False
        # Signature of (key, model, base_url) at the moment the user last
        # ran 测试连接 successfully. Restored from AppConfig on startup so
        # the green 已连接 badge persists across restarts.
        self._tested_signature: str | None = None
        # Transient flag set when 测试连接 fails. Cleared on any field edit
        # so the user can recover from "● 连接失败" by re-typing without
        # the page hanging on to a stale error state.
        self._last_test_failed: bool = False
        self._apply_card_style()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        # Header row: badge + name/vendor + status pill + 默认 badge
        head = QHBoxLayout(); head.setSpacing(10)
        badge = QLabel(meta["badge"], self)
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {meta['badge_bg']}; color: {_INK};"
            " border-radius: 8px; font-weight: 700; font-size: 12px;"
        )
        head.addWidget(badge)

        name_wrap = QVBoxLayout(); name_wrap.setSpacing(0); name_wrap.setContentsMargins(0, 0, 0, 0)
        name_row = QHBoxLayout(); name_row.setSpacing(6); name_row.setContentsMargins(0, 0, 0, 0)
        name = QLabel(meta["name"], self)
        name.setStyleSheet(f"color: {_INK}; font-size: 14px; font-weight: 600; background: transparent;")
        name_row.addWidget(name)
        self._default_badge = QLabel("默认", self)
        self._default_badge.setStyleSheet(
            f"color: {_INK_2}; background: {_INK_5}; border-radius: 4px;"
            " padding: 1px 6px; font-size: 10.5px;"
        )
        self._default_badge.hide()
        name_row.addWidget(self._default_badge)
        name_row.addStretch(1)
        name_wrap.addLayout(name_row)

        vendor = QLabel(f"{meta['vendor']} · {meta['base_url']}", self)
        vendor.setStyleSheet(f"color: {_INK_3}; font-size: 11px; background: transparent;")
        name_wrap.addWidget(vendor)
        head.addLayout(name_wrap, 1)

        self._status = QLabel("● 未配置", self)
        self._status.setStyleSheet(
            f"color: {_INK_3}; background: {_INK_5}; border-radius: 10px;"
            " padding: 2px 10px; font-size: 10.5px;"
        )
        head.addWidget(self._status, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(head)

        # Helper to build a labeled field row with consistent label width.
        def _field(label: str, control: QWidget) -> QHBoxLayout:
            row = QHBoxLayout(); row.setSpacing(8); row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label, self)
            lbl.setFixedWidth(60)
            lbl.setStyleSheet(
                f"color: {_INK_2}; font-size: 11.5px; background: transparent;"
            )
            row.addWidget(lbl)
            row.addWidget(control, 1)
            return row

        # Model — free-form text input. Users paste any model id (e.g.
        # "deepseek-v4-pro" or a fine-tune slug) without being constrained
        # to a curated dropdown.
        self.model_combo = LineEdit(self)
        self.model_combo.setPlaceholderText(meta["default_model"])
        self.model_combo.setText(meta["default_model"])
        # Editing the model invalidates the saved 已连接 marker — the new
        # combo hasn't been verified yet.
        self.model_combo.textChanged.connect(self._on_field_edited)
        outer.addLayout(_field("模型", self.model_combo))

        # API key
        self.key_input = PasswordLineEdit(self)
        self.key_input.setPlaceholderText(meta["key_placeholder"])
        self.key_input.textChanged.connect(self._on_field_edited)
        outer.addLayout(_field("API Key", self.key_input))

        # Base URL — overrides the SDK default when set. Provider-specific
        # placeholder hints at the expected shape (OpenAI vs Anthropic).
        self.base_url_input = LineEdit(self)
        default_url_hint = meta.get("default_base_url", "")
        api_style = meta.get("api_style", "OpenAI")
        if default_url_hint:
            self.base_url_input.setPlaceholderText(
                f"{default_url_hint}（{api_style} 格式）"
            )
        else:
            self.base_url_input.setPlaceholderText(f"自定义 {api_style} 端点（留空使用默认）")
        # Same invalidation semantics as model — base_url is part of the
        # tested signature.
        self.base_url_input.textChanged.connect(self._on_field_edited)
        outer.addLayout(_field("Base URL", self.base_url_input))

        # Action row
        actions = QHBoxLayout(); actions.setSpacing(8); actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        self.test_btn = PushButton("测试连接", self)
        self.test_btn.setFixedHeight(28)
        self.test_btn.clicked.connect(lambda: self.test_clicked.emit(meta["key"]))
        actions.addWidget(self.test_btn)
        self.default_btn = PushButton("设为默认", self)
        self.default_btn.setFixedHeight(28)
        self.default_btn.clicked.connect(lambda: self.default_clicked.emit(meta["key"]))
        actions.addWidget(self.default_btn)
        outer.addLayout(actions)

        if self._placeholder:
            self._apply_placeholder_state()

    def _apply_placeholder_state(self) -> None:
        """Visually mark a reserved-but-not-implemented provider.

        The card stays in the layout — model list, key field, and stats are
        all visible so users can see what's coming — but interactions that
        would hit the missing backend are disabled and the status pill
        reads 敬请接入.
        """
        self._status.setText("● 敬请接入")
        self._status.setStyleSheet(
            f"color: {_INK_3}; background: {_INK_5}; border-radius: 10px;"
            " padding: 2px 10px; font-size: 10.5px;"
        )
        self._status.setToolTip("此模型尚未在后端接入，敬请期待")
        self.model_combo.setEnabled(False)
        self.key_input.setEnabled(False)
        self.key_input.setPlaceholderText("尚未接入")
        self.base_url_input.setEnabled(False)
        self.test_btn.setEnabled(False)
        self.default_btn.setEnabled(False)

    def _apply_card_style(self) -> None:
        if self._is_default:
            self.setStyleSheet(
                f"#ProviderCard {{ background: #fafaf7;"
                f" border: 1px solid {_ACCENT}; border-radius: 12px; }}"
            )
        else:
            self.setStyleSheet(
                f"#ProviderCard {{ background: {_SURFACE};"
                f" border: 1px solid {_INK_5}; border-radius: 12px; }}"
            )

    def set_is_default(self, is_default: bool) -> None:
        self._is_default = is_default
        self._default_badge.setVisible(is_default)
        self.default_btn.setEnabled(not is_default)
        self.default_btn.setText("当前默认" if is_default else "设为默认")
        self._apply_card_style()

    # ── Status badge ──────────────────────────────────────────────────
    def current_signature(self) -> str:
        """Composite signature of the three fields the test verified."""
        return _provider_signature(
            self.key_input.text().strip(),
            self.model_combo.text().strip(),
            self.base_url_input.text().strip(),
        )

    def restore_tested_signature(self, sig: str | None) -> None:
        """Restore a saved 测试 OK marker from AppConfig at app startup.

        Called by ``SettingsPage._load_from`` *after* the three text fields
        have been populated, so a subsequent ``current_signature()`` reads
        the loaded values. If the saved signature still matches the
        current fields, the badge paints 已连接; if the user later edits
        any field, ``_on_field_edited`` repaints to 待测试 automatically.
        """
        self._tested_signature = sig
        # Don't carry a previous-session "失败" state forward — failures
        # are transient and only valid during the same UI session.
        self._last_test_failed = False
        self._refresh_status()

    def set_test_result(self, ok: bool, message: str = "") -> None:
        """Apply the immediate result of a 测试连接 click.

        On success we record the current (key, model, base_url) signature
        as the "verified" marker; the SettingsPage then mirrors it into
        AppConfig and asks MainWindow to persist. On failure we set a
        transient flag — no signature change.
        """
        if ok:
            self._tested_signature = self.current_signature()
            self._last_test_failed = False
        else:
            self._last_test_failed = True
        self._refresh_status()
        # Tooltip only carries useful info on failure.
        self._status.setToolTip(message if not ok else "")

    def _on_field_edited(self, *_args) -> None:
        # Any keystroke clears a prior failure (the user is fixing it)
        # and may also drop us out of 已连接 if the new triplet doesn't
        # match the saved signature. ``_refresh_status`` handles both.
        self._last_test_failed = False
        self._refresh_status()

    def _refresh_status(self, *_args) -> None:
        if self._placeholder:
            return
        text = self.key_input.text().strip()
        if not text:
            self._status.setText("● 未配置")
            self._status.setStyleSheet(
                f"color: {_INK_3}; background: {_INK_5}; border-radius: 10px;"
                " padding: 2px 10px; font-size: 10.5px;"
            )
            self._status.setToolTip("")
            return
        if self._last_test_failed:
            self._status.setText("● 连接失败")
            self._status.setStyleSheet(
                "color: #c25c4d; background: #fbe7e3; border-radius: 10px;"
                " padding: 2px 10px; font-size: 10.5px;"
            )
            return
        if (
            self._tested_signature
            and self.current_signature() == self._tested_signature
        ):
            self._status.setText("● 已连接")
            self._status.setStyleSheet(
                f"color: {_ACCENT}; background: #e6f1ec; border-radius: 10px;"
                " padding: 2px 10px; font-size: 10.5px;"
            )
            self._status.setToolTip("")
            return
        # Configured + no successful test yet for THIS triplet.
        self._status.setText("● 待测试")
        self._status.setStyleSheet(
            f"color: {_INK_2}; background: {_INK_5}; border-radius: 10px;"
            " padding: 2px 10px; font-size: 10.5px;"
        )
        self._status.setToolTip("")


class _ConcurrencyPills(QWidget):
    """Four-option pill group for 并发上限: 1 / 3 / 5 / 10."""

    from PyQt6.QtCore import pyqtSignal as _Signal
    value_changed = _Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self._value = 3
        self._buttons: dict[int, PushButton] = {}
        for n in (1, 3, 5, 10):
            b = PushButton(str(n), self)
            b.setCheckable(True)
            b.setFixedSize(44, 28)
            b.setStyleSheet(
                "PushButton { border-radius: 6px; font-size: 12px;"
                f" background: {_SURFACE}; border: 1px solid {_INK_5};"
                f" color: {_INK_2}; }}"
                "PushButton:checked {"
                f" background: {_ACCENT}; color: #ffffff;"
                f" border: 1px solid {_ACCENT}; }}"
            )
            b.clicked.connect(lambda _=False, v=n: self.set_value(v))
            self._buttons[n] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self.set_value(3)

    def value(self) -> int:
        return self._value

    def set_value(self, v: int) -> None:
        if v not in self._buttons:
            v = min(self._buttons, key=lambda k: abs(k - v))
        self._value = v
        for k, b in self._buttons.items():
            b.setChecked(k == v)
        self.value_changed.emit(v)


# ── Page ─────────────────────────────────────────────────────────────────────

_GROUPS = [
    ("general", "通用",       FluentIcon.SETTING),
    ("paths",   "存储路径",   FluentIcon.FOLDER),
    ("models",  "模型",       FluentIcon.ROBOT),
    ("skill",   "Skill 默认", FluentIcon.DICTIONARY),
    ("export",  "导出",       FluentIcon.SAVE),
    ("dedup",   "历史查重",   FluentIcon.SEARCH),
    ("monitor", "监测",       FluentIcon.VIEW),
    ("account", "账号",       FluentIcon.PEOPLE),
    ("about",   "关于",       FluentIcon.INFO),
]


class SettingsPage(QWidget):
    dedup_rebuild_requested = pyqtSignal(str)  # "history" | "vault"
    check_update_requested = pyqtSignal()
    # Fired the moment a 测试连接 ping returns OK — carries the provider
    # key and the new (key, model, base_url) signature. MainWindow uses
    # this to write the signature into settings.json *immediately*, so
    # the 已连接 badge survives an app restart even if the user closes
    # the window without clicking 保存设置.
    test_signature_changed = pyqtSignal(str, str)

    def __init__(self, config: AppConfig, on_save: Callable[[AppConfig], None], parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._config = config
        self._on_save = on_save

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 18, 28, 18)
        root.setSpacing(4)

        title = SubtitleLabel("设置", self)
        title.setStyleSheet(f"color: {_INK}; font-size: 22px; font-weight: 600;")
        root.addWidget(title)
        sub = CaptionLabel("工作空间偏好 · 存储路径 · 模型与 Skill 默认值", self)
        sub.setStyleSheet(f"color: {_INK_2}; font-size: 12.5px;")
        root.addWidget(sub)
        root.addSpacing(14)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(20)

        # ── Left nav ──────────────────────────────────────────────────────
        nav = QFrame(self)
        nav.setFixedWidth(210)
        nav.setObjectName("SettingsNav")
        nav.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav.setStyleSheet(
            f"#SettingsNav {{ background: #ffffff; border: 1px solid {_INK_5};"
            f" border-radius: 12px; }}"
        )
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(8, 10, 8, 10)
        nav_lay.setSpacing(2)

        self._nav_buttons: dict[str, _NavButton] = {}
        self.stack = _AdaptiveStack(self)
        self._group_index: dict[str, int] = {}

        for key, label, icon in _GROUPS:
            btn = _NavButton(label, icon, nav)
            self._nav_buttons[key] = btn
            nav_lay.addWidget(btn)
            btn.clicked.connect(lambda k=key: self._switch(k))

        nav_lay.addStretch(1)

        # Workspace footer chip — simple identity strip.
        chip = QFrame(nav)
        chip.setStyleSheet(
            f"background: {_INK_5}; border-radius: 10px;"
        )
        chip_lay = QHBoxLayout(chip)
        chip_lay.setContentsMargins(10, 8, 10, 8)
        chip_lay.setSpacing(8)
        dot = QLabel(chip)
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {_ACCENT}; border-radius: 4px;")
        chip_lay.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        chip_text = QWidget(chip)
        chip_text_lay = QVBoxLayout(chip_text)
        chip_text_lay.setContentsMargins(0, 0, 0, 0)
        chip_text_lay.setSpacing(0)
        l1 = QLabel("工作空间 · 本地", chip_text)
        l1.setStyleSheet(f"color: {_INK}; font-size: 11.5px; font-weight: 500; background: transparent;")
        l2 = QLabel("个人版 · 当前活跃", chip_text)
        l2.setStyleSheet(f"color: {_INK_3}; font-size: 10.5px; background: transparent;")
        chip_text_lay.addWidget(l1)
        chip_text_lay.addWidget(l2)
        chip_lay.addWidget(chip_text, 1)
        nav_lay.addWidget(chip)

        body.addWidget(nav)

        # ── Right scroll area ─────────────────────────────────────────────
        # The stacked panels live inside a single QScrollArea. Without
        # extra care, QStackedWidget sizes itself to the *largest* child
        # page — which on settings means short pages (通用 / 关于) end up
        # rendered in a viewport tall enough for the longest page (模型),
        # leaving a chunk of empty space below them that the scrollbar
        # can still reach. ``_switch`` resets the scrollbar to 0 on every
        # page change; combined with each panel getting MinimumExpanding
        # sizing, this keeps short pages flush against the top.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        scroll.viewport().setAutoFillBackground(False)
        self._scroll = scroll
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self._stack_lay = QVBoxLayout(host)
        self._stack_lay.setContentsMargins(0, 0, 0, 0)
        self._stack_lay.setSpacing(0)
        self._stack_lay.addWidget(self.stack, 1)
        scroll.setWidget(host)
        body.addWidget(scroll, 1)

        root.addLayout(body, 1)

        # Build each group panel
        self._group_index["general"] = self._add_panel(self._build_general())
        self._group_index["paths"] = self._add_panel(self._build_paths())
        self._group_index["models"] = self._add_panel(self._build_models())
        self._group_index["skill"] = self._add_panel(self._build_skill())
        self._group_index["export"] = self._add_panel(self._build_export())
        self._group_index["dedup"] = self._add_panel(self._build_dedup())
        self._group_index["monitor"] = self._add_panel(self._build_monitor())
        self._group_index["account"] = self._add_panel(self._build_account())
        self._group_index["about"] = self._add_panel(self._build_about())

        # Default selection
        self._switch("paths")

        # Save row pinned at the bottom
        self.save_button = PrimaryPushButton(FluentIcon.SAVE, "保存设置", self)
        self.save_button.clicked.connect(self._save)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_row.addWidget(self.save_button)
        root.addLayout(save_row)

        # Test-facing aliases (kept stable across the redesign).
        self.vault_input = self.vault_card.input
        self.out_input = self.out_card.input
        self.template_input = self.template_card.input
        self.skill_input = self.skill_card.input

        self._load_from(config)

    # ── Panel construction ────────────────────────────────────────────────
    def _add_panel(self, panel: QWidget) -> int:
        # Without an explicit Preferred / Expanding policy, QStackedWidget
        # collapses short pages oddly when other (taller) siblings exist.
        # Preferred + MinimumExpanding lets each page grow to fit the
        # viewport but never demands the height of its tallest sibling —
        # which is what produced the "blank space below 通用 once you've
        # scrolled inside 模型" bug.
        panel.setSizePolicy(QSizePolicy.Policy.Preferred,
                            QSizePolicy.Policy.MinimumExpanding)
        return self.stack.addWidget(panel)

    def _wrap_group(self, *cards: _SettingsCard) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(16)
        for c in cards:
            lay.addWidget(c)
        lay.addStretch(1)
        return host

    def _build_paths(self) -> QWidget:
        card = _SettingsCard(
            "存储路径",
            "所有文档、素材、模板都存在本地，路径改动不会迁移已有文件",
        )
        self.vault_card = _PathField("dir")
        self.out_card = _PathField("dir")
        self.template_card = _PathField("file")
        self.skill_card = _PathField("dir")

        rows = [
            ("素材库",       "Obsidian Vault — 文章引用的素材源", self.vault_card),
            ("导出目录",     "导出 Markdown / 报告 的默认落地位置", self.out_card),
            ("默认模板",     "新建文章时优先选用的模板（.json）", self.template_card),
            ("Skills 目录",  "Skill .md 文件目录 — 决定润色风格选项", self.skill_card),
        ]
        for label, hint, field in rows:
            r = _SettingsRow(label, hint)
            r.set_control(field)
            card.add_row(r)
        return self._wrap_group(card)

    def _build_models(self) -> QWidget:
        # ── 已连接模型 — card grid of providers ───────────────────────────
        grid_card = _SettingsCard(
            "已连接模型",
            f"{len(_PROVIDER_META)} 个模型 · 默认模型可在卡片底部设为默认",
        )
        grid_host = QWidget(grid_card)
        grid_host.setStyleSheet("background: transparent;")
        grid_lay = QHBoxLayout(grid_host)
        grid_lay.setContentsMargins(0, 8, 0, 8)
        grid_lay.setSpacing(14)
        left_col = QVBoxLayout(); left_col.setSpacing(14)
        right_col = QVBoxLayout(); right_col.setSpacing(14)

        self._provider_cards: dict[str, _ProviderCard] = {}
        for i, meta in enumerate(_PROVIDER_META):
            card = _ProviderCard(meta, grid_host)
            card.test_clicked.connect(self._on_test_provider)
            card.default_clicked.connect(self._on_set_default_provider)
            self._provider_cards[meta["key"]] = card
            (left_col if i % 2 == 0 else right_col).addWidget(card)
        left_col.addStretch(1); right_col.addStretch(1)
        grid_lay.addLayout(left_col, 1)
        grid_lay.addLayout(right_col, 1)
        grid_card._body_lay.addWidget(grid_host)

        # ── 高级 section ──────────────────────────────────────────────────
        adv_card = _SettingsCard("高级", "请求行为与训练数据相关选项")

        self.timeout_spin = SpinBox(adv_card)
        self.timeout_spin.setRange(5, 600)
        self.timeout_spin.setValue(180)
        self.timeout_spin.setMinimumWidth(120)
        r1 = _SettingsRow("超时", "单次请求等待上限，超过自动重试一次")
        suffix = BodyLabel("秒", adv_card)
        suffix.setStyleSheet(f"color: {_INK_3}; background: transparent;")
        r1.set_control(self.timeout_spin, suffix)
        adv_card.add_row(r1)

        self.concurrency_pills = _ConcurrencyPills(adv_card)
        r2 = _SettingsRow("并发上限", "批量任务同时跑几条")
        r2.set_control(self.concurrency_pills)
        adv_card.add_row(r2)

        self.training_switch = SwitchButton(adv_card)
        self.training_switch.setOnText("开")
        self.training_switch.setOffText("关")
        r3 = _SettingsRow("上传训练提示", "允许匿名样本改进官方 Skill 库（可随时关闭）")
        r3.set_control(self.training_switch)
        adv_card.add_row(r3)

        # Hidden legacy fields so the save/load code and existing tests that
        # poke ``provider_card`` / ``anthropic_key_input`` / ``deepseek_key_input``
        # keep working without change.
        self.provider_card = ComboBox(self)
        self.provider_card.addItems([m["key"] for m in _PROVIDER_META] + ["mock"])
        self.provider_card.hide()
        self.anthropic_key_input = self._provider_cards["anthropic"].key_input
        self.deepseek_key_input = self._provider_cards["deepseek"].key_input

        return self._wrap_group(grid_card, adv_card)

    def _on_test_provider(self, key: str) -> None:
        """Ping the provider's REST endpoint with the current key + model."""
        from csm_gui.llm_factory import build_client
        card = self._provider_cards.get(key)
        if card is None:
            return
        # Build an ephemeral config snapshot so we test what's on screen, not
        # what's been saved to disk.
        api_key = card.key_input.text().strip()
        if not api_key:
            card.set_test_result(False, "请先填写 API Key")
            return
        model = card.model_combo.text().strip() or None
        base_url = card.base_url_input.text().strip() or None
        snapshot = self._config.model_copy(update={
            "api_keys": {**self._config.api_keys, key: api_key},
            "default_model": {**self._config.default_model,
                              **({key: model} if model else {})},
            "base_urls": {**self._config.base_urls,
                          **({key: base_url} if base_url else {})},
            "timeout_seconds": self.timeout_spin.value(),
        })
        try:
            client = build_client(snapshot, key)
            # Keep the probe cheap — 1-token smoke to confirm auth + network.
            _ = client.complete(system="ping", user="ping")
            card.set_test_result(True)
            # ``set_test_result(True)`` recorded the freshly-tested
            # signature on the card; mirror it into our config and ask
            # MainWindow to flush it to disk so the 已连接 badge sticks
            # across restarts even without 保存设置.
            sig = card._tested_signature
            if sig:
                new_sigs = {**self._config.provider_test_signatures, key: sig}
                self._config = self._config.model_copy(update={
                    "provider_test_signatures": new_sigs,
                })
                self.test_signature_changed.emit(key, sig)
        except Exception as e:
            card.set_test_result(False, str(e))

    def _on_set_default_provider(self, key: str) -> None:
        self.provider_card.setCurrentText(key)
        for k, c in self._provider_cards.items():
            c.set_is_default(k == key)

    def _build_general(self) -> QWidget:
        appearance = _SettingsCard("外观", "主题与界面配色")
        theme_label = BodyLabel("跟随系统（暂未开放主题切换）", appearance)
        theme_label.setStyleSheet(f"color: {_INK_3};")
        r = _SettingsRow("主题")
        r.set_control(theme_label)
        appearance.add_row(r)

        accent_label = BodyLabel("墨绿（默认） · 待添加色板切换", appearance)
        accent_label.setStyleSheet(f"color: {_INK_3};")
        r2 = _SettingsRow("主色", "影响按钮、强调色、高亮")
        r2.set_control(accent_label)
        appearance.add_row(r2)

        lang = _SettingsCard("语言与地区")
        r3 = _SettingsRow("界面语言")
        r3.set_control(BodyLabel("简体中文", lang))
        lang.add_row(r3)

        behavior = _SettingsCard("行为", "窗口与系统托盘相关选项")
        self.close_action_combo = ComboBox(behavior)
        self.close_action_combo.setMinimumWidth(220)
        self.close_action_combo.addItem("最小化到托盘（推荐）", userData="minimize_to_tray")
        self.close_action_combo.addItem("直接退出 CSM", userData="quit")
        from PyQt6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.close_action_combo.setEnabled(False)
            self.close_action_combo.setToolTip("当前系统不支持托盘，已强制使用 \"直接退出\"")
            idx = self.close_action_combo.findData("quit")
            self.close_action_combo.setCurrentIndex(idx)
        r4 = _SettingsRow("关闭按钮行为", "点击窗口关闭按钮时的动作")
        r4.set_control(self.close_action_combo)
        behavior.add_row(r4)

        return self._wrap_group(appearance, lang, behavior)

    def _build_skill(self) -> QWidget:
        card = _SettingsCard(
            "Skill 默认值",
            "新建 Skill 与新建文章时的初始参数（部分项尚未接入实际管线）",
        )
        self.seed_card = SpinBox(self)
        self.seed_card.setRange(0, 99999)
        self.seed_card.setMinimumWidth(140)
        r = _SettingsRow("默认随机种子", "重新随机时的起始 seed — 0 表示每次随机")
        r.set_control(self.seed_card)
        card.add_row(r)
        return self._wrap_group(card)

    def _build_export(self) -> QWidget:
        card = _SettingsCard(
            "导出默认",
            "导出文章到「存储路径 · 导出目录」—— 仅导出文档内容，不含配置",
        )
        self.export_format_combo = ComboBox(card)
        self.export_format_combo.setMinimumWidth(220)
        # ``userData`` carries the config key; the visible label is human-readable.
        self.export_format_combo.addItem("Markdown (.md)", userData="markdown")
        self.export_format_combo.addItem("Word 文档 (.docx)", userData="docx")
        r = _SettingsRow("默认格式", "新文章导出时使用的格式")
        r.set_control(self.export_format_combo)
        card.add_row(r)
        return self._wrap_group(card)

    def _build_dedup(self) -> QWidget:
        """历史查重 section — enable toggle, corpus dir, rebuild buttons, thresholds."""
        card = _SettingsCard("历史查重", "对比历史文章库和 vault 素材，识别撞稿与未消化原文")

        # Enable switch
        row_enable = _SettingsRow("启用历史查重")
        self.dedup_enabled_switch = SwitchButton(self)
        self.dedup_enabled_switch.setChecked(self._config.dedup_enabled)
        row_enable.set_control(self.dedup_enabled_switch)
        card.add_row(row_enable)

        # History dir
        row_dir = _SettingsRow("历史文章库目录")
        dir_holder = QWidget(self)
        dir_lay = QHBoxLayout(dir_holder)
        dir_lay.setContentsMargins(0, 0, 0, 0)
        dir_lay.setSpacing(6)
        self.dedup_history_dir_edit = LineEdit(dir_holder)
        self.dedup_history_dir_edit.setText(self._config.dedup_history_dir or "")
        self.dedup_history_dir_edit.setPlaceholderText("选择存放历史成品文章的目录")
        dir_lay.addWidget(self.dedup_history_dir_edit, 1)
        browse_btn = PushButton("选择…", dir_holder)
        browse_btn.clicked.connect(self._on_browse_dedup_history_dir)
        dir_lay.addWidget(browse_btn)
        row_dir.set_control(dir_holder)
        card.add_row(row_dir)

        # Rebuild buttons
        row_rebuild = _SettingsRow("重建索引")
        rebuild_holder = QWidget(self)
        rb_lay = QHBoxLayout(rebuild_holder)
        rb_lay.setContentsMargins(0, 0, 0, 0)
        rb_lay.setSpacing(6)
        self.dedup_rebuild_history_button = PushButton("重建历史索引", rebuild_holder)
        self.dedup_rebuild_history_button.clicked.connect(
            lambda: self.dedup_rebuild_requested.emit("history")
        )
        rb_lay.addWidget(self.dedup_rebuild_history_button)
        self.dedup_rebuild_vault_button = PushButton("重建 Vault 索引", rebuild_holder)
        self.dedup_rebuild_vault_button.clicked.connect(
            lambda: self.dedup_rebuild_requested.emit("vault")
        )
        rb_lay.addWidget(self.dedup_rebuild_vault_button)
        rb_lay.addStretch(1)
        row_rebuild.set_control(rebuild_holder)
        card.add_row(row_rebuild)

        # Thresholds — fluent SpinBox so the up/down arrows render in the
        # warm-paper theme (the raw QSpinBox previously rendered with the
        # native Win32 spin arrows, which were invisible against the card
        # background on light builds).
        row_th = _SettingsRow(
            "阈值 (绿/黄)",
            "重复率低于「绿」显示为安全，介于绿/黄之间为提示，超过「黄」为告警",
        )
        th_holder = QWidget(self)
        th_lay = QHBoxLayout(th_holder)
        th_lay.setContentsMargins(0, 0, 0, 0)
        th_lay.setSpacing(8)
        self.dedup_threshold_green_spin = SpinBox(th_holder)
        self.dedup_threshold_green_spin.setRange(1, 99)
        self.dedup_threshold_green_spin.setSuffix(" %")
        self.dedup_threshold_green_spin.setValue(self._config.dedup_threshold_green)
        self.dedup_threshold_green_spin.setMinimumWidth(110)
        th_lay.addWidget(self.dedup_threshold_green_spin)
        sep = BodyLabel("/", th_holder)
        sep.setStyleSheet(f"color: {_INK_3}; background: transparent;")
        th_lay.addWidget(sep)
        self.dedup_threshold_yellow_spin = SpinBox(th_holder)
        self.dedup_threshold_yellow_spin.setRange(1, 99)
        self.dedup_threshold_yellow_spin.setSuffix(" %")
        self.dedup_threshold_yellow_spin.setValue(self._config.dedup_threshold_yellow)
        self.dedup_threshold_yellow_spin.setMinimumWidth(110)
        th_lay.addWidget(self.dedup_threshold_yellow_spin)
        th_lay.addStretch(1)
        row_th.set_control(th_holder)
        card.add_row(row_th)

        return self._wrap_group(card)

    def _on_browse_dedup_history_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择历史文章库目录",
            self.dedup_history_dir_edit.text() or "")
        if d:
            self.dedup_history_dir_edit.setText(d)

    def _build_monitor(self) -> QWidget:
        """监测中心相关设置：调度并发、请求间隔、告警阈值、Cookie 管理。"""
        m: MonitorConfig = self._config.monitor

        # ── 限速与并发 ───────────────────────────────────────────────
        rate_card = _SettingsCard(
            "限速与并发",
            "降低被风控的概率。所有抓取都在 QThread worker 中进行，不影响主界面。",
        )

        self.monitor_concurrency_spin = SpinBox(self)
        self.monitor_concurrency_spin.setRange(1, 8)
        self.monitor_concurrency_spin.setMinimumWidth(140)
        self.monitor_concurrency_spin.setValue(m.concurrency_per_platform)
        r_conc = _SettingsRow(
            "每平台并发数", "同一平台同时进行的检测任务上限"
        )
        r_conc.set_control(self.monitor_concurrency_spin)
        rate_card.add_row(r_conc)

        # Min/max delay live in one row, side-by-side, since they're a
        # single conceptual value (a window).
        self.monitor_delay_min_spin = DoubleSpinBox(self)
        self.monitor_delay_min_spin.setRange(0.0, 60.0)
        self.monitor_delay_min_spin.setSingleStep(0.5)
        self.monitor_delay_min_spin.setSuffix(" 秒")
        self.monitor_delay_min_spin.setMinimumWidth(120)
        self.monitor_delay_min_spin.setValue(m.request_delay_min)
        self.monitor_delay_max_spin = DoubleSpinBox(self)
        self.monitor_delay_max_spin.setRange(0.0, 120.0)
        self.monitor_delay_max_spin.setSingleStep(0.5)
        self.monitor_delay_max_spin.setSuffix(" 秒")
        self.monitor_delay_max_spin.setMinimumWidth(120)
        self.monitor_delay_max_spin.setValue(m.request_delay_max)
        delay_holder = QWidget(self)
        delay_lay = QHBoxLayout(delay_holder)
        delay_lay.setContentsMargins(0, 0, 0, 0)
        delay_lay.setSpacing(6)
        delay_lay.addWidget(self.monitor_delay_min_spin)
        delay_lay.addWidget(BodyLabel("到", delay_holder))
        delay_lay.addWidget(self.monitor_delay_max_spin)
        delay_lay.addStretch(1)
        r_delay = _SettingsRow(
            "请求间隔（随机）",
            "每次请求之间的随机等待区间，区间越宽越接近真实人工节奏",
        )
        r_delay.set_control(delay_holder)
        rate_card.add_row(r_delay)

        # ── 告警 ─────────────────────────────────────────────────────
        alert_card = _SettingsCard(
            "告警",
            "排名跌出 Top-N 时弹出告警卡，引导一键生成对标内容",
        )

        self.monitor_top_n_spin = SpinBox(self)
        self.monitor_top_n_spin.setRange(1, 50)
        self.monitor_top_n_spin.setMinimumWidth(140)
        self.monitor_top_n_spin.setValue(m.alert_top_n)
        r_top = _SettingsRow("告警阈值 Top-N", "排名超出该位次即触发告警")
        r_top.set_control(self.monitor_top_n_spin)
        alert_card.add_row(r_top)

        self.monitor_cooldown_spin = SpinBox(self)
        self.monitor_cooldown_spin.setRange(1, 168)
        self.monitor_cooldown_spin.setSuffix(" 小时")
        self.monitor_cooldown_spin.setMinimumWidth(140)
        self.monitor_cooldown_spin.setValue(m.alert_cooldown_hours)
        r_cooldown = _SettingsRow(
            "告警冷却时间", "同一任务再次触发告警的最短间隔，避免刷屏"
        )
        r_cooldown.set_control(self.monitor_cooldown_spin)
        alert_card.add_row(r_cooldown)

        # ── 浏览器兜底 ───────────────────────────────────────────────
        browser_card = _SettingsCard(
            "浏览器兜底",
            "知乎主路径失败时启用 Chromium 兜底；复用本机已安装的 Chrome",
        )

        chrome_holder = QWidget(self)
        chrome_lay = QHBoxLayout(chrome_holder)
        chrome_lay.setContentsMargins(0, 0, 0, 0)
        chrome_lay.setSpacing(6)
        self.monitor_chrome_path_edit = LineEdit(chrome_holder)
        self.monitor_chrome_path_edit.setText(m.chrome_path or "")
        self.monitor_chrome_path_edit.setPlaceholderText("留空自动检测；如手动指定，例如 C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe")
        chrome_lay.addWidget(self.monitor_chrome_path_edit, 1)
        chrome_browse_btn = PushButton("选择…", chrome_holder)
        chrome_browse_btn.clicked.connect(self._on_browse_chrome_path)
        chrome_lay.addWidget(chrome_browse_btn)
        r_chrome = _SettingsRow("Chrome 可执行文件", "DrissionPage 兜底使用")
        r_chrome.set_control(chrome_holder)
        browser_card.add_row(r_chrome)

        # ── Cookie 管理 ──────────────────────────────────────────────
        cookie_card = _SettingsCard(
            "Cookie 管理",
            "为四个平台单独维护 Cookie 池；连续失败 5 次将自动停用",
        )
        cookie_btn = PushButton(FluentIcon.CERTIFICATE, "打开 Cookie 管理…", self)
        cookie_btn.clicked.connect(self._on_open_cookie_manager)
        r_cookie = _SettingsRow("多平台 Cookie", "知乎 / B 站 / 抖音 / 快手")
        r_cookie.set_control(cookie_btn)
        cookie_card.add_row(r_cookie)

        return self._wrap_group(rate_card, alert_card, browser_card, cookie_card)

    def _on_browse_chrome_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Chrome 可执行文件",
            self.monitor_chrome_path_edit.text() or "",
            "可执行文件 (*.exe);;所有文件 (*)",
        )
        if path:
            self.monitor_chrome_path_edit.setText(path)

    def _on_open_cookie_manager(self) -> None:
        # Lazy import — the dialog reaches into csm_core.monitor.storage
        # which depends on the monitor.db being initialized. By the time
        # the user clicks this button MainWindow has already done that,
        # so we don't need to repeat the init here.
        from csm_gui.widgets.cookie_manager_dialog import CookieManagerDialog
        dlg = CookieManagerDialog(self.window())
        dlg.exec()

    def _build_account(self) -> QWidget:
        card = _SettingsCard(
            "账号",
            "本地账户信息 — 用于工作台问候语、导出署名等。仅保存在本机。",
        )

        # Current user — name (and optional product line) + edit button.
        # The labels are populated by ``_refresh_account_labels`` so they
        # stay in sync with config edits made elsewhere.
        row_user = _SettingsRow("当前用户")
        user_holder = QWidget(card)
        user_holder.setStyleSheet("background: transparent;")
        u_lay = QHBoxLayout(user_holder)
        u_lay.setContentsMargins(0, 0, 0, 0)
        u_lay.setSpacing(8)
        self._account_name_label = BodyLabel("", user_holder)
        self._account_name_label.setStyleSheet(
            f"color: {_INK}; font-size: 13px; background: transparent;"
        )
        u_lay.addWidget(self._account_name_label)
        u_lay.addStretch(1)
        self.account_edit_button = PushButton(FluentIcon.EDIT, "编辑账号", user_holder)
        self.account_edit_button.setFixedHeight(28)
        self.account_edit_button.clicked.connect(self._on_edit_account)
        u_lay.addWidget(self.account_edit_button)
        row_user.set_control(user_holder)
        card.add_row(row_user)

        # Product line — read-only display, edited via the same dialog.
        row_product = _SettingsRow("负责产品线")
        self._account_product_label = BodyLabel("—", card)
        self._account_product_label.setStyleSheet(
            f"color: {_INK_2}; font-size: 13px; background: transparent;"
        )
        row_product.set_control(self._account_product_label)
        card.add_row(row_product)

        self._refresh_account_labels()
        return self._wrap_group(card)

    def _refresh_account_labels(self) -> None:
        """Sync the account card text with ``self._config``."""
        if not hasattr(self, "_account_name_label"):
            return
        name = (self._config.user_name or "").strip()
        product = (self._config.user_product or "").strip()
        if name:
            self._account_name_label.setText(name)
            self._account_name_label.setStyleSheet(
                f"color: {_INK}; font-size: 13px; font-weight: 500;"
                " background: transparent;"
            )
            self.account_edit_button.setText("编辑账号")
        else:
            self._account_name_label.setText("未登录")
            self._account_name_label.setStyleSheet(
                f"color: {_INK_3}; font-size: 13px; background: transparent;"
            )
            self.account_edit_button.setText("设置账号")
        self._account_product_label.setText(product or "—")

    def _on_edit_account(self) -> None:
        """Pop the AccountDialog, persist the new name/product on accept."""
        from ..widgets.account_dialog import AccountDialog
        dlg = AccountDialog(
            name=self._config.user_name,
            product=self._config.user_product,
            parent=self,
        )
        if dlg.exec() != 1:
            return
        name, product = dlg.values()
        # Update in-memory config and persist via the standard save path so
        # MainWindow's apply_config fan-out (home greeting, etc.) runs.
        self._config = self._config.model_copy(update={
            "user_name": name,
            "user_product": product,
        })
        self._refresh_account_labels()
        self._on_save(self._config)

    def _build_about(self) -> QWidget:
        """关于 CSM section — current version + update repo + check button."""
        from csm_gui._version import __version__
        card = _SettingsCard("关于 CSM", "版本信息与更新")

        row_ver = _SettingsRow("当前版本")
        self.current_version_label = BodyLabel(f"v{__version__}", self)
        row_ver.set_control(self.current_version_label)
        card.add_row(row_ver)

        row_repo = _SettingsRow("更新仓库 (owner/name)")
        self.update_repo_edit = LineEdit(self)
        self.update_repo_edit.setText(self._config.update_repo or "")
        self.update_repo_edit.setPlaceholderText("例如：zev96/csm，留空则不检查更新")
        row_repo.set_control(self.update_repo_edit)
        card.add_row(row_repo)

        row_btn = _SettingsRow("更新")
        self.check_update_button = PushButton("检查更新", self)
        self.check_update_button.clicked.connect(
            self.check_update_requested.emit
        )
        row_btn.set_control(self.check_update_button)
        card.add_row(row_btn)

        return self._wrap_group(card)

    # ── Behaviour ─────────────────────────────────────────────────────────
    def _switch(self, key: str) -> None:
        idx = self._group_index.get(key)
        if idx is None:
            return
        self.stack.setCurrentIndex(idx)
        for k, btn in self._nav_buttons.items():
            btn.setChecked(k == key)
        # Tell the layout chain that the stack's reported size hint just
        # changed (it now reflects the new current page) so the scroll
        # area can drop the vertical scrollbar when the new page fits.
        self.stack.updateGeometry()
        scroll = getattr(self, "_scroll", None)
        if scroll is not None:
            # Reset scroll position so a short page (通用 / 关于) doesn't
            # render below the viewport when the user had scrolled inside
            # a taller page (模型 / 已连接模型) just before switching.
            bar = scroll.verticalScrollBar()
            if bar is not None:
                bar.setValue(0)

    def _load_from(self, cfg: AppConfig) -> None:
        self.vault_card.setText(cfg.vault_root or "")
        self.out_card.setText(cfg.out_dir or "")
        self.template_card.setText(cfg.default_template or "")
        self.skill_card.setText(cfg.skill_dir or "")
        idx = self.provider_card.findText(cfg.default_provider)
        if idx >= 0:
            self.provider_card.setCurrentIndex(idx)
        for key, card in self._provider_cards.items():
            if card._placeholder:
                # Placeholder cards are display-only — don't hydrate or
                # re-flip them as the active default.
                continue
            card.key_input.setText(cfg.api_keys.get(key, ""))
            model = cfg.default_model.get(key)
            if model:
                card.model_combo.setText(model)
            card.base_url_input.setText(cfg.base_urls.get(key, ""))
            # AFTER fields are populated — order matters because
            # ``current_signature()`` reads the live values.
            card.restore_tested_signature(
                cfg.provider_test_signatures.get(key)
            )
            card.set_is_default(cfg.default_provider == key)
        self.seed_card.setValue(cfg.last_seed)
        self.timeout_spin.setValue(cfg.timeout_seconds)
        self.concurrency_pills.set_value(cfg.concurrency)
        self.training_switch.setChecked(cfg.upload_training_hints)
        for i in range(self.export_format_combo.count()):
            if self.export_format_combo.itemData(i) == cfg.export_format:
                self.export_format_combo.setCurrentIndex(i)
                break
        idx = self.close_action_combo.findData(cfg.close_action)
        if idx >= 0:
            self.close_action_combo.setCurrentIndex(idx)
        self.dedup_enabled_switch.setChecked(cfg.dedup_enabled)
        self.dedup_history_dir_edit.setText(cfg.dedup_history_dir or "")
        self.dedup_threshold_green_spin.setValue(cfg.dedup_threshold_green)
        self.dedup_threshold_yellow_spin.setValue(cfg.dedup_threshold_yellow)

    def _save(self) -> None:
        api_keys: dict[str, str] = {}
        default_model: dict[str, str] = {}
        base_urls: dict[str, str] = {}
        for key, card in self._provider_cards.items():
            if card._placeholder:
                continue
            k = card.key_input.text().strip()
            if k:
                api_keys[key] = k
            m = card.model_combo.text().strip()
            if m:
                default_model[key] = m
            b = card.base_url_input.text().strip()
            if b:
                base_urls[key] = b
        new_cfg = AppConfig(
            user_name=self._config.user_name,
            user_product=self._config.user_product,
            vault_root=self.vault_card.text() or None,
            out_dir=self.out_card.text() or None,
            default_provider=cast(Provider, self.provider_card.currentText()),
            api_keys=api_keys,
            default_template=self.template_card.text() or None,
            skill_dir=self.skill_card.text() or None,
            last_seed=self.seed_card.value(),
            default_model=default_model,
            base_urls=base_urls,
            # Preserve test-signature state. ``self._config`` is kept in
            # sync by ``_on_test_provider`` whenever a test passes, so
            # forwarding it here keeps the 已连接 badge stable across a
            # 保存设置 click — the alternative was wiping every signature
            # on every save (Pydantic default_factory => empty dict).
            provider_test_signatures=self._config.provider_test_signatures,
            timeout_seconds=self.timeout_spin.value(),
            concurrency=self.concurrency_pills.value(),
            upload_training_hints=self.training_switch.isChecked(),
            export_format=cast(
                Literal["markdown", "docx"],
                self.export_format_combo.currentData() or "markdown",
            ),
            close_action=cast(
                Literal["minimize_to_tray", "quit"],
                self.close_action_combo.currentData() or "minimize_to_tray",
            ),
            dedup_enabled=self.dedup_enabled_switch.isChecked(),
            dedup_history_dir=self.dedup_history_dir_edit.text(),
            dedup_threshold_green=self.dedup_threshold_green_spin.value(),
            dedup_threshold_yellow=self.dedup_threshold_yellow_spin.value(),
            dedup_history_last_built=self._config.dedup_history_last_built,
            dedup_vault_last_built=self._config.dedup_vault_last_built,
            update_repo=self.update_repo_edit.text().strip(),
            # Monitor module: knobs live on this page now too. Cookies
            # are managed via the side dialog and persisted directly to
            # sqlite, so they don't appear here. Delay min/max are
            # swapped if the user inverted them — RequestPacer would
            # otherwise raise on apply_config and crash the save.
            monitor=MonitorConfig(
                enabled=self._config.monitor.enabled,
                concurrency_per_platform=self.monitor_concurrency_spin.value(),
                request_delay_min=min(
                    float(self.monitor_delay_min_spin.value()),
                    float(self.monitor_delay_max_spin.value()),
                ),
                request_delay_max=max(
                    float(self.monitor_delay_min_spin.value()),
                    float(self.monitor_delay_max_spin.value()),
                ),
                alert_top_n=self.monitor_top_n_spin.value(),
                alert_cooldown_hours=self.monitor_cooldown_spin.value(),
                chrome_path=self.monitor_chrome_path_edit.text().strip(),
            ),
        )
        self._config = new_cfg
        self._on_save(new_cfg)
