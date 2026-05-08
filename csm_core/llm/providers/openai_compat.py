"""Shared OpenAI-compatible Chat Completions client.

OpenAI, DeepSeek, Qwen (DashScope compatible-mode), and Gemini's
OpenAI-compat endpoint all share the same wire format. One client
class, four base URLs.

Streaming by design
-------------------
``complete()`` always opens an SSE stream (``stream=True``) and concatenates
the deltas. Non-streaming requests count the *whole* generation against the
HTTP read timeout, so polish-sized prompts on slower models (qwen-plus,
DeepSeek-V3 reasoning, etc.) commonly fail with ``ReadTimeout`` even
though the LLM is making progress. With streaming, the read timeout
becomes "max gap between chunks" — as long as the model keeps emitting
tokens we never time out, and we still surface a real timeout when the
backend genuinely stalls.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


# Only retry on truly transient network failures. ReadTimeout is NOT in this
# set on purpose — if a polish/title call takes longer than ``timeout``, the
# user's timeout is too short and retrying just multiplies the wait before
# they see the error. Connect-level failures (DNS hiccup, TCP reset, h2/h11
# protocol error) are the cases where a quick second try actually helps.
_TRANSIENT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
)


@dataclass
class OpenAICompatClient:
    api_key: str
    model: str
    base_url: str
    timeout: float = 180.0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(_TRANSIENT_ERRORS),
        reraise=True,
    )
    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        # Split timeout phases — connect should fail fast (real network
        # issue); read becomes the inter-chunk gap budget for the SSE
        # stream below, which is much more forgiving than a whole-response
        # timeout for slow LLMs.
        timeout = httpx.Timeout(
            connect=10.0,
            read=self.timeout,
            write=self.timeout,
            pool=10.0,
        )
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
        }
        chunks: list[str] = []
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, headers=headers, json=payload) as resp:
                # On error the body is a normal JSON error envelope, not an
                # SSE stream. Read it to enrich raise_for_status's message,
                # otherwise the user sees a bare HTTPStatusError with no
                # provider-side hint about what went wrong (model not found,
                # invalid api_key, etc.).
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code} from {self.base_url}: {body[:500]}",
                        request=resp.request,
                        response=resp,
                    )
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            break
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        # Some providers send keep-alive comments or
                        # non-JSON lines — skip rather than abort.
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        chunks.append(piece)
        return "".join(chunks)
