"""LLMClient protocol + factory."""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None = None,
    ) -> str:
        """Run an LLM completion.

        ``temperature`` is optional — pass a value in [0.0, 2.0] to
        override the provider's default sampling temperature for this one
        call (used e.g. by title generation where we want lower variance
        than polish's defaults). When ``None`` the provider falls back to
        whatever temperature it ships with, which preserves the legacy
        behaviour for every existing call-site.
        """
        ...


def make_client(*, provider: str, **kwargs) -> LLMClient:
    if provider == "mock":
        from .providers.mock import MockClient
        return MockClient(**kwargs)
    if provider == "anthropic":
        from .providers.anthropic import AnthropicClient
        return AnthropicClient(**kwargs)
    if provider == "deepseek":
        from .providers.deepseek import DeepSeekClient
        return DeepSeekClient(**kwargs)
    if provider == "openai":
        from .providers.openai import OpenAIClient
        return OpenAIClient(**kwargs)
    if provider == "gemini":
        from .providers.gemini import GeminiClient
        return GeminiClient(**kwargs)
    if provider == "qwen":
        from .providers.qwen import QwenClient
        return QwenClient(**kwargs)
    if provider == "kimi":
        from .providers.kimi import KimiClient
        return KimiClient(**kwargs)
    if provider == "doubao":
        from .providers.doubao import DoubaoClient
        return DoubaoClient(**kwargs)
    raise ValueError(f"unknown provider: {provider}")
