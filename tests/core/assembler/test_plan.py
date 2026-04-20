import json
from csm_core.assembler.plan import AssemblyPlan, SlotAssignment, PickedVariant


def test_plan_serializes_to_json():
    plan = AssemblyPlan(
        keyword="宠物吸尘器推荐",
        template_id="daogou-changjing-renqun",
        seed=42,
        slots=[
            SlotAssignment(
                slot_id="intro",
                picks=[PickedVariant(note_id="引言-吸尘器-毛发缠绕", variant_index=1, text="养宠家庭...")],
            ),
        ],
    )
    as_json = plan.to_json()
    data = json.loads(as_json)
    assert data["keyword"] == "宠物吸尘器推荐"
    assert data["seed"] == 42
    assert data["slots"][0]["slot_id"] == "intro"
    assert data["slots"][0]["picks"][0]["variant_index"] == 1


def test_plan_deserializes_from_json():
    payload = json.dumps({
        "keyword": "kw",
        "template_id": "t",
        "seed": 1,
        "slots": [
            {"slot_id": "s", "picks": [
                {"note_id": "n", "variant_index": 0, "text": "hello"}
            ]}
        ],
    })
    plan = AssemblyPlan.from_json(payload)
    assert plan.keyword == "kw"
    assert plan.slots[0].picks[0].text == "hello"


def test_plan_get_slot():
    plan = AssemblyPlan(
        keyword="k", template_id="t", seed=0,
        slots=[SlotAssignment(slot_id="a", picks=[])],
    )
    assert plan.get_slot("a").slot_id == "a"
    assert plan.get_slot("nope") is None


def test_plan_all_brands_in_slot():
    plan = AssemblyPlan(
        keyword="k", template_id="t", seed=0,
        slots=[SlotAssignment(
            slot_id="comp",
            picks=[
                PickedVariant(note_id="戴森V15-核心卖点", variant_index=0, text="", meta={"model": "戴森V15", "brand": "戴森"}),
                PickedVariant(note_id="小狗T12-核心卖点", variant_index=0, text="", meta={"model": "小狗T12", "brand": "小狗"}),
            ],
        )],
    )
    models = plan.models_in_slot("comp")
    assert set(models) == {"戴森V15", "小狗T12"}
