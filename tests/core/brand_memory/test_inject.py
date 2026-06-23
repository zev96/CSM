from pathlib import Path

from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.brand_memory.inject import (
    resolve_scopes, render_brand_facts, build_whitelist,
)

VAULT = "营销资料库/产品模块/吸尘器"
TESTS = "营销资料库/测试项目模块/吸尘器"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _vault(root: Path) -> None:
    _w(root / VAULT / "产品参数/CEWEYDS18-产品参数.md",
       "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
       "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 220 |\n"
       "| 电机转速 | 12万转 |\n\n"
       "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 认证检测 | CE、FCC |\n")
    _w(root / VAULT / "产品参数/戴森V12-产品参数.md",
       "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
       "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 240 |\n")
    _w(root / VAULT / "希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md",
       "---\n产品: 吸尘器\n素材类型: 动力系统\n核心关键词: x\n---\n"
       "① 220AW强劲吸力。\n\n② 12万转高速电机。\n\n③ 双层增压。\n\n④ 第四条变体。\n")
    _w(root / VAULT / "希喂推荐内容/品牌背书/吸尘器-CEWEY品牌背书-品牌定位①.md",
       "---\n产品: 吸尘器\n素材类型: 品牌定位\n核心关键词: x\n---\n① CEWEY 技术型品牌。\n")
    _w(root / VAULT / "竞品推荐内容/竞品-戴森V12.md",
       "---\n产品: 吸尘器\n素材类型: 产品推荐理由\n核心关键词: x\n---\n① 戴森V12 高端机型。\n")


def _plan() -> AssemblyPlan:
    return AssemblyPlan(
        keyword="无线吸尘器哪款好", template_id="t", seed=0,
        results=[
            BlockResult(block_id="hero", kind="hero_brand", text="CEWEYDS18"),
            BlockResult(block_id="comp", kind="competitor_pool", picks=[
                PickedVariant(note_id="竞品-戴森V12", variant_index=0, text="...",
                              meta={"title": "戴森V12", "model": "竞品-戴森V12"}),
            ]),
            BlockResult(block_id="junk", kind="hero_brand", text="不是型号的标题"),
        ],
    )


def _scopes(tmp_path: Path):
    _vault(tmp_path)
    index = scan_vault(tmp_path)
    registry = build_brand_registry(tmp_path)
    return resolve_scopes(
        _plan(), index, registry, own_brands={"CEWEY"}, category="吸尘器",
    )


def test_resolve_scopes_registry_anchored(tmp_path):
    scopes = _scopes(tmp_path)
    by_model = {s.model: s for s in scopes}
    assert set(by_model) == {"CEWEYDS18", "戴森V12"}   # 垃圾标题被丢弃
    assert by_model["CEWEYDS18"].brand == "CEWEY"
    assert by_model["CEWEYDS18"].role == "主推"
    assert by_model["戴森V12"].role == "竞品"


def test_render_brand_facts_caps_variants_and_uses_raw_specs(tmp_path):
    scopes = _scopes(tmp_path)
    facts = render_brand_facts(scopes, variant_cap=3, endorsement_cap=5)
    assert "吸力(AW): 220" in facts
    assert "电机转速: 12万转" in facts        # specs 用原始文本（万 不展开）
    assert "CE、FCC" in facts
    assert facts.count("第四条变体") == 0      # 每维度 ≤3 变体
    assert "技术型品牌" in facts               # 背书


def test_build_whitelist_unions_specs_and_sources(tmp_path):
    scopes = _scopes(tmp_path)
    facts = render_brand_facts(scopes)
    wl = build_whitelist(scopes, source_texts=["草稿提到 1700L/min。", facts])
    assert 220.0 in wl.numbers          # CEWEY specs
    assert 240.0 in wl.numbers          # 竞品 specs（也并入）
    assert 120000.0 in wl.numbers       # 12万转 经 normalize 展开（来自 facts 文本）
    assert 1700.0 in wl.numbers         # 来自 draft 源文本
    assert "CE" in wl.certs and "FCC" in wl.certs
