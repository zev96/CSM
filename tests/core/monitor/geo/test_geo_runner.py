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


def test_preset_cancel_token_skips_all_cells():
    # 传入已置位的 cancel_token → 每个 cell 在起始检查点被跳过,run_cell 一次都不真跑,
    # runner 抛取消(不返回含 None 的列表)。
    tok = threading.Event(); tok.set()
    called = {"n": 0}

    def run_cell(kw, plat):
        called["n"] += 1
        return _cell(kw, plat)

    plan = [("k1", "tongyi"), ("k2", "tongyi")]
    with pytest.raises(BaseException):          # 取消信号(_CancelledFetch 或 standalone 的 RuntimeError)
        runner.run_cells_dual_lane(plan, run_cell, mode_of=lambda p: "api",
                                   api_pool_size=2, rpa_platform_concurrency=3,
                                   cancel_token=tok)
    assert called["n"] == 0


def test_rpa_batch_hook_places_cells_and_ticks_progress():
    # rpa_batch 提供时,RPA 平台走「每平台一次 batch」路径:逐 cell 就位 + 逐 cell 进度。
    # API cell 放最前 → kimi 全局 index=[1,2] ≠ local_idx=[0,1],真正验 results[indices[local_idx]]
    # 映射(若 kimi 恰在 [0,1],results[local_idx] 的错写也蒙对,测不出回归)。
    plan = [("k1", "tongyi"), ("k1", "kimi"), ("k2", "kimi")]
    seen_batches = []

    def rpa_batch(plat, keywords, cancel_token):
        seen_batches.append((plat, tuple(keywords)))
        for li, kw in enumerate(keywords):
            yield li, _cell(kw, plat)          # 模拟复用浏览器逐关键词产出

    def run_cell(kw, plat):                     # 只应被 API 平台(tongyi)调用
        return _cell(kw, plat)

    prog = []
    out = runner.run_cells_dual_lane(
        plan, run_cell, mode_of=lambda p: "api" if p == "tongyi" else "rpa",
        api_pool_size=4, rpa_platform_concurrency=3,
        progress_cb=lambda c, t: prog.append((c, t)), rpa_batch=rpa_batch)

    assert [(c.keyword, c.platform) for c in out] == plan   # 顺序保持
    assert seen_batches == [("kimi", ("k1", "k2"))]         # kimi 只开一次 batch,含两个关键词
    assert prog[-1] == (3, 3)                                # 3 个 cell 全计进度


def test_rpa_batch_skips_queued_platform_after_cancel(monkeypatch):
    # 取消已触发(前一平台抛)后,队列里的 RPA 平台不应再调 rpa_batch(不开浏览器,不留孤儿)。
    monkeypatch.setattr(runner, "is_cancelled", lambda e: isinstance(e, _Cancel))
    called = []

    def rpa_batch(plat, keywords, tok):
        called.append(plat)
        if plat == "kimi":
            raise _Cancel("stop")
        yield 0, _cell(keywords[0], plat)

    plan = [("k1", "kimi"), ("k1", "deepseek")]
    with pytest.raises(_Cancel):
        runner.run_cells_dual_lane(
            plan, lambda kw, p: _cell(kw, p), mode_of=lambda p: "rpa",
            api_pool_size=1, rpa_platform_concurrency=1,   # 串行化 → deepseek 排在 kimi 后
            rpa_batch=rpa_batch)
    assert called == ["kimi"]                              # deepseek 被取消前置检查跳过


def test_rpa_batch_underyield_raises_not_silent():
    # batch 漏产某关键词 → 就地报错,不让 None 漂到 metrics 静默丢数据/远端炸。
    def rpa_batch(plat, keywords, tok):
        yield 0, _cell(keywords[0], plat)                  # 只产第一个,漏掉第二个

    plan = [("k1", "kimi"), ("k2", "kimi")]
    with pytest.raises(RuntimeError, match="漏产"):
        runner.run_cells_dual_lane(
            plan, lambda kw, p: _cell(kw, p), mode_of=lambda p: "rpa", rpa_batch=rpa_batch)
