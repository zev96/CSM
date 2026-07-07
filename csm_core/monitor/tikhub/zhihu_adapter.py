"""知乎问题排名监控的 TikHub API 版适配器。

设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §8.1
- 取数走 TikHub 付费 API(``/api/v1/zhihu/web/fetch_question_answers``),用
  ``paginate()`` 自适应翻页凑够 ``top_n`` 条。
- 匹配复用本地 ``ZhihuQuestionAdapter`` 的 ``_strip_tags`` / ``_rank_brand``
  两个 staticmethod,保证 API 路径与本地抓取路径对同一问题给出**同一个 rank**
  (设计 §8.1 红线)。``normalize_zhihu_answers`` 返回的 ``content`` 是原始
  HTML,必须先 ``_strip_tags`` 清洗,再喂给 ``_rank_brand``——本地 fast-path
  在匹配前就是这么做的,顺序不能反。
"""
from __future__ import annotations
import re
from datetime import datetime

from csm_core.monitor.base import MonitorResult
from csm_core.monitor.platforms.zhihu_question import ZhihuQuestionAdapter
from .normalize import normalize_zhihu_answers
from .client import paginate
from .errors import TikHubError

_QID = re.compile(r"/question/(\d+)")
_ENDPOINT = "/api/v1/zhihu/web/fetch_question_answers"


class ZhihuQuestionApiAdapter:
    """知乎问题排名监控的 TikHub API 版。取数走 API,匹配复用本地 _rank_brand。"""

    platform = "zhihu_question"

    def __init__(self, client_factory, page_limit: int = 20):
        # client_factory: () -> TikHubClient(由分派层用全局 config 造好后注入)
        self._cf = client_factory
        self._limit = page_limit

    def _failed(self, task, reason: str) -> MonitorResult:
        return MonitorResult(
            task_id=task.id or 0, checked_at=datetime.utcnow(),
            status="failed", rank=-1, error_message=reason,
            metric={"source": "tikhub"},
        )

    def fetch(self, task, cancel_token=None, progress_cb=None, **_) -> MonitorResult:
        m = _QID.search(task.target_url or "")
        if not m:
            return self._failed(task, "无法从 URL 解析 question_id")
        qid = m.group(1)
        brand = (task.config.get("target_brand") or "").strip()
        top_n = max(1, min(40, int(task.config.get("top_n") or 10)))
        client = self._cf()

        def page_fn(cursor):
            params = {"question_id": qid, "limit": self._limit}
            if cursor:
                params["cursor"] = cursor
            raw = client.get(_ENDPOINT, params)
            answers = normalize_zhihu_answers(raw)
            paging = (raw.get("data") or {}).get("paging") or {}
            has_more = not paging.get("is_end", True)
            return answers, (paging.get("next") if has_more else None), has_more

        try:
            answers = paginate(page_fn, target=top_n, max_pages=3, cancel_token=cancel_token)
        except TikHubError as e:
            return self._failed(task, e.reason)

        # 与本地 fast-path 一致:匹配前用**同一** _strip_tags 清洗正文,保证
        # API rank == 本地 rank(设计 §8.1 红线)。
        for a in answers:
            a["content"] = ZhihuQuestionAdapter._strip_tags(a.get("content") or "")

        first_rank, matched_ranks, snapshot = ZhihuQuestionAdapter._rank_brand(
            answers, brand, top_n,
        )
        return MonitorResult(
            task_id=task.id or 0, checked_at=datetime.utcnow(),
            status="ok", rank=first_rank,
            metric={
                "source": "tikhub",
                "target_brand": brand,
                "top_n": top_n,
                "matched_count": len(matched_ranks),
                "matched_ranks": matched_ranks,
                "answers": snapshot,
                "question_id": qid,
                "question_visit_count": None,   # API 路径不抓浏览量(本地也仅浏览器兜底才有)
                "scanned_full": True,
            },
        )
