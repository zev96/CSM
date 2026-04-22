import json
from csm_core.assembler.plan import (
    PickedVariant, BlockResult, AssemblyPlan,
)


def test_block_result_literal_roundtrip():
    br = BlockResult(block_id="l1", kind="literal", text="hello")
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0, results=[br])
    reparsed = AssemblyPlan.from_json(plan.to_json())
    assert reparsed.results[0].text == "hello"


def test_block_result_paragraph_with_picks():
    pv = PickedVariant(note_id="n1", variant_index=0, text="abc")
    br = BlockResult(block_id="s1", kind="paragraph", picks=[pv])
    plan = AssemblyPlan(keyword="k", template_id="t", seed=0, results=[br])
    found = plan.get_result("s1")
    assert found is not None and found.picks[0].text == "abc"
