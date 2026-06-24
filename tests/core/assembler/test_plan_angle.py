from csm_core.assembler.plan import AssemblyPlan
from csm_core.angle.model import Angle


def test_plan_carries_angle_round_trip():
    p = AssemblyPlan(keyword="k", template_id="t", seed=0,
                     angle=Angle(audience="铲屎官"))
    assert AssemblyPlan.from_json(p.to_json()).angle == Angle(audience="铲屎官")


def test_old_json_without_angle_defaults_none():
    p = AssemblyPlan(keyword="k", template_id="t", seed=0)
    assert p.angle is None
    # 模拟旧 JSON（无 angle 键）
    j = '{"keyword":"k","template_id":"t","seed":0,"results":[],"warnings":[]}'
    assert AssemblyPlan.from_json(j).angle is None
