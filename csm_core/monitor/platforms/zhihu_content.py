"""可选全文匹配用的知乎正文抓取 helper（best-effort）。

只支持 Article / Answer（其它类型返回 None 回退摘要）。curl_cffi
impersonate chrome120 + 复用 zhihu_question 的 Cookie 池。任意失败 → None。
"""
from __future__ import annotations
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_ENDPOINTS = {
    "Article": "https://www.zhihu.com/api/v4/articles/{cid}?include=content",
    "Answer": "https://www.zhihu.com/api/v4/answers/{cid}?include=content",
}


def _cc_get(url: str, **kwargs: Any) -> Any:
    """curl_cffi GET（indirection 便于单测 monkeypatch）。"""
    from curl_cffi import requests as cc_requests
    return cc_requests.get(url, impersonate="chrome120", timeout=15, **kwargs)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def fetch_text(content_type: str, content_id: str, *, cookie_store: Any = None) -> str | None:
    """抓一条知乎内容正文纯文本。失败 / 不支持的类型 → None。"""
    tmpl = _ENDPOINTS.get(content_type)
    if not tmpl or not content_id:
        return None
    cookies = {}
    if cookie_store is not None:
        cred = cookie_store.pick()
        if cred and cred.cookies_text:
            for piece in cred.cookies_text.split(";"):
                if "=" in piece:
                    k, _, v = piece.partition("=")
                    cookies[k.strip()] = v.strip()
    try:
        resp = _cc_get(tmpl.format(cid=content_id), cookies=cookies)
    except Exception as e:
        logger.info("zhihu_content fetch raised: %s", e)
        return None
    if resp.status_code != 200:
        return None
    try:
        content = (resp.json() or {}).get("content") or ""
    except Exception:
        return None
    text = _strip_tags(content)
    return text or None
