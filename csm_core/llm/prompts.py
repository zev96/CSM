"""Compose three-layer prompt: template default + user skill + SEO constraints."""
from __future__ import annotations
from dataclasses import dataclass
from ..template.schema import SEODefaults


@dataclass
class PromptInputs:
    template_system_prompt: str
    user_skill_prompt: str | None
    seo: SEODefaults
    keyword: str
    draft: str


def _format_seo_block(seo: SEODefaults, keyword: str) -> str:
    parts = [
        f"- 目标字数：{seo.target_word_count[0]}-{seo.target_word_count[1]} 字",
        f"- 主关键词「{keyword}」密度：{seo.keyword_density[0]}-{seo.keyword_density[1]} 次",
        f"- 口吻风格：{seo.tone}",
    ]
    if seo.long_tail_keywords:
        parts.append(f"- 长尾关键词（自然嵌入）：{', '.join(seo.long_tail_keywords)}")
    if seo.force_h2:
        parts.append("- 必须使用 H2 (##) 段落标题分隔核心板块")
    return "【SEO 约束】\n" + "\n".join(parts)


def build_prompt(inputs: PromptInputs) -> tuple[str, str]:
    layers: list[str] = [inputs.template_system_prompt.strip()]
    if inputs.user_skill_prompt:
        layers.append(inputs.user_skill_prompt.strip())
    layers.append(_format_seo_block(inputs.seo, inputs.keyword))
    system = "\n\n".join(layer for layer in layers if layer)

    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"【毛坯文】\n{inputs.draft}\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
    )
    return system, user
