"""Tests for the zhihu_search monitor adapter (官方搜索 API · 品牌词命中排名)."""
from __future__ import annotations

from csm_core.monitor.base import MonitorTask


def test_zhihu_search_is_valid_task_type():
    """MonitorTask 接受 type='zhihu_search'（Literal 已扩展）。"""
    t = MonitorTask(type="zhihu_search", name="测试", target_url="https://x")
    assert t.type == "zhihu_search"
