"""Compose prompt from a single user-selected skill. Template-level
system_prompt / SEO constraints were folded into the skill .md at migration
time (see scripts/migrate_template_to_skill.py); they no longer live on
the Template model."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PromptInputs:
    user_skill_prompt: str | None
    keyword: str
    draft: str


def build_prompt(inputs: PromptInputs) -> tuple[str, str]:
    system = (inputs.user_skill_prompt or "").strip()
    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"【毛坯文】\n{inputs.draft}\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
    )
    return system, user
