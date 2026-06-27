from csm_core.config import AppConfig, LintConfig
from csm_core.lint.model import LintHit, LintReport


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
