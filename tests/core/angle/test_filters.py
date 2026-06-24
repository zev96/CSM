from types import SimpleNamespace

from csm_core.angle.model import Angle
from csm_core.angle.filters import effective_sellpoints, effective_filters


def test_explicit_sellpoints_win():
    a = Angle(audience="铲屎官", sellpoints=["续航时间"])
    assert effective_sellpoints(a) == ["续航时间"]


def test_audience_derives_primary_dim():
    a = Angle(audience="铲屎官")  # 主推维度=防缠绕技术
    assert effective_sellpoints(a) == ["防缠绕技术"]


def test_audience_with_empty_primary_dim():
    a = Angle(audience="性价比党")  # 主推维度=""
    assert effective_sellpoints(a) == []


def test_no_audience_no_sellpoints():
    assert effective_sellpoints(Angle()) == []
    assert effective_sellpoints(None) == []


def _src(module, flt=None):
    return SimpleNamespace(module=module, filter=flt)


def test_audience_block_gets_renqun_filter():
    a = Angle(audience="铲屎官")
    eff = effective_filters(_src("营销资料库/用户人群/吸尘器"), a)
    assert eff == {"人群分类": "铲屎官"}


def test_audience_merges_with_existing_filter():
    a = Angle(audience="老年人")
    eff = effective_filters(_src("营销资料库/用户人群/吸尘器", {"产品": "吸尘器"}), a)
    assert eff == {"产品": "吸尘器", "人群分类": "老年人"}


def test_non_audience_block_untouched():
    a = Angle(audience="铲屎官")
    assert effective_filters(_src("营销资料库/科普模块/吸尘器", {"x": 1}), a) == {"x": 1}


def test_no_angle_returns_source_filter():
    assert effective_filters(_src("营销资料库/用户人群/吸尘器", {"x": 1}), None) == {"x": 1}
    assert effective_filters(_src("营销资料库/用户人群/吸尘器"), Angle()) == {}
