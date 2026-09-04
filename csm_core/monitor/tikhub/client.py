"""TikHub 付费 API 的 HTTP client 基座:鉴权 GET/POST + 错误映射 + 进程级 402 余额闩。

设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §9
- 每次请求带 `Authorization: Bearer <key>`。
- HTTP 非 200 **或** 响应体 `code != 200`(聚合 API 常用 HTTP 200 + body code 表业务错误)
  都映射成中文 TikHubError(见 errors.map_error)。触发时 `err.from_body` 标记该错误是
  否来自"HTTP 200 但服务端已出货"(见下)。
- 见到任一 402 立即置进程级闩(跨平台生效,因为余额是账户级而非平台级);
  分派层据此在本轮短路剩余任务,避免通知洪水 + 继续烧费。
- HTTP 200 + body code≠200:服务端已出货(可能已计费)—— `from_body=True`,上层
  不应把它当"没出货"重试造成重复计费。HTTP 层错误(非 200 状态码)或网络错误则
  `from_body=False`,可安全重试。
- 响应非法 JSON 在 HTTP 200 时同样标记 `from_body=True` 统一成 TikHubError,不让
  json.JSONDecodeError 击穿上层适配器的 `except TikHubError`。
- 日志绝不写 Authorization 头或 key(R7 安全红线):只记录 path/params 与状态码;
  记录响应体前先 `_redact()` 抹掉 key —— 防网关/CDN 把请求头回显进错误体导致泄漏。
- 不做自动重试(§9:重试可能重复计费);GET/POST 均如此。
- 本模块只负责单次 GET/POST;自适应翻页属于 Task 3(paginate()),此处不实现。
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
    """TikHub API 的最小 HTTP client:鉴权 GET/POST。"""

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
        err.from_body = (http_status == 200)
        if isinstance(err, TikHubBalanceExhausted):
            _trip_balance_latch()
        logger.warning(
            "[tikhub] %s http=%d code=%s first200=%s",
            path, http_status, effective_code, self._redact(body_text)[:200],
        )
        raise err

    def _parse(self, r: httpx.Response, path: str) -> dict:
        """HTTP 状态 → JSON → 业务 code 三层校验(get/post 共用)。"""
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
            # HTTP 200 意味着服务端已经出货(可能已计费)——不能让上层适配器把非法
            # JSON 误判为"服务端没出货"而重试,造成重复计费。
            err = TikHubError("TikHub 响应不是合法 JSON")
            err.from_body = True
            raise err from e

        # 3) 业务层错误:HTTP 200 但 body.code != 200(聚合 API 常见做法)
        biz_code = data.get("code") if isinstance(data, dict) else None
        if isinstance(biz_code, bool):                      # bool 是 int 子类，不当作业务码
            biz_code = None
        elif isinstance(biz_code, str) and biz_code.strip().isdecimal():
            biz_code = int(biz_code.strip())
        if isinstance(biz_code, int) and biz_code != 200:
            self._fail(biz_code, 200, path, r.text)

        return data

    def get(self, path: str, params: dict) -> dict:
        """对 TikHub API 发起一次鉴权 GET,返回解析后的 JSON 响应体(整个 wrapper)。

        触发 TikHubError 的情形:HTTP 非 200 / 响应体 code != 200 / 非法 JSON / 网络错误。
        402(HTTP 或 body code)会额外触发进程级余额闩。
        """
        if not path.startswith("/"):
            path = "/" + path
        # 日志绝不带 Authorization / key —— 也不记参数值(Bilibili/Kuaishou 搜索会把
        # keyword 当 GET 参数传,值可能是用户敏感词);只记参数名列表。
        logger.info("[tikhub] GET %s param_keys=%s", path, sorted(params))
        try:
            r = self._http.get(
                self._base + path,
                params=params,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError as e:
            raise TikHubError("网络错误") from e
        return self._parse(r, path)

    def post(self, path: str, json_body: dict) -> dict:
        """对 TikHub API 发起一次鉴权 POST(JSON body),错误语义与 get() 完全一致。

        抖音搜索系列端点(/api/v1/douyin/search/*)只收 POST。日志只记 body 的
        key 列表(keyword 可能含用户敏感词,不记值)。
        """
        if not path.startswith("/"):
            path = "/" + path
        logger.info("[tikhub] POST %s body_keys=%s", path, sorted(json_body))
        try:
            r = self._http.post(
                self._base + path,
                json=json_body,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError as e:
            raise TikHubError("网络错误") from e
        return self._parse(r, path)


def paginate(page_fn, target: int, max_pages: int, cancel_token=None, stop_predicate=None):
    """自适应翻页:反复调用 page_fn(cursor) 直到达到 target 条数或 API 报尽。

    page_fn(cursor) -> (items, next_cursor, has_more)。

    设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §7.2
    - 正常停止:已凑够 target 条 / has_more=False / 本页空 / stop_predicate 命中。
    - 异常停止:page_fn 抛异常直接向上传播(**绝不吞掉异常返回残缺列表**——
      否则会把"评论埋得深/翻页失败"误报成"评论被删");
      翻了 max_pages 页仍未终止,视为疑似死循环/风控假状态,主动熔断抛 TikHubError。
    - cancel_token(可选):每页开始前检查一次,置位则提前收工(用户取消属正常路径,
      返回已抓到的部分不算"残缺失败",与 page_fn 异常的语义不同)。
    - stop_predicate(可选,acc->bool):每抓完一页对**累积列表**求值一次,返回 True
      即提前停(命中即停)。用途:评论留存监控里,目标评论一旦出现就没必要继续深翻——
      为已留存的评论白翻到 target 上限是纯粹的浪费(付费 API 每页都计费)。找不到的
      才会一直翻到 has_more=False / target,用于确认"确实不在(疑似被删/限流)"。
    """
    out: list = []
    cursor = None
    pages = 0
    while len(out) < target:
        if cancel_token is not None and cancel_token.is_set():
            break
        if pages >= max_pages:
            raise TikHubError(f"翻页超过 {max_pages} 页仍未终止(疑似异常)")
        items, cursor, has_more = page_fn(cursor)  # 抛异常 = 整体失败,直接向上传播
        pages += 1
        if not items:
            break
        out.extend(items)
        if stop_predicate is not None and stop_predicate(out):
            break
        if not has_more or cursor is None:
            break
    return out[:target]
