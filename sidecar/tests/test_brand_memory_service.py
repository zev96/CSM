from pathlib import Path

from csm_sidecar.services import brand_memory_service as svc

VAULT = "营销资料库/产品模块/吸尘器"


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
       "① 220AW强劲吸力。\n\n② 12万转高速电机。\n")
    _w(root / VAULT / "希喂推荐内容/品牌背书/吸尘器-CEWEY品牌背书-品牌定位①.md",
       "---\n产品: 吸尘器\n素材类型: 品牌定位\n核心关键词: x\n---\n① CEWEY 技术型品牌。\n")


def test_list_models_includes_role_and_coverage(tmp_path):
    _vault(tmp_path)
    rows = svc.list_models(tmp_path, category="吸尘器", own_brands={"CEWEY"})
    by_model = {r["model"]: r for r in rows}
    assert by_model["CEWEYDS18"]["brand"] == "CEWEY"
    assert by_model["CEWEYDS18"]["role"] == "主推"
    assert by_model["CEWEYDS18"]["coverage"]["has_specs"] is True
    assert by_model["戴森V12"]["role"] == "竞品"


def test_get_model_detail_has_specs_and_inject_preview(tmp_path):
    _vault(tmp_path)
    d = svc.get_model_detail(
        tmp_path, "CEWEYDS18", category="吸尘器", own_brands={"CEWEY"},
        variant_cap=3, endorsement_cap=5)
    assert d is not None
    assert d["model_full"] == "CEWEYDS18"
    assert d["specs"]["吸力(AW)"]["numbers"] == [220.0]
    assert "CE" in d["certs"]
    # 注入预览 = render_brand_facts，应含参数原文 + 话术
    assert "220" in d["inject_preview"]
    assert "技术型品牌" in d["inject_preview"]


def test_get_model_detail_unknown_returns_none(tmp_path):
    _vault(tmp_path)
    assert svc.get_model_detail(
        tmp_path, "杂牌X9", category="吸尘器", own_brands={"CEWEY"},
        variant_cap=3, endorsement_cap=5) is None
