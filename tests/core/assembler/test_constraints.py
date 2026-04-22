from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.template.schema import Template
from csm_core.assembler.constraints import assemble_plan


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


def test_assemble_runs_all_block_kinds(tmp_path):
    _write(tmp_path, "A/a.md", "段落 A")
    tpl = _mktpl([
        {"kind": "heading", "id": "h1", "level": 2, "text": "题"},
        {"kind": "paragraph", "id": "p1", "label": "A",
         "source": {"type": "notes_query", "module": "A"}},
        {"kind": "literal", "id": "l1", "text": "end"},
    ])
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    plan = assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={},
    )
    kinds = [r.kind for r in plan.results]
    assert kinds == ["heading", "paragraph", "literal"]
    assert plan.results[1].picks[0].text.strip() == "段落 A"


def test_paragraph_children_are_sampled_nested(tmp_path):
    _write(tmp_path, "P/parent.md", "父")
    _write(tmp_path, "P/child.md", "子")
    tpl = _mktpl([{
        "kind": "paragraph", "id": "p1", "label": "parent",
        "source": {"type": "notes_query", "module": "P"},
        "children": [{
            "kind": "paragraph", "id": "p1_1", "label": "child",
            "source": {"type": "notes_query", "module": "P"},
        }],
    }])
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    plan = assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={},
    )
    assert plan.results[0].children[0].block_id == "p1_1"
    assert plan.results[0].children[0].picks
