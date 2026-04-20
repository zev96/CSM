from pathlib import Path
import pytest
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.schema import (
    Slot, NotesQuerySource, BrandFixedSource, BrandPoolSource, PickCountSpec,
)
from csm_core.assembler.sampler import sample_slot, EmptyPoolError


def test_sample_notes_query_slot(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="intro", label="引言",
        source=NotesQuerySource(module="引言模块", filter={"组件类型": "痛点共鸣"}),
        pick_notes=1, pick_variants_per_note=1,
    )
    picks = sample_slot(slot, index, registry, seed=42, user_config={})
    assert len(picks) == 1
    assert picks[0].note_id in {"引言-吸尘器-毛发缠绕", "引言-吸尘器-吸力衰减"}


def test_sample_reproducible_with_seed(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="kp", label="科普",
        source=NotesQuerySource(module="科普模块/挑选攻略"),
        pick_notes=PickCountSpec(random_between=[2, 2]),
        pick_variants_per_note=1,
    )
    r1 = sample_slot(slot, index, registry, seed=42, user_config={})
    r2 = sample_slot(slot, index, registry, seed=42, user_config={})
    assert [p.note_id for p in r1] == [p.note_id for p in r2]
    assert [p.variant_index for p in r1] == [p.variant_index for p in r2]


def test_sample_different_seeds_produce_different_picks(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="kp", label="科普",
        source=NotesQuerySource(module="科普模块/挑选攻略"),
        pick_notes=PickCountSpec(random_between=[2, 2]),
        pick_variants_per_note=1,
    )
    r1 = sample_slot(slot, index, registry, seed=0, user_config={})
    for s in range(1, 30):
        r2 = sample_slot(slot, index, registry, seed=s, user_config={})
        if [p.note_id for p in r2] != [p.note_id for p in r1]:
            return
    pytest.fail("Seed variation did not change picks across 30 seeds")


def test_sample_unique_notes_constraint(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="kp", label="科普",
        source=NotesQuerySource(module="科普模块/挑选攻略"),
        pick_notes=3,
        pick_variants_per_note=1,
        constraints=["unique_notes"],
    )
    picks = sample_slot(slot, index, registry, seed=0, user_config={})
    assert len({p.note_id for p in picks}) == 3


def test_sample_brand_fixed(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="self", label="自有",
        source=BrandFixedSource(brand="CEWEY", model="CEWEYDS18"),
    )
    picks = sample_slot(slot, index, registry, seed=0, user_config={})
    assert len(picks) == 1
    assert picks[0].meta["brand"] == "CEWEY"
    assert picks[0].meta["model"] == "CEWEYDS18"


def test_sample_brand_pool_respects_user_config(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="comp", label="竞品",
        source=BrandPoolSource(exclude_brands=["CEWEY"]),
        pick_notes=PickCountSpec(user_configurable=True, default=2, range=[1, 5]),
    )
    picks = sample_slot(slot, index, registry, seed=0, user_config={"comp": 2})
    assert len(picks) == 2
    brands = {p.meta["brand"] for p in picks}
    assert "CEWEY" not in brands


def test_sample_user_config_out_of_range_raises(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="comp", label="竞品",
        source=BrandPoolSource(exclude_brands=["CEWEY"]),
        pick_notes=PickCountSpec(user_configurable=True, default=2, range=[1, 3]),
    )
    with pytest.raises(ValueError, match="out of range"):
        sample_slot(slot, index, registry, seed=0, user_config={"comp": 99})
    with pytest.raises(ValueError, match="out of range"):
        sample_slot(slot, index, registry, seed=0, user_config={"comp": 0})


def test_sample_empty_pool_raises(mini_vault_path: Path):
    index = scan_vault(mini_vault_path)
    registry = build_brand_registry(mini_vault_path)
    slot = Slot(
        id="x", label="X",
        source=NotesQuerySource(module="不存在模块"),
        pick_notes=1, pick_variants_per_note=1,
    )
    with pytest.raises(EmptyPoolError):
        sample_slot(slot, index, registry, seed=0, user_config={})
