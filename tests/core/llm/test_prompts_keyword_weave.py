"""关键词自然植入引言/结尾 —— prompt 层的正向要求。

用户诉求：「我输入的关键词可以在润色的时候自然植入到引言和结尾吗？」
标题里的关键词已有 title_guard 管；正文（引言/结尾）此前完全没下要求，
LLM 不会主动把 SEO 词织进去。这里钉：

- build_prompt（链 step0 = 整篇润色主 pass）带植入指令；
- build_refine_prompt（链精修 pass）同款指令 —— 措辞幂等（没有才补，
  有则保持），后段 pass 不会把前段织进去的关键词又润掉；
- keyword 为空（横评可不填关键词）→ 一字不加（零回归）。
"""
from csm_core.llm.prompts import (
    PromptInputs, build_prompt, build_refine_prompt, keyword_weave_clause,
)


def test_step0_prompt_carries_weave_clause():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="空气净化器", draft="毛坯"))
    assert "【关键词植入】" in user
    assert "「空气净化器」" in user
    # 引言与结尾都点名 —— 只说「正文里出现」的话 LLM 常塞在中段完事
    assert "引言" in user and "结尾" in user


def test_step0_weave_clause_present_with_title_and_angle():
    # 有标题/角度的分支走不同 instruction，植入指令必须同样在场
    _, user = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="空气净化器", draft="毛坯",
        title="空气净化器哪款好", angle_directive="【写作角度】\n- 目标读者：宝妈"))
    assert "【关键词植入】" in user


def test_empty_keyword_adds_nothing():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="", draft="毛坯"))
    assert "【关键词植入】" not in user


def test_refine_prompt_carries_weave_clause_when_keyword_given():
    _, user = build_refine_prompt("小红书风格", "上一段正文", keyword="空气净化器")
    assert "【关键词植入】" in user
    assert "「空气净化器」" in user


def test_refine_prompt_default_is_unchanged():
    # 零回归：不传 keyword 的旧调用一字不加
    _, user = build_refine_prompt("小红书风格", "上一段正文")
    assert "【关键词植入】" not in user


def test_clause_is_idempotent_wording():
    # 措辞必须是「没有才补、有则保持」—— 链多 pass 下不会越织越多
    clause = keyword_weave_clause("空气净化器")
    assert "已" in clause  # 「已出现的保持原样」这层意思必须在
