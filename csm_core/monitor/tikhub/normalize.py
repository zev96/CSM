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


def normalize_kuaishou_comments(raw: dict) -> list[dict]:
    """快手 App 评论:单层 wrapper,raw.data.rootComments 是评论列表。"""
    cs = (raw.get("data") or {}).get("rootComments") or []
    out: list[dict] = []
    for c in cs:
        out.append({
            "rank": len(out) + 1,
            "text": c.get("content") or "",
            "author": c.get("author_name"),
            "likes": c.get("likedCount"),
        })
    return out


# ── 小红书 ──────────────────────────────────────────────────────────────

def _xhs_int(v) -> int | None:
    """小红书计数字段既可能是 int 也可能是 "1.2万" 这类展示态字符串,兜底转 int。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    t = str(v).strip().replace(",", "")
    if not t:
        return None
    try:
        if t.endswith(("万", "w", "W")):
            return int(float(t[:-1]) * 10_000)
        if t.endswith("亿"):
            return int(float(t[:-1]) * 100_000_000)
        return int(float(t))
    except (ValueError, TypeError, OverflowError):
        return None


def xiaohongshu_comment_page(raw: dict) -> dict:
    """取小红书评论接口的真数据层。

    TikHub 外层 ``raw.data`` 是小红书信封 ``{code, success, msg, data}``,评论列表与
    翻页字段(cursor / index / pageArea / has_more)在 ``raw.data.data``(TikHub 文档:
    「翻页所需字段通常位于响应的 $.data.data 对象中」)。若服务端把这一层摊平
    (``raw.data`` 直接带 comments),也认。非 dict 一律兜底成 {}。
    """
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    if isinstance(inner, dict) and any(k in inner for k in ("comments", "cursor", "has_more")):
        return inner
    return data


def normalize_xiaohongshu_comments(raw: dict) -> list[dict]:
    """小红书 App 评论:``comments[]`` 每条 ``content`` / ``user.nickname`` / ``like_count``。

    字段路径按小红书 App 评论接口的公开形态写(``content`` 正文、``user.nickname``
    作者、``like_count`` 点赞),尚未像抖音/B站/快手那样用真实 token 落 fixture 实测;
    首跑请用 ``sidecar/scripts/tikhub_probe.py --xhs`` 抓一份校正。
    """
    cs = xiaohongshu_comment_page(raw).get("comments") or []
    if not isinstance(cs, list):
        cs = []
    out: list[dict] = []
    for c in cs:
        if not isinstance(c, dict):
            continue
        user = c.get("user") if isinstance(c.get("user"), dict) else {}
        out.append({
            "rank": len(out) + 1,
            "text": str(c.get("content") or c.get("text") or ""),
            "author": user.get("nickname") or user.get("name"),
            "likes": _xhs_int(c.get("like_count", c.get("liked_count"))),
        })
    return out
