"""版本组：抽签确定性、过滤、覆盖、批量共享版本、零回归。"""
from pathlib import Path

import pytest

from csm_core.assembler.constraints import assemble_plan, draw_versions
from csm_core.assembler.render import compose_draft
from csm_core.template.schema import Template
from csm_core.vault.brand_registry import build_brand_registry
from csm_core.vault.scanner import scan_vault


def _write(vault: Path, rel: str, body: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n产品: 吸尘器\n---\n{body}\n", encoding="utf-8")


def _tpl(blocks, groups=None):
    payload = {
        "id": "t", "name": "T", "product": "吸尘器", "blocks": blocks,
    }
    if groups is not None:
        payload["version_groups"] = groups
    return Template.model_validate(payload)


_GROUP = [{"id": "ver", "label": "推荐区版本", "options": ["版本1", "版本2"]}]


def _two_version_tpl():
    return _tpl(
        [
            {"kind": "literal", "id": "shared", "text": "共同引言"},
            {"kind": "paragraph", "id": "v1_p", "label": "口碑",
             "source": {"type": "notes_query", "module": "V1"},
             "versions": ["版本1"]},
            {"kind": "paragraph", "id": "v2_p", "label": "功能",
             "source": {"type": "notes_query", "module": "V2"},
             "versions": ["版本2"]},
        ],
        _GROUP,
    )


def _vault(tmp_path: Path):
    _write(tmp_path, "V1/a.md", "版本一素材")
    _write(tmp_path, "V2/b.md", "版本二素材")
    return scan_vault(tmp_path), build_brand_registry(tmp_path)


# ── 抽签 ────────────────────────────────────────────────────────────
def test_draw_is_deterministic_per_seed():
    tpl = _two_version_tpl()
    assert draw_versions(tpl, seed=7) == draw_versions(tpl, seed=7)


def test_draw_covers_both_options_across_seeds():
    tpl = _two_version_tpl()
    seen = {draw_versions(tpl, seed=s)["ver"] for s in range(20)}
    assert seen == {"版本1", "版本2"}


def test_draw_no_streak_across_consecutive_low_seeds():
    """相邻整数 seed 不能系统性连出同一版本。

    「重新随机」每次 seed+1；早期 key 把 seed 放开头（``{seed}::version::gid``），
    相邻 seed 的首个 .random() 高度相关 —— 用户从 seed 0 连点一直是同一版本，
    看着像「版本锁死」。seed 放末尾后打散。

    ⚠ 必须用**生产同款 group id** ``rec_ver``：这个缺陷与 gid 强相关，旧 key 下
    ``rec_ver`` 的 seed 0..6 恰好连出 7 个版本2（真机就是它），而随手取的
    ``ver`` 在旧 key 下本就混合 —— 用 ``ver`` 测这条会**在带 bug 的旧 key 上照样
    通过**，成为守不住回归的纸老虎（对抗性审查实测坐实）。这里钉「rec_ver 头 7
    个连续 seed 两个版本都出现」，旧 key 上会真失败。
    """
    tpl = _tpl(
        [{"kind": "literal", "id": "l", "text": "x", "versions": ["版本1"]}],
        [{"id": "rec_ver", "options": ["版本1", "版本2"]}],
    )
    first7 = {draw_versions(tpl, seed=s)["rec_ver"] for s in range(7)}
    assert first7 == {"版本1", "版本2"}


def test_version_rng_namespace_cannot_collide_with_block_key():
    """版本 RNG key 含 ``::`` 命名空间，块 key 用 ``-`` 连接 —— 名叫
    ``version-ver`` 的块也不会与版本抽签共享随机流。"""
    tpl = _tpl(
        [{"kind": "literal", "id": "version-ver", "text": "x"}],
        _GROUP,
    )
    import random
    block_key_rng = random.Random("0-version-ver")
    version_rng = random.Random("version::ver::0")   # 与 draw_versions 现用格式一致
    assert block_key_rng.random() != version_rng.random()


def test_overrides_win_over_draw():
    tpl = _two_version_tpl()
    forced = draw_versions(tpl, seed=1, overrides={"ver": "版本2"})
    assert forced["ver"] == "版本2"


def test_bogus_override_falls_back_to_draw():
    tpl = _two_version_tpl()
    got = draw_versions(tpl, seed=1, overrides={"ver": "不存在的版本"})
    assert got["ver"] in {"版本1", "版本2"}


def test_disabled_option_never_drawn():
    tpl = _tpl(
        [{"kind": "literal", "id": "l", "text": "x", "versions": ["版本1"]}],
        [{"id": "ver", "options": ["版本1", "版本2"],
          "disabled_options": ["版本2"]}],
    )
    assert {draw_versions(tpl, seed=s)["ver"] for s in range(15)} == {"版本1"}


def test_all_options_disabled_rejected():
    with pytest.raises(ValueError, match="至少留一个可用版本"):
        _tpl(
            [{"kind": "literal", "id": "l", "text": "x"}],
            [{"id": "ver", "options": ["版本1"], "disabled_options": ["版本1"]}],
        )


# ── 过滤 ────────────────────────────────────────────────────────────
def test_filter_keeps_only_chosen_version_blocks(tmp_path):
    idx, reg = _vault(tmp_path)
    tpl = _two_version_tpl()
    plan = assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={}, version_overrides={"ver": "版本1"},
    )
    ids = [r.block_id for r in plan.results]
    assert ids == ["shared", "v1_p"]
    assert plan.version_choices == {"ver": "版本1"}

    plan2 = assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={}, version_overrides={"ver": "版本2"},
    )
    assert [r.block_id for r in plan2.results] == ["shared", "v2_p"]


def test_untagged_blocks_visible_in_every_version(tmp_path):
    idx, reg = _vault(tmp_path)
    tpl = _two_version_tpl()
    for opt in ("版本1", "版本2"):
        plan = assemble_plan(
            keyword="k", template=tpl, index=idx, registry=reg,
            seed=0, user_config={}, version_overrides={"ver": opt},
        )
        assert "shared" in [r.block_id for r in plan.results]


def test_version_seed_decouples_structure_from_material(tmp_path):
    """批量候选：素材 seed 各异、版本 seed 统一 ⇒ 同结构不同素材。"""
    idx, reg = _vault(tmp_path)
    tpl = _two_version_tpl()
    base = 3
    choices = {
        assemble_plan(
            keyword="k", template=tpl, index=idx, registry=reg,
            seed=base + k * 1000, user_config={}, version_seed=base,
        ).version_choices["ver"]
        for k in range(4)
    }
    assert len(choices) == 1


# ── 零回归 ──────────────────────────────────────────────────────────
def test_no_version_groups_is_byte_identical(tmp_path):
    """没有版本组的模板：过滤恒真、不创建版本 RNG，输出逐字节不变。"""
    _write(tmp_path, "A/a.md", "① 甲\n② 乙\n③ 丙")
    _write(tmp_path, "A/b.md", "① 丁\n② 戊")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    tpl = _tpl([
        {"kind": "heading", "id": "h", "level": 2, "text": "题"},
        {"kind": "paragraph", "id": "p", "label": "A",
         "source": {"type": "notes_query", "module": "A"}},
        {"kind": "numbered_list", "id": "n", "label": "L",
         "source": {"type": "notes_query", "module": "A"}, "pick_notes": 2},
    ])
    drafts = {
        compose_draft(assemble_plan(
            keyword="无线吸尘器", template=tpl, index=idx, registry=reg,
            seed=s, user_config={},
        ))
        for s in (0, 1, 2)
    }
    # 三个种子各自稳定复现（同 seed 再跑一次结果一致）
    for s in (0, 1, 2):
        a = compose_draft(assemble_plan(
            keyword="无线吸尘器", template=tpl, index=idx, registry=reg,
            seed=s, user_config={},
        ))
        b = compose_draft(assemble_plan(
            keyword="无线吸尘器", template=tpl, index=idx, registry=reg,
            seed=s, user_config={},
        ))
        assert a == b
    assert len(drafts) >= 1
    # 没有版本组 ⇒ version_choices 为空，不污染 plan JSON 语义
    plan = assemble_plan(
        keyword="k", template=tpl, index=idx, registry=reg,
        seed=0, user_config={},
    )
    assert plan.version_choices == {}


def test_version_draw_does_not_perturb_block_streams(tmp_path):
    """加了版本组之后，同一个块在相同 seed 下抽到的素材不变 ——
    块 RNG 以 block.id 为键，与版本抽签互不干扰。"""
    _write(tmp_path, "A/a.md", "① 甲\n② 乙\n③ 丙\n④ 丁")
    idx = scan_vault(tmp_path)
    reg = build_brand_registry(tmp_path)
    blocks = [{"kind": "paragraph", "id": "p", "label": "A",
               "source": {"type": "notes_query", "module": "A"}}]
    plain = assemble_plan(
        keyword="k", template=_tpl(blocks), index=idx, registry=reg,
        seed=5, user_config={},
    )
    versioned = assemble_plan(
        keyword="k", template=_tpl(blocks, _GROUP), index=idx, registry=reg,
        seed=5, user_config={},
    )
    assert plain.results[0].picks[0].text == versioned.results[0].picks[0].text
