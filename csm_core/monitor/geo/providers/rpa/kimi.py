"""Kimi RPA provider —— 驱动 kimi.com 网页采集联网回答+来源。

阶段 2 确认 Moonshot API 的 $web_search 不回信源（annotations 恒 0），故 Kimi
改走 RPA。错误纪律同 DeepSeek：未登录→blocked；超时/异常→error；空→empty；
取消（用户 Stop）上抛、不算失败。
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
_SPEC = SITES["kimi"]


class KimiProvider:
    platform = "kimi"
    mode = "rpa"

    @contextlib.contextmanager
    def session(self, *, web_search: bool = True,
                cancel_token: "threading.Event | None" = None, retry: int = 1):
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
        maybe_cancel(cancel_token)
        try:
            with self.session(web_search=web_search, cancel_token=cancel_token) as query_one:
                return query_one(keyword)
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo-rpa][kimi] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
