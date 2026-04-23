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
