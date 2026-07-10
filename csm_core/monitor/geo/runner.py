"""GEO 采集并发调度器(纯逻辑,无 I/O)。

把 (关键词, 平台) cell 列表按平台 mode 分成两条车道并发执行:
- API 车道:线程池并发所有 API cell(默认 5 并发)。
- RPA 车道:每平台一个 worker 串行跑自己的关键词(平台内串行 = 每关键词
  独立会话,无上下文污染),最多 rpa_platform_concurrency 个平台并发。

进度:单一带锁计数器,保证末次 progress_cb == (total, total)。
取消:任一 cell 抛「取消」异常(is_cancelled)即置标志,其余 cell 早退,
join 所有线程后把该异常重新抛出(不留孤儿浏览器)。
返回:按传入 cells_plan 顺序排列的 GeoCell 列表。
"""
from __future__ import annotations
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..base import is_cancelled
from .models import GeoCell

logger = logging.getLogger(__name__)


def run_cells_dual_lane(
    cells_plan: "list[tuple[str, str]]",
    run_cell: "Callable[[str, str], GeoCell]",
    *,
    mode_of: "Callable[[str], str]",
    api_pool_size: int = 5,
    rpa_platform_concurrency: int = 3,
    progress_cb: "Callable[[int, int], None] | None" = None,
    initial_done: int = 0,
) -> "list[GeoCell]":
    total = initial_done + len(cells_plan)
    results: "list[GeoCell | None]" = [None] * len(cells_plan)
    lock = threading.Lock()
    done = {"n": initial_done}
    cancelled: "dict[str, BaseException | None]" = {"exc": None}

    def _emit_initial() -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(initial_done, total)
        except Exception:
            logger.exception("[geo.runner] progress_cb(initial) raised; ignoring")

    def _tick() -> None:
        if progress_cb is None:
            return
        # 自增与回调一起放锁内 → 回调按计数顺序串行,末次必是 (total, total)。
        # 若把 progress_cb 移出锁,慢线程可能在 (total,total) 之后才发 (total-1,total),
        # 让进度条卡在满格之下,并使 fetch 的 progress[-1]==(total,total) 断言变 flaky。
        with lock:
            done["n"] += 1
            n = done["n"]
            try:
                progress_cb(n, total)
            except Exception:
                logger.exception("[geo.runner] progress_cb(%s,%s) raised; ignoring", n, total)

    def _one(i: int) -> None:
        if cancelled["exc"] is not None:
            return
        kw, plat = cells_plan[i]
        try:
            results[i] = run_cell(kw, plat)
        except BaseException as e:          # noqa: BLE001 —— 取消是 BaseException 之外的普通异常,但统一兜
            if is_cancelled(e):
                cancelled["exc"] = e
                return
            raise                            # run_cell 应自行把非取消异常隔离成 error cell;冒泡=上游 bug
        _tick()

    def _rpa_worker(indices: "list[int]") -> None:
        for i in indices:
            if cancelled["exc"] is not None:
                return
            _one(i)

    _emit_initial()

    api_idx = [i for i, (_, p) in enumerate(cells_plan) if mode_of(p) == "api"]
    rpa_groups: "dict[str, list[int]]" = {}
    for i, (_, p) in enumerate(cells_plan):
        if mode_of(p) != "api":
            rpa_groups.setdefault(p, []).append(i)

    api_ex = ThreadPoolExecutor(max_workers=max(1, api_pool_size))
    rpa_ex = ThreadPoolExecutor(max_workers=max(1, rpa_platform_concurrency))
    futs = []
    try:
        for i in api_idx:
            futs.append(api_ex.submit(_one, i))
        for indices in rpa_groups.values():
            futs.append(rpa_ex.submit(_rpa_worker, indices))
        for f in futs:
            f.result()                       # join 全部;非取消异常在此重抛
    finally:
        api_ex.shutdown(wait=True)           # 等所有在飞 cell 收尾 → 不留孤儿浏览器
        rpa_ex.shutdown(wait=True)

    if cancelled["exc"] is not None:
        raise cancelled["exc"]
    return [c for c in results]              # 非取消路径下全部已填充
