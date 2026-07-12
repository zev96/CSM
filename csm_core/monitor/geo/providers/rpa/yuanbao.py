"""腾讯元宝 RPA provider —— 驱动 yuanbao.tencent.com 网页采集联网回答+来源。

登录走 QQ/微信扫码（用户在有头窗扫码，持久档存会话）。错误纪律同 DeepSeek：
未登录→blocked；超时/异常→error；空→empty；取消（用户 Stop）上抛、不算失败。
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
_SPEC = SITES["yuanbao"]


class YuanbaoProvider:
    platform = "yuanbao"
    mode = "rpa"

    @contextlib.contextmanager
    def session(self, *, web_search: bool = True,
                cancel_token: "threading.Event | None" = None):
        spec = _SPEC
        with rpa_page(self.platform, headless=False) as page:
            page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
            logged_in = _flow.wait_login_ready(page, logged_in_sel=spec.logged_in_sel,
                                               logged_out_sel=spec.logged_out_sel)

            def query_one(keyword: str) -> GeoAnswer:
                return _driver.run_one_keyword(page, spec, keyword, web_search=web_search,
                                               cancel_token=cancel_token, logged_in=logged_in)
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
            logger.exception("[geo-rpa][yuanbao] query failed kw=%s", keyword)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
