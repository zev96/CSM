"""B1.6：reroll 跟随 plan.angle（用户人群不跳出）。

用 real vault on disk 让 vault_index.query 真的按 frontmatter 过滤。
用户人群 module 下放多条 人群分类=铲屎官 + 一条 人群分类=老年人；
reroll 的 swap-in note 必须仍是 人群分类=铲屎官。
"""
from pathlib import Path
import random
from csm_core.vault.scanner import scan_vault
from csm_core.template.schema import (
    Template, NumberedListBlock, NotesQuerySource,
)
from csm_core.assembler.plan import AssemblyPlan, BlockResult, PickedVariant
from csm_core.assembler.reroll import reroll_pick
from csm_core.angle.model import Angle


def _write(vault: Path, rel: str, frontmatter: dict, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    p.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")


def _vault(vault: Path) -> None:
    # 三条铲屎官 note（reroll 才有别 note 可换）+ 一条老年人（不应被换入）
    _write(vault, "营销资料库/用户人群/吸尘器/铲屎官A.md",
           {"产品": "吸尘器", "人群分类": "铲屎官"}, "铲屎官文案A")
    _write(vault, "营销资料库/用户人群/吸尘器/铲屎官B.md",
           {"产品": "吸尘器", "人群分类": "铲屎官"}, "铲屎官文案B")
    _write(vault, "营销资料库/用户人群/吸尘器/铲屎官C.md",
           {"产品": "吸尘器", "人群分类": "铲屎官"}, "铲屎官文案C")
    _write(vault, "营销资料库/用户人群/吸尘器/老年人.md",
           {"产品": "吸尘器", "人群分类": "老年人"}, "老年人文案")


def _tpl() -> Template:
    return Template(
        id="t", name="T", product="吸尘器",
        blocks=[NumberedListBlock(
            id="rq", label="人群", source=NotesQuerySource(module="用户人群"),
            pick_notes=1,
        )],
    )


def _plan(angle) -> AssemblyPlan:
    # 当前 pick 是铲屎官A；reroll 应换到 铲屎官B/C 之一（老年人不可入）
    return AssemblyPlan(
        keyword="kw", template_id="t", seed=1, angle=angle,
        results=[BlockResult(
            block_id="rq", kind="numbered_list",
            picks=[PickedVariant(note_id="铲屎官A", variant_index=0, text="铲屎官文案A")],
            meta={"number_style": "1.", "item_separator": "\n\n"},
        )],
    )


def test_reroll_stays_within_audience(tmp_path):
    _vault(tmp_path)
    idx = scan_vault(tmp_path)
    tpl = _tpl()
    plan = _plan(Angle(audience="铲屎官"))
    # 跑多个 seed，确保从不换入老年人
    for s in range(12):
        new_plan = reroll_pick(plan, "rq", 0, tpl, idx, rng=random.Random(s))
        new_pick = new_plan.get_result("rq").picks[0]
        assert new_pick.note_id in {"铲屎官B", "铲屎官C"}
        assert "老年人" not in new_pick.text


def test_reroll_no_angle_unconstrained(tmp_path):
    """plan.angle=None → 行为同今天（纯 source.filter，可换入任意 note）。"""
    _vault(tmp_path)
    idx = scan_vault(tmp_path)
    tpl = _tpl()
    plan = _plan(None)
    # 没有角度约束 → 老年人 note 也在候选池；多 seed 应至少命中一次
    seen = set()
    for s in range(40):
        new_plan = reroll_pick(plan, "rq", 0, tpl, idx, rng=random.Random(s))
        seen.add(new_plan.get_result("rq").picks[0].note_id)
    assert "老年人" in seen, "无角度时老年人应可被换入"
