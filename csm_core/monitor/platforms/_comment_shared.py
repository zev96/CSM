"""进程级评论区快照共享 —— 同视频多任务每轮只抓一次评论区。

背景：任务身份键是 (type, target_url, 评论文本)，同一条视频下可以有
N 条评论任务（各监测一条评论）。派发是逐任务的（定时 tick 与手动
run-now 都是），没有共享层时同一视频的评论区每轮会被完整抓 N 次：
本地模式同 cookie 反复穷举同一视频翻页是显眼的机器人特征，TikHub
模式每页计费直接 ×N。共享层放在适配器层而不是 monitor_loop —— loop
的两条派发路径（tick / run-now 逐任务 POST）都会自动经过这里，且
取消令牌、进度事件、活跃跟踪全部保持逐任务语义，loop 一行不改。

共享单元 = 一份评论区快照，keyed by (source, platform, video_id)：
  - source 区分本地网页端与 TikHub APP 端（两端评论排序不同，绝不互用）；
  - video_id 用解析后的视频 ID —— 同视频的不同 URL 写法（短链 / 全链）
    也能共享；URL → video_id 的解析结果另有一层小缓存（短链展开是一次
    真实请求，同视频 N 任务只展开一次）。

语义（等价于「每轮每视频抓一次」）：
  - 单飞：同 key 并发抓取只放行一个，其余任务等它的结果（等待期间仍
    响应自己的取消令牌；等待超时则放弃共享自己抓，防挂死）；
  - served-set：每个任务对同一份快照最多消费一次 —— 同一任务再次运行
    （用户重跑）会强制刷新快照，随后组内其他任务复用新快照。这让
    "linger 窗口"只是同一轮内排队任务的复用窗口，不是跨轮缓存；
  - 失败负缓存：抓取失败（含风控）在窗口内对组内所有任务统一报同一
    原因，避免对疑似风控 / 失效的端点连环重试；熔断器只被真实抓取记
    一次（簿记都在 do_fetch 闭包里，复用方不碰）；
  - 截短快照防错位：因「命中即停」提前收工的快照（early_stopped），
    只有「在快照里能命中自己评论」的任务可复用；命中不了的任务必须
    自己重抓 —— 绝不把"快照没抓那么深"误报成"评论不在"。翻尽整个
    评论区（exhausted）或覆盖完整深度的快照对任何任务都是完整证据。

task.id 为 None（mining 引流预筛 / 脚本 / 单测直接调适配器）时 task_id
记 0，**完全绕过共享仓**：不读、不写、不单飞，每次都真实抓取 —— 即
"无 id 就不共享"，与旧行为逐字节一致。这同时隔离了 mining 预筛：它用
浅深度（scrape_top_n=30）+ 占位评论文本扫同一批视频，若与监控任务共
仓，预筛失败会负缓存喂给监控、预筛浅快照会被监控当成本轮数据。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..base import MonitorResult, MonitorTask, maybe_cancel
from ..text_match import find_best_match
from ._comment_common import build_match_result, fail_result, risk_control_result

logger = logging.getLogger(__name__)

#: 快照存活窗口（秒）。只需覆盖「同一轮派发里排队在后的同视频任务」——
#: 组员紧随 fetcher 之后到达通常是秒级，放宽到 15 分钟是容忍多视频交错
#: 排队的极端顺序。每日定时的轮间隔远大于它，不构成跨轮缓存。
_LINGER_SECONDS = 900.0

#: 等待别的线程抓同一 key 的上限（秒）；超过则放弃共享、自己抓（防挂死）。
#: 必须 ≥ 最坏**合法** fetch 时长（bilibili 20 页 ×(pacer 15s + HTTP 20s) +
#: aid 解析 ≈ 700s+），否则极慢但正常的抓取会让等待者提前放弃、对同一
#: 视频开出第二路并发抓取 —— 恰是本功能要消除的机器人特征。
_WAIT_FETCH_TIMEOUT = 900.0


@dataclass
class CommentSnapshot:
    """一次评论区抓取的结果（或失败）。comments 的 rank 必须是全局位次。"""

    comments: list[dict[str, Any]] = field(default_factory=list)
    #: 本次抓取的目标深度（scrape_top_n / depth）。
    depth: int = 0
    #: 评论区在到达 depth 前被翻尽（快照就是完整评论区）。
    exhausted: bool = False
    #: 因命中即停 / 取消而提前收工（快照比 depth 短是"故意的"，不完整）。
    early_stopped: bool = False
    #: 非 None = 抓取失败（负缓存），值为错误原因。
    error: str | None = None
    #: 失败来源标签（fail_result 的 source 位）。
    error_source: str = "fetch"
    #: 非 None = 风控（risk_control_result 的 source 位），优先于 error。
    risk_source: str | None = None
    #: False = 不入缓存（如用户取消导致的截断快照，只给取消者本人用）。
    cacheable: bool = True
    #: time.monotonic() 打点（store 写入时盖章）。
    at: float = 0.0
    #: 已消费过本快照的 task_id 集合（served-set，见模块 docstring）。
    served: set[int] = field(default_factory=set)


def result_from_snapshot(
    task: MonitorTask,
    snap: CommentSnapshot,
    *,
    source: str,
    scan_limit: int | None = None,
) -> MonitorResult:
    """快照 → MonitorResult。失败 / 风控快照映射回适配器的原有结果形状。

    评论 dict 逐条浅拷贝再交给 build_match_result：metric.hot_comments 会
    随结果落库 / 发事件，若与缓存快照共享同一批 dict，任何下游写者都会
    跨任务 + 回溯污染缓存 —— 拷一层把别名面掐断（150 条 dict 的成本可忽略）。
    """
    if snap.risk_source:
        return risk_control_result(task, snap.risk_source)
    if snap.error is not None:
        return fail_result(task, snap.error_source, snap.error)
    comments = [dict(c) for c in snap.comments]
    return build_match_result(task, comments, source=source, scan_limit=scan_limit)


def group_comment_texts(task: MonitorTask) -> list[str]:
    """同 (type, target_url) 全部启用任务的评论文本（含自己），排序去重。

    给 TikHub 的命中即停当组感知谓词用：快照是共享的，必须扫到「该视频
    所有在监测的评论都命中」或翻满深度才停 —— 只按自己的评论停会让快照
    对组内其他任务不完整（有防错位守卫兜底，但会退化成各自重抓）。

    storage 未初始化（独立脚本 / 单测直接调适配器）或查询失败时退化为
    只看自己 —— 行为与共享层引入前逐字节一致。
    """
    own = str((task.config or {}).get("my_comment_text") or "").strip()
    texts = {own} if own else set()
    try:
        from .. import storage

        for t in storage.list_tasks(type=task.type):
            if not t.enabled or t.target_url != task.target_url:
                continue
            txt = str((t.config or {}).get("my_comment_text") or "").strip()
            if txt:
                texts.add(txt)
    except Exception:
        # storage 未 init（RuntimeError）或任何查询失败 → 退化为单任务谓词。
        logger.debug("group_comment_texts fallback to own text", exc_info=True)
    return sorted(texts)


class SharedCommentStore:
    def __init__(
        self,
        *,
        linger_seconds: float = _LINGER_SECONDS,
        wait_timeout: float = _WAIT_FETCH_TIMEOUT,
    ) -> None:
        self._linger = float(linger_seconds)
        self._wait_timeout = float(wait_timeout)
        self._lock = threading.Lock()
        self._snaps: dict[tuple, CommentSnapshot] = {}
        self._inflight: dict[tuple, threading.Event] = {}
        # (source, platform, url) -> (vid, id_type, at)
        self._vids: dict[tuple, tuple[str, str, float]] = {}

    # ── URL → video_id 缓存（省同视频短链的重复展开请求）─────────────────
    def get_video_id(self, source: str, platform: str, url: str) -> tuple[str, str] | None:
        with self._lock:
            hit = self._vids.get((source, platform, url))
            if hit is None:
                return None
            vid, id_type, at = hit
            if (time.monotonic() - at) >= self._linger:
                del self._vids[(source, platform, url)]
                return None
            return vid, id_type

    def put_video_id(
        self, source: str, platform: str, url: str, vid: str, id_type: str = ""
    ) -> None:
        with self._lock:
            self._vids[(source, platform, url)] = (vid, id_type, time.monotonic())

    # ── 快照复用判定 ─────────────────────────────────────────────────────
    def _fresh(self, snap: CommentSnapshot) -> bool:
        return (time.monotonic() - snap.at) < self._linger

    @staticmethod
    def _usable_for(
        snap: CommentSnapshot, my_text: str, threshold: float, depth: int
    ) -> bool:
        # 负缓存（失败 / 风控）对组内所有任务"可用"——统一报同一原因。
        if snap.error is not None or snap.risk_source:
            return True
        ranked = [c for c in snap.comments if c.get("rank", -1) > 0]
        if find_best_match(my_text, ranked, threshold)["found"]:
            return True
        if snap.exhausted:
            return True
        # 未截短且覆盖了本任务要求的深度：未命中 = 真不在窗口内。
        return (not snap.early_stopped) and snap.depth >= depth

    def peek(
        self,
        key: tuple,
        *,
        task_id: int,
        my_text: str,
        threshold: float,
        depth: int,
    ) -> CommentSnapshot | None:
        """纯内存查询：有本任务可复用的快照就消费并返回，否则 None。

        不等待、不抓取 —— 给本地适配器放在熔断 / 建会话之前用：复用命中
        时零网络、零副作用直接出结果。
        """
        if task_id == 0:
            # 无 id 调用（mining 预筛 / 脚本 / 单测）不参与共享 —— 见模块 docstring。
            return None
        with self._lock:
            snap = self._snaps.get(key)
            if snap is None:
                return None
            if not self._fresh(snap):
                del self._snaps[key]
                return None
            if task_id in snap.served:
                return None
            if not self._usable_for(snap, my_text, threshold, depth):
                return None
            snap.served.add(task_id)
            return snap

    def run(
        self,
        key: tuple,
        *,
        task_id: int,
        my_text: str,
        threshold: float,
        depth: int,
        cancel_token: "threading.Event | None",
        do_fetch: Callable[[], CommentSnapshot],
    ) -> CommentSnapshot:
        """复用可用快照，否则单飞抓取（其余同 key 任务等待结果）。

        do_fetch 闭包负责真实抓取与全部簿记（pacer / 熔断 / cookie 标记），
        失败以 error / risk_source 字段表达而不是抛异常；上抛的异常（典型：
        maybe_cancel 的取消）会清理单飞状态后原样传播 —— 等待者随后接棒
        自己抓，取消只作用于被取消的那个任务。
        """
        if task_id == 0:
            # 无 id 调用（mining 预筛 / 脚本 / 单测）完全绕过共享仓：不读、
            # 不写、不单飞 —— 预筛的浅快照 / 失败绝不能污染监控任务，反之
            # 监控快照也不该被预筛消费。见模块 docstring。
            return do_fetch()
        deadline = time.monotonic() + self._wait_timeout
        while True:
            with self._lock:
                snap = self._snaps.get(key)
                if snap is not None and not self._fresh(snap):
                    del self._snaps[key]
                    snap = None
                if (
                    snap is not None
                    and task_id not in snap.served
                    and self._usable_for(snap, my_text, threshold, depth)
                ):
                    snap.served.add(task_id)
                    return snap
                ev = self._inflight.get(key)
                if ev is None:
                    # 由本任务抓：无快照 / 已消费过（重跑）/ 快照对本任务不可用。
                    ev = threading.Event()
                    self._inflight[key] = ev
                    break
            # 别的任务在抓同一 key —— 等它，期间保持本任务自己的取消语义。
            if time.monotonic() > deadline:
                # 等待超时（fetcher 疑似挂死）：放弃共享，自己抓。不注册
                # 单飞、结果不回写 —— 免得与迟到的 fetcher 互踩缓存。
                logger.warning(
                    "shared comment fetch wait timed out for %s; fetching solo", key
                )
                return do_fetch()
            maybe_cancel(cancel_token)
            ev.wait(0.5)

        # 本任务是 fetcher。
        try:
            snap = do_fetch()
        except BaseException:
            with self._lock:
                self._inflight.pop(key, None)
            ev.set()
            raise
        with self._lock:
            snap.at = time.monotonic()
            snap.served = {task_id}
            if snap.cacheable:
                self._snaps[key] = snap
            else:
                self._snaps.pop(key, None)
            self._inflight.pop(key, None)
        ev.set()
        return snap


# ── 进程级单例 ──────────────────────────────────────────────────────────────
_STORE = SharedCommentStore()


def shared_store() -> SharedCommentStore:
    """适配器统一从这里取仓（函数间接层让测试能整仓重置）。"""
    return _STORE


def reset_shared_store() -> None:
    """测试专用：换一个全新的空仓（防跨测试串快照 / 串 vid 缓存）。"""
    global _STORE
    _STORE = SharedCommentStore()
