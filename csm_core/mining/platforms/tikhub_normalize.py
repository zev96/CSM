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
    翻页：``data.pcursor`` 是搜索翻页的主判据 —— ``recoPcursor`` 是推荐流（相关搜索
    卡）的游标，与本次搜索翻页无关，**不是**终止信号（曾误用，见审查修复记录）。

约定：``*_first_*(keyword, plat_filters)`` 造首页请求；``*_next_*(prev, raw)`` 从上一页
响应造下一页请求，返回 None = 没有下一页；``normalize_*(raw, plat_filters)`` 出卡片。
对实测到的畸形结构（非 dict 层级、数值字段为字符串、游标类型漂移）做兜底；叶子字段
类型错误由适配器层（``tikhub_search._fetch_page``）统一按页级错误处理。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from csm_core.mining.models import VideoCard
from csm_core.mining.platforms._common import (
    date_to_epoch, iso_within_epoch_range, parse_duration, parse_int_count,
)
from csm_core.mining.platforms.bilibili_search import (
    _VALID_ORDERS as _BL_VALID_ORDERS,  # order 白名单直接复用 bilibili_search，不再本地复制一份
    _normalize_url, _pubdate_to_iso, _strip_em,
)
from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
from csm_core.mining.platforms.kuaishou_search import _ts_ms_to_iso

logger = logging.getLogger(__name__)

# 无状态抽取器，模块级单例复用（构造函数不做任何 IO，但没必要每次调用都新建）。
_DY = DouyinSearchAdapter()


# ── 共享小工具 ──────────────────────────────────────────────────────────

def _dict(v: Any) -> dict[str, Any]:
    """任意值兜底成 dict —— TikHub 返回的中间字段可能是 list/str/None，绝不能让
    .get() 直接抛 AttributeError。"""
    return v if isinstance(v, dict) else {}


def _to_int(v: Any, default: int = 0) -> int:
    """任意值兜底转 int —— 畸形 page/numPages（非数字字符串等）不抛 ValueError。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _count(v: Any) -> int | None:
    """B站计数字段可能是真实 int，也可能是 "1.2万"/"3,456" 这类展示态字符串
    （浏览器适配器一直有这层兜底，TikHub 归一化之前漏掉了）。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return parse_int_count(str(v or ""))


def _first_cover(v: Any) -> str:
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, dict):
            return str(first.get("url") or "")
        return str(first or "")
    return ""


def _douyin_content_type(f: dict[str, Any]) -> str:
    """UI content_types → 抖音 content_type 档位：仅视频=1、仅图文=2、两者都要=0（全部）。
    实测出现过裸字符串（非 list）——不能直接 set() 拆成一堆单字符。"""
    raw = _dict(f).get("content_types")
    if isinstance(raw, str):
        types = {raw}
    elif isinstance(raw, (list, tuple, set, frozenset)):
        types = set(raw) or {"video"}
    else:
        types = {"video"}
    if types == {"video"}:
        return "1"
    if types == {"note"}:
        return "2"
    return "0"


def _preview(raw: Any, n: int = 200) -> str:
    """日志预览用——绝不能反过来把归一化本身打崩：畸形 raw（例如键是 tuple 之类
    非法 JSON key）会让 json.dumps 抛 TypeError，此时兜底成 repr。"""
    try:
        return json.dumps(raw, ensure_ascii=False, default=str)[:n]
    except Exception:  # noqa: BLE001 — 日志预览绝不能反过来把归一化打崩
        return repr(raw)[:n]


def _log_inner_error(platform: str, code: Any, raw: Any) -> None:
    logger.warning(
        "[tikhub-normalize] %s inner error code=%s first200=%s",
        platform, code, _preview(raw),
    )


# ── 抖音 ────────────────────────────────────────────────────────────────

# UI 档位 → TikHub publish_time（UI 半年=182，TikHub 半年=180）
_DY_PUBLISH_TIME = {"0": "0", "1": "1", "7": "7", "182": "180"}


def douyin_first_body(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """抖音首页 POST body：筛选全部下推（排序 / 发布时间 / 内容类型）。

    content_type 下推给服务端；本地不再按类型后过滤（TikHub 已按 content_type
    筛过；本地 images/aweme_type 判据对 TikHub 形态不可靠）。
    """
    f = _dict(f)
    return {
        "keyword": keyword,
        "cursor": 0,
        "search_id": "",
        "backtrace": "",
        "sort_type": str(f.get("sort_type") or "0"),
        "publish_time": _DY_PUBLISH_TIME.get(str(f.get("publish_time") or "0"), "0"),
        "content_type": _douyin_content_type(f),
    }


def douyin_next_body(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    cfg = _dict(_dict(_dict(raw).get("data")).get("business_config"))
    # has_more 是弱类型字段（int/str/bool 都实测出现过），白名单枚举"真值"反而会漏
    # 掉未枚举到的等价写法（"true"/2/1.0 等），提前误判没有下一页。改为只认显式
    # 否定值为停止信号，其余一律继续翻页——游标不动点防护 + 适配器层"全重复页停"
    # 兜底控制误判继续翻页的代价。
    if cfg.get("has_more") in (0, "0", False, None, "", "false", "False"):
        return None
    nxt = _dict(cfg.get("next_page"))
    if nxt.get("cursor") is None:
        return None
    body = dict(prev)
    body["cursor"] = nxt.get("cursor")
    body["search_id"] = nxt.get("search_id") or prev.get("search_id") or ""
    body["backtrace"] = cfg.get("backtrace") or ""
    # 游标不动点防护：服务端偶尔回声同一个 cursor（has_more 却仍是 1），照买会
    # 死循环重复拉同一页。cursor 不推进就当作没有下一页。
    if prev.get("cursor") is not None and str(body["cursor"]) == str(prev.get("cursor")):
        return None
    return body


def normalize_douyin_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    """只取 type==1 的视频卡（type 未标注 untrusted，实测出现过 int 也出现过
    str，统一 str() 比较）；aweme_info 与浏览器 XHR 同形，直接借用现有抽取器。
    content_type 下推给服务端；本地不再按类型后过滤（TikHub 已按 content_type
    筛过；本地 images/aweme_type 判据对 TikHub 形态不可靠）。"""
    data = _dict(_dict(raw).get("data"))
    code = data.get("status_code")
    if code not in (None, 0, "0"):
        _log_inner_error("douyin", code, raw)
    allowed = frozenset({"video", "note"})
    raw_items = data.get("business_data")
    raw_items = raw_items if isinstance(raw_items, list) else []
    items = [
        it["data"]
        for it in raw_items
        if isinstance(it, dict) and str(it.get("type")) == "1" and isinstance(it.get("data"), dict)
    ]
    # 单卡容错：逐张调抽取器而不是整批传入——一张卡叶子字段类型错（比如 author
    # 是字符串）只应该丢这一张，不该连累同页其余正常卡片。
    cards: list[VideoCard] = []
    for it in items:
        try:
            cards.extend(_DY._extract_cards({"data": [it]}, allowed_types=allowed))
        except Exception as e:  # noqa: BLE001 — 单卡畸形不该打崩整页
            logger.warning("[tikhub-normalize] douyin card skipped: %r", e)
    return cards


# ── B站 ─────────────────────────────────────────────────────────────────

_BL_PAGE_SIZE = 20


def bilibili_first_params(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """B站 general_search：order 必填（实测 totalrank 通过；其余为 B 站原生取值），
    日期区间 → pubtime_begin_s / pubtime_end_s（本地时区当天 00:00:00 / 23:59:59）。"""
    f = _dict(f)
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
    inner = _dict(_dict(_dict(raw).get("data")).get("data"))
    result = inner.get("result")
    if not isinstance(result, list) or not result:
        return None
    # page 只信"我们自己请求的"那一份，服务端回声整段不采信 —— 曾实测到回声
    # page/numPages 与我们请求的页码不一致（例如首页请求就回声 page=numPages=50，
    # 或回声一个比我们请求页更大的 page），照单全收会误判尾页、白白跳过中间页。
    page = _to_int(prev.get("page")) or 1
    num_pages = _to_int(inner.get("numPages"))
    # numPages 缺失或 0 时不拦截翻页——交给调用方 adapter 的 MAX_PAGES 兜底防止死循环。
    if num_pages and page >= num_pages:
        return None
    params = dict(prev)
    params["page"] = page + 1
    return params


def normalize_bilibili_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    f = _dict(f)
    data = _dict(_dict(raw).get("data"))
    code = data.get("code")
    if code not in (None, 0, "0"):
        _log_inner_error("bilibili", code, raw)
    inner = _dict(data.get("data"))
    result = inner.get("result")
    result = result if isinstance(result, list) else []
    cards: list[VideoCard] = []
    for it in result:
        if not isinstance(it, dict) or str(it.get("type")).lower() != "video":
            continue
        bvid = it.get("bvid")
        if not bvid:
            continue
        # 单卡容错：畸形叶子字段（比如 play 是超长数字字符串，parse_int_count 内部
        # float() 溢出成 inf 再 int() 抛 OverflowError）只应该丢这一张卡。
        try:
            cards.append(VideoCard(
                platform="bilibili",
                platform_video_id=str(bvid),
                url=f"https://www.bilibili.com/video/{bvid}",
                title=_strip_em(str(it.get("title") or "")).strip(),
                author_name=str(it.get("author") or "").strip(),
                author_id=str(it.get("mid") or ""),
                cover_url=_normalize_url(str(it.get("pic") or "")),
                duration_sec=parse_duration(str(it.get("duration") or "")),
                play_count=_count(it.get("play")),
                like_count=_count(it.get("like")),
                published_at=_pubdate_to_iso(it.get("pubdate")),
                raw=it,
            ))
        except Exception as e:  # noqa: BLE001 — 单卡畸形不该打崩整页
            logger.warning("[tikhub-normalize] bilibili card skipped: %r", e)
            continue
    return cards


# ── 快手 ────────────────────────────────────────────────────────────────

def kuaishou_first_params(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """快手 search_video_v2 无服务端筛选 —— 时间区间在 normalize 里本地后过滤。"""
    return {"keyword": keyword, "pcursor": ""}


def kuaishou_next_params(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    """pcursor 是搜索翻页的主判据；recoPcursor 是推荐流（相关搜索卡）的游标，
    与本次搜索翻页无关，不作为终止信号（曾误用 recoPcursor=="no_more" 判定
    结束，会导致只要相关搜索卡先耗尽推荐游标就永久停在第一页）。停止条件：
    mixFeeds 空/缺失，或 pcursor 缺失/空/"no_more"，或 pcursor 与上次相同
    （游标不动点，防止死循环重复拉同一页）。"""
    d = _dict(_dict(raw).get("data"))
    mix_feeds = d.get("mixFeeds")
    if not isinstance(mix_feeds, list) or not mix_feeds:
        return None
    pc = d.get("pcursor")
    if not pc or pc == "no_more":
        return None
    if str(pc) == str(prev.get("pcursor") or ""):
        return None
    params = dict(prev)
    params["pcursor"] = str(pc)
    return params


def normalize_kuaishou_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    """只取 itemType==5 的视频项；feed 为 flat 字段；时间区间本地后过滤（被滤掉的不
    计入 emitted，翻页自然补偿 —— 与浏览器快手适配器同口径）。"""
    f = _dict(f)
    d = _dict(_dict(raw).get("data"))
    resp_code = d.get("responseCode")
    if resp_code not in (None, 0, "0"):
        _log_inner_error("kuaishou", resp_code, raw)
    elif "result" in d and d.get("result") not in (1, "1"):
        _log_inner_error("kuaishou", d.get("result"), raw)
    begin = date_to_epoch(f.get("time_begin"))
    end = date_to_epoch(f.get("time_end"), end_of_day=True)
    mix_feeds = d.get("mixFeeds")
    mix_feeds = mix_feeds if isinstance(mix_feeds, list) else []
    cards: list[VideoCard] = []
    for it in mix_feeds:
        if not isinstance(it, dict) or str(it.get("itemType")) != "5":
            continue
        feed = _dict(it.get("feed"))
        pid = feed.get("photo_id")
        if not pid:
            continue
        # 单卡容错：畸形叶子字段不该打崩整页，只跳过这一张。
        try:
            pid = str(pid)
            dur_ms = _to_int(feed.get("duration"))
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
                play_count=_count(feed.get("view_count")),
                like_count=_count(feed.get("like_count")),
                published_at=_ts_ms_to_iso(ts_ms) if ts_ms else None,
                raw=feed,
            )
            if not iso_within_epoch_range(card.published_at, begin, end):
                continue
            cards.append(card)
        except Exception as e:  # noqa: BLE001 — 单卡畸形不该打崩整页
            logger.warning("[tikhub-normalize] kuaishou card skipped: %r", e)
            continue
    return cards
