"""B1.3：sampler 按角度过滤用户人群块 + 空池回退。

用 real vault on disk（同 test_block_sampler.py 风格）。用户人群块的 note 带
``人群分类`` frontmatter，module 路径含「用户人群」标记。
"""
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.assembler.sampler import sample_block
from csm_core.template.schema import (
    NumberedListBlock, ParagraphBlock, NotesQuerySource,
)
from csm_core.angle.model import Angle


def _write(vault: Path, rel: str, frontmatter: dict, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    p.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")


def _renqun_vault(vault: Path) -> None:
    # 「用户人群」module 下两条不同 人群分类 的 note
    _write(vault, "营销资料库/用户人群/吸尘器/铲屎官.md",
           {"产品": "吸尘器", "人群分类": "铲屎官"}, "铲屎官痛点文案")
    _write(vault, "营销资料库/用户人群/吸尘器/老年人.md",
           {"产品": "吸尘器", "人群分类": "老年人"}, "老年人痛点文案")


def test_audience_filters_renqun_block(tmp_path):
    """angle.audience=铲屎官 → 只采到 人群分类=铲屎官 的 note。"""
    _renqun_vault(tmp_path)
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = NumberedListBlock(
        id="rq", label="人群", source=NotesQuerySource(module="用户人群"),
        pick_notes=5,  # 想多采，但池被角度过滤后只剩 1 条
    )
    br = sample_block(blk, idx, reg, seed=7, user_config={},
                      angle=Angle(audience="铲屎官"))
    assert br.picks, "should pick at least one"
    assert all("铲屎官" in p.text for p in br.picks)
    assert all("老年人" not in p.text for p in br.picks)


def test_unmatched_audience_falls_back_no_empty(tmp_path):
    """angle 含未命中人群（空池）→ 回退不过滤池（不抛 EmptyPoolError）。"""
    _renqun_vault(tmp_path)
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = NumberedListBlock(
        id="rq", label="人群", source=NotesQuerySource(module="用户人群"),
        pick_notes=1,
    )
    br = sample_block(blk, idx, reg, seed=1, user_config={},
                      angle=Angle(audience="火星人"))  # 没有此 人群分类
    assert br.picks, "回退后池非空，应仍采到（不抛 EmptyPoolError）"


def test_non_renqun_block_unaffected_by_angle(tmp_path):
    """非用户人群 module 块不受 angle 影响（仍按 source.filter 采全池）。"""
    _write(tmp_path, "营销资料库/科普模块/吸尘器/a.md",
           {"产品": "吸尘器"}, "科普文案A")
    _write(tmp_path, "营销资料库/科普模块/吸尘器/b.md",
           {"产品": "吸尘器"}, "科普文案B")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blk = ParagraphBlock(
        id="kp", label="科普", source=NotesQuerySource(module="科普模块"),
        pick_notes=1, pick_variants_per_note=1,
    )
    # 即便传 audience，科普块不带「用户人群」标记 → 不加 人群分类 filter
    br = sample_block(blk, idx, reg, seed=2, user_config={},
                      angle=Angle(audience="铲屎官"))
    assert br.picks
    assert "科普文案" in br.picks[0].text
