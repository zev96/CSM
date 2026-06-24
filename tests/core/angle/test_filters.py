from csm_core.angle.model import Angle
from csm_core.angle.filters import effective_sellpoints


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
