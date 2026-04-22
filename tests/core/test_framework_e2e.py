"""Full pipeline → draft text, verifying framework layout takes effect.

This uses a minimal in-memory vault so we don't depend on any specific
template / vault shape the project may have today.

Key fixture notes:
- Vault note variants are split on circled-number markers (①②③…), NOT on
  Markdown ``---`` horizontal rules.  Two sci variants = body starting with
  ``① …\n\n② …``.
- ``build_prompt`` lives in ``csm_core.llm.prompts`` but is imported into
  ``csm_core.pipeline``; monkeypatching ``csm_core.pipeline.build_prompt``
  intercepts the call correctly.
- ``PromptInputs`` is a dataclass with a ``.draft`` attribute — the spy
  captures ``inputs.draft`` (the framed draft before the LLM call).
"""
import json
from pathlib import Path
import pytest
from csm_core.pipeline import GenerateRequest, generate


class _FakeLLM:
    def complete(self, system: str, user: str) -> str:
        return "LLM-OUT"


def _write_vault(root: Path) -> None:
    (root / "intro").mkdir(parents=True)
    (root / "intro" / "a.md").write_text(
        "---\n素材类型: 引言痛点\n---\n痛点正文", encoding="utf-8"
    )
    (root / "sci").mkdir(parents=True)
    # Two variants split by circled-number markers (the vault scanner
    # recognises ①/② lines as variant boundaries, NOT "---" separators).
    (root / "sci" / "b.md").write_text(
        "---\n素材类型: 科普\n---\n① 科普1\n\n② 科普2", encoding="utf-8"
    )
    (root / "brand").mkdir(parents=True)
    (root / "brand" / "c.md").write_text(
        "---\n素材类型: 推荐\n品牌: CEWEY\n型号: DS18\n---\n这是好货",
        encoding="utf-8",
    )


def _write_template(path: Path) -> None:
    path.write_text(json.dumps({
        "id": "test-tpl", "name": "T", "product": "P",
        "default_framework": "e2e",
        "slots": [
            {"id": "intro", "label": "intro",
             "source": {"type": "notes_query", "module": "intro",
                        "filter": {"素材类型": "引言痛点"}},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
            {"id": "sci", "label": "sci",
             "source": {"type": "notes_query", "module": "sci",
                        "filter": {"素材类型": "科普"}},
             "pick_notes": 1, "pick_variants_per_note": 2,
             "constraints": [], "depends_on": []},
            {"id": "brand", "label": "brand",
             "source": {"type": "notes_query", "module": "brand",
                        "filter": {"素材类型": "推荐"}},
             "pick_notes": 1, "pick_variants_per_note": 1,
             "constraints": [], "depends_on": []},
        ],
        "render_order": ["intro", "sci", "brand"],
    }, ensure_ascii=False), encoding="utf-8")


def _write_framework(path: Path) -> None:
    path.write_text(json.dumps({
        "id": "e2e", "name": "E2E", "variables": ["keyword"],
        "blocks": [
            {"kind": "paragraph", "slot": "intro"},
            {"kind": "heading", "level": 2, "index": "一",
             "text": "{keyword}怎么选"},
            {"kind": "numbered_list", "slot": "sci"},
            {"kind": "heading", "level": 2, "index": "二",
             "text": "{keyword}推荐"},
            {"kind": "brand_reason_list", "slots": ["brand"],
             "reason_label": "推荐理由："},
        ],
    }, ensure_ascii=False), encoding="utf-8")


def test_full_pipeline_applies_framework(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_vault(vault)

    tpl_path = tmp_path / "t.json"
    _write_template(tpl_path)

    fw_dir = tmp_path / "frameworks"
    fw_dir.mkdir()
    _write_framework(fw_dir / "e2e.json")

    captured: dict[str, str] = {}
    import csm_core.pipeline as pmod
    orig_build = pmod.build_prompt
    def _spy(inputs):
        captured["draft"] = inputs.draft
        return orig_build(inputs)
    monkeypatch.setattr(pmod, "build_prompt", _spy)

    req = GenerateRequest(
        keyword="吸尘器", vault_root=vault, template_path=tpl_path,
        out_dir=tmp_path / "out", llm_client=_FakeLLM(), seed=1,
        frameworks_dir=fw_dir,
    )
    (tmp_path / "out").mkdir()
    res = generate(req)
    assert res.final_text == "LLM-OUT"

    draft = captured["draft"]
    assert "## 一、吸尘器怎么选" in draft
    assert "## 二、吸尘器推荐" in draft
    assert "1. " in draft
    assert "1.CEWEY DS18 吸尘器" in draft
    assert "推荐理由：" in draft
