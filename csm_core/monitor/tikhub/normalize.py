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
