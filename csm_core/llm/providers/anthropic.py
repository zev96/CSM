"""Anthropic Claude provider."""
from __future__ import annotations
from dataclasses import dataclass
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class AnthropicClient:
    api_key: str
    model: str = "claude-opus-4-7"
    max_tokens: int = 4096

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def complete(self, *, system: str, user: str) -> str:
        sdk = Anthropic(api_key=self.api_key)
        resp = sdk.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text
