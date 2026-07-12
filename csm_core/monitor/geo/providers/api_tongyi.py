"""通义千问 provider —— DashScope 原生 generation 端点 + enable_search。

信源走 output.search_info.search_results[]（含 url/title/site_name）。
key 复用现有 LLM provider 的 'qwen' keyring 项（read_api_key("qwen")）。
"""
from __future__ import annotations
import logging
import threading
import httpx

from csm_core.config import read_api_key, get_config
from csm_core.monitor.base import maybe_cancel
from ..models import GeoAnswer, Citation

logger = logging.getLogger(__name__)

_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

import threading as _threading
import time as _time

_client_lock = _threading.Lock()
_client: "httpx.Client | None" = None


def _shared_client() -> httpx.Client:
    """进程内复用一个 httpx.Client(连接池 + 线程安全)。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client()
    return _client


def _post_retry_429(url: str, *, headers: dict, json: dict, timeout) -> httpx.Response:
    """采集调用:仅对 429 / 连接建立失败重试一次(未计费)。已生成响应绝不重发。"""
    client = _shared_client()
    for attempt in range(2):
        try:
            r = client.post(url, headers=headers, json=json, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == 0:
                _time.sleep(1.0)
                continue
            raise
        if r.status_code == 429 and attempt == 0:
            try:
                delay = min(float(r.headers.get("Retry-After", "1") or 1), 10.0)
            except (TypeError, ValueError):
                delay = 1.0
            _time.sleep(max(0.0, delay))
            continue
        return r
    return r  # pragma: no cover


def parse_tongyi_response(raw: dict) -> tuple[str, list[Citation]]:
    out = raw.get("output") or {}
    # answer：result_format=message → output.choices[0].message.content；
    # 兼容 output.text（result_format=text）。
    text = ""
    choices = out.get("choices") or []
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    if not text:
        text = out.get("text") or ""
    cits: list[Citation] = []
    for sr in (out.get("search_info") or {}).get("search_results") or []:
        url = sr.get("url") or ""
        if not url:
            continue
        title = sr.get("title") or ""
        site = sr.get("site_name") or ""
        cits.append(Citation(url=url, title=f"{title} - {site}".strip(" -") if site else title))
    return text, cits


class TongyiProvider:
    platform = "tongyi"
    mode = "api"

    def __init__(self, *, model: str | None = None, timeout: float = 120.0) -> None:
        # Only the model is configurable. _URL stays on the NATIVE DashScope
        # generation endpoint (different from the qwen compatible-mode base
        # URL in base_urls["qwen"]), so we deliberately do NOT read base_urls.
        self._model = model or get_config().default_model.get("qwen") or "qwen-plus"
        self._timeout = timeout

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        key = read_api_key("qwen")
        if not key:
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error="通义(qwen) API key 未配置")
        body = {
            "model": self._model,
            "input": {"messages": [{"role": "user", "content": keyword}]},
            "parameters": {"enable_search": bool(web_search),
                           "search_options": {"enable_source": True, "enable_citation": True},
                           "result_format": "message"},
        }
        try:
            r = _post_retry_429(
                _URL,
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=self._timeout, pool=10.0),
            )
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
        # raw-logging（silent-failure 防御）
        logger.info("[geo.tongyi] kw=%s http=%d len=%d first200=%s",
                    keyword, r.status_code, len(r.text), r.text[:200].replace("\n", " "))
        if r.status_code >= 400:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"http {r.status_code}: {r.text[:300]}", raw={"status": r.status_code})
        # FIX 1: guard against non-JSON 200
        try:
            raw = r.json()
        except Exception:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"非 JSON 响应 (http {r.status_code}): {r.text[:200]}")
        # FIX 2: DashScope app-level errors (HTTP 200 + code != Success)
        code = raw.get("code") if isinstance(raw, dict) else None
        if code and code not in ("Success", "200", 200):
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"dashscope error {code}: {raw.get('message', '')}", raw=raw)
        # FIX 2: content filter — finish_reason == "sensitive" → blocked
        fr = (((raw.get("output") or {}).get("choices") or [{}])[0]).get("finish_reason")
        if fr == "sensitive":
            return GeoAnswer(platform=self.platform, keyword=keyword, status="blocked",
                             error="内容被通义安全过滤", raw=raw)
        text, cits = parse_tongyi_response(raw)
        status = "ok" if text else "empty"
        return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=text,
                         citations=cits, raw=raw, status=status)
