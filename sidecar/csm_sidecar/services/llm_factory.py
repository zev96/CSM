"""Build an LLMClient from current config + keyring.

Single source of truth for "which provider, which model, which key" —
every sidecar route that needs a client goes through this so behaviour
stays consistent.
"""
from __future__ import annotations

from typing import Any

from csm_core.config import get_secret
from csm_core.llm.client import LLMClient, make_client

from . import config_service


class LLMConfigError(ValueError):
    """Raised when the resolved config can't produce a valid client."""


def build_client(
    *,
    provider: str | None = None,
    model: str | None = None,
) -> LLMClient:
    """Resolve a usable :class:`LLMClient`.

    Resolution order, per field:

    * ``provider`` — call arg → ``AppConfig.default_provider``
    * ``api_key`` — OS keyring → ``AppConfig.api_keys[provider]``
    * ``model`` — call arg → ``AppConfig.default_model[provider]`` → provider default
    * ``base_url`` — ``AppConfig.base_urls[provider]`` → provider default
    """
    cfg = config_service.load()
    p = provider or cfg.default_provider

    if p is None:
        raise LLMConfigError("尚未选择默认 provider，请先在 设置 中配置")

    if p == "mock":
        return make_client(provider="mock")

    api_key = get_secret(p) or cfg.api_keys.get(p, "")
    if not api_key:
        raise LLMConfigError(
            f"no API key configured for provider '{p}' — "
            f"set one via POST /api/keyring/{p} or AppConfig.api_keys"
        )

    kwargs: dict[str, Any] = {"api_key": api_key}
    chosen_model = model or cfg.default_model.get(p)
    if chosen_model:
        kwargs["model"] = chosen_model
    chosen_base = cfg.base_urls.get(p)
    if chosen_base:
        kwargs["base_url"] = chosen_base
    if cfg.timeout_seconds and cfg.timeout_seconds > 0:
        # Anthropic dataclass has no `timeout`; openai_compat does. Pass
        # only when the provider accepts it — make_client raises TypeError
        # for unknown kwargs, so we filter by provider.
        if p in ("openai", "deepseek", "gemini", "qwen", "openai_compat"):
            kwargs["timeout"] = float(cfg.timeout_seconds)

    return make_client(provider=p, **kwargs)
