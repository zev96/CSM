"""DeepSeek RPA provider —— 驱动 chat.deepseek.com 网页采集联网回答+来源。

错误纪律：未登录→blocked；超时/浏览器异常→error；空回答→empty。provider
绝不让异常冒泡（adapter 虽也兜，但 provider 自身要稳）。选择器全在 sites.py，
线上漂移改那里。
"""
from __future__ import annotations
import logging
import threading

from csm_core.monitor.base import maybe_cancel, is_cancelled
from csm_core.monitor.geo.models import GeoAnswer
from csm_core.monitor.geo.providers.rpa import _flow
from csm_core.monitor.geo.providers.rpa._session import rpa_page
from csm_core.monitor.geo.providers.rpa.sites import SITES

logger = logging.getLogger(__name__)
_SPEC = SITES["deepseek"]


class DeepSeekProvider:
    platform = "deepseek"
    mode = "rpa"

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        spec = _SPEC
        try:
            with rpa_page(self.platform, headless=False) as page:
                page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                if not _flow.detect_login(page, logged_in_sel=spec.logged_in_sel,
                                          logged_out_sel=spec.logged_out_sel):
                    return GeoAnswer(platform=self.platform, keyword=keyword,
                                     status="blocked", error="DeepSeek 未登录，请在设置中登录")
                if web_search and spec.web_toggle_sel:
                    _flow.ensure_web_toggle(page, toggle_sel=spec.web_toggle_sel, want_on=True)
                _flow.submit_query(page, composer_sel=spec.composer_sel,
                                   send_sel=spec.send_sel, text=keyword)

                done_pred = _flow.make_done_predicate(
                    page, generating_sel=spec.generating_sel, answer_sel=spec.answer_sel)
                _flow.wait_stream_done(page, done_predicate=done_pred, idle_ms=1500,
                                       timeout_s=120.0, cancel_token=cancel_token)
                html = page.content()
            answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
            cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                            exclude_hosts=spec.exclude_hosts)
            logger.info("[geo-rpa][deepseek] kw=%s answer_len=%d cite_n=%d",
                        keyword, len(answer), len(cites))
            return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=answer,
                             citations=cites, status="ok" if answer else "empty",
                             raw={"html_len": len(html), "cite_n": len(cites)})
        except Exception as e:
            if is_cancelled(e):   # 用户 Stop 不是采集失败——上抛，让 adapter/loop 干净中止
                raise
            logger.exception("[geo-rpa][deepseek] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error=str(e))
