# GEO 采集升级 Phase 1 实施计划 —— 双车道并发地基

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GEO 采集从「27 关键词 × 5 平台全串行」改成「API 平台并发 + RPA 平台按平台并发」的双车道调度,单轮墙钟大幅下降,且不改任何采集行为语义(零回归)。

**Architecture:** 新增一个纯并发调度模块 `geo/runner.py`(不碰 provider、不碰浏览器),`fetch()` 把原来的串行 `for` 循环替换成调用它。API 车道用线程池并发所有 (关键词×API平台) cell;RPA 车道每个平台一个 worker 线程串行跑自己的关键词(仍逐 cell 开关浏览器 = 每关键词独立会话,无污染),最多 N 个平台并发。进度用单一带锁计数器保证末值 =(total,total);取消时置标志 + join 所有线程(不留孤儿 Chrome)再抛。API provider 顺带复用 `httpx.Client` 连接池 + 对 429/连接失败单次重试(未计费,不违反 §9 防重复计费)。

**Tech Stack:** Python 3.12 sidecar,`concurrent.futures.ThreadPoolExecutor`,`threading`,`httpx`,pytest。前端不涉及。

**Spec:** `docs/superpowers/specs/2026-07-09-geo-collection-upgrade-design.md`(§3 双车道、§4.1、§4.8)

**范围边界:** 本 Phase **只做并发地基**。RPA 浏览器跨关键词复用 + goto 会话重置 = Phase 2;失败原因传导/合成 cell/节奏 = Phase 3;多采样/完整度 = Phase 4。各自独立 plan。

**运行测试:** `cd D:/CSM/.claude/worktrees/objective-moore-ecce71 && "D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/ -v`(sidecar 测试需显式 `pytest sidecar/tests/`,本 Phase 不涉及)。

---

## 文件结构

- **新建** `csm_core/monitor/geo/runner.py` —— 纯并发调度器,单一职责:把 cell 列表按平台 mode 分车道并发执行,返回按原顺序排列的 `GeoCell` 列表。无 I/O、无浏览器、无网络,可用假 `run_cell` 完整单测。
- **新建** `tests/core/monitor/geo/test_geo_runner.py` —— runner 单测(并发性、串行约束、进度、取消、顺序)。
- **修改** `csm_core/monitor/platforms/geo_query.py:88-98` —— 把串行循环换成 `runner.run_cells_dual_lane(...)`;读 `geo_api_pool_size`/`geo_rpa_platform_concurrency` 配置。
- **修改** `csm_core/monitor/geo/providers/api_doubao.py` —— 共享 `httpx.Client` + 429/连接失败单次重试。
- **修改** `csm_core/monitor/geo/providers/api_tongyi.py` —— 同上。
- **修改** `tests/core/monitor/geo/test_geo_query_adapter.py` —— 补两条 fetch 级测试(① API cell 并发;② 分类阶段 get_provider 失败隔离成 error cell,修 I1 回归),现有测试断言不变、应继续通过。

---

## Task 1: 纯并发调度器 `geo/runner.py`

**Files:**
- Create: `csm_core/monitor/geo/runner.py`
- Test: `tests/core/monitor/geo/test_geo_runner.py`

- [ ] **Step 1: 写失败测试 —— 顺序保持 + 进度首末值**

Create `tests/core/monitor/geo/test_geo_runner.py`:

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_runner.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'csm_core.monitor.geo.runner' has no attribute 'run_cells_dual_lane'`

- [ ] **Step 3: 写最小实现**

Create `csm_core/monitor/geo/runner.py`:

```python
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

from ..base import is_cancelled, maybe_cancel
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
    cancel_token: "threading.Event | None" = None,
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
            maybe_cancel(cancel_token)       # 队列中 cell 起始检查点:token 已置位则抛取消(与串行版逐 cell 检查对齐)
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_runner.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/geo/runner.py tests/core/monitor/geo/test_geo_runner.py
git commit -m "feat(geo): 并发调度器 runner —— 顺序保持 + 进度边界"
```

- [ ] **Step 6: 写失败测试 —— API 车道真并发(用 Barrier 确定性断言)**

Append to `tests/core/monitor/geo/test_geo_runner.py`:

```python
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
```

- [ ] **Step 7: 运行确认通过(实现已支持)**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_runner.py::test_api_lane_runs_concurrently -v`
Expected: PASS(Task1 实现已含 API 线程池)

- [ ] **Step 8: 写失败测试 —— RPA 同平台串行、跨平台并发**

Append:

```python
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
```

- [ ] **Step 9: 运行确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_runner.py::test_rpa_same_platform_serial_cross_platform_concurrent -v`
Expected: PASS(每平台一个 worker 串行、两 worker 并发)

- [ ] **Step 10: 写失败测试 —— 取消传导 + 不留半成品**

Append:

```python
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
```

- [ ] **Step 11: 运行确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 12: 提交**

```bash
git add tests/core/monitor/geo/test_geo_runner.py
git commit -m "test(geo): runner 并发/串行/取消/顺序 确定性单测"
```

---

## Task 2: `fetch()` 接入双车道调度器

**Files:**
- Modify: `csm_core/monitor/platforms/geo_query.py:65-98`
- Test: `tests/core/monitor/geo/test_geo_query_adapter.py`(补 2 条:并发 + I1 隔离回归,不改原有断言)

- [ ] **Step 1: 写失败测试 —— fetch 下 API 并发 + RPA 同平台串行**

Append to `tests/core/monitor/geo/test_geo_query_adapter.py`:

```python
def test_fetch_uses_dual_lane_api_concurrent(fresh_db, monkeypatch):
    import threading as _t
    barrier = _t.Barrier(2, timeout=3)

    class _ApiProv:
        def __init__(self, p):
            self.platform = p; self.mode = "api"
        def query(self, keyword, *, web_search=True, cancel_token=None):
            barrier.wait()                       # 两 API cell 必须并发才通过
            from csm_core.monitor.geo.models import GeoAnswer
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             answer_text=f"{self.platform} 推荐 小鹏")

    monkeypatch.setattr(geo_mod, "get_provider", lambda p: _ApiProv(p))
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi", "doubao"],
                "extract_provider": "mock", "geo_api_pool_size": 2}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                 # 未 BrokenBarrier → 两 API cell 并发成功
    assert result.metric["error_cells"] == 0
```

- [ ] **Step 1b: 写回归守卫测试 —— 分类阶段 get_provider 失败也要隔离(修 I1)**

Append to `tests/core/monitor/geo/test_geo_query_adapter.py`:

```python
def test_fetch_isolates_unconstructable_platform(fresh_db, monkeypatch):
    # I1 回归守卫:某平台 get_provider 抛错(未知/废弃平台 key、模块 import 失败)
    # 必须只让该平台变 error cell,健康平台照常成功;整轮不因分类阶段异常而崩。
    from csm_core.monitor.geo.providers.base import GeoProviderError

    def picker(p):
        if p == "badplat":
            raise GeoProviderError("未知 GEO 平台: badplat")
        return FakeProvider(p)
    monkeypatch.setattr(geo_mod, "get_provider", picker)
    monkeypatch.setattr(geo_mod, "build_extract_client", lambda p: FakeClient())

    tid = storage.create_task(MonitorTask(
        type="geo_query", name="t", target_url="geo://x",
        config={"brand": "小鹏", "keywords": ["k1"], "platforms": ["tongyi", "badplat"],
                "extract_provider": "mock"}))
    result = geo_mod.ADAPTER.fetch(storage.get_task(tid))
    assert result.status == "ok"                  # 一个坏平台不拖垮整轮
    assert result.metric["error_cells"] == 1
    conn = storage.get_conn()
    rows = conn.execute("SELECT platform, status FROM geo_cells WHERE task_id=?", (tid,)).fetchall()
    statuses = {r["platform"]: r["status"] for r in rows}
    assert statuses["tongyi"] == "ok"
    assert statuses["badplat"] == "error"
```

> **为什么**:串行版 `get_provider(platform)` 在 `_run_cell` 的 try/except 内,坏平台(未知 key / provider 模块 import 失败)只会变成一个 error cell,健康平台照跑。若把 Step 3 写成 `mode_of=lambda p: get_provider(p).mode`,`mode_of` 会在 runner 的**分类阶段**(`_run_cell` 之外)调 `get_provider`,一个坏平台就直接抛出 `fetch()` → 整轮零 cell、不 record_run,健康平台被连带打死 → 违反「零回归」。此测试守住该边界:在 Step 3 的 `mode_map` 预计算修复(逐平台兜住 get_provider,失败归入 API 车道由 `_run_cell` 再次调用时隔离)下通过;在朴素 `mode_of=lambda p: get_provider(p).mode` 下失败(异常直接冒出 `fetch()`)。

- [ ] **Step 2: 运行确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_query_adapter.py::test_fetch_uses_dual_lane_api_concurrent -v`
Expected: FAIL — 串行执行下 `barrier.wait()` 超时 → `BrokenBarrierError` → cell 变 error → `error_cells==2`,断言失败

- [ ] **Step 3: 改 `fetch()` —— 用 runner 替换串行循环**

In `csm_core/monitor/platforms/geo_query.py`, add import near line 34:

```python
from ..geo import runner as geo_runner
```

Replace the serial loop block (current lines 87-98, from `cells: list[GeoCell] = []` through the `for` loop end) with:

```python
        # 双车道并发调度(API 并发 + RPA 按平台并发)。cell 级隔离与串行版一致:
        # _run_cell 内部把非取消异常兜成 error cell,取消异常上抛由 runner 传导。
        def _int_cfg(key: str, default: int, hi: int) -> int:
            try:
                v = int(cfg.get(key, default) or default)
            except (TypeError, ValueError):
                v = default
            return max(1, min(v, hi))
        api_pool_size = _int_cfg("geo_api_pool_size", 5, 16)
        rpa_conc = _int_cfg("geo_rpa_platform_concurrency", 3, 8)

        # 预计算每个平台的车道(mode)。get_provider 可能抛(未知/废弃平台 key、
        # provider 模块 import 失败)——逐平台兜住,把失败平台并入 API 车道,让
        # _run_cell 执行时再次 get_provider 抛错并隔离成 error cell(恢复串行版的
        # cell 级隔离:一个坏平台不拖垮整轮),顺带每平台只构造一次 provider。
        mode_map: "dict[str, str]" = {}
        for _p in dict.fromkeys(plat for _, plat in cells_plan):
            try:
                mode_map[_p] = get_provider(_p).mode
            except Exception:
                logger.warning("[geo] 平台 %s 无法构造(未知/模块缺失),归入 API 车道由 _run_cell 兜错", _p)
                mode_map[_p] = "api"

        def _cell(kw: str, plat: str) -> GeoCell:
            return self._run_cell(kw, plat, brand, aliases, web_search, client,
                                  cancel_token=cancel_token)

        maybe_cancel(cancel_token)               # 开跑前先检一次取消(等价串行版首个 maybe_cancel)
        tail = cells_plan[resume_from:]
        cells: list[GeoCell] = geo_runner.run_cells_dual_lane(
            tail, _cell,
            mode_of=lambda p: mode_map.get(p, "api"),
            api_pool_size=api_pool_size,
            rpa_platform_concurrency=rpa_conc,
            progress_cb=progress_cb,
            initial_done=resume_from,
            cancel_token=cancel_token,
        )

        # C1 修复:runner 返回后复查取消。API cell 的同步 httpx POST 只在
        # provider.query() 起始处调过一次 maybe_cancel —— 若用户在该 cell 已
        # 发出请求、尚未返回时点 Stop,POST 会照常跑完并记 ok,token 置位这件事
        # 就被在飞请求"吞掉"。这里补一次复查,把「运行期间被取消」正确抛成取消,
        # 而不是悄悄按 status="ok" 持久化(甚至误发告警)。
        maybe_cancel(cancel_token)
```

> **为什么用 `mode_map` 预计算而非直接 `mode_of=lambda p: get_provider(p).mode`**(修 I1 回归):runner 的分类阶段在 `_run_cell` 的隔离之外调 `mode_of`。若 `mode_of` 直接 `get_provider(p).mode`,一个无法构造的平台(未知/废弃 key、provider 模块 import 失败)会把 `GeoProviderError` 抛出整个 `fetch()` —— 零 cell、不 record_run、健康平台被连带打死。这里逐平台 try/except 兜住 get_provider,失败平台记 `"api"` 车道;真正执行时 `_run_cell` 内部再次 `get_provider` 抛错,被其 try/except 隔离成 error cell,恢复串行版语义。`dict.fromkeys` 保序去重让每平台只在分类阶段构造一次 provider(顺带省掉朴素写法里每 cell 一次的重复构造)。Step 1b 的 `test_fetch_isolates_unconstructable_platform` 守此边界。

Then delete the now-duplicate up-front progress emit block (current lines 81-85 `if progress_cb is not None: ... progress_cb(resume_from, total)`) — the runner emits the initial event itself.

> **保留 `total = len(cells_plan)`(约第 66 行)** —— 它仍被第 76 行的 resume clamp `resume_from = max(0, min(int(resume_from), total))` 使用,**不要删**。runner 内部另算自己的 total 用于进度,与此不冲突。
> 原循环内的 `maybe_cancel(cancel_token)` 随循环删除;Step 3 已在调用 runner 前补一次 `maybe_cancel`,且每个 provider.query 内部首行也调 `maybe_cancel`,取消覆盖不丢。

- [ ] **Step 4: 运行新测试确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_query_adapter.py::test_fetch_uses_dual_lane_api_concurrent -v`
Expected: PASS

- [ ] **Step 5: 运行全部 adapter 测试确认零回归**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_geo_query_adapter.py -v`
Expected: 全部 PASS —— 尤其 `test_fetch_fans_out_and_records`(`progress[0]==(0,4)`、`progress[-1]==(4,4)`)、`test_all_cells_failed_marks_run_failed`(4 error → failed)、`test_one_provider_error_does_not_kill_run`(1 error)。若 `progress[-1]` 偶发不等于 `(4,4)`,说明进度计数未在锁内自增——回查 Task1 `_tick`。

- [ ] **Step 6: 提交**

```bash
git add csm_core/monitor/platforms/geo_query.py tests/core/monitor/geo/test_geo_query_adapter.py
git commit -m "feat(geo): fetch 接入双车道调度 —— API 并发 + RPA 按平台并发"
```

---

## Task 3: 豆包 provider 共享 httpx.Client + 429 单次重试

**Files:**
- Modify: `csm_core/monitor/geo/providers/api_doubao.py`
- Test: `tests/core/monitor/geo/test_api_doubao_retry.py`(新建)

- [ ] **Step 1: 写失败测试 —— 429 重试一次后成功;共享 client**

Create `tests/core/monitor/geo/test_api_doubao_retry.py`:

```python
from __future__ import annotations
import httpx
import pytest

from csm_core.monitor.geo.providers import api_doubao


class _Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text or ""
        self.headers = headers or {}
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
    def post(self, url, **kw):
        self.calls += 1
        return self._responses.pop(0)


def _ok_payload():
    return {"choices": [{"message": {"content": "推荐 CEWEY", "references": []},
                         "finish_reason": "stop"}]}


def test_doubao_retries_once_on_429(monkeypatch):
    fake = _FakeClient([_Resp(429, text="rate", headers={"Retry-After": "0"}),
                        _Resp(200, _ok_payload())])
    monkeypatch.setattr(api_doubao, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_doubao, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_doubao, "get_config",
                        lambda: type("C", (), {"doubao_bot_id": "bot-1", "base_urls": {}})())
    prov = api_doubao.DoubaoProvider()
    ans = prov.query("家用吸尘器哪种好")
    assert ans.status == "ok"
    assert fake.calls == 2                        # 首个 429 → 重试一次 → 200


def test_doubao_no_retry_on_500(monkeypatch):
    fake = _FakeClient([_Resp(500, text="boom")])
    monkeypatch.setattr(api_doubao, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_doubao, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_doubao, "get_config",
                        lambda: type("C", (), {"doubao_bot_id": "bot-1", "base_urls": {}})())
    ans = api_doubao.DoubaoProvider().query("k")
    assert ans.status == "error"                  # 5xx 不属于 429/连接失败 → 不重试
    assert fake.calls == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_api_doubao_retry.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_shared_client'`

- [ ] **Step 3: 改 `api_doubao.py` —— 共享 client + 429/连接失败重试**

In `csm_core/monitor/geo/providers/api_doubao.py`, add after the imports (after line 16):

```python
import threading as _threading
import time as _time

_client_lock = _threading.Lock()
_client: "httpx.Client | None" = None


def _shared_client() -> httpx.Client:
    """进程内复用一个 httpx.Client(连接池 + 线程安全),避免每 cell 重握手 TLS。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client()
    return _client


def _post_retry_429(url: str, *, headers: dict, json: dict, timeout) -> httpx.Response:
    """采集调用:仅对 429 / 连接建立失败重试一次(均未计费,不违反 §9 防重复计费)。
    已开始生成的响应(2xx/4xx≠429/5xx)绝不重发。"""
    client = _shared_client()
    for attempt in range(2):
        try:
            r = client.post(url, headers=headers, json=json, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == 0:
                _time.sleep(1.0)
                continue
            raise
        if r.status_code == 429 and attempt == 0:
            try:
                delay = min(float(r.headers.get("Retry-After", "1") or 1), 10.0)
            except (TypeError, ValueError):
                delay = 1.0
            _time.sleep(max(0.0, delay))
            continue
        return r
    return r  # pragma: no cover —— 循环必在上面 return/raise
```

Then in `DoubaoProvider.query`, replace the current try/except around `httpx.post` (lines 62-65):

```python
        try:
            r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=timeout)
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
```

with:

```python
        try:
            r = _post_retry_429(url, headers={"Authorization": f"Bearer {key}"},
                                json=body, timeout=timeout)
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_api_doubao_retry.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/geo/providers/api_doubao.py tests/core/monitor/geo/test_api_doubao_retry.py
git commit -m "feat(geo): 豆包 provider 共享 httpx 连接池 + 429/连接失败单次重试"
```

---

## Task 4: 通义 provider 共享 httpx.Client + 429 单次重试

**Files:**
- Modify: `csm_core/monitor/geo/providers/api_tongyi.py`
- Test: `tests/core/monitor/geo/test_api_tongyi_retry.py`(新建)

- [ ] **Step 1: 写失败测试**

Create `tests/core/monitor/geo/test_api_tongyi_retry.py`:

```python
from __future__ import annotations
import httpx
import pytest

from csm_core.monitor.geo.providers import api_tongyi


class _Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text or ""
        self.headers = headers or {}
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
    def post(self, url, **kw):
        self.calls += 1
        return self._responses.pop(0)


def _ok_payload():
    return {"output": {"choices": [{"message": {"content": "推荐 CEWEY"},
                                    "finish_reason": "stop"}],
                       "search_info": {"search_results": []}}}


def test_tongyi_retries_once_on_429(monkeypatch):
    fake = _FakeClient([_Resp(429, text="rate", headers={"Retry-After": "0"}),
                        _Resp(200, _ok_payload())])
    monkeypatch.setattr(api_tongyi, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_tongyi, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_tongyi, "get_config",
                        lambda: type("C", (), {"default_model": {}})())
    ans = api_tongyi.TongyiProvider().query("家用吸尘器哪种好")
    assert ans.status == "ok"
    assert fake.calls == 2


def test_tongyi_no_retry_on_500(monkeypatch):
    fake = _FakeClient([_Resp(500, text="boom")])
    monkeypatch.setattr(api_tongyi, "_shared_client", lambda: fake)
    monkeypatch.setattr(api_tongyi, "read_api_key", lambda p: "sk-x")
    monkeypatch.setattr(api_tongyi, "get_config",
                        lambda: type("C", (), {"default_model": {}})())
    ans = api_tongyi.TongyiProvider().query("k")
    assert ans.status == "error"
    assert fake.calls == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_api_tongyi_retry.py -v`
Expected: FAIL — `AttributeError: ... '_shared_client'`

- [ ] **Step 3: 改 `api_tongyi.py`**

In `csm_core/monitor/geo/providers/api_tongyi.py`, add after imports (after line 17, below `_URL`):

```python
import threading as _threading
import time as _time

_client_lock = _threading.Lock()
_client: "httpx.Client | None" = None


def _shared_client() -> httpx.Client:
    """进程内复用一个 httpx.Client(连接池 + 线程安全)。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client()
    return _client


def _post_retry_429(url: str, *, headers: dict, json: dict, timeout) -> httpx.Response:
    """采集调用:仅对 429 / 连接建立失败重试一次(未计费)。已生成响应绝不重发。"""
    client = _shared_client()
    for attempt in range(2):
        try:
            r = client.post(url, headers=headers, json=json, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == 0:
                _time.sleep(1.0)
                continue
            raise
        if r.status_code == 429 and attempt == 0:
            try:
                delay = min(float(r.headers.get("Retry-After", "1") or 1), 10.0)
            except (TypeError, ValueError):
                delay = 1.0
            _time.sleep(max(0.0, delay))
            continue
        return r
    return r  # pragma: no cover
```

Then replace the current try/except around `httpx.post` (lines 66-75):

```python
        try:
            r = httpx.post(
                _URL,
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=self._timeout, pool=10.0),
            )
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
```

with:

```python
        try:
            r = _post_retry_429(
                _URL,
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=self._timeout, pool=10.0),
            )
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
```

- [ ] **Step 4: 运行确认通过**

Run: `"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/test_api_tongyi_retry.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/geo/providers/api_tongyi.py tests/core/monitor/geo/test_api_tongyi_retry.py
git commit -m "feat(geo): 通义 provider 共享 httpx 连接池 + 429/连接失败单次重试"
```

---

## Task 5: 全量回归 + 真机冒烟

**Files:** 无(验证任务)

- [ ] **Step 1: 跑全部 GEO 相关 Python 测试**

Run:
```bash
cd D:/CSM/.claude/worktrees/objective-moore-ecce71
"D:/CSM/.venv/Scripts/python.exe" -m pytest tests/core/monitor/geo/ -v
"D:/CSM/.venv/Scripts/python.exe" -m pytest sidecar/tests/test_geo_routes.py sidecar/tests/test_geo_exposure_summary.py sidecar/tests/test_geo_leaderboard_global.py -v
```
Expected: 全部 PASS(sidecar/tests 不在默认 pytest 收集范围,必须显式路径 —— 见记忆 [reference_csm_sidecar_tests_excluded_from_ci])。

- [ ] **Step 2: 真机冒烟(可选,需登录态)**

在 worktree 起 dev 端(见记忆 [reference_csm_worktree_tauri_coldstart]),对一个含 tongyi+doubao(API)与 kimi+deepseek+yuanbao(RPA)的小任务(2 关键词)点「立即运行」,确认:
- API 两平台明显并发返回(日志时间戳接近);
- 三个 RPA 平台各自开一个屏外 Chrome、同时在跑(任务管理器可见 3 个 chrome 树);
- 进度条单调不倒退,末值满格;
- 结果数据与串行版一致(提及/排名/信源无异常)。

- [ ] **Step 3: 对抗性审查(按用户全局规则)**

并行派 2–3 个独立 subagent 证伪本 Phase 改动,视角:①并发正确性(结果错位/进度竞态/取消孤儿)②回归(现有 6 条 adapter 断言、record_run 单写、checked_at 关联)③资源(线程池泄漏、httpx client 生命周期)。发现逐条核实修复,误报说明理由。

- [ ] **Step 4: Phase 1 收尾提交(如审查有修则一并)**

```bash
git add -A && git commit -m "chore(geo): Phase 1 收尾 —— 回归通过 + 对抗性审查修正"
```

> **对抗性审查发现并已修复(C1,确认属实)**:串行版 `fetch()` 在每个 cell 前都调
> `maybe_cancel(cancel_token)`;双车道 `run_cells_dual_lane` 只在 cell **抛**取消时
> 才响应——RPA provider 每 500ms 自轮询 token(能响应 Stop),但 API provider(通义/
> 豆包)只在 `query()` 起始检查一次,随后阻塞在同步 httpx POST 里。若用户在 API cell
> 已发出请求、尚未返回时点 Stop(无排队 cell 可早退),token 置位这件事被在飞请求
> "吞掉"→ cell 照常返回 ok → 整轮被当成 `status="ok"` 落库(甚至误发告警),违反
> 「零回归」(串行版会诚实抛取消)。**修复分两部分**:①`runner.run_cells_dual_lane`
> 新增 keyword-only `cancel_token` 参数,`_one` 在起始检查点调 `maybe_cancel`,让排
> 队中(尚未开始)的 cell 提前早退,对齐串行版逐 cell 检查的语义;②`fetch()` 在
> `run_cells_dual_lane(...)` 返回后、`metrics.aggregate(cells)` 之前补一次
> `maybe_cancel(cancel_token)` 复查,把"运行期间被取消但已在飞的 cell 悄悄跑成 ok"
> 兜底转成正确抛出的取消异常。二者缺一不可:①堵住"还没轮到的 cell",②堵住"已经在
> 飞、来不及自己感知取消的 cell"。回归测试:`test_geo_runner.py::
> test_preset_cancel_token_skips_all_cells`(预置 token → 排队 cell 零执行)、
> `test_geo_query_adapter.py::test_fetch_cancel_midrun_not_swallowed_as_ok`(模拟
> cell 执行期间置位 → fetch 必须抛 `_CancelledFetch`,不是 status="ok")。
>
> **顺带加固(与 C1 同一代码块,成本低)**:`geo_api_pool_size` /
> `geo_rpa_platform_concurrency` 原来直接 `int(cfg.get(...))`,非数值配置(如历史
> 脏数据或手改 config JSON 传了字符串)会让 `int()` 抛 `ValueError` 崩掉整个
> `fetch()`。改用 `_int_cfg` helper:`(TypeError, ValueError)` 兜底回落默认值,并
> `max(1, min(v, hi))` 钳制上限(池子 16、RPA 平台并发 8),防止超大配置值把线程池
> 撑爆。回归测试:`test_fetch_tolerates_non_numeric_pool_config`。

---

## Self-Review(对照 spec 的覆盖检查)

- **spec §3 双车道** → Task 1(runner)+ Task 2(接入)。✓
- **spec §4.1 进度单计数器 / 取消 join / resume 完成集** → Task 1 `_tick` 带锁、`shutdown(wait=True)` join、`initial_done` 承接 resume。✓(注:本 Phase resume 仍按「尾部下标切片」`cells_plan[resume_from:]`,与串行版语义一致;spec 提的「(平台,关键词) 完成集」重定义留到 Phase 2 引入浏览器复用、cell 不再一一对应时再做——此处标注为已知延后项,非占位。)
- **spec §4.8 httpx 复用 + 429 豁免** → Task 3 / Task 4。✓
- **RPA 浏览器复用 + goto 重置** → **不在本 Phase**(Phase 2)。本 Phase RPA 仍逐 cell 开关浏览器 = 每关键词独立会话,故无 fix#1 的会话污染风险,安全。✓
- **失败原因传导 / 合成 cell / 节奏 / 多采样 / 完整度** → Phase 3、Phase 4。✓
- **占位扫描**:无 TBD/TODO;每个 code step 含完整代码。✓
- **类型一致性**:`run_cells_dual_lane` 签名在 Task 1 定义、Task 2 调用一致;`_shared_client`/`_post_retry_429` 在 doubao/tongyi 两文件同名同签名。✓
