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
    return make_client(provider=provider, **kwargs)
