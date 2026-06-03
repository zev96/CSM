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
