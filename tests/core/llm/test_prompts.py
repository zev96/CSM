from csm_core.llm.prompts import PromptInputs, build_prompt


def test_build_prompt_uses_skill_only_as_system():
    system, user = build_prompt(PromptInputs(
        user_skill_prompt="be concise.",
        keyword="吸尘器",
        draft="draft text",
    ))
    assert system == "be concise."
    assert "吸尘器" in user
    assert "draft text" in user


def test_build_prompt_empty_skill_yields_empty_system():
    system, user = build_prompt(PromptInputs(
        user_skill_prompt=None,
        keyword="吸尘器",
        draft="draft",
    ))
    assert system == ""
    assert "【毛坯文】" in user


def test_build_prompt_strips_skill_whitespace():
    system, _ = build_prompt(PromptInputs(
        user_skill_prompt="   \n  hello \n ",
        keyword="k",
        draft="d",
    ))
    assert system == "hello"


def test_build_prompt_without_brand_facts_is_unchanged():
    s, u = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="无线吸尘器", draft="草稿正文"))
    assert s == "人设"
    assert "【关键词】无线吸尘器" in u
    assert "【毛坯文】" in u and "草稿正文" in u
    assert "品牌型号事实" not in u        # 无 facts 不注入该段
    assert "严禁引入" not in u


def test_build_prompt_injects_brand_facts_and_hard_constraint():
    s, u = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="kw", draft="草稿",
        brand_facts="## CEWEY DS18（主推）\n参数：\n- 吸力(AW): 220"))
    assert "品牌型号事实" in u
    assert "吸力(AW): 220" in u
    assert "严禁引入" in u                 # 硬约束句
    assert u.index("品牌型号事实") < u.index("【毛坯文】")  # facts 段在毛坯文之前
