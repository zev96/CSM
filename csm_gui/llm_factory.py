"""Build LLMClient from AppConfig + provider name. Shared by GenerateWorker and PolishWorker."""
from __future__ import annotations
from csm_core.llm.client import LLMClient, make_client
from .config import AppConfig


def build_client(cfg: AppConfig, provider: str) -> LLMClient:
    kwargs: dict[str, object] = {}
    if provider == "mock":
        kwargs["response"] = "# (mock polished output)"
    else:
        kwargs["api_key"] = cfg.api_keys.get(provider, "")
        default = cfg.default_model.get(provider)
        if default:
            kwargs["model"] = default
        base_url = cfg.base_urls.get(provider)
        if base_url:
            kwargs["base_url"] = base_url
        # Anthropic uses the official SDK and doesn't accept ``timeout`` as
        # a keyword on its dataclass; the OpenAI-compatible providers all
        # do. Limit the kwarg to those.
        if cfg.timeout_seconds and provider in {"deepseek", "openai", "gemini", "qwen"}:
            kwargs["timeout"] = float(cfg.timeout_seconds)
    return make_client(provider=provider, **kwargs)
