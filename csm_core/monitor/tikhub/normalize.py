"""把 TikHub 知乎 /feeds 信封拆包成扁平答案列表。

设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §8.1
- TikHub 知乎接口返回 `data.data[]`,每项是一张 feed 卡片,`type=='question_feed_card'`。
- 只有 `target_type=='answer'` 的卡片才是真答案,答案本体在 `target`(含
  `content` 完整 HTML、`author.name`、`voteup_count`、`comment_count`、`url` 等)。
- 同一页可能混入非 answer 卡(广告 / 视频等),必须过滤掉;本地抓取路径没有
  广告卡概念,为保持两条路径口径一致,rank 按**过滤后**的顺序连续编号,
  而不是按原始下标编号。
- 本函数只做结构拆包,`content` 保留原始 HTML,不做任何清洗(不 import
  `_strip_tags`)——正文清洗留给后续适配器在与本地路径做品牌匹配前统一处理。
"""

from __future__ import annotations


def normalize_zhihu_answers(raw: dict) -> list[dict]:
    """把 TikHub 知乎 /feeds 信封拆成扁平答案列表。

    结构: raw.data.data[N],每项 type=='question_feed_card'、target_type=='answer',
    真答案在 target。过滤非 answer 卡(广告/视频等),按过滤后顺序连续编号 rank。
    content 保留原始 HTML(供后续用与本地相同的 _strip_tags 清洗后做品牌匹配)。
    """
    cards = (raw.get("data") or {}).get("data") or []
    out: list[dict] = []
    for card in cards:
        if card.get("type") != "question_feed_card":
            continue
        if card.get("target_type") != "answer":
            continue
        t = card.get("target")
        if not isinstance(t, dict):
            continue
        out.append({
            "rank": len(out) + 1,                       # 过滤后连续编号
            "author": (t.get("author") or {}).get("name"),
            "content": t.get("content") or "",          # 原始 HTML
            "voteup_count": t.get("voteup_count"),
            "comment_count": t.get("comment_count"),
            "url": t.get("url"),
        })
    return out


def normalize_douyin_comments(raw: dict) -> list[dict]:
    """抖音 App 评论:单层 wrapper,raw.data.comments 是评论列表。"""
    cs = (raw.get("data") or {}).get("comments") or []
    out: list[dict] = []
    for c in cs:
        out.append({
            "rank": len(out) + 1,
            "text": c.get("text") or "",
            "author": (c.get("user") or {}).get("nickname"),
            "likes": c.get("digg_count"),
        })
    return out


def _bili_one(node: dict) -> dict:
    return {
        "text": (node.get("content") or {}).get("message") or "",
        "author": (node.get("member") or {}).get("uname"),
        "likes": node.get("like"),
    }


def normalize_bilibili_comments(raw: dict, first_page: bool = False) -> list[dict]:
    """B站 App 评论:双层 wrapper(raw.data 是B站信封,raw.data.data 才是真数据)。
    首屏把置顶(data.data.top.upper / .admin)放最前,再 hots、replies,按文本全局去重。"""
    inner = ((raw.get("data") or {}).get("data")) or {}
    rows: list[dict] = []
    seen: set[str] = set()

    def push(node):
        if not isinstance(node, dict):
            return
        c = _bili_one(node)
        if c["text"] in seen:
            return
        seen.add(c["text"])
        rows.append(c)

    if first_page:
        top = inner.get("top") or {}
        push(top.get("upper"))   # UP 置顶
        push(top.get("admin"))   # 管理员置顶
    for h in (inner.get("hots") or []):
        push(h)
    for r in (inner.get("replies") or []):
        push(r)
    return [{**c, "rank": i + 1} for i, c in enumerate(rows)]
