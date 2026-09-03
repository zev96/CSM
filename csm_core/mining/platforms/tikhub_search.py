"""TikHub 付费关键词搜索适配器 —— 采集模块「找视频」这一步的 API 路径。

设计依据：docs/superpowers/specs/2026-09-01-mining-tikhub-search-design.md（§5.3 / §5.4）
+ 实现期修订（plan「Amendments」修订 B）。

实现现有 ``SearchAdapter`` Protocol；拿到 ``VideoCard`` 后走与浏览器适配器**完全相同**的
``on_card`` 管线（去重 / 入库 / 品牌预筛都不变）。与浏览器路径的差异：

- 免登录、无并发风控限速（这正是切换的动机）；
- 失败**不回退**浏览器（spec D5）；
- 每页失败**重试 ≤ PAGE_RETRIES 次**（官方标注搜索端点偶发失败，且该类失败不计费）；
  402 余额耗尽**不重试**，并走进程级余额闩本轮短路；
- 终止判据（成本护栏，按触发顺序）：达 target / 整页都是重复卡（cards 非空且 0 张新卡，
  游标疑似卡住）/ 无下一页 / MAX_PAGES 硬闸。整页被本地过滤为空**不**停（快手日期区间靠
  翻页补偿）；
- 页级错误语义：**首页**失败（重试耗尽 / 解析异常）→ ``failed``；**已发出 ≥1 张卡后**的
  后续页失败 → ``done`` + note（已入库的候选不能因翻页失败被记成失败——runner 只对
  ``done`` 跑品牌预筛）；
- 适配器层永不异常穿透：normalize / next_request 的任何异常都按页级错误处理。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from csm_core.mining.models import Platform, ProgressUpdate, SearchOutcome, VideoCard
from csm_core.mining.platforms import tikhub_normalize as N
from csm_core.mining.platforms._common import OnCard, OnProgress
from csm_core.monitor.tikhub.client import TikHubClient, balance_exhausted
from csm_core.monitor.tikhub.errors import TikHubBalanceExhausted, TikHubError

logger = logging.getLogger(__name__)

HARD_CAP = 80          # 每平台单次采集条数硬顶（spec D3）
MAX_PAGES = 12         # 翻页硬闸：抖音每页 ~6–14 条，80 条最多 ~12 页；超过视为异常停
PAGE_RETRIES = 3       # 每页最多尝试次数（官方：搜索偶发失败，同参重试 1–3 次）
_RETRY_SLEEP_S = 1.0   # 重试间隔（测试里 monkeypatch 成 0）
_CURSOR_KEYS = ("cursor", "page", "pcursor")


@dataclass(frozen=True)
class SearchSpec:
    platform: Platform
    method: str                                                        # "GET" | "POST"
    path: str
    first_request: Callable[[str, dict[str, Any]], dict[str, Any]]      # (keyword, plat_filters)
    next_request: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]  # (prev, raw)
    normalize: Callable[[dict[str, Any], dict[str, Any]], list[VideoCard]]           # (raw, plat_filters)


DOUYIN_SEARCH_SPEC = SearchSpec(
    "douyin", "POST", "/api/v1/douyin/search/fetch_video_search_v2",
    N.douyin_first_body, N.douyin_next_body, N.normalize_douyin_search,
)
BILIBILI_SEARCH_SPEC = SearchSpec(
    "bilibili", "GET", "/api/v1/bilibili/web/fetch_general_search",
    N.bilibili_first_params, N.bilibili_next_params, N.normalize_bilibili_search,
)
KUAISHOU_SEARCH_SPEC = SearchSpec(
    "kuaishou", "GET", "/api/v1/kuaishou/app/search_video_v2",
    N.kuaishou_first_params, N.kuaishou_next_params, N.normalize_kuaishou_search,
)


def _cursor_of(req: dict[str, Any]) -> str:
    """日志用：只取游标类字段（不记 keyword 等业务值）。"""
    return ",".join(f"{k}={req[k]!r}" for k in _CURSOR_KEYS if k in req)


class _PageError(Exception):
    """一页的获取 / 解析失败（重试已耗尽）。reason 面向用户。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TikHubSearchAdapter:
    """一个通用适配器 + 平台 spec。client_factory 惰性建 client（配置改了下个任务生效）。"""

    def __init__(self, spec: SearchSpec, client_factory: Callable[[], TikHubClient]):
        self.spec = spec
        self.platform: Platform = spec.platform
        self._cf = client_factory

    # ── 单页调用（含重试）──────────────────────────────────────────────
    def _call(self, client: TikHubClient, req: dict[str, Any]) -> dict[str, Any]:
        if self.spec.method == "POST":
            return client.post(self.spec.path, req)
        return client.get(self.spec.path, req)

    def _call_with_retry(self, client: TikHubClient, req: dict[str, Any]) -> dict[str, Any]:
        last: TikHubError | None = None
        for attempt in range(1, PAGE_RETRIES + 1):
            try:
                return self._call(client, req)
            except TikHubBalanceExhausted:
                raise                                   # 余额耗尽不重试
            except TikHubError as e:
                last = e
                logger.info(
                    "[tikhub-search] %s page attempt %d/%d failed: %s",
                    self.platform, attempt, PAGE_RETRIES, e.reason,
                )
                if attempt < PAGE_RETRIES:
                    time.sleep(_RETRY_SLEEP_S)
        assert last is not None
        raise last

    def _fetch_page(
        self, client: TikHubClient, req: dict[str, Any], plat_filters: dict[str, Any],
    ) -> tuple[list[VideoCard], dict[str, Any] | None]:
        """取一页并归一化，返回 (cards, next_req)。任何异常统一成 _PageError。"""
        try:
            raw = self._call_with_retry(client, req)
        except TikHubError as e:
            raise _PageError(e.reason) from e
        try:
            cards = self.spec.normalize(raw, plat_filters)
            nxt = self.spec.next_request(req, raw)
        except Exception as e:  # noqa: BLE001 — 适配器层永不异常穿透
            logger.warning("[tikhub-search] %s parse error: %r", self.platform, e, exc_info=True)
            raise _PageError(f"响应解析失败：{e!r}"[:160]) from e
        return cards, nxt

    # ── SearchAdapter Protocol ─────────────────────────────────────────
    def search(
        self,
        keyword: str,
        target_count: int,
        on_card: OnCard,
        on_progress: OnProgress,
        cancel_event: threading.Event,
        max_attempts: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> SearchOutcome:
        target = max(1, min(int(target_count), HARD_CAP))
        plat_filters = (filters or {}).get(self.platform) or {}
        max_pages = MAX_PAGES if max_attempts is None else max(1, min(MAX_PAGES, int(max_attempts)))

        def _progress(phase: str, got: int, note: str = "") -> None:
            on_progress(ProgressUpdate(
                platform=self.platform, phase=phase, got=got, target=target, note=note[:120],
            ))

        def _failed(reason: str, emitted: int, pages: int = 0) -> SearchOutcome:
            _progress("failed", emitted, reason)
            suffix = f"（已抓 {pages} 页）" if pages else ""
            return SearchOutcome(
                platform=self.platform, status="failed", cards_emitted=emitted,
                error_message=f"TikHub 搜索失败{suffix}：{reason}",
            )

        def _done(emitted: int, note: str = "") -> SearchOutcome:
            _progress("done", emitted, note)
            return SearchOutcome(
                platform=self.platform, status="done", cards_emitted=emitted, error_message=note,
            )

        if balance_exhausted():
            return _failed("TikHub 余额不足（本轮短路，未发请求）", 0)
        try:
            client = self._cf()
        except Exception as e:                           # 缺 key / 配置损坏 → 记失败，不抛
            return _failed(str(getattr(e, "reason", e)), 0)

        _progress("scrolling", 0)
        emitted = 0
        pages = 0
        seen: set[str] = set()
        req = self.spec.first_request(keyword, plat_filters)
        while emitted < target and pages < max_pages:
            if cancel_event.is_set():
                return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
            try:
                cards, nxt = self._fetch_page(client, req, plat_filters)
            except _PageError as e:
                if emitted == 0:
                    return _failed(e.reason, 0, pages)
                # 已有候选入库：后续页失败只停止，不把整个平台记成失败（runner 只对 done 跑预筛）
                logger.warning(
                    "[tikhub-search] %s stopped at page %d after %d cards: %s",
                    self.platform, pages + 1, emitted, e.reason,
                )
                return _done(emitted, f"第 {pages + 1} 页失败已停止：{e.reason}")
            pages += 1
            new_this_page = 0
            for card in cards:
                if emitted >= target:
                    break
                if card.platform_video_id in seen:
                    continue
                seen.add(card.platform_video_id)
                emitted += 1
                new_this_page += 1
                card.rank_in_search = emitted
                on_card(card)
            logger.info(
                "[tikhub-search] %s page %d [%s] -> %d cards, %d new, emitted=%d/%d",
                self.platform, pages, _cursor_of(req), len(cards), new_this_page, emitted, target,
            )
            _progress("scrolling", emitted)
            if cards and new_this_page == 0:
                logger.info("[tikhub-search] %s page %d was all duplicates; stopping", self.platform, pages)
                break
            if nxt is None:
                break
            req = nxt

        if cancel_event.is_set():
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        return _done(emitted)


def build_tikhub_search_adapters(get_config, key_reader) -> dict[str, TikHubSearchAdapter]:
    """构造 {platform: adapter}。与 monitor.tikhub.build_api_adapters 同款注入方式：
    get_config() -> AppConfig（取 monitor.tikhub_base_url）；key_reader("tikhub", cfg) -> key。
    key 为空时 factory 抛 TikHubError，适配器捕获后记 failed（永不异常穿透）。"""
    def client_factory() -> TikHubClient:
        cfg = get_config()
        key = (key_reader("tikhub", cfg) or "").strip()
        if not key:
            raise TikHubError("未配置 TikHub API Key，请到设置页粘贴")
        return TikHubClient(base_url=cfg.monitor.tikhub_base_url, api_key=key)

    return {
        "douyin": TikHubSearchAdapter(DOUYIN_SEARCH_SPEC, client_factory),
        "bilibili": TikHubSearchAdapter(BILIBILI_SEARCH_SPEC, client_factory),
        "kuaishou": TikHubSearchAdapter(KUAISHOU_SEARCH_SPEC, client_factory),
    }
