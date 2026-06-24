from csm_core.angle.model import Angle
from csm_core.angle.directive import render_angle_directive


def test_empty_angle_no_directive():
    assert render_angle_directive(Angle()) is None
    assert render_angle_directive(None) is None


def test_full_directive_mentions_facets():
    a = Angle(audience="铲屎官", sellpoints=["防缠绕技术", "续航时间"], tone="口语")
    d = render_angle_directive(a)
    assert "铲屎官" in d
    assert "宠物毛发缠绕刷头" in d        # 来自 AUDIENCES 痛点主题
    assert "防缠绕" in d and "续航" in d   # 维度 display 标签
    assert "口语" in d


def test_audience_only_uses_primary_dim():
    d = render_angle_directive(Angle(audience="铲屎官"))
    assert "防缠绕" in d                   # 主推维度派生进侧重


def test_unknown_values_skipped_not_crash():
    d = render_angle_directive(Angle(audience="火星人", sellpoints=["不存在"], tone="???"))
    assert isinstance(d, str)              # 不抛异常；非法值跳过
