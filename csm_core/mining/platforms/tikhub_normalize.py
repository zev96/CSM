"""TikHub 关键词搜索响应 → VideoCard 归一化 + 翻页请求构造（纯函数，fixture 可测）。

字段路径全部来自 2026-09-01 用真实 token 实测（spec §4.2），不是文档猜测：

- 抖音 ``POST /api/v1/douyin/search/fetch_video_search_v2``
    视频：``data.business_data[type==1].data.aweme_info``（与浏览器 XHR 的
    aweme_info **同形** → 直接借用 ``douyin_search.DouyinSearchAdapter._extract_cards``）
    翻页：``data.business_config.{has_more, next_page.cursor, next_page.search_id, backtrace}``
- B站 ``GET /api/v1/bilibili/web/fetch_general_search``
    视频：``data.data.result[type=="video"]``；翻页：``data.data.{page, numPages}``
- 快手 ``GET /api/v1/kuaishou/app/search_video_v2``
    视频：``data.mixFeeds[itemType==5].feed``（flat 字段）；
    翻页：``data.pcursor``，``data.recoPcursor=="no_more"`` 结束

约定：``*_first_*(keyword, plat_filters)`` 造首页请求；``*_next_*(prev, raw)`` 从上一页
响应造下一页请求，返回 None = 没有下一页；``normalize_*(raw, plat_filters)`` 出卡片。
"""
from __future__ import annotations

from typing import Any

from csm_core.mining.models import VideoCard
from csm_core.mining.platforms._common import (
    date_to_epoch, iso_within_epoch_range, parse_duration,
)
from csm_core.mining.platforms.bilibili_search import (
    _normalize_url, _pubdate_to_iso, _strip_em,
)
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import _ts_ms_to_iso

# ── 抖音 ────────────────────────────────────────────────────────────────

# UI 档位 → TikHub publish_time（UI 半年=182，TikHub 半年=180）
_DY_PUBLISH_TIME = {"0": "0", "1": "1", "7": "7", "182": "180"}


def douyin_first_body(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """抖音首页 POST body：筛选全部下推（排序 / 发布时间 / 内容类型）。

    content_type：仅视频=1、仅图文=2、两者都要=0（全部）再由 normalize 按
    content_types 后过滤（与浏览器适配器"综合搜索 + 后过滤"同口径）。
    """
    types = set(f.get("content_types") or ["video"])
    if types == {"video"}:
        content_type = "1"
    elif types == {"note"}:
        content_type = "2"
    else:
        content_type = "0"
    return {
        "keyword": keyword,
        "cursor": 0,
        "search_id": "",
        "backtrace": "",
        "sort_type": str(f.get("sort_type") or "0"),
        "publish_time": _DY_PUBLISH_TIME.get(str(f.get("publish_time") or "0"), "0"),
        "content_type": content_type,
    }


def douyin_next_body(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    cfg = (raw.get("data") or {}).get("business_config") or {}
    if cfg.get("has_more") != 1:
        return None
    nxt = cfg.get("next_page") or {}
    if nxt.get("cursor") is None:
        return None
    body = dict(prev)
    body["cursor"] = nxt.get("cursor")
    body["search_id"] = nxt.get("search_id") or prev.get("search_id") or ""
    body["backtrace"] = cfg.get("backtrace") or ""
    return body


def normalize_douyin_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    """只取 type==1 的视频卡；aweme_info 与浏览器 XHR 同形，直接借用现有抽取器。"""
    allowed = frozenset(f.get("content_types") or ["video"])
    items = [
        it["data"]
        for it in ((raw.get("data") or {}).get("business_data") or [])
        if isinstance(it, dict) and it.get("type") == 1 and isinstance(it.get("data"), dict)
    ]
    return DouyinSearchAdapter()._extract_cards({"data": items}, allowed_types=allowed)
