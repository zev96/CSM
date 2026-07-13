"""DeepSeek RPA provider —— 驱动 chat.deepseek.com 网页采集联网回答+来源。

错误纪律：未登录→blocked；超时/浏览器异常→error；空回答→empty。provider
绝不让异常冒泡（adapter 虽也兜，但 provider 自身要稳）。选择器全在 sites.py，
线上漂移改那里。
"""
from __future__ import annotations
import contextlib
import logging
import threading

from csm_core.monitor.base import maybe_cancel, is_cancelled
from csm_core.monitor.geo.models import GeoAnswer
from csm_core.monitor.geo.providers.rpa import _driver, _flow
from csm_core.monitor.geo.providers.rpa._session import rpa_page
from csm_core.monitor.geo.providers.rpa.sites import SITES

logger = logging.getLogger(__name__)
_SPEC = SITES["deepseek"]


class DeepSeekProvider:
    platform = "deepseek"
    mode = "rpa"

    @contextlib.contextmanager
    def session(self, *, web_search: bool = True,
                cancel_token: "threading.Event | None" = None, retry: int = 1):
        """开浏览器 + 登录检查**一次**,yield query_one(keyword) 复用同一 page。"""
        spec = _SPEC
        with rpa_page(self.platform, headless=False) as page:
            page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
            logged_in = _flow.wait_login_ready(page, logged_in_sel=spec.logged_in_sel,
                                               logged_out_sel=spec.logged_out_sel)

            def query_one(keyword: str) -> GeoAnswer:
                return _driver.run_one_keyword(page, spec, keyword, web_search=web_search,
                                               cancel_token=cancel_token, logged_in=logged_in,
                                               retry=retry)
            yield query_one

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        """单发(向后兼容):开一次 session 只问一个关键词。"""
        maybe_cancel(cancel_token)
        try:
            with self.session(web_search=web_search, cancel_token=cancel_token) as query_one:
                return query_one(keyword)
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo-rpa][deepseek] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
