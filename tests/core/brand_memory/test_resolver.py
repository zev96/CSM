from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.brand_memory.resolver import resolve_memory

VAULT = "营销资料库/产品模块/吸尘器"


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _make_vault(root: Path) -> None:
    _write(root / VAULT / "产品参数/CEWEYDS18-产品参数.md",
           "---\n产品: 吸尘器\n素材类型: 产品参数\n核心关键词: x\n---\n"
           "## 性能参数\n\n| 参数 | 数值 |\n|--|--|\n| 吸力(AW) | 220 |\n\n"
           "## 基础信息\n\n| 参数 | 数值 |\n|--|--|\n| 认证检测 | CE、FCC |\n")
    _write(root / VAULT / "希喂推荐内容/核心技术/吸尘器-CEWEY核心技术-动力系统①.md",
           "---\n产品: 吸尘器\n素材类型: 动力系统\n核心关键词: x\n---\n"
           "① 220AW强劲吸力。\n\n② 12万转电机。\n")
    _write(root / VAULT / "希喂推荐内容/品牌背书/吸尘器-CEWEY品牌背书-品牌定位①.md",
           "---\n产品: 吸尘器\n素材类型: 品牌定位\n核心关键词: x\n---\n"
           "① CEWEY 是技术型品牌。\n")
    _write(root / VAULT / "竞品推荐内容/竞品-戴森V12.md",
           "---\n产品: 吸尘器\n素材类型: 产品推荐理由\n核心关键词: x\n---\n"
           "① 戴森 V12 高端机型。\n")


def test_resolves_own_brand_deep(tmp_path):
    _make_vault(tmp_path)
    index = scan_vault(tmp_path)
    mem = resolve_memory("CEWEY", "DS18", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.role == "主推"
    assert mem.specs["吸力(AW)"].numbers == [220.0]
    assert mem.certs == ["CE", "FCC"]
    assert mem.scripts["动力系统"] == ["220AW强劲吸力。", "12万转电机。"]
    assert any("技术型品牌" in e for e in mem.endorsements)
    assert mem.coverage["has_tests"] is False


def test_resolves_competitor_shallow(tmp_path):
    _make_vault(tmp_path)
    index = scan_vault(tmp_path)
    mem = resolve_memory("戴森", "V12", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.role == "竞品"
    assert any("V12" in i for i in mem.intro)
    assert mem.scripts == {}   # 竞品无技术话术


def test_competitor_model_match_is_word_bounded(tmp_path):
    # 型号 "V1" 不应吃到 "戴森V12" 的竞品笔记（子串误匹配回归）。
    _write(tmp_path / VAULT / "竞品推荐内容/竞品-戴森V12.md",
           "---\n产品: 吸尘器\n素材类型: 产品推荐理由\n核心关键词: x\n---\n"
           "① 戴森 V12 高端机型。\n")
    index = scan_vault(tmp_path)
    mem = resolve_memory("戴森", "V1", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.intro == []   # V1 ≠ V12
