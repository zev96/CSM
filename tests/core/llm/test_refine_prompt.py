from csm_core.llm.prompts import build_refine_prompt


def test_refine_system_is_skill_body():
    system, user = build_refine_prompt("小红书风格", "上一段正文")
    assert system == "小红书风格"
    assert "上一段正文" in user


def test_refine_user_has_conservative_constraint():
    _, user = build_refine_prompt("x", "正文")
    assert "保留所有信息点" in user
    assert "不改动任何参数数字或认证" in user
    assert "不删减" in user


def test_refine_empty_body_blank_system():
    system, user = build_refine_prompt(None, "正文")
    assert system == ""
    assert "正文" in user
