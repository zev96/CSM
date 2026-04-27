"""LLMClient protocol + factory."""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


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
    raise ValueError(f"unknown provider: {provider}")
