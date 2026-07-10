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
