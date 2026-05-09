"""Cookie management dialog for the four monitor platforms.

Single dialog with a Pivot at the top to switch platforms; for each
platform, a list of stored Cookie entries plus an editor underneath to
add a new cred or replace an existing one. The dialog operates directly
on the ``platform_credentials`` sqlite table — there is no separate
in-memory model that needs syncing.

Cookie strings live as plaintext in the db (consistent with the rest
of CSM's secret handling per the existing TODO on ``api_keys``). The
dialog is a thin CRUD surface; risk-control de-rotation logic stays in
``CookieStore``.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, FluentIcon, InfoBar, InfoBarPosition, LineEdit,
    MessageBox, MessageBoxBase, Pivot, PrimaryPushButton, PushButton,
    StrongBodyLabel, SubtitleLabel, TextEdit,
)

from csm_core.monitor import storage

logger = logging.getLogger(__name__)


# Platform code → human label. Order matters: the Pivot lays them out
# in the order they're declared here.
_PLATFORMS: list[tuple[str, str]] = [
    ("zhihu_question", "知乎"),
    ("bilibili_comment", "B 站"),
    ("douyin_comment", "抖音"),
    ("kuaishou_comment", "快手"),
]


class CookieManagerDialog(MessageBoxBase):
    """Tabbed dialog for managing platform_credentials rows."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.widget.setMinimumSize(720, 560)
        self.viewLayout.addWidget(SubtitleLabel("Cookie 管理", self))
        self.viewLayout.addWidget(BodyLabel(
            "为每个平台粘贴登录后的 Cookie 字符串。系统会按"
            "「失败次数升序、最近最少使用优先」自动轮询；连续失败 5 次将自动停用。",
            self,
        ))

        # Top: platform pivot.
        self._pivot = Pivot(self)
        for code, label in _PLATFORMS:
            self._pivot.addItem(routeKey=code, text=label)
        self._pivot.setCurrentItem(_PLATFORMS[0][0])
        self._pivot.currentItemChanged.connect(self._on_platform_changed)
        self.viewLayout.addWidget(self._pivot)

        # Middle: list of existing creds for the active platform.
        body = QWidget(self)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(8)

        body_lay.addWidget(StrongBodyLabel("已保存的 Cookie", body))
        self._list = QListWidget(body)
        self._list.setMinimumHeight(140)
        self._list.itemSelectionChanged.connect(self._on_list_selection_changed)
        body_lay.addWidget(self._list)

        list_btns = QHBoxLayout()
        list_btns.setSpacing(8)
        self._enable_btn = PushButton(FluentIcon.ACCEPT, "启用", body)
        self._enable_btn.setEnabled(False)
        self._enable_btn.clicked.connect(lambda: self._set_enabled(True))
        list_btns.addWidget(self._enable_btn)
        self._disable_btn = PushButton(FluentIcon.CANCEL, "停用", body)
        self._disable_btn.setEnabled(False)
        self._disable_btn.clicked.connect(lambda: self._set_enabled(False))
        list_btns.addWidget(self._disable_btn)
        self._delete_btn = PushButton(FluentIcon.DELETE, "删除", body)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        list_btns.addWidget(self._delete_btn)
        list_btns.addStretch(1)
        body_lay.addLayout(list_btns)

        # Bottom: add new cred form.
        body_lay.addSpacing(6)
        body_lay.addWidget(StrongBodyLabel("新增 Cookie", body))
        body_lay.addWidget(BodyLabel("标签（可选，用于区分多账号）", body))
        self._label_edit = LineEdit(body)
        self._label_edit.setPlaceholderText("如：主账号 / 备用号")
        body_lay.addWidget(self._label_edit)
        body_lay.addWidget(BodyLabel("Cookie 字符串", body))
        self._cookie_edit = TextEdit(body)
        self._cookie_edit.setPlaceholderText(
            "粘贴整段 Cookie，如：buvid3=...; SESSDATA=...; bili_jct=..."
        )
        self._cookie_edit.setMinimumHeight(80)
        body_lay.addWidget(self._cookie_edit)
        body_lay.addWidget(BodyLabel("User-Agent（可选）", body))
        self._ua_edit = LineEdit(body)
        self._ua_edit.setPlaceholderText("留空使用默认 UA 池")
        body_lay.addWidget(self._ua_edit)

        add_btns = QHBoxLayout()
        add_btns.setSpacing(8)
        add_btns.addStretch(1)
        self._add_btn = PrimaryPushButton(FluentIcon.ADD, "保存为新条目", body)
        self._add_btn.clicked.connect(self._on_add)
        add_btns.addWidget(self._add_btn)
        body_lay.addLayout(add_btns)

        self.viewLayout.addWidget(body, 1)

        # Dialog footer — only "关闭" since adds are committed inline.
        self.yesButton.setText("关闭")
        self.cancelButton.hide()

        # Initial load.
        self._refresh_list()

    # ── Platform switching ─────────────────────────────────────────────────
    def _current_platform(self) -> str:
        return self._pivot.currentRouteKey() or _PLATFORMS[0][0]

    def _on_platform_changed(self, _key: str) -> None:
        # Clear the add-form when switching platforms so a half-typed
        # cred for B 站 doesn't accidentally land under 抖音.
        self._label_edit.clear()
        self._cookie_edit.clear()
        self._ua_edit.clear()
        self._refresh_list()

    # ── List CRUD ──────────────────────────────────────────────────────────
    def _refresh_list(self) -> None:
        self._list.clear()
        try:
            rows = storage.list_credentials(self._current_platform(), enabled_only=False)
        except Exception:
            logger.exception("cookie manager: list_credentials failed")
            rows = []
        for r in rows:
            label = (r.get("label") or "").strip() or "(未命名)"
            status = "启用" if r.get("enabled") else "已停用"
            fails = int(r.get("fail_count") or 0)
            cookie_preview = (r.get("cookies_text") or "")[:48].replace("\n", " ")
            text = f"[{status}] {label} · 失败 {fails} 次 · {cookie_preview}…"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self._list.addItem(item)
        self._on_list_selection_changed()

    def _on_list_selection_changed(self) -> None:
        has = self._list.currentItem() is not None
        self._enable_btn.setEnabled(has)
        self._disable_btn.setEnabled(has)
        self._delete_btn.setEnabled(has)

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _set_enabled(self, enabled: bool) -> None:
        cred_id = self._selected_id()
        if cred_id is None:
            return
        try:
            storage.get_conn().execute(
                "UPDATE platform_credentials SET enabled=?, fail_count=0 WHERE id=?",
                (1 if enabled else 0, cred_id),
            )
        except Exception as e:
            self._error(f"操作失败：{e}")
            return
        self._refresh_list()

    def _on_delete(self) -> None:
        cred_id = self._selected_id()
        if cred_id is None:
            return
        box = MessageBox("删除 Cookie", "确认删除该条目？", self.window())
        if not box.exec():
            return
        try:
            storage.delete_credential(cred_id)
        except Exception as e:
            self._error(f"删除失败：{e}")
            return
        self._refresh_list()

    def _on_add(self) -> None:
        cookie_text = self._cookie_edit.toPlainText().strip()
        if not cookie_text:
            self._error("请粘贴 Cookie 字符串")
            return
        try:
            storage.add_credential(
                self._current_platform(),
                cookie_text,
                self._label_edit.text().strip(),
                self._ua_edit.text().strip(),
            )
        except Exception as e:
            self._error(f"保存失败：{e}")
            return
        self._info("已保存")
        self._label_edit.clear()
        self._cookie_edit.clear()
        self._ua_edit.clear()
        self._refresh_list()

    # ── Notification helpers ───────────────────────────────────────────────
    def _info(self, message: str) -> None:
        InfoBar.success(
            "提示", message, duration=2000,
            position=InfoBarPosition.TOP, parent=self,
        )

    def _error(self, message: str) -> None:
        InfoBar.error(
            "错误", message, duration=4000,
            position=InfoBarPosition.TOP, parent=self,
        )
