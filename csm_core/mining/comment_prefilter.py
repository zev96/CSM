"""引流预筛：复用监控评论适配器抓单视频评论 + 数品牌词命中。

Registry confirmed:
  csm_core.monitor.platforms.ALL maps type strings to adapter singletons:
    "bilibili_comment" → BILIBILI ADAPTER
    "douyin_comment"   → DOUYIN ADAPTER
    "kuaishou_comment" → KUAISHOU ADAPTER
    "xiaohongshu_comment" → 占位(真实抓取固定走 TikHub,见 _resolve_adapter)

hot_comments key confirmed in _comment_common.build_match_result line 99:
    metric["hot_comments"] = hot_slice  (list of {rank, text, author, likes, ...})
"""
from __future__ import annotations
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 匹配前抹掉所有空白：让「希 喂」「希　喂」「CE WEY」也能命中「希喂」「CEWEY」。
# 评论里在品牌词中间插空格是常见写法（手滑 / 故意规避）。代价：极短英文品牌
# 理论上可能跨词命中（如 "ice weyland"→"iceweyland" 含 "cewey"），但真实品牌名
# 几乎不会撞；中文几乎零误伤。\s 在 Python3 默认含全角空格 　。
_WS_RE = re.compile(r"\s+")

# 占位：build_match_result 要求 my_comment_text 非空（strip 后）。预筛只数评论、
# 不关心 rank，用一个不会出现在评论里、strip 后非空的哨兵，让 status=ok + 拿到 hot_comments。
_PREFILTER_PLACEHOLDER = "__csm_prefilter_noop__"

# mining platform name → monitor comment adapter type key (matches ALL registry)
_PLATFORM_COMMENT_TYPE = {
    "douyin": "douyin_comment",
    "bilibili": "bilibili_comment",
    "kuaishou": "kuaishou_comment",
    "xiaohongshu": "xiaohongshu_comment",
}

# 只有 TikHub 路径的平台:没有本地免费实现,缺 key 就直接放弃(fail-open,不排除视频)。
_TIKHUB_ONLY_PLATFORMS = frozenset({"xiaohongshu"})
# 优先走 TikHub 的平台(有 key 就用;缺 key / 构建失败回落本地):抖音本地 X-Bogus 是假桩。
_TIKHUB_PREFERRED_PLATFORMS = frozenset({"douyin"}) | _TIKHUB_ONLY_PLATFORMS


def count_brand_hits(texts: list[str], brands: list[str]) -> int:
    """Case- and whitespace-insensitive count of texts containing a brand.

    All whitespace is stripped from both the brand and the comment before the
    substring check, so "希 喂" / "CE WEY" still match "希喂" / "CEWEY".
    Each text is counted at most once, regardless of how many brands it matches.
    Brands that are empty / whitespace-only are ignored.

    Args:
        texts:  List of comment/review strings to scan.
        brands: Brand keyword strings (case-insensitive substring match).

    Returns:
        Number of texts that contain at least one brand keyword.
    """
    bl = [_WS_RE.sub("", b.lower()) for b in brands if b and b.strip()]
    if not bl:
        return 0
    return sum(
        1
        for t in texts
        if any(b in _WS_RE.sub("", (t or "").lower()) for b in bl)
    )


def _resolve_adapter(ctype: str, platform: str):
    """Pick the comment adapter for one prefilter fetch.

    抖音优先走 TikHub API（配置了 tikhub key 时）：本地抖音评论接口的
    X-Bogus 是假桩，基本抓不到东西 —— 见 douyin_comment.py 模块注释。
    B 站 / 快手本地路径免费可用，留在本地省 TikHub 额度。TikHub 构建
    失败（缺依赖 / 配置损坏）时回落本地，与整体 fail-open 口径一致。
    """
    if platform in _TIKHUB_PREFERRED_PLATFORMS:
        try:
            from csm_core.config import get_config, read_api_key

            cfg = get_config()
            if (read_api_key("tikhub", cfg) or "").strip():
                from csm_core.monitor.tikhub import build_api_adapters

                return build_api_adapters(get_config, read_api_key)[ctype]
        except Exception:
            logger.info(
                "[prefilter] tikhub adapter unavailable for %s, falling back to local",
                platform, exc_info=True,
            )
        if platform in _TIKHUB_ONLY_PLATFORMS:
            # 小红书没有本地评论路径:缺 key 就跳过预筛(fail-open),不能拿注册表里的
            # 占位适配器去"抓"——它只会返回 failed。
            logger.info("[prefilter] %s has no local comment path and no tikhub key; skip", platform)
            return None
    from csm_core.monitor.platforms import ALL as _ADAPTERS  # registry confirmed
    return _ADAPTERS.get(ctype)


def fetch_video_comments(
    platform: str, video_url: str, limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch the first ~limit comments for a video, reusing monitor adapters.

    Delegates to the same comment-retention adapter that powers the Monitor tab
    (bilibili_comment / kuaishou_comment locally; douyin via TikHub when a key
    is configured — see ``_resolve_adapter``). The adapter handles cookie
    selection, anti-scrape measures, and pagination internally.

    A placeholder ``my_comment_text`` is injected so that ``build_match_result``
    does not short-circuit with status="failed". The caller only cares about the
    raw ``hot_comments`` list, not rank / match results.

    Args:
        platform:  One of "douyin", "bilibili", "kuaishou", "xiaohongshu".
        video_url: Full URL of the target video / item.
        limit:     Approximate number of comments to fetch (maps to scrape_top_n).

    Returns:
        List of ``{"text": str, "likes": int|None, "author": str}`` dicts, or []
        on any failure (fail-open: callers should not exclude a video simply
        because comments couldn't be fetched).
    """
    ctype = _PLATFORM_COMMENT_TYPE.get(platform)
    if ctype is None:
        return []

    if platform in _TIKHUB_PREFERRED_PLATFORMS:
        from csm_core.monitor.tikhub.client import balance_exhausted

        if balance_exhausted():
            # 余额闩已置位:抖音 / 小红书评论预筛走的是 TikHub API(见 _resolve_adapter),
            # 再发请求注定 402。提前短路,不浪费一次已知会失败的调用,也避免
            # 在余额耗尽期间刷一堆重复的失败日志。fail-open:不排除该视频。
            logger.info(
                "[prefilter] tikhub balance exhausted; skip %s comment fetch (fail-open)", platform,
            )
            return []

    try:
        from csm_core.monitor.base import MonitorTask

        adapter = _resolve_adapter(ctype, platform)
        if adapter is None:
            return []

        task = MonitorTask(
            type=ctype,
            name="prefilter",
            target_url=video_url,
            config={
                # Non-empty placeholder so build_match_result does not fail-fast
                "my_comment_text": _PREFILTER_PLACEHOLDER,
                "scrape_top_n": int(limit),
            },
        )
        result = adapter.fetch(task)

        if getattr(result, "status", "") != "ok":
            return []

        hots: list[dict[str, Any]] = (result.metric or {}).get("hot_comments") or []
        return [
            {
                "text": str(c.get("text") or ""),
                "likes": c.get("likes"),
                "author": str(c.get("author") or ""),
            }
            for c in hots
        ]

    except Exception:
        logger.info(
            "[prefilter] fetch comments failed platform=%s url=%s",
            platform,
            (video_url or "")[:80],
            exc_info=True,
        )
        return []


def fetch_video_comment_texts(platform: str, video_url: str, limit: int = 30) -> list[str]:
    """Text-only convenience wrapper around ``fetch_video_comments``."""
    return [c["text"] for c in fetch_video_comments(platform, video_url, limit=limit)]
