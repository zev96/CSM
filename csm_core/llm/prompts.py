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
    # Plan 3: 结构化型号事实（参数/认证/话术/背书）。None = 不注入（今天行为）。
    brand_facts: str | None = None


def build_prompt(inputs: PromptInputs) -> tuple[str, str]:
    system = (inputs.user_skill_prompt or "").strip()
    facts_block = ""
    constraint = ""
    if inputs.brand_facts:
        facts_block = (
            "【品牌型号事实（仅可使用以下参数/认证，不得新增或改动任何"
            "数字、单位、认证名）】\n"
            f"{inputs.brand_facts}\n\n"
        )
        constraint = "\n严禁引入上面【品牌型号事实】之外的任何参数数字或认证名称。"
    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"{facts_block}"
        f"【毛坯文】\n{inputs.draft}\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
        f"{constraint}"
    )
    return system, user
