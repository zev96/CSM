"""Tests for the per-slot reroll pure function."""
from __future__ import annotations
from pathlib import Path

from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.loader import load_template
from csm_core.assembler.constraints import assemble_plan
from csm_gui.workers.reroll import reroll_slot


def test_reroll_changes_single_slot(mini_vault_path):
    tpl_path = (
        Path(__file__).parent.parent.parent
        / "templates" / "daogou-changjing-renqun.json"
    )
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    template = load_template(tpl_path)
    plan = assemble_plan(
        keyword="k", template=template, index=index,
        registry=registry, seed=1, user_config={"brand_competitors": 2},
    )
    new_plan = reroll_slot(
        slot_id="keypoints", template=template, index=index,
        registry=registry, current_plan=plan, counter=1,
        user_config={"brand_competitors": 2},
    )
    # Keypoints picks should actually change after reroll.
    before = [(p.note_id, p.variant_index) for p in plan.get_slot("keypoints").picks]
    after = [(p.note_id, p.variant_index) for p in new_plan.get_slot("keypoints").picks]
    assert before != after, "reroll should change keypoints picks"
    # Other independent slots unchanged.
    assert (
        plan.get_slot("brand_self").picks[0].meta
        == new_plan.get_slot("brand_self").picks[0].meta
    )
    # Keyword / template_id / seed preserved.
    assert new_plan.keyword == plan.keyword
    assert new_plan.template_id == plan.template_id
    assert new_plan.seed == plan.seed


def test_reroll_downstream_of_dependent_slot(mini_vault_path):
    from csm_core.template.schema import (
        Template, Slot, BrandFixedSource, BrandPoolSource,
        TestResultsAlignedSource,
    )
    t = Template(
        id="duibi", name="对比", product="吸尘器",
        slots=[
            Slot(
                id="self", label="自",
                source=BrandFixedSource(brand="CEWEY", model="CEWEYDS18"),
            ),
            Slot(
                id="comp", label="竞",
                source=BrandPoolSource(exclude_brands=["CEWEY"]),
                pick_notes=1,
            ),
            Slot(
                id="tests", label="测",
                source=TestResultsAlignedSource(
                    follow_slot="self+comp",
                    module="测试项目模块/品牌产品测试结果",
                ),
                depends_on=["self", "comp"],
            ),
        ],
        render_order=["self", "comp", "tests"],
    )
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    plan = assemble_plan(
        keyword="k", template=t, index=index, registry=registry,
        seed=1, user_config={},
    )
    new_plan = reroll_slot(
        slot_id="comp", template=t, index=index, registry=registry,
        current_plan=plan, counter=1, user_config={},
    )
    new_comp_models = {p.meta["model"] for p in new_plan.get_slot("comp").picks}
    new_test_models = {p.meta.get("model") for p in new_plan.get_slot("tests").picks}
    # tests slot follows self+comp, so its models should equal {self} U {comp}.
    assert {"CEWEYDS18"} | new_comp_models == new_test_models
    # self slot (not downstream of comp) should be untouched.
    assert (
        plan.get_slot("self").picks[0].meta
        == new_plan.get_slot("self").picks[0].meta
    )
