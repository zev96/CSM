"""TikHub 付费 API 的 HTTP client 基座:鉴权 GET + 错误映射 + 进程级 402 余额闩。

设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §9
- 每次请求带 `Authorization: Bearer <key>`。
- 非 2xx 响应 -> 映射成中文 TikHubError(见 errors.map_error)。
- 见到任一 402 立即置进程级闩(跨平台生效,因为余额是账户级而非平台级);
  分派层据此在本轮短路剩余任务,避免通知洪水 + 继续烧费。
- 日志绝不写 Authorization 头或 key(R7 安全红线);只记录 path/params 与响应状态码
  + 截断的响应体前 200 字符,便于诊断 silent failure。
- 不做自动重试(§9:重试可能重复计费)。
- 本模块只负责单次 GET;自适应翻页属于 Task 3(paginate()),此处不实现。
"""

from __future__ import annotations

import logging
import threading

import httpx

from .errors import TikHubBalanceExhausted, TikHubError, map_error

logger = logging.getLogger(__name__)

# 进程级、跨平台生效的 402 "余额耗尽" 闩。
# 余额是账户级的,一旦任一平台的请求收到 402,所有平台都应立即停止继续请求
# (而不是每个任务各自撞一次 402、刷一堆重复通知)。
_balance_lock = threading.Lock()
_balance_exhausted = False


def balance_exhausted() -> bool:
    """查询进程级余额闩是否已置位。分派层应在发请求前先查这个。"""
    with _balance_lock:
        return _balance_exhausted


def reset_balance_latch() -> None:
    """重置余额闩(用户手动重置,或下一整点定时重置)。"""
    global _balance_exhausted
    with _balance_lock:
        _balance_exhausted = False


def _trip_balance_latch() -> None:
    global _balance_exhausted
    with _balance_lock:
        _balance_exhausted = True


class TikHubClient:
    """TikHub API 的最小 HTTP client:一个鉴权 GET 方法。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        _transport: httpx.BaseTransport | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._key = api_key
        # _transport 仅供测试注入 httpx.MockTransport;生产环境走默认 None
        # (httpx.Client 会使用真实网络 transport)。
        self._http = httpx.Client(timeout=timeout, transport=_transport)

    def get(self, path: str, params: dict) -> dict:
        """对 TikHub API 发起一次鉴权 GET,返回解析后的 JSON 响应体。

        非 2xx 响应会被映射成 TikHubError 并抛出;402 会额外触发进程级余额闩。
        """
        # 日志绝不带 Authorization / key —— 只记录路径与参数。
        logger.info("[tikhub] GET %s params=%s", path, {k: v for k, v in params.items()})
        try:
            r = self._http.get(
                self._base + path,
                params=params,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError as e:
            raise TikHubError("网络错误") from e
        if r.status_code != 200:
            err = map_error(r.status_code, None)
            if isinstance(err, TikHubBalanceExhausted):
                _trip_balance_latch()
            logger.warning("[tikhub] %s http=%d first200=%s", path, r.status_code, r.text[:200])
            raise err
        return r.json()
