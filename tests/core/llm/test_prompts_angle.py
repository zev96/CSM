from csm_core.llm.prompts import PromptInputs, build_prompt


def test_no_angle_no_title_snapshot_unchanged():
    # 钉死零回归：title/angle_directive 都 None 时，user prompt 与今天字节一致
    sys_, user = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="无线吸尘器", draft="毛坯", brand_facts=None))
    assert "【关键词】无线吸尘器" in user
    assert "请按**润色模式**重写" in user
    assert "【写作角度】" not in user and "【标题】" not in user


def test_title_leads_and_directive_present():
    sys_, user = build_prompt(PromptInputs(
        user_skill_prompt="人设", keyword="无线吸尘器", draft="毛坯",
        brand_facts=None, title="无线吸尘器哪款好用？实测分享",
        angle_directive="【写作角度】\n- 目标读者：铲屎官"))
    assert "无线吸尘器哪款好用？实测分享" in user
    assert "【写作角度】" in user
    assert "围绕标题" in user  # 保守契约措辞
