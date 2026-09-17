"""小红书评论留存 —— 本地(浏览器 / 直连)路径不存在,本模块只做两件事:

1. ``_extract_note_id``:链接 → 笔记 ID。与其它平台的 ``_extract_video_id`` 同位置,
   TikHub 适配器(``csm_core.monitor.tikhub.build_api_adapters``)复用它。支持
   ``xiaohongshu.com/explore/{id}`` / ``discovery/item/{id}`` 长链、``xhslink.com`` /
   ``xhslink.cn`` 分享短链(跟随重定向展开)、以及整段粘贴的 App 分享文案(从中挑出 URL)。
2. 注册表占位:小红书 web 接口全程 x-s/x-t 签名 + xsec_token,没有可用的本地免费实现,
   评论留存监控固定走 TikHub API —— ``monitor_loop`` 对本类型忽略「抓取数据源」开关
   (见 ``monitor_loop.API_ONLY_TYPES``)。本适配器只在 TikHub 适配器缺席时兜底,直接
   判 failed 并提示去配置 Key,绝不尝试抓取。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..base import MonitorResult, MonitorTask
from ._comment_common import fail_result

logger = logging.getLogger(__name__)

# 笔记 ID 固定 24 位十六进制。
_NOTE_ID_PATTERNS = [
    re.compile(r"/explore/([0-9a-fA-F]{24})"),
    re.compile(r"/discovery/item/([0-9a-fA-F]{24})"),
    re.compile(r"/item/([0-9a-fA-F]{24})"),
    re.compile(r"[?&]note_id=([0-9a-fA-F]{24})"),
    re.compile(r"/notes?/([0-9a-fA-F]{24})"),
]
_BARE_NOTE_ID = re.compile(r"^[0-9a-fA-F]{24}$")
_SHORT_HOSTS = ("xhslink.com", "xhslink.cn")

NO_LOCAL_PATH_MESSAGE = (
    "小红书评论留存仅支持 TikHub API 抓取，请在「设置 › 监测 › 抓取数据源」配置 TikHub API Key"
)


class XiaohongshuCommentAdapter:
    platform = "xiaohongshu_comment"

    @staticmethod
    def _extract_note_id(session: Any, raw_url: str) -> tuple[str | None, str]:
        """(note_id | None, "")。session 只在需要展开短链时使用。"""
        text = (raw_url or "").strip()
        if _BARE_NOTE_ID.match(text):
            return text.lower(), ""
        url = text
        if not url.startswith("http"):
            m = re.search(r"(https?://[^\s，。！？、]+)", url)
            if not m:
                return None, "could not find a URL in the input"
            url = m.group(1).rstrip("，。！？、")
        for pattern in _NOTE_ID_PATTERNS:
            m = pattern.search(url)
            if m:
                return m.group(1).lower(), ""
        if any(h in url for h in _SHORT_HOSTS) and session is not None:
            try:
                resp = session.get(url, allow_redirects=True, timeout=15)
                final = str(getattr(resp, "url", "") or "")
                for pattern in _NOTE_ID_PATTERNS:
                    m = pattern.search(final)
                    if m:
                        return m.group(1).lower(), ""
            except Exception as e:  # noqa: BLE001 — 短链展开失败按解析失败处理
                logger.info("xiaohongshu short-link expansion failed: %s", type(e).__name__)
        return None, "could not extract note_id from URL"

    def fetch(self, task: MonitorTask, cancel_token=None, progress_cb=None, **_) -> MonitorResult:
        return fail_result(task, "local", NO_LOCAL_PATH_MESSAGE)


ADAPTER = XiaohongshuCommentAdapter()
