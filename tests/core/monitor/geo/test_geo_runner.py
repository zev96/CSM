from __future__ import annotations
import threading
import time
import pytest

from csm_core.monitor.geo import runner
from csm_core.monitor.geo.models import GeoCell


def _cell(kw, plat, status="ok"):
    return GeoCell(platform=plat, keyword=kw, status=status)


def test_results_in_plan_order_and_progress_bounds():
    plan = [("k1", "tongyi"), ("k2", "tongyi"), ("k1", "kimi"), ("k2", "kimi")]
    calls = []

    def run_cell(kw, plat):
        return _cell(kw, plat)

    prog = []
    out = runner.run_cells_dual_lane(
        plan, run_cell,
        mode_of=lambda p: "api",            # 全 API 车道
        api_pool_size=4, rpa_platform_concurrency=3,
        progress_cb=lambda c, t: prog.append((c, t)),
    )
    assert [(c.keyword, c.platform) for c in out] == plan   # 顺序 == plan
    assert prog[0] == (0, 4)                                # 初始事件先发
    assert prog[-1] == (4, 4)                               # 末值必达 total
    assert len(out) == 4


def test_api_lane_runs_concurrently():
    # 两个 API cell 必须同时在飞才能一起过 Barrier;若被串行执行 → 第二个永远
    # 到不了 Barrier,首个 wait 超时 BrokenBarrier → 断言失败。确定性,不靠 sleep 猜。
    barrier = threading.Barrier(2, timeout=3)
    plan = [("k1", "tongyi"), ("k2", "tongyi")]

    def run_cell(kw, plat):
        barrier.wait()                       # 需要 2 个并发才能通过
        return _cell(kw, plat)

    out = runner.run_cells_dual_lane(
        plan, run_cell, mode_of=lambda p: "api",
        api_pool_size=2, rpa_platform_concurrency=3,
    )
    assert len(out) == 2                      # 未抛 BrokenBarrierError → 确有并发


def test_rpa_same_platform_serial_cross_platform_concurrent():
    active: "dict[str, bool]" = {}
    overlap_violation = {"v": False}
    guard = threading.Lock()
    cross = threading.Barrier(2, timeout=3)   # 两个平台需同时在飞

    plan = [("k1", "kimi"), ("k2", "kimi"), ("k1", "deepseek"), ("k2", "deepseek")]
    first_seen = {"v": set()}

    def run_cell(kw, plat):
        with guard:
            if active.get(plat):
                overlap_violation["v"] = True   # 同平台并发 = 违规
            active[plat] = True
            new_platform = plat not in first_seen["v"]
            first_seen["v"].add(plat)
        if new_platform:
            try:
                cross.wait()                    # 每平台的首个 cell 汇合 → 证明跨平台并发
            except threading.BrokenBarrierError:
                pass
        time.sleep(0.03)                        # 拉宽窗口便于观测重叠
        with guard:
            active[plat] = False
        return _cell(kw, plat)

    out = runner.run_cells_dual_lane(
        plan, run_cell, mode_of=lambda p: "rpa",
        api_pool_size=5, rpa_platform_concurrency=3,
    )
    assert overlap_violation["v"] is False      # 同平台内严格串行
    assert not cross.broken                      # 跨平台确有并发(两平台首 cell 汇合成功)
    assert len(out) == 4


class _Cancel(Exception):
    pass


def test_cancellation_propagates_and_stops(monkeypatch):
    monkeypatch.setattr(runner, "is_cancelled", lambda e: isinstance(e, _Cancel))
    started = {"n": 0}
    guard = threading.Lock()

    def run_cell(kw, plat):
        with guard:
            started["n"] += 1
        raise _Cancel("user stop")

    plan = [("k1", "tongyi"), ("k2", "tongyi"), ("k3", "tongyi")]
    with pytest.raises(_Cancel):
        runner.run_cells_dual_lane(
            plan, run_cell, mode_of=lambda p: "api",
            api_pool_size=1,                     # 串行池 → 首个取消后其余早退
            rpa_platform_concurrency=1,
        )
    # api_pool_size=1 → 第一个 cell 取消置标志,后续 _one 早退,不应全部启动
    assert started["n"] < 3
