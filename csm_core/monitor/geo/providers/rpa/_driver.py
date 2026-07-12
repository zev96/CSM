"""规格驱动的 RPA per-keyword 流程(三站统一;差异全在 SiteSpec)。

只做「在一个已开好、已登录的 page 上,对单个关键词跑一轮采集」——不管浏览器
生命周期(由 provider.session 负责开/关一次)。每轮先 page.goto 回首页重置会话,
避免复用浏览器时上一关键词的上下文污染本轮(致命修复①)。
"""
from __future__ import annotations
import logging
import threading
from typing import Any

from csm_core.monitor.base import maybe_cancel
from csm_core.monitor.geo.models import GeoAnswer
from csm_core.monitor.geo.providers.rpa import _flow
from csm_core.monitor.geo.providers.rpa.sites import SiteSpec

logger = logging.getLogger(__name__)


_SALVAGE_MIN_CHARS = 80   # 验尸阈值:超时但答案已 ≥ 此长度 = 慢站/睡眠唤醒下其实已出完整答案,当成功用(GEO 答案都长,空/失败仅几字)


def run_one_keyword(page: Any, spec: SiteSpec, keyword: str, *, web_search: bool,
                    cancel_token: "threading.Event | None", logged_in: bool,
                    retry: int = 1) -> GeoAnswer:
    if not logged_in:
        return GeoAnswer(platform=spec.platform, keyword=keyword, status="blocked",
                         error=spec.login_blocked_msg)
    attempt = 0
    while True:
        # 会话重置(fix #1):回首页 →(有新建按钮的站)开干净会话,清掉上一关键词上下文。
        page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
        if spec.new_chat_sel:
            _flow.start_new_chat(page, new_chat_sel=spec.new_chat_sel, answer_sel=spec.answer_sel)
            if spec.post_new_chat_wait_ms:
                page.wait_for_timeout(spec.post_new_chat_wait_ms)
        maybe_cancel(cancel_token)
        if spec.deep_think:
            _flow.enable_toggle_by_text(page, text="深度思考")
        if web_search and spec.web_toggle_sel:
            _flow.ensure_web_toggle(page, toggle_sel=spec.web_toggle_sel, want_on=True)
        if web_search and spec.tool_web_search:
            _flow.enable_tool_web_search(page, tool_sel=spec.tool_web_search[0],
                                         item_text=spec.tool_web_search[1])
        maybe_cancel(cancel_token)
        _flow.submit_query(page, composer_sel=spec.composer_sel, send_sel=spec.send_sel, text=keyword)
        done_pred = _flow.make_done_predicate(page, generating_sel=spec.generating_sel,
                                              answer_sel=spec.answer_sel)
        try:
            _flow.wait_stream_done(page, done_predicate=done_pred, idle_ms=1500,
                                   timeout_s=spec.stream_timeout_s, cancel_token=cancel_token,
                                   length_fn=lambda: _flow.answer_text_len(page, spec.answer_sel))
            break                                             # 正常完成
        except (TimeoutError, _flow.StreamInterrupted) as e:
            interrupted = isinstance(e, _flow.StreamInterrupted)
            # 验尸:抓内容,答案已够长 → 慢站/睡眠唤醒时答案其实已完整,当成功用
            # (直接抛会丢弃完整答案 + 触发无谓 retry)。
            try:
                salvaged = _flow.extract_answer_text(page.content(), container_sel=spec.answer_sel)
            except Exception:
                salvaged = ""
            if len(salvaged) >= _SALVAGE_MIN_CHARS:
                logger.info("[geo-rpa][%s] kw=%s %s 但答案已 %d 字,验尸救回",
                            spec.platform, keyword, type(e).__name__, len(salvaged))
                break
            if interrupted or attempt >= retry:               # 中断不 retry;retry 用尽 → 抛
                raise
            attempt += 1
            logger.info("[geo-rpa][%s] kw=%s 超时且答案不足(%d字),第 %d 次重试",
                        spec.platform, keyword, len(salvaged), attempt)
            maybe_cancel(cancel_token)
    # ── 抽取(正常完成 or 验尸救回)──
    html = page.content()
    answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
    # 信源三分支互斥(sites.py 里三站 toolcall_sel/source_text_sel 无一同设);web_toggle_sel
    # 与 deep_think 亦不同现——将来某 spec 同设时需重排本段/上面的开关段。
    if spec.toolcall_sel:                 # Kimi:点开「搜索网页」toolcall 再全页抓 <a>
        _flow.expand_search_toolcalls(page, toolcall_sel=spec.toolcall_sel)
        html = page.content()
        cites = _flow.extract_citations(html, container_sel=None, exclude_hosts=spec.exclude_hosts)
    elif spec.source_text_sel:            # 元宝:COT 里 name-only 信源(无 URL)
        cites = _flow.parse_source_items(html, item_sel=spec.source_text_sel)
    else:                                 # DeepSeek:答案容器内 <a>
        cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                        exclude_hosts=spec.exclude_hosts)
    logger.info("[geo-rpa][%s] kw=%s answer_len=%d cite_n=%d",
                spec.platform, keyword, len(answer), len(cites))
    return GeoAnswer(platform=spec.platform, keyword=keyword, answer_text=answer,
                     citations=cites, status="ok" if answer else "empty",
                     raw={"html_len": len(html), "cite_n": len(cites)})
