from csm_core.angle.model import Angle


def test_empty_angle_is_empty():
    assert Angle().is_empty() is True
    assert Angle(audience=None, sellpoints=[], tone=None).is_empty() is True


def test_any_facet_makes_nonempty():
    assert Angle(audience="铲屎官").is_empty() is False
    assert Angle(sellpoints=["防缠绕技术"]).is_empty() is False
    assert Angle(tone="口语").is_empty() is False


def test_json_round_trip():
    a = Angle(audience="老年人", sellpoints=["机身重量"], tone="专业")
    assert Angle.model_validate(a.model_dump()) == a


def test_defaults_are_safe():
    a = Angle()
    assert a.audience is None and a.sellpoints == [] and a.tone is None
