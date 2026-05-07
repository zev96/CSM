"""Shared OpenAI-compatible Chat Completions client.

OpenAI, DeepSeek, Qwen (DashScope compatible-mode), and Gemini's
OpenAI-compat endpoint all share the same wire format. One client
class, four base URLs.
"""
from __future__ import annotations
from dataclasses import dataclass
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class OpenAICompatClient:
    api_key: str
    model: str
    base_url: str
    timeout: float = 60.0

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
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
        }
        if temperature is not None:
            payload["temperature"] = temperature
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
