"""腾讯元宝 RPA provider —— 驱动 yuanbao.tencent.com 网页采集联网回答+来源。

登录走 QQ/微信扫码（用户在有头窗扫码，持久档存会话）。错误纪律同 DeepSeek：
未登录→blocked；超时/异常→error；空→empty；取消（用户 Stop）上抛、不算失败。
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
_SPEC = SITES["yuanbao"]


class YuanbaoProvider:
    platform = "yuanbao"
    mode = "rpa"

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        spec = _SPEC
        try:
            with rpa_page(self.platform, headless=False) as page:
                page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
                if not _flow.wait_login_ready(page, logged_in_sel=spec.logged_in_sel,
                                              logged_out_sel=spec.logged_out_sel):
                    return GeoAnswer(platform=self.platform, keyword=keyword,
                                     status="blocked", error="腾讯元宝 未登录，请在设置中扫码登录")
                # 元宝打开即恢复上次会话 → 先开干净会话，否则会读到上一轮答案。
                if spec.new_chat_sel:
                    _flow.start_new_chat(page, new_chat_sel=spec.new_chat_sel,
                                         answer_sel=spec.answer_sel)
                    page.wait_for_timeout(600)   # 等新会话 composer 渲染就绪再提交
                    maybe_cancel(cancel_token)
                # 用户实测：元宝须开 深度思考 + 联网搜索（工具菜单内）才出参考资料。
                if spec.deep_think:
                    _flow.enable_toggle_by_text(page, text="深度思考")
                if web_search and spec.tool_web_search:
                    _flow.enable_tool_web_search(
                        page, tool_sel=spec.tool_web_search[0],
                        item_text=spec.tool_web_search[1])
                maybe_cancel(cancel_token)
                _flow.submit_query(page, composer_sel=spec.composer_sel,
                                   send_sel=spec.send_sel, text=keyword)
                done_pred = _flow.make_done_predicate(
                    page, generating_sel=spec.generating_sel, answer_sel=spec.answer_sel)
                # 深度思考+联网搜索更慢 → 放宽超时到 180s。
                _flow.wait_stream_done(page, done_predicate=done_pred, idle_ms=1500,
                                       timeout_s=180.0, cancel_token=cancel_token)
                html = page.content()
                answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
                # 元宝信源无 URL（DOM 里全程没有真实来源链接，只有名字/标题）。深度思考 COT
                # 里「搜到的 N 篇资料」是 in-page 的（无需点击/hover），比 hover-gated 的「源」
                # 抽屉稳得多 → 直接抓 COT 文档标题作 name-only 信源（domain="", 不进域名榜）。
                if spec.source_text_sel:
                    cites = _flow.parse_source_items(html, item_sel=spec.source_text_sel)
                else:
                    cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                                    exclude_hosts=spec.exclude_hosts)
            logger.info("[geo-rpa][yuanbao] kw=%s answer_len=%d cite_n=%d",
                        keyword, len(answer), len(cites))
            return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=answer,
                             citations=cites, status="ok" if answer else "empty",
                             raw={"html_len": len(html), "cite_n": len(cites)})
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo-rpa][yuanbao] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error=str(e))
