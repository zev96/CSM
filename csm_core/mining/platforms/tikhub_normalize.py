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
- 小红书 ``GET /api/v1/xiaohongshu/app_v2/search_notes``（⚠️ 尚未用真实 token 实测，
    按小红书 App 搜索接口的公开形态写并逐层兜底）
    笔记：``data(.data).items[model_type=="note"].note``（或字段摊平的笔记）；
    翻页：``page+1`` + 首页回传的 ``search_id`` / ``search_session_id``；``has_more`` 显式
    为假或本页无 items 即停。首跑请用 ``sidecar/scripts/tikhub_probe.py --xhs-search``
    落 fixture 校正字段路径。

约定：``*_first_*(keyword, plat_filters)`` 造首页请求；``*_next_*(prev, raw)`` 从上一页
响应造下一页请求，返回 None = 没有下一页；``normalize_*(raw, plat_filters)`` 出卡片。
对实测到的畸形结构（非 dict 层级、数值字段为字符串、游标类型漂移）做兜底；叶子字段
类型错误由适配器层（``tikhub_search._fetch_page``）统一按页级错误处理。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
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
    """封面 URL 只认 str 或带 url 的 dict——其余类型（嵌套 list、int 等）一律回退
    空字符串，不能被 str() 硬转成 "['x']" 这类明显不是 URL 的垃圾字符串落库。"""
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, dict):
            return str(first.get("url") or "")
        if isinstance(first, str):
            return first
    return ""


def _douyin_content_type(f: dict[str, Any]) -> str:
    """UI content_types → 抖音 content_type 档位：仅视频=1、仅图文=2、两者都要=0（全部）。
    实测出现过裸字符串（非 list）——不能直接 set() 拆成一堆单字符；list 里混入非
    字符串元素（比如脏数据 dict）也不能让它原样进 set() 参与后面的 == 比较——
    非 str 元素必然不等于 "video"/"note"，只会让判据永远落到"两者都要"这个错误
    档位，必须先过滤掉。"""
    raw = _dict(f).get("content_types")
    if isinstance(raw, str):
        types = {raw}
    elif isinstance(raw, (list, tuple, set, frozenset)):
        types = {x for x in raw if isinstance(x, str)} or {"video"}
    else:
        types = {"video"}
    if types == {"video"}:
        return "1"
    if types == {"note"}:
        return "2"
    return "0"


def _preview(raw: Any, n: int = 200) -> str:
    """日志预览用——外层信封是计费路由/请求回声等噪音（TikHub 聚合网关会把
    request_id、路由信息、联系方式之类的样板文字都塞在顶层），真正有诊断价值的
    status_code / params.keyword 往往被挤到 1KB 开外，200 字符的预览窗口经常连
    ``data`` 字段本身都看不到。``data`` 存在就只预览 ``data``；不存在（比如整个
    raw 本身已经畸形，没有这一层结构）才退回整个 raw。
    绝不能反过来把归一化本身打崩：畸形 raw（例如键是 tuple 之类非法 JSON key）
    会让 json.dumps 抛 TypeError，此时兜底成 repr。"""
    d = _dict(raw)
    target = d.get("data") if "data" in d else raw
    try:
        return json.dumps(target, ensure_ascii=False, default=str)[:n]
    except Exception:  # noqa: BLE001 — 日志预览绝不能反过来把归一化打崩
        return repr(target)[:n]


def _log_inner_error(platform: str, code: Any, raw: Any) -> None:
    logger.warning(
        "[tikhub-normalize] %s inner error code=%s first200=%s",
        platform, code, _preview(raw),
    )


# ── 抖音 ────────────────────────────────────────────────────────────────

# UI 档位 → TikHub publish_time（UI 半年=182，TikHub 半年=180）
_DY_PUBLISH_TIME = {"0": "0", "1": "1", "7": "7", "182": "180"}
# 抖音 sort_type：0=综合排序、1=最多点赞、2=最新发布——白名单之外的值（畸形筛选值/
# 未来平台新增档位我们还不认识）一律兜底成 0，不能把未知取值原样透传给上游 API。
_DY_SORT_TYPES = frozenset({"0", "1", "2"})


def douyin_first_body(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """抖音首页 POST body：筛选全部下推（排序 / 发布时间 / 内容类型）。

    content_type 下推给服务端；本地不再按类型后过滤（TikHub 已按 content_type
    筛过；本地 images/aweme_type 判据对 TikHub 形态不可靠）。
    """
    f = _dict(f)
    sort_type = str(f.get("sort_type") or "0")
    if sort_type not in _DY_SORT_TYPES:
        sort_type = "0"
    return {
        "keyword": keyword,
        "cursor": 0,
        "search_id": "",
        "backtrace": "",
        "sort_type": sort_type,
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
            logger.warning("[tikhub-normalize] douyin card skipped: %s", type(e).__name__)
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
            logger.warning("[tikhub-normalize] bilibili card skipped: %s", type(e).__name__)
            continue
    return cards


# ── 快手 ────────────────────────────────────────────────────────────────

# raw 落库前剔除的流媒体/清单类大字段——归一化后的卡片不消费它们，整段存进
# raw 纯粹是存储膨胀。
_KS_RAW_DROP = frozenset({"streamManifest", "main_mv_urls", "ff_cover_thumbnail_urls"})


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
                # dur_ms // 1000 or None:不足 1 秒(整除得 0)也归一成 None，语义上
                # 视为"时长未知"，不能报成"0 秒"。
                duration_sec=(dur_ms // 1000) or None if dur_ms else None,
                play_count=_count(feed.get("view_count")),
                like_count=_count(feed.get("like_count")),
                published_at=_ts_ms_to_iso(ts_ms) if ts_ms else None,
                raw={k: v for k, v in feed.items() if k not in _KS_RAW_DROP},
            )
            if not iso_within_epoch_range(card.published_at, begin, end):
                continue
            cards.append(card)
        except Exception as e:  # noqa: BLE001 — 单卡畸形不该打崩整页
            logger.warning("[tikhub-normalize] kuaishou card skipped: %s", type(e).__name__)
            continue
    return cards


# ── 小红书 ──────────────────────────────────────────────────────────────

_XHS_SORT_TYPES = frozenset({
    "general", "time_descending", "popularity_descending",
    "comment_descending", "collect_descending",
})
# UI 档位 → TikHub 接口的中文档位（接口只认中文取值）
_XHS_NOTE_TYPE = {"all": "不限", "video": "视频笔记", "image": "普通笔记"}
_XHS_TIME_FILTER = {"0": "不限", "1": "一天内", "7": "一周内", "182": "半年内"}
# raw 落库前剔除的媒体大字段——卡片只消费封面 URL / 时长，整段存进 raw 纯粹是存储膨胀。
_XHS_RAW_DROP = frozenset({
    "video_info_v2", "video_info", "video", "images_list", "image_list",
    "widgets_context", "share_info",
})
_XHS_NOTE_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def xiaohongshu_first_params(keyword: str, f: dict[str, Any]) -> dict[str, Any]:
    """小红书首页 GET 参数：排序 / 笔记类型 / 发布时间全部下推（白名单之外一律兜底默认档）。"""
    f = _dict(f)
    sort_type = str(f.get("sort_type") or "general")
    return {
        "keyword": keyword,
        "page": 1,
        "sort_type": sort_type if sort_type in _XHS_SORT_TYPES else "general",
        "note_type": _XHS_NOTE_TYPE.get(str(f.get("note_type") or "all"), "不限"),
        "time_filter": _XHS_TIME_FILTER.get(str(f.get("time_filter") or "0"), "不限"),
    }


def _xhs_search_page(raw: Any) -> dict[str, Any]:
    """搜索真数据层：raw.data（TikHub 外层）→ 若含小红书信封 data.data 且带 items，取内层。"""
    data = _dict(_dict(raw).get("data"))
    inner = data.get("data")
    if isinstance(inner, dict) and ("items" in inner or "notes" in inner):
        return inner
    return data


def _xhs_items(page: dict[str, Any]) -> list[Any]:
    items = page.get("items")
    if not isinstance(items, list):
        items = page.get("notes")
    return items if isinstance(items, list) else []


def xiaohongshu_next_params(prev: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    """翻页 = page+1，并带上首页回传的 search_id / search_session_id（缺失就沿用上一页的）。
    本页无 items 或 has_more 显式为假 → 没有下一页。"""
    page = _xhs_search_page(raw)
    if not _xhs_items(page):
        return None
    if page.get("has_more") in (0, "0", False, "false", "False"):
        return None
    data = _dict(_dict(raw).get("data"))
    search_id = page.get("search_id") or data.get("search_id") or prev.get("search_id") or ""
    session_id = (
        page.get("search_session_id") or data.get("search_session_id")
        or page.get("session_id") or prev.get("search_session_id") or ""
    )
    params = dict(prev)
    params["page"] = (_to_int(prev.get("page")) or 1) + 1
    if search_id:
        params["search_id"] = str(search_id)
    if session_id:
        params["search_session_id"] = str(session_id)
    return params


def _xhs_note(it: Any) -> dict[str, Any]:
    """一条搜索结果 → 笔记 dict。形态 A：{model_type:"note", note:{...}}；形态 B：笔记字段摊平。
    非笔记卡（广告 / 用户 / 话题等 model_type）→ {}。"""
    it = _dict(it)
    mt = it.get("model_type")
    if mt not in (None, "note", "note_card", "normal", "video"):
        return {}
    note = it.get("note") or it.get("note_card")
    if isinstance(note, dict):
        return {**note, "_xsec_token": it.get("xsec_token") or note.get("xsec_token")}
    if it.get("id") or it.get("note_id"):
        return {**it, "_xsec_token": it.get("xsec_token")}
    return {}


def _xhs_ts_to_iso(v: Any) -> str | None:
    """time / timestamp（秒或毫秒）→ ISO UTC；非法 → None。"""
    n = _to_int(v)
    if n <= 0:
        return None
    if n > 10**11:          # 毫秒
        n //= 1000
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _xhs_cover(note: dict[str, Any]) -> str:
    for key in ("images_list", "image_list"):
        v = note.get(key)
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, dict):
                u = first.get("url") or first.get("url_default") or first.get("url_pre")
                return str(u) if u else ""
            if isinstance(first, str):
                return first
    cover = note.get("cover")
    if isinstance(cover, dict):
        return str(cover.get("url") or cover.get("url_default") or "")
    if isinstance(cover, str):
        return cover
    return ""


def _xhs_duration(note: dict[str, Any]) -> int | None:
    """视频笔记时长（秒）；图文笔记 None。实测前兼容 video_info.duration /
    video_info_v2.capa.duration / video.media.video.duration 三种落点，毫秒自动折算。"""
    for key in ("video_info", "video_info_v2", "video"):
        v = note.get(key)
        if not isinstance(v, dict):
            continue
        d = v.get("duration")
        if d is None:
            d = _dict(v.get("capa")).get("duration")
        if d is None:
            d = _dict(_dict(v.get("media")).get("video")).get("duration")
        n = _to_int(d)
        if n > 0:
            return n // 1000 if n > 36_000 else n
    return None


def normalize_xiaohongshu_search(raw: dict[str, Any], f: dict[str, Any]) -> list[VideoCard]:
    """搜索结果 → VideoCard。规范链接 ``xiaohongshu.com/explore/{note_id}``，结果里带
    ``xsec_token`` 时追加 ``?xsec_token=…&xsec_source=pc_search``（网页端没有它打不开笔记；
    App 内两种都能打开）。播放数小红书不回，恒 None；点赞数兼容 "1.2万" 展示态。"""
    data = _dict(_dict(raw).get("data"))
    code = data.get("code")
    if data.get("success") is False or code not in (None, 0, "0", 200, "200"):
        _log_inner_error("xiaohongshu", code, raw)
    cards: list[VideoCard] = []
    for it in _xhs_items(_xhs_search_page(raw)):
        note = _xhs_note(it)
        if not note:
            continue
        nid = str(note.get("id") or note.get("note_id") or "").strip()
        if not nid:
            continue
        # 单卡容错：畸形叶子字段只丢这一张，不连累同页其余卡片。
        try:
            user = _dict(note.get("user"))
            title = str(note.get("title") or note.get("display_title") or "").strip()
            if not title:
                desc = str(note.get("desc") or "").strip()
                title = desc.splitlines()[0][:80] if desc else ""
            interact = _dict(note.get("interact_info"))
            xsec = note.get("_xsec_token")
            url = f"https://www.xiaohongshu.com/explore/{nid}"
            if isinstance(xsec, str) and xsec:
                url += f"?xsec_token={xsec}&xsec_source=pc_search"
            cards.append(VideoCard(
                platform="xiaohongshu",
                platform_video_id=nid,
                url=url,
                title=title,
                author_name=str(user.get("nickname") or user.get("name") or "").strip(),
                author_id=str(user.get("userid") or user.get("user_id") or user.get("id") or ""),
                cover_url=_xhs_cover(note),
                duration_sec=_xhs_duration(note),
                play_count=_count(note.get("view_count") or interact.get("view_count")),
                like_count=_count(
                    note.get("liked_count") or note.get("likes") or interact.get("liked_count")
                ),
                published_at=_xhs_ts_to_iso(
                    note.get("time") or note.get("timestamp") or note.get("create_time")
                ),
                raw={k: v for k, v in note.items() if k not in _XHS_RAW_DROP and not str(k).startswith("_")},
            ))
        except Exception as e:  # noqa: BLE001 — 单卡畸形不该打崩整页
            logger.warning("[tikhub-normalize] xiaohongshu card skipped: %s", type(e).__name__)
            continue
    return cards
