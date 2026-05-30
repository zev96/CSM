"""通义千问 provider —— DashScope 原生 generation 端点 + enable_search。

信源走 output.search_info.search_results[]（含 url/title/site_name）。
key 复用现有 LLM provider 的 'qwen' keyring 项（read_api_key("qwen")）。
"""
from __future__ import annotations
import logging
import httpx

from csm_core.config import read_api_key
from ..models import GeoAnswer, Citation

logger = logging.getLogger(__name__)

_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"


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

    def __init__(self, *, model: str = "qwen-plus", timeout: float = 120.0) -> None:
        self._model = model
        self._timeout = timeout

    def query(self, keyword, *, web_search=True, cancel_token=None) -> GeoAnswer:
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
            r = httpx.post(_URL, headers={"Authorization": f"Bearer {key}"},
                           json=body, timeout=self._timeout)
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
        # raw-logging（silent-failure 防御）
        logger.info("[geo.tongyi] kw=%s http=%d len=%d first200=%s",
                    keyword, r.status_code, len(r.text), r.text[:200].replace("\n", " "))
        if r.status_code >= 400:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"http {r.status_code}: {r.text[:300]}", raw={"status": r.status_code})
        raw = r.json()
        text, cits = parse_tongyi_response(raw)
        status = "ok" if text else "empty"
        return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=text,
                         citations=cits, raw=raw, status=status)
