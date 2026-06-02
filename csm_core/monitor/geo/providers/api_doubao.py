"""豆包(火山方舟 Ark)联网 provider —— 走「应用(bot)」端点拿 references。

Ark 普通 /chat/completions 不联网；联网 + 信源走 /api/v3/bots/chat/completions，
model 传用户在控制台建的联网 bot 的 bot_id（配置项 doubao_bot_id）。
key 用 keyring 'doubao' 项（read_api_key("doubao")，与 LLM provider 同 key）。
"""
from __future__ import annotations
import logging
import threading
import httpx

from csm_core.config import read_api_key, get_config
from csm_core.monitor.base import maybe_cancel
from ..models import GeoAnswer, Citation

logger = logging.getLogger(__name__)


def parse_doubao_response(raw: dict) -> tuple[str, list[Citation]]:
    choices = raw.get("choices") or []
    if not choices:
        return "", []
    msg = choices[0].get("message") or {}
    text = msg.get("content") or ""
    cits: list[Citation] = []
    # references 可能在 message.references 或顶层（按探针确认）；两处都看。
    refs = msg.get("references") or raw.get("references") or []
    for ref in refs:
        url = (ref or {}).get("url") or ""
        if not url:
            continue
        title = ref.get("title") or ""
        site = ref.get("site_name") or ""
        cits.append(Citation(url=url, title=f"{title} - {site}".strip(" -") if site else title))
    return text, cits


class DoubaoProvider:
    platform = "doubao"
    mode = "api"

    def __init__(self, *, bot_id: str | None = None, base_url: str | None = None,
                 timeout: float = 120.0) -> None:
        cfg = get_config()
        self._bot = bot_id or getattr(cfg, "doubao_bot_id", "") or ""
        self._base = base_url or cfg.base_urls.get("doubao") or "https://ark.cn-beijing.volces.com/api/v3"
        self._timeout = timeout

    def query(self, keyword: str, *, web_search: bool = True,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer:
        maybe_cancel(cancel_token)
        key = read_api_key("doubao")
        if not key:
            return GeoAnswer(platform=self.platform, keyword=keyword,
                             status="error", error="豆包(doubao/Ark) API key 未配置")
        if not self._bot:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error="豆包联网需配置 doubao_bot_id（控制台建联网 bot）")
        url = f"{self._base.rstrip('/')}/bots/chat/completions"
        body = {"model": self._bot, "messages": [{"role": "user", "content": keyword}], "stream": False}
        timeout = httpx.Timeout(connect=10.0, read=self._timeout, write=self._timeout, pool=10.0)
        try:
            r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=timeout)
        except httpx.HTTPError as e:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error", error=str(e))
        logger.info("[geo.doubao] kw=%s http=%d len=%d first200=%s",
                    keyword, r.status_code, len(r.text), r.text[:200].replace("\n", " "))
        if r.status_code >= 400:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"http {r.status_code}: {r.text[:300]}", raw={"status": r.status_code})
        try:
            raw = r.json()
        except Exception:
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"非 JSON 响应 (http {r.status_code}): {r.text[:200]}")
        if isinstance(raw, dict) and raw.get("error"):
            err = raw["error"]
            m = err.get("message") if isinstance(err, dict) else str(err)
            return GeoAnswer(platform=self.platform, keyword=keyword, status="error",
                             error=f"ark error: {m}", raw=raw)
        fr = ((raw.get("choices") or [{}])[0]).get("finish_reason")
        if fr in ("content_filter", "sensitive"):
            return GeoAnswer(platform=self.platform, keyword=keyword, status="blocked",
                             error="内容被豆包安全过滤", raw=raw)
        text, cits = parse_doubao_response(raw)
        return GeoAnswer(platform=self.platform, keyword=keyword, answer_text=text,
                         citations=cits, raw=raw, status="ok" if text else "empty")
