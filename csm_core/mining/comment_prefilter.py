"""引流预筛：复用监控评论适配器抓单视频评论 + 数品牌词命中。

Registry confirmed:
  csm_core.monitor.platforms.ALL maps type strings to adapter singletons:
    "bilibili_comment" → BILIBILI ADAPTER
    "douyin_comment"   → DOUYIN ADAPTER
    "kuaishou_comment" → KUAISHOU ADAPTER

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
}


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


def fetch_video_comment_texts(platform: str, video_url: str, limit: int = 30) -> list[str]:
    """Fetch the first ~limit comment texts for a video, reusing monitor adapters.

    Delegates to the same comment-retention adapter that powers the Monitor tab
    (bilibili_comment / douyin_comment / kuaishou_comment). The adapter handles
    cookie selection, anti-scrape measures, and pagination internally.

    A placeholder ``my_comment_text`` is injected so that ``build_match_result``
    does not short-circuit with status="failed". The caller only cares about the
    raw ``hot_comments`` list, not rank / match results.

    Args:
        platform:  One of "douyin", "bilibili", "kuaishou".
        video_url: Full URL of the target video / item.
        limit:     Approximate number of comments to fetch (maps to scrape_top_n).

    Returns:
        List of comment text strings, or [] on any failure (fail-open: callers
        should not exclude a video simply because comments couldn't be fetched).
    """
    ctype = _PLATFORM_COMMENT_TYPE.get(platform)
    if ctype is None:
        return []

    try:
        from csm_core.monitor.platforms import ALL as _ADAPTERS  # registry confirmed
        from csm_core.monitor.base import MonitorTask

        adapter = _ADAPTERS.get(ctype)
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
        return [str(c.get("text") or "") for c in hots]

    except Exception:
        logger.info(
            "[prefilter] fetch comments failed platform=%s url=%s",
            platform,
            (video_url or "")[:80],
            exc_info=True,
        )
        return []
