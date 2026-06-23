from pathlib import Path

import pytest

from csm_core.assembler.plan import AssemblyPlan, BlockResult
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.brand_memory.inject import (
    resolve_scopes, render_brand_facts, build_whitelist,
)
from csm_core.factcheck import check_facts

VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


def _ds18_scopes():
    index = scan_vault(VAULT)
    registry = build_brand_registry(VAULT)
    plan = AssemblyPlan(
        keyword="无线吸尘器", template_id="t", seed=0,
        results=[BlockResult(block_id="hero", kind="hero_brand", text="CEWEYDS18")])
    scopes = resolve_scopes(
        plan, index, registry, own_brands={"CEWEY"}, category="吸尘器")
    return scopes, render_brand_facts(scopes)


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_real_ds18_facts_have_specs_and_certs():
    scopes, facts = _ds18_scopes()
    assert scopes and scopes[0].model == "CEWEYDS18"
    assert "参数：" in facts            # specs 渲染到了
    assert scopes[0].memory.specs       # 有参数


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_real_faithful_draft_not_blocked():
    # 验收 #4：用注入事实本身当「忠实成稿」→ 不应被拦
    scopes, facts = _ds18_scopes()
    wl = build_whitelist(scopes, source_texts=[facts])
    report = check_facts(
        facts, allowed_numbers=wl.numbers, allowed_certs=wl.certs)
    assert report.ok, [v.model_dump() for v in report.violations]


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_real_fabricated_number_blocked():
    # 验收 #3：注入事实里塞一个白名单外的离谱参数 → 被拦
    scopes, facts = _ds18_scopes()
    wl = build_whitelist(scopes, source_texts=[facts])
    tampered = facts + "\n实测吸力高达99999AW，远超同级。"
    report = check_facts(
        tampered, allowed_numbers=wl.numbers, allowed_certs=wl.certs)
    assert report.ok is False
    assert any(v.value == "99999AW" for v in report.violations)
