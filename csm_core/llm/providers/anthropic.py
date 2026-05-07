"""Anthropic Claude provider."""
from __future__ import annotations
from dataclasses import dataclass, field
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class AnthropicClient:
    api_key: str
    model: str = "claude-opus-4-7"
    max_tokens: int = 4096
    base_url: str | None = None
    _sdk: Anthropic | None = field(default=None, init=False, repr=False)

    def _client(self) -> Anthropic:
        if self._sdk is None:
            kwargs: dict[str, object] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._sdk = Anthropic(**kwargs)
        return self._sdk

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None = None,
    ) -> str:
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = self._client().messages.create(**kwargs)
        return resp.content[0].text
