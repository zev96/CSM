"""内容守卫：拆解后的 3 个 skill 必须去品牌 + role 正确。

钉死 Plan 4 的核心契约——品牌事实已从 skill 移除（改由 Plan 1-3 注入），
并验证 role 元数据。读真实 example 种子文件（即交付物本身）。
"""
from pathlib import Path

from csm_sidecar.services import skills_service

# 任一 token 出现 = 品牌事实泄漏（应来自记忆注入，不应硬编码进 skill）
BRAND_FACT_TOKENS = [
    "CEWEY", "希喂", "DS18", "220AW", "12万转", "35kPa", "35000Pa",
    "1700L", "555nm", "22项黑科技", "Quad-Stage", "Dual-HEPA", "DS 2.0",
]
DECOUPLED = {
    "家电科普博主": "persona",   # 原地改写=合并 skill
    "家电科普人设": "persona",
    "去AI味": "humanize",
}


def _skills_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "examples" / "skills"
        if cand.is_dir():
            return cand
    raise RuntimeError("找不到 examples/skills")


def test_decoupled_skills_exist_and_nonempty():
    d = _skills_dir()
    for sid in DECOUPLED:
        sk = skills_service.get_skill(d, sid)
        assert sk is not None, f"{sid} 缺失"
        assert sk.body.strip(), f"{sid} body 为空"


def test_decoupled_skills_have_no_brand_facts():
    d = _skills_dir()
    for sid in DECOUPLED:
        sk = skills_service.get_skill(d, sid)
        for tok in BRAND_FACT_TOKENS:
            assert tok not in sk.body, f"{sid} 仍含品牌事实 token: {tok!r}"


def test_decoupled_skill_roles():
    d = _skills_dir()
    for sid, role in DECOUPLED.items():
        assert skills_service.get_skill(d, sid).role == role, f"{sid} role 应为 {role}"


def test_inrepo_template_default_skill_still_resolves():
    """零迁移保证：default_skill_id: 家电科普博主 的模板 id 未变，仍解析到 skill。"""
    import json
    import pytest
    d = _skills_dir()
    tpl = d.parent.parent / "templates" / "导购·吸尘器·三品-r2j7.json"
    if not tpl.exists():
        pytest.skip("模板不在本检出")
    sid = json.loads(tpl.read_text(encoding="utf-8")).get("default_skill_id")
    assert sid == "家电科普博主"
    assert skills_service.get_skill(d, sid) is not None, f"模板引用 {sid} 断链"
