"""DeepSeek provider (OpenAI-compatible API)."""
from __future__ import annotations
from dataclasses import dataclass
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class DeepSeekClient:
    api_key: str
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    timeout: float = 60.0

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def complete(self, *, system: str, user: str) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
