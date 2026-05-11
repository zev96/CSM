"""Single-block polish.

csm_core has no "polish one paragraph" entrypoint — its pipeline runs the
whole article through one LLM call. Per A2 we keep the UI button and
implement it here in the sidecar as a simple LLM wrapper. **Critically,
we don't touch csm_core**: this is a sidecar adapter, not new business
logic in the core.
"""
from __future__ import annotations

from . import llm_factory, skills_service, config_service
from pathlib import Path


_POLISH_SYSTEM = (
    "你是中文改写编辑。将给定段落改写为更自然的中文，"
    "保留事实信息，不增不减要点。仅返回改写后的段落正文，"
    "不要加任何前后缀、引号或标题。"
)


def polish_block(
    *,
    text: str,
    skill_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = 0.6,
) -> str:
    """Return the LLM's rewrite of ``text``. Skill prompt prepended if given."""
    text = (text or "").strip()
    if not text:
        return ""

    skill_prompt: str | None = None
    if skill_id:
        cfg = config_service.load()
        skill = skills_service.get_skill(
            Path(cfg.skill_dir) if cfg.skill_dir else None,
            skill_id,
        )
        if skill is not None:
            skill_prompt = skill.body

    system_parts = [_POLISH_SYSTEM]
    if skill_prompt:
        system_parts.append("【改写风格指引】\n" + skill_prompt)
    system = "\n\n".join(system_parts)

    client = llm_factory.build_client(provider=provider, model=model)
    return client.complete(system=system, user=text, temperature=temperature)
