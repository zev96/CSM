from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.schema import (
    Template, Slot, BrandFixedSource, BrandPoolSource, TestResultsAlignedSource,
)
from csm_core.assembler.constraints import assemble_plan


def _duibi_template() -> Template:
    return Template(
        id="duibi-test", name="对比文测试", product="吸尘器",
        slots=[
            Slot(id="brand_self", label="自有",
                 source=BrandFixedSource(brand="CEWEY", model="CEWEYDS18")),
            Slot(id="brand_competitors", label="竞品",
                 source=BrandPoolSource(exclude_brands=["CEWEY"]),
                 pick_notes=2),
            Slot(id="test_results", label="测试结果",
                 source=TestResultsAlignedSource(
                     follow_slot="brand_self+brand_competitors",
                     module="测试项目模块/品牌产品测试结果",
                 ),
                 depends_on=["brand_self", "brand_competitors"]),
        ],
        render_order=["brand_self", "brand_competitors", "test_results"],
    )


def test_assemble_respects_topological_order(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    tpl = _duibi_template()
    plan = assemble_plan(
        keyword="kw", template=tpl, index=index, registry=registry,
        seed=42, user_config={},
    )
    test_slot = plan.get_slot("test_results")
    assert test_slot is not None
    self_models = set(plan.models_in_slot("brand_self"))
    comp_models = set(plan.models_in_slot("brand_competitors"))
    test_models = {p.meta.get("model") for p in test_slot.picks}
    assert test_models == self_models | comp_models


def test_assemble_missing_test_data_recorded(tmp_path: Path):
    vault = tmp_path / "营销资料库"
    (vault / "产品模块/吸尘器/产品参数").mkdir(parents=True)
    (vault / "产品模块/吸尘器/产品参数/CEWEYDS18-产品参数.md").write_text(
        "---\n品牌: CEWEY\n型号: CEWEYDS18\n---\n吸力 220AW",
        encoding="utf-8",
    )
    (vault / "测试项目模块/吸尘器/品牌产品测试结果").mkdir(parents=True)
    index = scan_vault(vault)
    registry = build_brand_registry(vault)

    tpl = Template(
        id="t", name="T", product="吸尘器",
        slots=[
            Slot(id="self", label="自",
                 source=BrandFixedSource(brand="CEWEY", model="CEWEYDS18")),
            Slot(id="tests", label="测",
                 source=TestResultsAlignedSource(
                     follow_slot="self",
                     module="测试项目模块/品牌产品测试结果",
                 ),
                 depends_on=["self"]),
        ],
        render_order=["self", "tests"],
    )
    plan = assemble_plan(keyword="k", template=tpl, index=index, registry=registry, seed=0, user_config={})
    test_slot = plan.get_slot("tests")
    assert len(test_slot.picks) == 1
    assert test_slot.picks[0].meta.get("missing") is True
