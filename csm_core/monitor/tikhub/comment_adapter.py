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
from csm_core.monitor.platforms._comment_shared import (
    CommentSnapshot, group_comment_texts, shared_store)
from csm_core.monitor.text_match import find_best_match, DEFAULT_SIMILARITY_THRESHOLD
from .normalize import (
    normalize_douyin_comments, normalize_bilibili_comments, normalize_kuaishou_comments)
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

# ── 评论检索深度(三平台统一,改深度只动这一处)──
# 只检索前 N 名。抖音评论(APP 接口=手机端排序)里营销评论常年沉底,深扫去定位它的确切
# 排名意义不大又费钱(每页计费),所以只扫前 N——命中就报排名;不在前 N 就由上层标
# "超出 N 名以外或被删"。N 会随 metric.depth_cap 传给前端,前端不写死、自动跟随此处。
_COMMENT_SCAN_DEPTH = 100

DOUYIN_SPEC = PlatformSpec("douyin_comment", "/api/v1/douyin/app/v3/fetch_video_comments",
                           default_depth=_COMMENT_SCAN_DEPTH, depth_cap=_COMMENT_SCAN_DEPTH,
                           build_params=_dy_params, parse_page=_dy_parse)


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
                             default_depth=_COMMENT_SCAN_DEPTH, depth_cap=_COMMENT_SCAN_DEPTH,
                             build_params=_bl_params, parse_page=_bl_parse)


# ── 快手(单层 wrapper;pcursor=="no_more" 是翻页到底标记,不做平台级错误检测)──
def _ks_params(vid, id_type, cursor):
    p = {"photo_id": vid}
    if cursor:
        p["pcursor"] = cursor
    return p

def _ks_parse(raw, first_page):
    data = raw.get("data") or {}
    items = normalize_kuaishou_comments(raw)
    pcursor = data.get("pcursor")
    has_more = bool(pcursor) and pcursor != "no_more"
    return items, (pcursor if has_more else None), has_more

KUAISHOU_SPEC = PlatformSpec("kuaishou_comment", "/api/v1/kuaishou/app/fetch_video_comment",
                             default_depth=_COMMENT_SCAN_DEPTH, depth_cap=_COMMENT_SCAN_DEPTH,
                             build_params=_ks_params, parse_page=_ks_parse)


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
        store = shared_store()
        # URL → vid 缓存:抖音/快手的 id_extractor 会真发一次短链展开请求,
        # 同视频多任务只展开一次。
        cached = store.get_video_id("tikhub", self.platform, task.target_url)
        if cached:
            vid, id_type = cached
        else:
            vid, id_type = self._extract(task.target_url)
            if not vid:
                return self._failed(task, "无法从 URL 解析视频 ID")
            store.put_video_id("tikhub", self.platform, task.target_url, vid, id_type)
        depth = min(int(task.config.get("scrape_top_n") or self.spec.default_depth),
                    self.spec.depth_cap)
        # 顶部校验要监测的评论文本:缺了必然判 failed,提前返回省掉整轮白翻的付费请求
        # (否则会先深翻 depth 条、每页计费,最后才在 build_match_result 里报 required)。
        my_text = (task.config.get("my_comment_text") or "").strip()
        if not my_text:
            return self._failed(task, "未填写要监测的评论内容")
        threshold = float(task.config.get("threshold") or DEFAULT_SIMILARITY_THRESHOLD)

        def do_fetch() -> CommentSnapshot:
            client = self._cf()
            first = {"v": True}
            state = {"more": True}   # 记录最后一页 has_more,用于精确判断是否翻到评论区底部

            def page_fn(cursor):
                raw = client.get(self.spec.endpoint, self.spec.build_params(vid, id_type, cursor))
                items, nxt, more = self.spec.parse_page(raw, first["v"])
                first["v"] = False
                state["more"] = more
                return items, nxt, more

            # 命中即停(组感知):快照由同视频的所有评论任务共享(任务身份键含评论
            # 文本,同一条视频下常有多条任务)——必须扫到「该视频所有在监测的评论
            # 都命中」或翻满深度才停;只按自己的评论停会让快照对组内其他任务不完整
            # (共享层有防错位守卫兜底,但会退化成各自重抓、白付重复页费)。留存
            # 的评论通常都在前排,组感知即停仍远省于翻满;找不到的(可能被删/限流)
            # 才翻满,用于确认"确实不在"。匹配口径与 build_match_result 完全相同
            # (阈值 + find_best_match),避免"停了但最终又判没命中"的错位。
            texts = group_comment_texts(task)

            def stop_predicate(acc):
                return all(find_best_match(t, acc, threshold)["found"] for t in texts)

            # max_pages 用 //10 而非 //20:抖音/TikHub 常返回不足 count 条(被删/折叠/末页),
            # //20+2 只留 2 页余量,页面稍欠填就在到达 depth 前撞熔断、把"评论埋得深/找不到"
            # 误判成整任务失败(恰是本功能要识别的限流场景)。//10+2 容忍到约 10 条/页;
            # 真·病态(<9 条/页且 has_more 恒真)才熔断——那才是需要防的死循环/风控假状态。
            try:
                comments = paginate(page_fn, target=depth, max_pages=(depth // 10) + 2,
                                    cancel_token=cancel_token, stop_predicate=stop_predicate)
            except TikHubError as e:
                return CommentSnapshot(depth=depth, error=e.reason)

            # 关键:normalizer 给的是每页 1..N 的 rank,paginate 累积后必须按全局重排,
            # 否则匹配到的排名会是"页内位置"而非真实全局排名。
            for i, c in enumerate(comments):
                c["rank"] = i + 1

            cancelled = cancel_token is not None and cancel_token.is_set()
            early = len(comments) < depth and state["more"] and not cancelled
            # exhausted:最后一页 has_more=False(API 说没有更多了),或抓到的比 depth 少
            # 且不是提前收工 —— 即"整个评论区都翻遍了"。⚠️ 仅当 depth 是每页条数(20)
            # 的整数倍时才干净(无 out[:depth] 截断的溢出带)。前端不据它分档(改用留存
            # 历史 prev 判断,见 CommentMonitorModule),此处仅作原始信号保留。
            return CommentSnapshot(
                comments=comments, depth=depth,
                early_stopped=early or cancelled,
                exhausted=(not state["more"]) or (len(comments) < depth and not early and not cancelled),
                # 取消导致的截断快照只给取消者本人出结果,不入缓存 —— 它既不完整
                # 也不是"故意截短到全组命中",复用会污染组内其他任务。
                cacheable=not cancelled,
            )

        snap = store.run(
            ("tikhub", self.platform, vid), task_id=task.id or 0,
            my_text=my_text, threshold=threshold, depth=depth,
            cancel_token=cancel_token, do_fetch=do_fetch,
        )
        if snap.error is not None:
            return self._failed(task, snap.error)

        # scan_limit=depth:匹配窗口==抓取深度,防止 build_match_result 默认的 150 上限
        # 与 depth 不一致时把已抓到的评论切掉误判(depth 未来若再调大也不会有死区)。
        # 评论 dict 逐条浅拷贝:metric.hot_comments 随结果落库/发事件,不能与
        # 共享缓存里的快照互为别名(下游任何写者都会跨任务污染缓存)。
        result = build_match_result(
            task, [dict(c) for c in snap.comments], source="tikhub", scan_limit=depth)
        # depth_cap(前端"前 N 名"的 N)由 build_match_result 统一写(=scan_limit=depth),本地/API 口径一致。
        if isinstance(result.metric, dict):
            result.metric["exhausted"] = snap.exhausted
        return result
