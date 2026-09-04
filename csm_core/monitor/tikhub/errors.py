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
        # HTTP 200 但 body.code != 200:服务端已经出货(可能已计费),重试无意义/有风险。
        # 由 client._fail() 按 http_status 是否为 200 置位;默认 False(HTTP 层错误 /
        # 网络错误都算"服务端没出货")。
        self.from_body: bool = False
        # 是否可重试的显式覆盖:None = 交给调用方按 code/from_body 推导(默认路径,
        # 走 map_error 产出的错误都是 None);client.get()/post() 在请求发送阶段
        # (连接失败 / 已发出但超时 / 发送前构造失败)会显式置位 —— 这三类失败的
        # "是否已出货"判据不是 HTTP 状态码/业务码能表达的,必须由触发点自己声明。
        self.retryable: bool | None = None
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
    return TikHubError(f"TikHub API 错误(code={status})", code)
