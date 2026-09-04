"""TikHub 付费关键词搜索适配器 —— 采集模块「找视频」这一步的 API 路径。

设计依据：docs/superpowers/specs/2026-09-01-mining-tikhub-search-design.md（§5.3 / §5.4）
+ 实现期修订（plan「Amendments」修订 B）。

实现现有 ``SearchAdapter`` Protocol；拿到 ``VideoCard`` 后走与浏览器适配器**完全相同**的
``on_card`` 管线（去重 / 入库 / 品牌预筛都不变）。与浏览器路径的差异：

- 免登录、无并发风控限速（这正是切换的动机）；
- 失败**不回退**浏览器（spec D5）；
- 每页失败**重试 ≤ PAGE_RETRIES 次**，且只重试「服务端没出货」的失败（网络未连上 /
  HTTP 5xx / 429，见 ``_retryable``）；已出货响应（HTTP 200 + body code≠200，含
  body 429 / 读超时等"请求已发出"类网络错误）一律不重试，避免重复计费；402 余额耗尽
  **不重试**，并触发进程级余额闩（闩本身带 TTL 兜底，见
  ``monitor.tikhub.client.BALANCE_LATCH_TTL_S``；本适配器不再做「开搜前全局预检」——
  job 级短路由 runner 负责，一次 402 仍会在请求中途通过 client 触发闩）；
- 终止判据（成本护栏，按触发顺序）：达 target / 整页都是重复卡（cards 非空且 0 张新卡，
  游标疑似卡住）/ 连续 ``_MAX_EMPTY_PAGES`` 页无有效结果 / 无下一页 / MAX_PAGES 硬闸。
  单页被本地过滤为空但未连续达到止损阈值**不**停（快手日期区间靠翻页补偿）；未达 target
  就提前停止时，note 里写明具体停止原因，方便诊断；
- 页级错误语义：**首页**失败（重试耗尽 / 解析异常）→ ``failed``；**已发出 ≥1 张卡后**的
  后续页失败 → ``done`` + note（已入库的候选不能因翻页失败被记成失败——runner 只对
  ``done`` 跑品牌预筛）；
- 适配器层永不异常穿透：normalize / next_request 的任何异常都按页级错误处理，且日志/
  note 绝不 ``repr()`` 第三方异常（R7 安全红线——某些异常的 repr 会带出触发它的完整
  原始字符串，例如含非 ASCII 字符的 key 编码失败时的 UnicodeEncodeError），只记类型名。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from csm_core.mining.models import Platform, ProgressUpdate, SearchOutcome, VideoCard
from csm_core.mining.platforms import tikhub_normalize as N
from csm_core.mining.platforms._common import OnCard, OnProgress
from csm_core.monitor.tikhub.client import TikHubClient
from csm_core.monitor.tikhub.errors import TikHubBalanceExhausted, TikHubError

logger = logging.getLogger(__name__)

HARD_CAP = 80          # 每平台单次采集条数硬顶（spec D3）
# 翻页硬闸：抖音每页 ~6–14 条，80 条最多 ~12 页；超过视为异常停。
# 上界优先成本：抖音实测每页 6–14 条，落到 6 条/页时 12 页只有 72 < 80，可能翻不满硬顶。
MAX_PAGES = 12
PAGE_RETRIES = 3       # 每页最多尝试次数（官方：搜索偶发失败，同参重试 1–3 次）
_RETRY_SLEEP_S = 1.0   # 重试间隔（测试里 monkeypatch 成 0）
_CURSOR_KEYS = ("cursor", "page", "pcursor")
_MAX_EMPTY_PAGES = 3   # 连续几页 0 张有效卡就止损（C3）：本地过滤/风控软限流常见表现，
                       # 靠 MAX_PAGES 硬闸兜底代价太大（每页仍是一次计费请求）。


def _retryable(e: TikHubError) -> bool:
    """只重试「服务端没出货」的失败。判据优先级：
    1) e.retryable 显式声明（由 client.get()/post() 在请求发送阶段的三类失败上
       显式置位：连接未建立=可重试；已发出但读超时等=不可重试；发送前构造失败=
       不可重试）—— 有显式声明就直接采信，不再靠 code/from_body 推导。
    2) from_body=True：HTTP 200 + body code≠200，服务端已出货（可能已计费），
       即使 body code 恰好是 429 也不重试——这是"服务端已经处理并回了限流提示"，
       跟"请求根本没被处理"的真限流是两回事，必须先判 from_body 再看 429。
    3) 真正没出货的限流/瞬时故障：网络错误（code None）/ HTTP 5xx / HTTP 429。
    401/403（key 无效，重试无意义）、其它 4xx 都不重试。"""
    if e.retryable is not None:
        return e.retryable
    if getattr(e, "from_body", False):  # HTTP 200 + body code≠200：服务端已出货，可能已计费
        return False
    code = e.code
    return code is None or code == 429 or (isinstance(code, int) and 500 <= code < 600)


def _retry_delay(code: int | None, attempt: int) -> float:
    """429 指数退避（1×,2×,4×…），其它固定间隔。"""
    return _RETRY_SLEEP_S * (2 ** (attempt - 1)) if code == 429 else _RETRY_SLEEP_S


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

    def _call_with_retry(
        self, client: TikHubClient, req: dict[str, Any], cancel_event: threading.Event,
    ) -> dict[str, Any]:
        last: TikHubError | None = None
        for attempt in range(1, PAGE_RETRIES + 1):
            try:
                return self._call(client, req)
            except TikHubBalanceExhausted:
                raise                                   # 余额耗尽不重试
            except TikHubError as e:
                last = e
                if not _retryable(e):
                    raise                                # 服务端已出货/鉴权失败等：重试无意义或有风险
                logger.info(
                    "[tikhub-search] %s page attempt %d/%d failed: %s",
                    self.platform, attempt, PAGE_RETRIES, e.reason,
                )
                if attempt < PAGE_RETRIES:
                    # 用 Event.wait 代替 sleep：取消事件在等待期间被置位会立即唤醒，
                    # 不必等满整个重试间隔才发现用户已取消（M1）。
                    if cancel_event.wait(_retry_delay(e.code, attempt)):
                        raise _PageError("已取消") from e
        assert last is not None
        raise last

    def _fetch_page(
        self, client: TikHubClient, req: dict[str, Any], plat_filters: dict[str, Any],
        cancel_event: threading.Event,
    ) -> tuple[list[VideoCard], dict[str, Any] | None]:
        """取一页并归一化，返回 (cards, next_req)。任何异常统一成 _PageError。"""
        try:
            raw = self._call_with_retry(client, req, cancel_event)
        except _PageError:
            raise                                        # 已经是页级错误（如取消），原样上抛
        except TikHubError as e:
            raise _PageError(e.reason) from e
        except Exception as e:  # noqa: BLE001 — 适配器层永不异常穿透：覆盖 httpx.InvalidURL /
            # UnicodeEncodeError / transport 插件 bug 等不是 TikHubError 的异常（I1）。
            # S1 安全红线：绝不能用 %r/repr(e) —— UnicodeEncodeError 等异常的 repr() 会
            # 带出触发编码失败的整个原始字符串（含 "Bearer <key>" 全文）；str(e)/traceback
            # 本身是安全的（只含编解码位置信息，不含原串），但只记类型名更省心也更保险。
            logger.warning(
                "[tikhub-search] %s request error: %s", self.platform, type(e).__name__, exc_info=True,
            )
            raise _PageError(f"请求失败：{type(e).__name__}"[:160]) from e
        try:
            cards = self.spec.normalize(raw, plat_filters)
            # 具体化 + 校验必须在 try 内完成：normalize 可能返回一个惰性生成器，
            # 真正的异常要到迭代时才抛出——如果这里只是把生成器原样传出去，异常会在
            # try 块外的 for 循环里穿透 search()。同时过滤掉非 VideoCard 元素，
            # 防止归一化实现返回脏数据时下游属性访问穿透。
            cards = [c for c in (cards or []) if isinstance(c, VideoCard)]
            nxt = self.spec.next_request(req, raw)
        except Exception as e:  # noqa: BLE001 — 适配器层永不异常穿透；同上不 repr(e)（S1）
            logger.warning(
                "[tikhub-search] %s parse error: %s", self.platform, type(e).__name__, exc_info=True,
            )
            raise _PageError(f"响应解析失败：{type(e).__name__}"[:160]) from e
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
        plat_filters = filters.get(self.platform) if isinstance(filters, dict) else None
        plat_filters = plat_filters if isinstance(plat_filters, dict) else {}
        # 不读 mining/config.MAX_ATTEMPTS_PER_PLATFORM：那是浏览器路径的反爬翻页上限；
        # API 路径无风控，页数只是成本闸。
        max_pages = MAX_PAGES if max_attempts is None else max(1, min(MAX_PAGES, int(max_attempts)))

        def _progress(phase: str, got: int, note: str = "") -> None:
            on_progress(ProgressUpdate(
                platform=self.platform, phase=phase, got=got, target=target, note=note[:120],
            ))

        def _failed(reason: str, emitted: int, pages: int = 0) -> SearchOutcome:
            reason = reason[:200]
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

        # 不再在这里做「开搜前全局余额预检」——job 级短路移交 runner（另一 agent）；
        # 一次 402 仍会在下面的请求中途通过 client._fail() 触发进程级闩，只是不再
        # 由本适配器在发第一个请求之前就抢先短路整个 job。
        try:
            client = self._cf()
        except Exception as e:                           # 缺 key / 配置损坏 → 记失败，不抛
            # S1：不 str(e) 兜底——任意第三方异常的 str() 都可能带出敏感上下文；
            # 优先信任 TikHubError.reason（我们自己写的、已知安全的中文原因），
            # 否则只报类型名。
            reason = getattr(e, "reason", None) or f"客户端构建失败：{type(e).__name__}"
            return _failed(reason, 0)

        _progress("scrolling", 0)
        emitted = 0
        pages = 0
        empty_streak = 0
        stop_reason = ""
        seen: set[str] = set()
        try:
            req = self.spec.first_request(keyword, plat_filters)
        except Exception as e:  # noqa: BLE001 — 筛选值类型错等，记失败不穿透；S1 不 repr(e)
            return _failed(f"请求构造失败：{type(e).__name__}", 0)
        while emitted < target and pages < max_pages:
            if cancel_event.is_set():
                return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
            try:
                cards, nxt = self._fetch_page(client, req, plat_filters, cancel_event)
            except _PageError as e:
                if cancel_event.is_set():
                    # 重试等待期间被取消（M1）：不算失败，也不算已停止的 done —— 与
                    # 用户主动取消同一语义。
                    return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
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
            # C3：连续 N 页 0 张有效卡就止损——单独一页被本地过滤为空不停（快手日期
            # 区间靠翻页补偿），但连续多页都是空的多半是风控软限流/查询本身无结果，
            # 靠 MAX_PAGES 硬闸兜底代价太大（每页仍是一次计费请求）。
            if cards:
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak >= _MAX_EMPTY_PAGES:
                    stop_reason = f"连续 {empty_streak} 页无有效结果"
                    break
            if cards and new_this_page == 0:
                logger.info("[tikhub-search] %s page %d was all duplicates; stopping", self.platform, pages)
                stop_reason = "整页均为重复卡（游标疑似未推进）"
                break
            if nxt is None:
                if emitted < target:
                    stop_reason = "服务端无下一页"
                break
            req = nxt

        # D3：pages 达到硬闸而不是因为 target 已凑够退出循环——上面几种 break 都会
        # 显式写好 stop_reason，只有"自然跑满 max_pages"这一种退出方式没有单独的
        # break 语句可挂，在这里补上。
        if not stop_reason and pages >= max_pages and emitted < target:
            stop_reason = f"达到翻页上限 {max_pages} 页"

        # 循环退出后取消事件已置位：只有还没达标时才算真正的"用户取消打断"；已经
        # 凑够 target 条的话，循环是因为 emitted>=target 正常退出的，不应把已经
        # 入库的候选降级成 cancelled 而丢弃。
        if cancel_event.is_set() and emitted < target:
            return SearchOutcome(platform=self.platform, status="cancelled", cards_emitted=emitted)
        # D3：早停时把具体原因写进 note，方便诊断"为什么没凑够 target"。
        # 翻了页却一条都没命中：多半是筛选条件过严/关键词冷门，不是采集本身出了问题——
        # 给用户一个可诊断的提示,而不是静默的"done, 0 条"（0 命中诊断优先，止损原因追加
        # 在后面，两者不互斥——0 命中本身也是止损触发的结果）。
        if emitted == 0 and pages > 0:
            note = f"已翻 {pages} 页，0 条命中（筛选条件可能过严或无结果）"
            if stop_reason:
                note += f"；{stop_reason}"
        elif emitted < target and stop_reason:
            note = f"提前停止：{stop_reason}（{emitted}/{target}）"
        else:
            note = ""
        return _done(emitted, note)


def build_tikhub_search_adapters(
    get_config: Callable[[], Any], key_reader: Callable[[str, Any], str | None],
) -> dict[str, TikHubSearchAdapter]:
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
