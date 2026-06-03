"""知乎搜索排名监控 adapter（官方开放平台 API）。

与 baidu_keyword 同语义（关键词 → 品牌词在前 N 的排名），但走知乎官方
搜索 API（GET /api/v1/content/zhihu_search，Bearer 鉴权），返回结构化
JSON，无需爬虫 / cookie / 验证码 / 风控 / 正文抽取。每个关键词 = 一次
API 调用（每天 1000 配额）。匹配字段：Title + ContentText(摘要) +
AuthorName，大小写不敏感。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from ..base import BaseMonitorAdapter, MonitorResult, MonitorTask, maybe_cancel
from ..rate_limit import get_pacer, get_breaker
from csm_core.config import read_api_key

logger = logging.getLogger(__name__)

ZHIHU_SEARCH_URL = "https://developer.zhihu.com/api/v1/content/zhihu_search"


def _api_error(msg: str, *, http_status: int | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "code": None,
        "message": "",
        "items": [],
        "empty_reason": None,
        "search_hash_id": None,
        "http_status": http_status,
        "error": msg,
    }


def zhihu_search_api(
    query: str,
    count: int,
    secret: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """发一次知乎搜索 API 请求。纯函数，便于 mock httpx 单测。

    Returns 归一化 dict：ok / code / message / items / empty_reason /
    search_hash_id / http_status / error。
    """
    headers = {
        "Authorization": f"Bearer {secret}",
        "X-Request-Timestamp": str(int(time.time())),
        "Content-Type": "application/json",
    }
    params = {"Query": query, "Count": count}
    try:
        resp = httpx.get(ZHIHU_SEARCH_URL, headers=headers, params=params, timeout=timeout)
    except Exception as e:
        return _api_error(f"request raised: {e!r}")

    if resp.status_code >= 400:
        return _api_error(f"http {resp.status_code}", http_status=resp.status_code)

    try:
        payload = resp.json()
    except Exception:
        return _api_error("non-JSON response", http_status=resp.status_code)

    code = payload.get("Code")
    data = payload.get("Data") or {}
    items = data.get("Items") or []
    return {
        "ok": code == 0,
        "code": code,
        "message": str(payload.get("Message") or ""),
        "items": items if isinstance(items, list) else [],
        "empty_reason": data.get("EmptyReason"),
        "search_hash_id": data.get("SearchHashId"),
        "http_status": resp.status_code,
        "error": None,
    }


def match_brand(text: str, brands: list[str]) -> str | None:
    """大小写不敏感找首个出现的品牌词（brands 顺序代表优先级）。"""
    if not text or not brands:
        return None
    text_lc = text.lower()
    for brand in brands:
        if brand and brand.lower() in text_lc:
            return brand
    return None


class ZhihuSearchAdapter:
    """BaseMonitorAdapter 实现。关键词 → 知乎官方搜索 API → 品牌词命中排名。"""

    platform: str = "zhihu_search"

    def __init__(self) -> None:
        self._pacer = get_pacer(self.platform)
        self._breaker = get_breaker(self.platform)

    @staticmethod
    def _match_item(raw: dict[str, Any], brands: list[str]) -> tuple[str | None, str | None]:
        """Return (matched_brand, matched_field) for one item, or (None, None).

        字段优先级：title > excerpt(ContentText) > author。
        """
        for field_name, value in (
            ("title", raw.get("Title")),
            ("excerpt", raw.get("ContentText")),
            ("author", raw.get("AuthorName")),
        ):
            hit = match_brand(str(value or ""), brands)
            if hit:
                return hit, field_name
        return None, None

    @classmethod
    def _rank_results(
        cls, items: list[dict[str, Any]], brands: list[str], count: int,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        """Return (first_rank, matched_count, snapshot[]). rank 1-based，-1=无命中。"""
        snapshot: list[dict[str, Any]] = []
        matched_ranks: list[int] = []
        for i, raw in enumerate(items[:count], start=1):
            matched_brand, matched_field = cls._match_item(raw, brands)
            hit = matched_brand is not None
            if hit:
                matched_ranks.append(i)
            snapshot.append({
                "rank": i,
                "title": str(raw.get("Title") or ""),
                "content_type": str(raw.get("ContentType") or ""),
                "content_id": str(raw.get("ContentID") or ""),
                "url": str(raw.get("Url") or ""),
                "voteup_count": int(raw.get("VoteUpCount") or 0),
                "comment_count": int(raw.get("CommentCount") or 0),
                "author_name": str(raw.get("AuthorName") or ""),
                "authority_level": str(raw.get("AuthorityLevel") or ""),
                "ranking_score": float(raw.get("RankingScore") or 0.0),
                "edit_time": raw.get("EditTime"),
                "matches_brand": hit,
                "matched_brand": matched_brand,
                "matched_field": matched_field,
                "excerpt": str(raw.get("ContentText") or "")[:160],
            })
        first_rank = matched_ranks[0] if matched_ranks else -1
        return first_rank, len(matched_ranks), snapshot
