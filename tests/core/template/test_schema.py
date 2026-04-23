from csm_core.template.schema import Template


def _minimal_template_dict(**overrides) -> dict:
    d = {
        "id": "t1",
        "name": "T",
        "product": "吸尘器",
        "blocks": [{"kind": "literal", "id": "lit", "text": "hi"}],
    }
    d.update(overrides)
    return d


def test_template_loads_without_dead_fields():
    tpl = Template.model_validate(_minimal_template_dict())
    assert tpl.id == "t1"
    # New optional field defaults to None.
    assert tpl.default_skill_id is None


def test_template_silently_ignores_legacy_fields():
    """Old JSONs still carry version / system_prompt_default / seo_defaults.
    extra='ignore' lets them load; values are discarded."""
    legacy = _minimal_template_dict(
        version=3,
        system_prompt_default="you are an editor",
        seo_defaults={"target_word_count": [500, 800], "tone": "冷静"},
    )
    tpl = Template.model_validate(legacy)
    dumped = tpl.model_dump()
    assert "version" not in dumped
    assert "system_prompt_default" not in dumped
    assert "seo_defaults" not in dumped


def test_template_accepts_default_skill_id():
    tpl = Template.model_validate(_minimal_template_dict(default_skill_id="xhs"))
    assert tpl.default_skill_id == "xhs"
