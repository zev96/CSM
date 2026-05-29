"""zhihu 问题浏览量抓取测试。

浏览量改从浏览器渲染好的页面 DOM 抓「被浏览」（cookie-less API 403 被反爬
封死，已删）。这里只验两件行为，不去 mock 整个浏览器 driver：
  1. fetch() 成功路径把 _fetch_browser 抓到的浏览量穿进 metric。
  2. _parse_count 能把页面上真实出现的两种写法（裸逗号整数 / "万" 缩写）
     归一成 int —— DOM 抓回来的原始串就靠它转换。
"""
from __future__ import annotations

from csm_core.monitor.platforms.zhihu_question import (
    ZhihuQuestionAdapter,
    _parse_count,
)


def test_fetch_threads_browser_visit_count_into_metric(monkeypatch):
    """fast path 失败 → 走 browser，browser 抓到的浏览量进 metric。"""
    from csm_core.monitor.base import MonitorTask

    a = ZhihuQuestionAdapter()
    # fast path 返回 (answers=None, source, visit_count=None) —— 答案 feed
    # API 没浏览量。模拟它撞 HTTP 400 走 fallback。
    monkeypatch.setattr(
        a, "_fetch_fast", lambda qid: (None, "curl_cffi_http_400", None),
    )
    # browser path 回传 3 元组：答案 + source + DOM 抓到的浏览量。
    monkeypatch.setattr(
        a, "_fetch_browser",
        lambda url, qid, top_n=20: (
            [{
                "author": "u", "content": "戴森好用", "voteup_count": 1,
                "comment_count": 0, "url": "", "created_time": None,
            }],
            "browser_patchright",
            2570169,
        ),
    )
    task = MonitorTask(
        id=1, type="zhihu_question", name="q",
        target_url="https://www.zhihu.com/question/12345",
        config={"target_brand": "戴森", "top_n": 5},
    )
    result = a.fetch(task)
    assert result.status == "ok"
    assert result.metric["question_visit_count"] == 2570169


def test_parse_count_handles_realistic_forms():
    """锁住 DOM 抓回来的两种真实写法的转换。"""
    # NumberBoard value 的 title 属性：裸逗号精确整数。
    assert _parse_count("2,570,169") == 2570169
    # 可见文本被知乎缩写成「万」。
    assert _parse_count("257 万") == 2570000
