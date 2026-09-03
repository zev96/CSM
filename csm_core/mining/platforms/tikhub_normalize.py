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


# ── B站 ─────────────────────────────────────────────────────────────────

_BL_VALID_ORDERS = {"totalrank", "click", "pubdate", "dm", "stow"}   # 与 bilibili_search 同集合
_BL_PAGE_SIZE = 20


def bilibili_first_params(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """B站 general_search：order 必填（实测 totalrank 通过；其余为 B 站原生取值），
    日期区间 → pubtime_begin_s / pubtime_end_s（本地时区当天 00:00:00 / 23:59:59）。"""
    order = str(f.get("order") or "totalrank")
    params: dict[str, Any] = {
        "keyword": keyword,
        "order": order if order in _BL_VALID_ORDERS else "totalrank",
        "page": 1,
        "page_size": _BL_PAGE_SIZE,
    }
    begin = date_to_epoch(f.get("time_begin"))
    if begin is not None:
        params["pubtime_begin_s"] = begin
    end = date_to_epoch(f.get("time_end"), end_of_day=True)
    if end is not None:
        params["pubtime_end_s"] = end
    return params


def bilibili_next_params(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    inner = (raw.get("data") or {}).get("data") or {}
    if not inner.get("result"):
        return None
    page = int(inner.get("page") or prev.get("page") or 1)
    num_pages = int(inner.get("numPages") or 0)
    if num_pages and page >= num_pages:
        return None
    params = dict(prev)
    params["page"] = page + 1
    return params


def _int_or_none(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def normalize_bilibili_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    inner = (raw.get("data") or {}).get("data") or {}
    cards: list[VideoCard] = []
    for it in inner.get("result") or []:
        if not isinstance(it, dict) or it.get("type") != "video":
            continue
        bvid = it.get("bvid")
        if not bvid:
            continue
        cards.append(VideoCard(
            platform="bilibili",
            platform_video_id=str(bvid),
            url=f"https://www.bilibili.com/video/{bvid}",
            title=_strip_em(str(it.get("title") or "")).strip(),
            author_name=str(it.get("author") or "").strip(),
            author_id=str(it.get("mid") or ""),
            cover_url=_normalize_url(str(it.get("pic") or "")),
            duration_sec=parse_duration(str(it.get("duration") or "")),
            play_count=_int_or_none(it.get("play")),
            like_count=_int_or_none(it.get("like")),
            published_at=_pubdate_to_iso(it.get("pubdate")),
            raw=it,
        ))
    return cards


# ── 快手 ────────────────────────────────────────────────────────────────

def kuaishou_first_params(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """快手 search_video_v2 无服务端筛选 —— 时间区间在 normalize 里本地后过滤。"""
    return {"keyword": keyword, "pcursor": ""}


def kuaishou_next_params(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    d = raw.get("data") or {}
    pc = d.get("pcursor")
    if d.get("recoPcursor") == "no_more" or not pc or pc == "no_more" or not d.get("mixFeeds"):
        return None
    params = dict(prev)
    params["pcursor"] = str(pc)
    return params


def _first_cover(v: Any) -> str:
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, dict):
            return str(first.get("url") or "")
        return str(first or "")
    return ""


def normalize_kuaishou_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    """只取 itemType==5 的视频项；feed 为 flat 字段；时间区间本地后过滤（被滤掉的不
    计入 emitted，翻页自然补偿 —— 与浏览器快手适配器同口径）。"""
    begin = date_to_epoch(f.get("time_begin"))
    end = date_to_epoch(f.get("time_end"), end_of_day=True)
    cards: list[VideoCard] = []
    for it in (raw.get("data") or {}).get("mixFeeds") or []:
        if not isinstance(it, dict) or str(it.get("itemType")) != "5":
            continue
        feed = it.get("feed") or {}
        pid = feed.get("photo_id")
        if not pid:
            continue
        pid = str(pid)
        dur_ms = feed.get("duration") or 0
        ts_ms = feed.get("timestamp") or 0
        card = VideoCard(
            platform="kuaishou",
            platform_video_id=pid,
            url=f"https://www.kuaishou.com/short-video/{pid}",
            title=str(feed.get("caption") or "").strip(),
            author_name=str(feed.get("user_name") or "").strip(),
            author_id=str(feed.get("user_id") or ""),
            cover_url=_first_cover(feed.get("cover_thumbnail_urls")),
            duration_sec=int(dur_ms / 1000) if dur_ms else None,
            play_count=_int_or_none(feed.get("view_count")),
            like_count=_int_or_none(feed.get("like_count")),
            published_at=_ts_ms_to_iso(ts_ms) if ts_ms else None,
            raw=feed,
        )
        if not iso_within_epoch_range(card.published_at, begin, end):
            continue
        cards.append(card)
    return cards
