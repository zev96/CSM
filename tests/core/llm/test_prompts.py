from csm_core.llm.prompts import build_prompt, PromptInputs
from csm_core.template.schema import SEODefaults


def test_build_prompt_composes_three_layers():
    inputs = PromptInputs(
        template_system_prompt="你是资深家电编辑。",
        user_skill_prompt="保持小红书语气。",
        seo=SEODefaults(
            target_word_count=[1500, 2000],
            keyword_density=[5, 8],
            long_tail_keywords=["宠物吸尘器", "毛发缠绕"],
            tone="小红书笔记体",
            force_h2=True,
        ),
        keyword="宠物吸尘器推荐",
        draft="毛坯文内容...",
    )
    system, user = build_prompt(inputs)
    assert "你是资深家电编辑" in system
    assert "保持小红书语气" in system
    assert "1500" in system and "2000" in system
    assert "5" in system and "8" in system
    assert "H2" in system or "h2" in system.lower()
    assert "小红书笔记体" in system
    assert "宠物吸尘器" in system

    assert "毛坯文内容" in user
    assert "宠物吸尘器推荐" in user
    assert "润色" in user  # polish mode instruction


def test_build_prompt_omits_optional_layers():
    inputs = PromptInputs(
        template_system_prompt="A",
        user_skill_prompt=None,
        seo=SEODefaults(),
        keyword="k",
        draft="d",
    )
    system, user = build_prompt(inputs)
    assert "A" in system
    assert "d" in user
