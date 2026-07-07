"""TikHub API 错误类型 + HTTP 状态码 -> 中文原因映射。

设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §9
- 402 余额不足(TikHubBalanceExhausted 子类,供上层做进程级闩判断)
- 429 限流
- 401/403 鉴权失败或 Key 无效
- 其它非 2xx -> 通用错误,附 HTTP 状态码
"""

from __future__ import annotations


class TikHubError(Exception):
    """TikHub API 调用失败的基类。`reason` 是给用户看的中文原因。"""

    def __init__(self, reason: str, code: int | None = None):
        self.reason = reason
        self.code = code
        super().__init__(reason)


class TikHubBalanceExhausted(TikHubError):
    """账户余额耗尽(HTTP 402)。账户级、跨平台生效 —— 由调用方触发进程级闩。"""


def map_error(status: int, code: int | None) -> TikHubError:
    """把 HTTP 状态码(以及可选的响应体 code 字段)映射成中文 TikHubError。"""
    if status == 402:
        return TikHubBalanceExhausted("TikHub 余额不足", code)
    if status == 429:
        return TikHubError("TikHub 限流", code)
    if status in (401, 403):
        return TikHubError("TikHub 鉴权失败或 Key 无效", code)
    return TikHubError(f"TikHub API 错误(HTTP {status})", code)
