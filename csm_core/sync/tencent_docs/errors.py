"""腾讯文档 MCP 服务错误类型。

错误码来源：官方龙虾 skill 包 SKILL.md 的错误表（400006 token 失效、
400007 VIP 权限不足、400008 积分不足）。其余错误统一 TencentDocsError，
reason 里带上服务端原文，UI 直接展示。
"""
from __future__ import annotations


class TencentDocsError(Exception):
    """腾讯文档同步失败的基类。reason 为面向用户的中文描述。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TokenInvalidError(TencentDocsError):
    """Token 缺失/失效（400006）—— 提示用户去官网重取并在设置页重贴。"""

    def __init__(self, reason: str = "腾讯文档 Token 失效，请在设置页重新粘贴"):
        super().__init__(reason)


class VipRequiredError(TencentDocsError):
    """VIP 权限不足（400007）。"""

    def __init__(self, reason: str = "该操作需要腾讯文档 VIP 权限"):
        super().__init__(reason)


_CODE_MAP = {
    "400006": TokenInvalidError,
    "400007": VipRequiredError,
}


def map_error(message: str) -> TencentDocsError:
    """按服务端错误文本映射到具体异常类型（找不到码就退回基类）。"""
    for code, exc_cls in _CODE_MAP.items():
        if code in (message or ""):
            return exc_cls(f"腾讯文档服务报错：{message}")
    return TencentDocsError(f"腾讯文档服务报错：{message or '未知错误'}")
