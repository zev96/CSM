"""TikHub 付费 API 的 HTTP client 基座:鉴权 GET + 错误映射 + 进程级 402 余额闩。

设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §9
- 每次请求带 `Authorization: Bearer <key>`。
- HTTP 非 200 **或** 响应体 `code != 200`(聚合 API 常用 HTTP 200 + body code 表业务错误)
  都映射成中文 TikHubError(见 errors.map_error)。
- 见到任一 402 立即置进程级闩(跨平台生效,因为余额是账户级而非平台级);
  分派层据此在本轮短路剩余任务,避免通知洪水 + 继续烧费。
- 响应非法 JSON 也统一成 TikHubError,不让 json.JSONDecodeError 击穿上层
  适配器的 `except TikHubError`。
- 日志绝不写 Authorization 头或 key(R7 安全红线):只记录 path/params 与状态码;
  记录响应体前先 `_redact()` 抹掉 key —— 防网关/CDN 把请求头回显进错误体导致泄漏。
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

    def _redact(self, text: str) -> str:
        """从待记录文本里抹掉 key —— 保证日志绝不泄漏 key(R7 安全红线)。"""
        if not text or not self._key:
            return text or ""
        return text.replace(self._key, "***")

    def _fail(self, effective_code: int, http_status: int, path: str, body_text: str) -> None:
        """按 effective_code 映射错误、必要时置余额闩、redact 后落日志,然后抛出。"""
        err = map_error(effective_code, effective_code)
        if isinstance(err, TikHubBalanceExhausted):
            _trip_balance_latch()
        logger.warning(
            "[tikhub] %s http=%d code=%s first200=%s",
            path, http_status, effective_code, self._redact(body_text)[:200],
        )
        raise err

    def get(self, path: str, params: dict) -> dict:
        """对 TikHub API 发起一次鉴权 GET,返回解析后的 JSON 响应体(整个 wrapper)。

        触发 TikHubError 的情形:HTTP 非 200 / 响应体 code != 200 / 非法 JSON / 网络错误。
        402(HTTP 或 body code)会额外触发进程级余额闩。
        """
        if not path.startswith("/"):
            path = "/" + path
        # 日志绝不带 Authorization / key —— 只记录路径与参数。
        logger.info("[tikhub] GET %s params=%s", path, dict(params))
        try:
            r = self._http.get(
                self._base + path,
                params=params,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError as e:
            raise TikHubError("网络错误") from e

        # 1) HTTP 层错误
        if r.status_code != 200:
            self._fail(r.status_code, r.status_code, path, r.text)

        # 2) 解析 JSON —— 非法 JSON 统一成 TikHubError,别让 JSONDecodeError 击穿上层
        try:
            data = r.json()
        except ValueError as e:
            logger.warning(
                "[tikhub] %s http=200 非法JSON first200=%s", path, self._redact(r.text)[:200]
            )
            raise TikHubError("TikHub 响应不是合法 JSON") from e

        # 3) 业务层错误:HTTP 200 但 body.code != 200(聚合 API 常见做法)
        biz_code = data.get("code") if isinstance(data, dict) else None
        if isinstance(biz_code, int) and biz_code != 200:
            self._fail(biz_code, 200, path, r.text)

        return data
