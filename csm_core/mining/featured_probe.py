"""精选评论轻量探测 —— 不抓评论、只确认评论区是否开启了「精选后可见」。

背景：博主开启评论精选后（B 站评论框提示「评论被up主精选后，对所有人可见」），
访客发的评论要被博主手动精选才公开 —— 引流评论发了也没人看得见，这类视频抓到
就该直接跳过。

两条识别路径：
  - 任务填了品牌词：预筛本来就要抓评论区，适配器顺带把信号带回来（零额外请求），
    见 ``comment_prefilter.probe_video_comments``；适配器那次抓取失败（没结论）时
    runner 回落到本模块补判；
  - 没填品牌词：走本模块 —— 每视频 1 个小请求（``ps=1``，只为读 control 块）。

免登录：B 站评论接口首页匿名即返回 control 块（2026-09 实测），探测不带 cookie，
不消耗账号风控额度。匿名请求会被随机风控抽检（偶发 code=-352），所以单次失败先
重试一次。fail-open：探测失败 / 不支持的平台一律返回 None，调用方不排除视频；
连续失败达到上限后熔断，本轮剩余视频不再发请求（多半是 IP 被风控，继续打只会
更糟）。

抖音 / 快手 / 小红书：暂不支持。手头的真实响应样本都是普通视频，看不出哪个字段
对应「精选」，没有开启精选的样本可对照，不做猜测式判断（误判 = 白丢候选视频）。
拿到样本确认字段后，加进 ``FEATURED_PROBE_PLATFORMS`` 并在 ``FeaturedProber.check``
里补分支即可。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from csm_core.browser_infra.rate_limit import RequestPacer
from csm_core.monitor.platforms.bilibili_comment import featured_only_from_reply_data

logger = logging.getLogger(__name__)

#: 支持轻量探测的平台 = 精选信号已实测确认、且有免登录接口可读。
FEATURED_PROBE_PLATFORMS: frozenset[str] = frozenset({"bilibili"})

_BILI_REPLY_API = "https://api.bilibili.com/x/v2/reply/main"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT_S = 15.0

# 匿名小请求，不涉及账号软封，间隔比评论监控（默认 5–15s）短得多；仍带抖动，
# 避免对同一接口打出等间隔的机器节拍。
_DELAY_MIN_S = 1.0
_DELAY_MAX_S = 2.5

#: 连续失败这么多次就熔断（本实例后续 check 直接返回 None，不再发请求）。
_MAX_CONSECUTIVE_FAILURES = 3

# B 站业务码里属于「风控 / 限流」的那几个 —— 计入熔断。其余非 0 码（12002 评论区
# 已关闭、-404 视频不存在……）是单条视频自身的状态，不代表探测通道坏了。
_BILI_RISK_CODES = frozenset({-352, -401, -403, -412, -509, -799})

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"/av(\d+)", re.IGNORECASE)

# ── BV → aid（离线换算，省掉一次 /x/web-interface/view 请求）─────────────────
# B 站 2024 版算法（aid 上限 2^51），与官方前端一致。两代 ID 都实测过：
# BV1GJ411x7h7 ↔ av80433022、BV1rAeH6JE5k ↔ av117276078507046。
_BV_XOR_CODE = 23442827791579
_BV_MASK_CODE = 2251799813685247
_BV_BASE = 58
_BV_TABLE = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"


def bilibili_bv_to_aid(bvid: str) -> int | None:
    """``BV1xx411c7mD`` → 数字 aid；格式不对 / 含表外字符返回 None。"""
    if not isinstance(bvid, str) or len(bvid) != 12 or not bvid.startswith("BV1"):
        return None
    chars = list(bvid)
    chars[3], chars[9] = chars[9], chars[3]
    chars[4], chars[7] = chars[7], chars[4]
    acc = 0
    for ch in chars[3:]:
        idx = _BV_TABLE.find(ch)
        if idx < 0:
            return None
        acc = acc * _BV_BASE + idx
    aid = (acc & _BV_MASK_CODE) ^ _BV_XOR_CODE
    return aid if aid > 0 else None


def _bilibili_aid_from_url(video_url: str) -> int | None:
    m = _BV_RE.search(video_url or "")
    if m:
        return bilibili_bv_to_aid(m.group(1))
    m = _AV_RE.search(video_url or "")
    return int(m.group(1)) if m else None


def _default_session() -> Any:
    # 与评论适配器同款 TLS 指纹伪装；不带 Cookie —— 探测走匿名。
    from curl_cffi import requests as cc_requests

    session = cc_requests.Session(impersonate="chrome120")
    session.headers.update({
        "User-Agent": _USER_AGENT,
        "Origin": "https://www.bilibili.com",
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return session


class FeaturedProber:
    """一轮预筛用一个实例：复用同一个 HTTP 会话 + 自带节流与熔断。

    不是线程安全的 —— runner 单线程逐视频调用，用完 ``close()``（或 ``with``）。
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] | None = None,
        pacer: RequestPacer | None = None,
    ) -> None:
        self._session_factory = session_factory or _default_session
        self._pacer = pacer or RequestPacer(delay_min=_DELAY_MIN_S, delay_max=_DELAY_MAX_S)
        self._session: Any = None
        self._failures = 0

    def __enter__(self) -> "FeaturedProber":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def tripped(self) -> bool:
        """连续失败已达上限：后续 check 不再发请求，调用方可以提前收工。"""
        return self._failures >= _MAX_CONSECUTIVE_FAILURES

    def close(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.debug("[featured-probe] session close failed", exc_info=True)

    def check(self, platform: str, video_url: str) -> bool | None:
        """True = 评论区开启了精选后可见；False = 没开；None = 不知道（不支持的
        平台 / URL 解析不出 ID / 请求失败 / 已熔断）—— None 一律按「不排除」处理。"""
        if platform not in FEATURED_PROBE_PLATFORMS or self.tripped:
            return None
        aid = _bilibili_aid_from_url(video_url)
        if aid is None:
            logger.info("[featured-probe] no aid in url=%s", (video_url or "")[:80])
            return None
        verdict, channel_ok = self._check_bilibili(aid)
        if not channel_ok:
            # B 站对匿名请求有随机风控抽检（实测偶发 code=-352，紧接着重试就过）。
            # 单次偶发失败不该让精选视频漏网 —— 重试一次（仍过 pacer，自带退避），
            # 两次都不行才计一次失败。
            verdict, channel_ok = self._check_bilibili(aid)
        if channel_ok:
            self._failures = 0
        else:
            self._failures += 1
            if self.tripped:
                logger.warning(
                    "[featured-probe] %d consecutive failures — probe disabled for this pass",
                    self._failures,
                )
        return verdict

    def _check_bilibili(self, aid: int) -> tuple[bool | None, bool]:
        """→ (verdict, channel_ok)。channel_ok=False 才计入熔断。"""
        try:
            if self._session is None:
                self._session = self._session_factory()
            self._pacer.wait()
            resp = self._session.get(
                _BILI_REPLY_API,
                params={"oid": aid, "type": 1, "mode": 3, "next": 0, "ps": 1},
                timeout=_TIMEOUT_S,
            )
            if resp.status_code != 200 or resp.text.lstrip().startswith("<"):
                logger.info("[featured-probe] bilibili aid=%s HTTP %s", aid, resp.status_code)
                return None, False
            body = resp.json()
        except Exception as e:  # noqa: BLE001 — 探测失败一律 fail-open
            logger.info("[featured-probe] bilibili aid=%s request failed: %s", aid, e)
            return None, False
        if not isinstance(body, dict):
            return None, False
        code = body.get("code")
        if code != 0:
            logger.info("[featured-probe] bilibili aid=%s code=%s", aid, code)
            return None, code not in _BILI_RISK_CODES
        return featured_only_from_reply_data(body.get("data")), True
