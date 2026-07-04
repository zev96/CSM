from csm_core.config import AppConfig, ContractConfig, ScoringConfig
from csm_core.llm.prompts import PromptInputs, build_prompt


def test_config_defaults():
    assert ContractConfig().mode == "conservative"
    sc = ScoringConfig()
    assert sc.enabled is True and sc.extra_ai_words == []
    cfg = AppConfig.model_validate({})
    assert cfg.contract.mode == "conservative"
    assert cfg.scoring.enabled is True


# —— 保守分支零回归：钉死当前字节（改动 prompts.py 后这些断言不许变）——
def test_conservative_default_unchanged():
    system, user = build_prompt(PromptInputs(
        user_skill_prompt="skill正文", keyword="吸尘器", draft="毛坯"))
    assert system == "skill正文"
    assert user == (
        "【关键词】吸尘器\n\n"
        "【毛坯文】\n毛坯\n\n"
        "请按**润色模式**重写：保留所有信息点和段落结构，只改进文字流畅度、"
        "衔接和风格一致性；不新增虚构事实，不删减关键信息。"
    )


def test_conservative_with_title_angle_unchanged():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="k", draft="d",
        title="T", angle_directive="【写作角度】x"))
    assert "请按上面【写作角度】组织成文：保留所有信息点，可调整侧重、顺序、详略与语调；" in user
    assert "围绕标题开篇点题、贯穿全文；" in user
    assert "不新增虚构事实，不改动任何数字、单位、认证，不删减关键信息点。" in user


def test_aggressive_with_angle():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="k", draft="d",
        angle_directive="【写作角度】x", contract_mode="aggressive"))
    assert "可取舍删减次要或重复的信息点、让篇幅更精炼" in user
    assert "主推型号的参数、认证与标题承诺的卖点必须完整保留" in user
    assert "不删减关键信息点" not in user


def test_aggressive_default_mode():
    _, user = build_prompt(PromptInputs(
        user_skill_prompt=None, keyword="k", draft="d",
        contract_mode="aggressive"))
    assert "请按**精炼模式**重写：可删减次要或重复内容、合并冗余段落" in user
    assert "所有型号参数、认证与核心卖点必须完整保留" in user


def test_facts_constraint_present_in_both_modes():
    for mode in ("conservative", "aggressive"):
        _, user = build_prompt(PromptInputs(
            user_skill_prompt=None, keyword="k", draft="d",
            brand_facts="## CEWEY DS18", contract_mode=mode))
        assert "严禁引入上面【品牌型号事实】之外的任何参数数字或认证名称。" in user
