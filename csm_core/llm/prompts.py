"""Compose prompt from a single user-selected skill. Template-level
system_prompt / SEO constraints were folded into the skill .md at migration
time (see scripts/migrate_template_to_skill.py); they no longer live on
the Template model."""
from __future__ import annotations
from dataclasses import dataclass

from .layout_guard import LAYOUT_CLAUSE


@dataclass
class PromptInputs:
    user_skill_prompt: str | None
    keyword: str
    draft: str
    # Plan 3: 结构化型号事实（参数/认证/话术/背书）。None = 不注入（今天行为）。
    brand_facts: str | None = None
    # Phase 2a: 标题领衔 + 角度指令块。两者都空 = 今天行为（零回归）。
    title: str | None = None
    angle_directive: str | None = None
    # Phase 4+: 成文契约档。"conservative"（默认）= 今天行为字节级不变；
    # "aggressive" = 允许取舍删减（主推事实必须保留，另有完整性核对兜底）。
    contract_mode: str = "conservative"
    # 榜单卡片区：禁止改动标题行/加粗小节/分段。False = 今天行为字节级不变。
    preserve_layout: bool = False


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

    title_block = (
        f"【标题】{inputs.title.strip()}\n\n"
        if inputs.title and inputs.title.strip() else ""
    )
    angle_block = (
        f"{inputs.angle_directive.strip()}\n\n"
        if inputs.angle_directive else ""
    )

    aggressive = inputs.contract_mode == "aggressive"
    if title_block or angle_block:
        if aggressive:
            instruction = (
                "请按上面【写作角度】组织成文：可取舍删减次要或重复的信息点、"
                "让篇幅更精炼；但主推型号的参数、认证与标题承诺的卖点必须完整保留；"
                "不新增虚构事实，不改动任何数字、单位、认证。"
            )
        else:
            # 保守契约：保信息点 + 按角度调侧重/顺序/详略/语调 + 标题领衔；不取舍删减、不增改事实
            instruction = (
                "请按上面【写作角度】组织成文：保留所有信息点，可调整侧重、顺序、详略与语调；"
                + ("围绕标题开篇点题、贯穿全文；" if title_block else "")
                + "不新增虚构事实，不改动任何数字、单位、认证，不删减关键信息点。"
            )
    else:
        if aggressive:
            instruction = (
                "请按**精炼模式**重写：可删减次要或重复内容、合并冗余段落；"
                "但所有型号参数、认证与核心卖点必须完整保留；"
                "不新增虚构事实，不改动任何数字、单位、认证。"
            )
        else:
            instruction = (
                "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
                "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
            )

    layout = f"\n{LAYOUT_CLAUSE}" if inputs.preserve_layout else ""

    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"{title_block}"
        f"{angle_block}"
        f"{facts_block}"
        f"【毛坯文】\n{inputs.draft}\n\n"
        f"{instruction}"
        f"{constraint}"
        f"{layout}"
    )
    return system, user


def build_refine_prompt(
    skill_body: str | None, prev_text: str, *, preserve_layout: bool = False,
) -> tuple[str, str]:
    """链 step[1:] 的精修 prompt：按 skill 风格改写上段输出，保守约束
    （保信息点/数字/单位/认证，只改文风）。step[0] 仍用 build_prompt。"""
    system = (skill_body or "").strip()
    layout = f"\n{LAYOUT_CLAUSE}" if preserve_layout else ""
    user = (
        f"【待改写正文】\n{prev_text}\n\n"
        "请按上面的风格指引改写这段正文：保留所有信息点、段落要点与全部"
        "数字/单位/认证名称，只改进措辞、语感与风格一致性；不新增虚构事实，"
        "不删减关键信息，不改动任何参数数字或认证。"
        f"{layout}"
    )
    return system, user
