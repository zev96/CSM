"""Kimi(Moonshot) provider —— OpenAI 兼容 + $web_search builtin。

信源走 choices[0].message.annotations[].url_citation。
key 用 keyring 'kimi' 项（read_api_key("kimi")）。

$web_search 是 server-side builtin：首个响应若 finish_reason=="tool_calls"，
把 tool_call 的 arguments 原样回传作为 tool 结果，模型续写最终答案（最多
max_tool_rounds 轮）。
"""
from __future__ import annotations
import logging
import threading
import httpx

from csm_core.config import read_api_key
from csm_core.monitor.base import maybe_cancel
from ..models import GeoAnswer, Citation

logger = logging.getLogger(__name__)

_URL = "https://api.moonshot.cn/v1/chat/completions"
_SEARCH_TOOL = {"type": "builtin_function", "function": {"name": "$web_search"}}


def parse_kimi_response(raw: dict) -> tuple[str, list[Citation]]:
    choices = raw.get("choices") or []
    if not choices:
        return "", []
    msg = choices[0].get("message") or {}
    text = msg.get("content") or ""
    cits: list[Citation] = []
    for ann in msg.get("annotations") or []:
        uc = ann.get("url_citation") or {}
        url = uc.get("url") or ""
        if url:
            cits.append(Citation(url=url, title=uc.get("title") or ""))
    return text, cits


class KimiProvider:
    platform = "kimi"
    mode = "api"

    def __init__(self, *, model: str = "moonshot-v1-8k", timeout: float = 120.0,
                 max_tool_rounds: int = 3) -> None:
        self._model = model
        self._timeout = timeout
        self._max_rounds = max_tool_rounds

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        # Pre-call cancel check
        maybe_cancel(cancel_token)
        key = read_api_key("kimi")
        if not key:
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error="Kimi(moonshot) API key 未配置")
        messages: list[dict] = [{"role": "user", "content": keyword}]
        tools = [_SEARCH_TOOL] if web_search else None
        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=self._timeout,
                                      write=self._timeout, pool=10.0)
            ) as client:
                for _ in range(self._max_rounds):
                    # Cancel check at top of each tool-round iteration
                    maybe_cancel(cancel_token)
                    body: dict = {"model": self._model, "messages": messages}
                    if tools:
                        body["tools"] = tools
                    r = client.post(
                        _URL,
                        headers={"Authorization": f"Bearer {key}"},
                        json=body,
                    )
                    # raw-logging（silent-failure 防御）
                    logger.info("[geo.kimi] kw=%s http=%d len=%d first200=%s",
                                keyword, r.status_code, len(r.text),
                                r.text[:200].replace("\n", " "))
                    if r.status_code >= 400:
                        return GeoAnswer(platform=self.platform, keyword=keyword,
                                         status="error",
                                         error=f"http {r.status_code}: {r.text[:300]}")
                    # Guard against non-JSON 200 (proxy/captcha could inject HTML)
                    try:
                        raw = r.json()
                    except Exception:
                        return GeoAnswer(platform=self.platform, keyword=keyword,
                                         status="error",
                                         error=f"非 JSON 响应 (http {r.status_code}): {r.text[:200]}")
                    # App-level error detection: Moonshot returns {"error": {...}} envelopes
                    if isinstance(raw, dict) and raw.get("error"):
                        err_obj = raw["error"]
                        msg_str = (err_obj.get("message") if isinstance(err_obj, dict)
                                   else str(err_obj))
                        return GeoAnswer(platform=self.platform, keyword=keyword,
                                         status="error",
                                         error=f"moonshot error: {msg_str}", raw=raw)
                    choice = (raw.get("choices") or [{}])[0]
                    finish = choice.get("finish_reason")
                    msg_obj = choice.get("message") or {}
                    if finish == "tool_calls":
                        # Echo $web_search arguments back as tool result (server-side execution)
                        messages.append(msg_obj)
                        for tc in msg_obj.get("tool_calls") or []:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id"),
                                "name": (tc.get("function") or {}).get("name"),
                                "content": (tc.get("function") or {}).get("arguments") or "{}",
                            })
                        continue
                    text, cits = parse_kimi_response(raw)
                    return GeoAnswer(platform=self.platform, keyword=keyword,
                                     answer_text=text, citations=cits, raw=raw,
                                     status="ok" if text else "empty")
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error=str(e))
        # Exhausted max_tool_rounds without a final answer
        return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                         error="超过 $web_search 工具轮次上限")
