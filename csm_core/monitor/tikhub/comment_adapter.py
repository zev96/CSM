"""通用评论 API 适配器 + 抖音/B站 spec。

设计依据: docs/superpowers/specs/2026-07-06-tikhub-api-scraping-mode-design.md §8.2
- 抖音、B站(以及未来快手)评论排名监控走同一套流程:解析 URL 拿视频 ID →
  ``paginate()`` 自适应翻页凑够 depth 条 → 复用
  ``csm_core/monitor/platforms/_comment_common.py`` 的 ``build_match_result``
  做匹配与结果构造。差异只在参数构造(``build_params``)与响应拆包
  (``parse_page``),用 ``PlatformSpec`` 参数化后一份 ``CommentApiAdapter``
  即可服务两个平台。
- 关键红线:``normalize_*`` 每页给出的是**页内** 1..N 的 rank;``paginate()``
  只是简单 extend 多页结果,不会重排。若不在这里按跨页顺序重新赋值 rank,
  第 2 页起的评论会全部顶着"页内 rank"喂给 ``build_match_result`` →
  ``find_best_match`` 直接读 ``comment["rank"]``(见 text_match.py),命中的
  排名会是错的页内位置而非真实全局排名。因此 ``fetch()`` 在拿到全部
  ``comments`` 后必须做一次 ``for i, c in enumerate(comments): c["rank"] = i + 1``
  的全局重排,这是本模块与知乎适配器最大的行为差异点。
- 平台级错误检测:抖音 ``data.status_code != 0``、B站信封 ``data.code != 0``
  都代表业务层失败(非 HTTP/网络错误),``parse_page`` 探测到就抛
  ``TikHubError``,经 ``paginate()`` 原样上抛,适配器捕获后整体判 failed
  ——不能把这类错误响应误当"空评论区"处理。
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from csm_core.monitor.base import MonitorResult
from csm_core.monitor.platforms._comment_common import build_match_result
from .normalize import normalize_douyin_comments, normalize_bilibili_comments
from .client import paginate
from .errors import TikHubError


@dataclass
class PlatformSpec:
    platform: str
    endpoint: str
    default_depth: int
    depth_cap: int
    build_params: Callable    # (vid, id_type, cursor) -> dict
    parse_page: Callable      # (raw, first_page) -> (items, next_cursor, has_more);平台级错误抛 TikHubError


# ── 抖音(单层 wrapper;data.status_code!=0 是平台级错误)──
def _dy_params(vid, id_type, cursor):
    return {"aweme_id": vid, "count": 20, "cursor": cursor or 0}

def _dy_parse(raw, first_page):
    data = raw.get("data") or {}
    sc = data.get("status_code")
    if sc not in (0, None):
        raise TikHubError(f"抖音接口错误: {data.get('status_msg') or sc}")
    items = normalize_douyin_comments(raw)
    return items, data.get("cursor"), bool(data.get("has_more"))

DOUYIN_SPEC = PlatformSpec("douyin_comment", "/api/v1/douyin/app/v3/fetch_video_comments",
                           default_depth=50, depth_cap=50, build_params=_dy_params, parse_page=_dy_parse)


# ── B站(双层 wrapper;raw.data 是B站信封 code/message/ttl/data)──
def _bl_params(vid, id_type, cursor):
    p = {"mode": 3, "next_offset": cursor or 1}
    if id_type == "avid":
        p["av_id"] = vid
    else:                       # "bvid" 或其它 → 当 BV 号
        p["bv_id"] = vid
    return p

def _bl_parse(raw, first_page):
    env = raw.get("data") or {}          # B站信封
    code = env.get("code")
    if code not in (0, None):
        raise TikHubError(f"B站接口错误: {env.get('message') or code}")
    items = normalize_bilibili_comments(raw, first_page=first_page)
    cur = (env.get("data") or {}).get("cursor") or {}
    return items, cur.get("next"), (not cur.get("is_end", True))

BILIBILI_SPEC = PlatformSpec("bilibili_comment", "/api/v1/bilibili/app/fetch_video_comments",
                             default_depth=150, depth_cap=200, build_params=_bl_params, parse_page=_bl_parse)


class CommentApiAdapter:
    """视频评论留存/排名监控的 TikHub API 版(通用,按 PlatformSpec 参数化)。"""

    def __init__(self, spec: PlatformSpec, client_factory, id_extractor):
        self.spec = spec
        self.platform = spec.platform
        self._cf = client_factory          # () -> TikHubClient
        self._extract = id_extractor       # (url) -> (vid|None, id_type)

    def _failed(self, task, reason: str) -> MonitorResult:
        return MonitorResult(task_id=task.id or 0, checked_at=datetime.utcnow(),
                             status="failed", rank=-1, error_message=reason,
                             metric={"source": "tikhub"})

    def fetch(self, task, cancel_token=None, progress_cb=None, **_) -> MonitorResult:
        vid, id_type = self._extract(task.target_url)
        if not vid:
            return self._failed(task, "无法从 URL 解析视频 ID")
        depth = min(int(task.config.get("scrape_top_n") or self.spec.default_depth),
                    self.spec.depth_cap)
        client = self._cf()
        first = {"v": True}

        def page_fn(cursor):
            raw = client.get(self.spec.endpoint, self.spec.build_params(vid, id_type, cursor))
            items, nxt, more = self.spec.parse_page(raw, first["v"])
            first["v"] = False
            return items, nxt, more

        try:
            comments = paginate(page_fn, target=depth, max_pages=(depth // 20) + 2,
                                cancel_token=cancel_token)
        except TikHubError as e:
            return self._failed(task, e.reason)

        # 关键:normalizer 给的是每页 1..N 的 rank,paginate 累积后必须按全局重排,
        # 否则匹配到的排名会是"页内位置"而非真实全局排名。
        for i, c in enumerate(comments):
            c["rank"] = i + 1

        result = build_match_result(task, comments, source="tikhub")  # 返回 MonitorResult
        if isinstance(result.metric, dict):
            result.metric["scanned_full"] = True   # 页失败会整体 fail,能到这就是扫全了
        return result
