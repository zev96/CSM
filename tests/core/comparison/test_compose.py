"""横评确定性骨架 compose_comparison_draft 单测（合成 memory fixtures）。"""
from __future__ import annotations

from csm_core.brand_memory.inject import ModelScope
from csm_core.brand_memory.model import BrandModelMemory, SpecValue
from csm_core.comparison.compose import _pick_sellpoint_dims, _model_label


def _mem(brand: str, model: str, role: str, *,
         specs: dict[str, str] | None = None,
         scripts: dict[str, list[str]] | None = None,
         certs: list[str] | None = None,
         endorsements: list[str] | None = None,
         tests: dict[str, str] | None = None) -> BrandModelMemory:
    spec_objs = {}
    for f, raw in (specs or {}).items():
        nums = [float(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", raw)]
        spec_objs[f] = SpecValue(field=f, raw=raw, numbers=nums)
    return BrandModelMemory(
        brand=brand, model=model, category="吸尘器", role=role,
        specs=spec_objs, certs=certs or [], scripts=scripts or {},
        endorsements=endorsements or [], intro=[], tests=tests or {})


def _scope(brand: str, model: str, role: str, **kw) -> ModelScope:
    return ModelScope(brand=brand, model=model, role=role,
                      memory=_mem(brand, model, role, **kw))


def test_pick_sellpoint_dims_one_variant_cap_three():
    scripts = {
        "动力系统": ["强劲吸力 A", "强劲吸力 B"],
        "过滤系统": ["HEPA A"],
        "防缠绕技术": ["防缠 A"],
        "噪音大小": ["静音 A"],
    }
    picked = _pick_sellpoint_dims(scripts)
    # 每维取第 1 变体，最多 3 维（插入序）
    assert picked == [
        ("动力系统", "强劲吸力 A"),
        ("过滤系统", "HEPA A"),
        ("防缠绕技术", "防缠 A"),
    ]


def test_pick_sellpoint_dims_empty_for_competitor():
    assert _pick_sellpoint_dims({}) == []


def test_model_label_brand_space_model():
    sc = _scope("CEWEY", "CEWEYDS18", "主推")
    assert _model_label(sc) == "CEWEY CEWEYDS18"
