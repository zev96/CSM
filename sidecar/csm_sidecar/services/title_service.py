"""Title generation — wraps csm_core.title.generate_titles."""
from __future__ import annotations

from pathlib import Path

from csm_core.title.generator import generate_titles

from . import config_service, llm_factory, vault_service


def generate(
    *,
    keyword: str,
    template_type: str | None = None,
    n_candidates: int = 3,
    provider: str | None = None,
    model: str | None = None,
) -> list[str]:
    cfg = config_service.load()
    if not cfg.vault_root:
        raise ValueError("AppConfig.vault_root is unset")
    client = llm_factory.build_client(provider=provider, model=model)
    # If we have a recent vault scan cached, reuse it; otherwise generate_titles
    # will scan its own copy.
    cached = vault_service.cached()
    return generate_titles(
        keyword=keyword,
        template_type=template_type,
        vault_root=Path(cfg.vault_root),
        llm_client=client,
        n_candidates=n_candidates,
        vault_index=cached,
    )
