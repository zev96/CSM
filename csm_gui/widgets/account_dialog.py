"""Account edit dialog — matches the 新建模板 dialog style.

Reuses ``MessageBoxBase`` from qfluentwidgets so the visual treatment
(rounded card, accent primary button, light cancel button) lines up with
the rest of the app's modal flows. The first-run path is owned by
``FirstRunWelcome``; this dialog is only used for later edits invoked
from the sidebar avatar or the settings page's account panel.

姓名必填（trim 后非空）；负责产品线可空。``exec()`` 返回 1 = 已确认，
0 = 取消。``values()`` 返回 ``(name, product_or_None)``。
"""
from __future__ import annotations

from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, BodyLabel, LineEdit,
    InfoBar, InfoBarPosition,
)


class AccountDialog(MessageBoxBase):
    """Modal dialog that edits ``user_name`` / ``user_product``."""

    def __init__(
        self,
        *,
        name: str | None = None,
        product: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.widget.setMinimumWidth(420)

        # Title — bigger / bolder than BodyLabel, mirrors 新建模板.
        self.viewLayout.addWidget(SubtitleLabel("编辑账户", self))

        # 姓名（必填）
        self.viewLayout.addWidget(BodyLabel("姓名 *"))
        self.name_input = LineEdit(self)
        self.name_input.setPlaceholderText("如：小王、Wang Xi")
        if name:
            self.name_input.setText(name)
        self.viewLayout.addWidget(self.name_input)

        # 负责产品线（可选）
        self.viewLayout.addWidget(BodyLabel("负责产品线"))
        self.product_input = LineEdit(self)
        self.product_input.setPlaceholderText("如：吸尘器")
        if product:
            self.product_input.setText(product)
        self.viewLayout.addWidget(self.product_input)

        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    # ── MessageBoxBase API ────────────────────────────────────────────
    def validate(self) -> bool:
        if not self.name_input.text().strip():
            InfoBar.error(
                "验证失败", "姓名不能为空",
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )
            return False
        return True

    # ── Public API ────────────────────────────────────────────────────
    def values(self) -> tuple[str, str | None]:
        name = self.name_input.text().strip()
        product = self.product_input.text().strip() or None
        return name, product


def initial_for(name: str | None) -> str:
    """Return the 1-character avatar initial for *name*.

    * Empty / None  → "?"
    * Contains CJK  → first CJK character
    * Otherwise     → first letter of the first whitespace-split token,
      uppercased.
    """
    if not name:
        return "?"
    s = name.strip()
    if not s:
        return "?"
    for ch in s:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF       # CJK Unified Ideographs
            or 0x3400 <= cp <= 0x4DBF    # CJK Extension A
            or 0x3040 <= cp <= 0x30FF    # Hiragana / Katakana
            or 0xAC00 <= cp <= 0xD7AF    # Hangul Syllables
        ):
            return ch
    token = s.split()[0]
    return token[0].upper() if token else "?"
