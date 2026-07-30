"""Compose prompt from a single user-selected skill. Template-level
system_prompt / SEO constraints were folded into the skill .md at migration
time (see scripts/migrate_template_to_skill.py); they no longer live on
the Template model."""
from __future__ import annotations
from dataclasses import dataclass

from .layout_guard import LAYOUT_CLAUSE
from .title_guard import TITLE_CLAUSE, keyword_title_clause


def keyword_weave_clause(keyword: str) -> str:
    """关键词自然植入引言/结尾的正向要求。

    标题里的关键词有 title_guard 钉着；正文此前没人管 —— 毛坯文的引言/结尾
    来自素材库，往往不含用户输入的搜索词，SEO 词全文只在标题出现一次。
    措辞必须**幂等**（没有才补、有则保持）：链多 pass 逐段改写，每个 pass 都
    带这条，非幂等措辞会让关键词越织越多。
    """
    return (
        f"【关键词植入】检查引言（开篇段落）与结尾段：尚未出现关键词「{keyword}」"
        "的，各自然融入一次 —— 贴合上下文、语句通顺，不得生硬堆砌或罗列；"
        "已出现的位置保持原样，不要重复追加。"
    )


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

    weave = f"\n{keyword_weave_clause(inputs.keyword)}" if inputs.keyword else ""
    layout = f"\n{LAYOUT_CLAUSE}" if inputs.preserve_layout else ""
    # 标题两种情形都要下约束，正文首行的 H1 就是全链路认定的文章标题：
    #   · 用户定了标题 → 一个字都不许动（上面 title_block 把标题当写作指引
    #     给了 LLM「围绕标题开篇点题」，不拦着它就会顺手改写成自己的版本）；
    #   · 用户没定标题（默认流程只填关键词）→ 链可以自己拟，但关键词必须
    #     一字不差留着，否则用户的 SEO 词就被润色改没了。
    # title_guard.enforce 是确定性兜底，这两条是正向要求。
    if title_block:
        title_rule = f"\n{TITLE_CLAUSE}"
    elif inputs.keyword:
        title_rule = f"\n{keyword_title_clause(inputs.keyword)}"
    else:
        title_rule = ""

    user = (
        f"【关键词】{inputs.keyword}\n\n"
        f"{title_block}"
        f"{angle_block}"
        f"{facts_block}"
        f"【毛坯文】\n{inputs.draft}\n\n"
        f"{instruction}"
        f"{constraint}"
        f"{weave}"
        f"{layout}"
        f"{title_rule}"
    )
    return system, user


def build_refine_prompt(
    skill_body: str | None, prev_text: str, *,
    preserve_layout: bool = False, title_rule: str = "",
    keyword: str = "",
) -> tuple[str, str]:
    """链 step[1:] 的精修 prompt：按 skill 风格改写上段输出，保守约束
    （保信息点/数字/单位/认证，只改文风）。step[0] 仍用 build_prompt。

    ``title_rule`` 由调用方按上段输出的形态选：带标题行就下 TITLE_CLAUSE，
    否则下 keyword_title_clause —— 链越往后越容易被「改进措辞」顺手把标题
    改掉，或者临时起意加一个自己的标题。空串 = 不加（无标题也无关键词时）。

    ``keyword`` 非空时同样下关键词植入条款（幂等措辞）：step0 织进引言/结尾
    的关键词，精修 pass 一「改进措辞」就容易被润掉。默认空串 = 不加（零回归）。
    """
    system = (skill_body or "").strip()
    weave = f"\n{keyword_weave_clause(keyword)}" if keyword else ""
    layout = f"\n{LAYOUT_CLAUSE}" if preserve_layout else ""
    title_rule = f"\n{title_rule}" if title_rule else ""
    user = (
        f"【待改写正文】\n{prev_text}\n\n"
        "请按上面的风格指引改写这段正文：保留所有信息点、段落要点与全部"
        "数字/单位/认证名称，只改进措辞、语感与风格一致性；不新增虚构事实，"
        "不删减关键信息，不改动任何参数数字或认证。"
        f"{weave}"
        f"{layout}"
        f"{title_rule}"
    )
    return system, user
