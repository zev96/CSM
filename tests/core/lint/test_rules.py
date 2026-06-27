from csm_core.config import AppConfig, LintConfig
from csm_core.lint.model import LintHit, LintReport
from csm_core.lint.rules import build_rules, DEFAULT_ABSOLUTE, DEFAULT_TRAFFIC, DEFAULT_META


def test_lint_config_defaults():
    c = LintConfig()
    assert c.enabled is True
    assert c.extra_meta == [] and c.extra_absolute == [] and c.extra_traffic == []
    assert c.disabled_categories == []


def test_appconfig_has_lint_default():
    # 旧 settings.json 无 lint 键也安全：model_validate 补默认
    cfg = AppConfig.model_validate({})
    assert cfg.lint.enabled is True


def test_lint_models_construct():
    h = LintHit(category="absolute", text="最佳", start=3, end=5,
                sentence="这是最佳之选", fixable=False, suggestion="改写")
    assert h.category == "absolute" and h.fixable is False
    r = LintReport(hits=[h], fixed_text="原文")
    assert r.fixed_text == "原文" and len(r.hits) == 1


def test_build_rules_defaults():
    r = build_rules(None)
    assert "最佳" in r.absolute and "加微信" in r.traffic and "软文" in r.meta
    assert r.check_emoji and r.check_dash and r.check_quote


def test_build_rules_extends_not_replaces():
    r = build_rules(LintConfig(extra_absolute=["史诗级"]))
    assert "史诗级" in r.absolute and "最佳" in r.absolute  # 加而非替
    # 去重保序：默认词不因 extra 重复出现两次
    assert list(r.absolute).count("最佳") == 1


def test_build_rules_disable_category():
    r = build_rules(LintConfig(disabled_categories=["quote", "meta_speak"]))
    assert r.check_quote is False
    assert r.meta == ()          # 词类禁用 → 空
    assert r.check_emoji is True  # 未禁用的不受影响
