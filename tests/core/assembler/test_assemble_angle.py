"""B1.2：assemble_plan 透传 angle 并落 plan.angle。

复用既有 assembler 测试夹具风格（real vault on disk + _mktpl）。
这里只验透传 + 落 plan.angle；过滤行为在 B1.3 测。
"""
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.schema import Template
from csm_core.assembler.constraints import assemble_plan
from csm_core.angle.model import Angle


def _mktpl(blocks):
    return Template.model_validate({
        "id": "t", "name": "T", "product": "吸尘器", "version": 1,
        "system_prompt_default": "",
        "seo_defaults": {},
        "blocks": blocks,
    })


def _write(vault: Path, rel: str, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n产品: 吸尘器\n---\n{body}\n", encoding="utf-8")


def _plan_with_angle(tmp_path: Path, angle):
    _write(tmp_path, "A/a.md", "段落 A")
    tpl = _mktpl([
        {"kind": "paragraph", "id": "p1", "label": "A",
         "source": {"type": "notes_query", "module": "A"}},
    ])
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    return assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={}, angle=angle,
    )


def test_assemble_plan_stores_angle(tmp_path):
    angle = Angle(audience="铲屎官")
    plan = _plan_with_angle(tmp_path, angle)
    assert plan.angle == angle


def test_assemble_plan_no_angle_stays_none(tmp_path):
    plan = _plan_with_angle(tmp_path, None)
    assert plan.angle is None
