"""模板结构 lint —— 版本标签的防错层。

版本统一（主推抽版本1 ⇒ 竞品也版本1）在机制上由「一次抽签、多处消费」
保证；但那只在**块都标对了版本**时成立。漏标一个块（``versions=[]`` =
全版本可见）会让它出现在每个版本里，把另一个版本的推荐区结构搅乱，而且
不报错、只在某几次生成里显形 —— 所以必须有静态检查。

这里按每个版本 option 模拟一遍过滤后的序列，检查结构自洽。返回
``LintIssue`` 列表；``level="error"`` 的问题阻断保存，``level="warning"``
的只提示（旧模板、以及故意的边缘用法不该被卡死）。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Literal

from .schema import (
    CompetitorPoolBlock, HeroBrandBlock, ParagraphBlock, Template,
    TestFrameworkBlock, VersionGroup,
)

LintLevel = Literal["error", "warning"]

# 会被 hero 区域「吞并」的块类型 —— 它们出现在 hero…竞品池之间时，输出
# 归属于主推卡而不是顶层段落，所以漏标版本的后果最严重。
_REGION_BODY_KINDS = ("paragraph", "numbered_list")


@dataclass(frozen=True)
class LintIssue:
    level: LintLevel
    code: str
    message: str
    block_id: str | None = None
    version: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "block_id": self.block_id,
            "version": self.version,
        }


def _combinations(groups: list[VersionGroup]) -> Iterable[dict[str, str]]:
    """所有版本组的抽签组合。单组模板就是每个 option 一条。

    只枚举**启用**的 option —— 被禁用的版本压根不会被抽中（素材还没铺齐
    才禁用的），拿它去判 error 会把一个正常模板锁得存不下去。
    多版本组是笛卡尔积；组数在 UI 上限制为 1，真出现多组时组合数也可控。
    """
    if not groups:
        return []
    for combo in product(*[g.enabled_options() for g in groups]):
        yield {g.id: opt for g, opt in zip(groups, combo)}


def _visible(template: Template, choices: dict[str, str]) -> list:
    return [b for b in template.blocks if template.is_visible(b, choices)]


def _referenced_ids(block) -> list[str]:
    """块引用的其他块 id —— follow_slot（测试框架）与 depends_on（段落）。"""
    out: list[str] = []
    if isinstance(block, TestFrameworkBlock) and block.follow_slot:
        out.extend(x.strip() for x in block.follow_slot.split("+") if x.strip())
    src = getattr(block, "source", None)
    if src is not None and getattr(src, "type", "") == "test_results_aligned":
        out.extend(x.strip() for x in src.follow_slot.split("+") if x.strip())
    if isinstance(block, ParagraphBlock):
        out.extend(block.depends_on)
    return out


def lint_template(template: Template) -> list[LintIssue]:
    """检查模板结构。无版本组的模板只跑通用检查。"""
    issues: list[LintIssue] = []
    issues.extend(_lint_regions_generic(template))
    if not template.version_groups:
        return issues

    issues.extend(_lint_option_coverage(template))
    for choices in _combinations(template.version_groups):
        issues.extend(_lint_one_version(template, choices))
    return issues


def _version_label(choices: dict[str, str]) -> str:
    return " / ".join(choices.values())


def _lint_option_coverage(template: Template) -> list[LintIssue]:
    """每个 option 至少被一个块引用 —— 否则抽中它时推荐区整块消失。"""
    used: set[str] = set()
    for b in template.blocks:
        for v in getattr(b, "versions", None) or []:
            used.add(v)
    issues: list[LintIssue] = []
    for g in template.version_groups:
        for opt in g.enabled_options():
            if opt not in used:
                issues.append(LintIssue(
                    level="warning", code="empty_version", version=opt,
                    message=(
                        f"版本「{opt}」没有任何块标了它 —— 抽中这个版本时"
                        f"该版本专属内容会整块缺失。要么给块打上标签，"
                        f"要么在版本组里先禁用它。"
                    ),
                ))
    return issues


def _lint_regions_generic(template: Template) -> list[LintIssue]:
    """与版本无关的榜单区检查。

    这些规则**不能**只在有版本组时跑 —— 榜单模板完全可以不用版本组，
    而卡片/legacy 混用、卡片池没有主推这些问题与版本毫无关系。
    """
    issues: list[LintIssue] = []
    for hero, pools in _regions(template.blocks):
        card_pools = [p for p in pools if getattr(p, "sections", None)]
        if hero is None:
            if card_pools:
                issues.append(LintIssue(
                    level="warning", code="pool_without_hero",
                    block_id=card_pools[0].id,
                    message=(
                        f"卡片竞品池 '{card_pools[0].id}' 前面没有主推卡 —— "
                        f"排位会从 TOP1 开始编号。"
                    ),
                ))
            continue
        hero_card = bool(getattr(hero, "sections", None))
        for pool in pools:
            pool_card = bool(getattr(pool, "sections", None))
            if pool_card != hero_card:
                issues.append(LintIssue(
                    level="error", code="mixed_card_legacy", block_id=pool.id,
                    message=(
                        f"榜单区里主推块 '{hero.id}' 与竞品池 '{pool.id}' 一个是"
                        f"卡片模式、一个是旧模式 —— 两者渲染语义不同，不能混用。"
                        f"要么两边都配小节，要么都不配。"
                    ),
                ))
        # 同一榜单区必须挂同一个版本组，否则主推与竞品各抽各的签 —— 「主推
        # 版本1 ⇒ 竞品也版本1」这条核心约束会被彻底绕开（同篇出两个 TOP1）。
        if len(template.version_groups) > 1:
            hero_group = template.group_of(hero)
            for pool in pools:
                pool_group = template.group_of(pool)
                if (hero_group and pool_group
                        and hero_group.id != pool_group.id):
                    issues.append(LintIssue(
                        level="error", code="mixed_version_group",
                        block_id=pool.id,
                        message=(
                            f"主推块 '{hero.id}' 挂在版本组 '{hero_group.id}'、"
                            f"竞品池 '{pool.id}' 挂在 '{pool_group.id}' —— 两组各抽"
                            f"各的签，主推和竞品会落到不同版本。同一榜单区必须"
                            f"用同一个版本组。"
                        ),
                    ))
    return issues


def _regions(blocks: list) -> list[tuple[object | None, list]]:
    """把块序列切成榜单区：(hero, [竞品池…])。

    区域从 hero_brand 开始，到下一个 hero_brand / heading 结束；中间的
    竞品池都算这个区的（深浅双池：TOP2-3 一个池、TOP4-10 另一个池）。
    没有 hero 的孤立竞品池以 ``hero=None`` 单独成区。
    """
    regions: list[tuple[object | None, list]] = []
    current_hero = None
    current_pools: list = []
    open_region = False

    def close():
        nonlocal current_hero, current_pools, open_region
        if open_region:
            regions.append((current_hero, current_pools))
        current_hero, current_pools, open_region = None, [], False

    for b in blocks:
        if isinstance(b, HeroBrandBlock):
            close()
            current_hero, current_pools, open_region = b, [], True
        elif isinstance(b, CompetitorPoolBlock):
            if not open_region:
                current_hero, current_pools, open_region = None, [], True
            current_pools.append(b)
        elif b.kind == "heading":
            close()
    close()
    return regions


def _lint_one_version(template: Template, choices: dict[str, str]) -> list[LintIssue]:
    visible = _visible(template, choices)
    visible_ids = {b.id for b in visible}
    label = _version_label(choices)
    issues: list[LintIssue] = []

    # ① 跨版本引用：follow_slot / depends_on 指向了本版本看不见的块。
    #    引擎对此只发 warning 然后渲染「缺数据：未选中产品」占位 —— 静默
    #    残文，必须在保存期就拦下来。
    for b in visible:
        for ref in _referenced_ids(b):
            if ref not in visible_ids:
                issues.append(LintIssue(
                    level="error", code="cross_version_ref",
                    block_id=b.id, version=label,
                    message=(
                        f"版本「{label}」下，块 '{b.id}' 引用了 '{ref}'，"
                        f"但 '{ref}' 在这个版本里不可见 —— 生成时会出现"
                        f"「缺数据」占位。请给 '{ref}' 补上该版本标签，"
                        f"或给 '{b.id}' 收窄版本范围。"
                    ),
                ))

    # ② 漏标夹心块：某版本的 hero 区域中间夹着未标版本的块。它在别的版本
    #    里会变成孤儿顶层段落（或者被另一个版本的 hero 吞并），是最典型的
    #    漏标事故。只在 hero…最后一个竞品池之间查 —— 区域没有池时不能一路
    #    查到文末，否则收尾段落会被误报成夹心块。
    for hero, pools in _regions(visible):
        if hero is None or not pools:
            continue
        hero_versions = getattr(hero, "versions", None) or []
        if not hero_versions:
            continue
        start = visible.index(hero)
        end = visible.index(pools[-1])
        for b in visible[start + 1:end + 1]:
            if b.kind not in _REGION_BODY_KINDS:
                continue
            if getattr(b, "versions", None):
                continue
            issues.append(LintIssue(
                level="warning", code="untagged_in_region",
                block_id=b.id, version=label,
                message=(
                    f"块 '{b.id}' 夹在版本「{label}」的推荐区里但没标版本 —— "
                    f"它会同时出现在其他版本，很可能是漏标。"
                ),
            ))

    # ③ 主推卡/竞品池自身漏标 —— 这两个才是本方案里真正需要打标签的块
    #    （每版本就它俩），漏标的后果最严重：同一篇里出现两个 TOP1、两个
    #    版本的点混在一起。早期版本只查 paragraph/numbered_list，恰好把最
    #    该查的两类漏掉了。
    for hero, pools in _regions(visible):
        members = ([hero] if hero is not None else []) + list(pools)
        tagged = [b for b in members if getattr(b, "versions", None)]
        untagged = [b for b in members if not getattr(b, "versions", None)]
        if tagged and untagged:
            for b in untagged:
                issues.append(LintIssue(
                    level="warning", code="untagged_card_block",
                    block_id=b.id, version=label,
                    message=(
                        f"榜单区里 '{b.id}' 没标版本，同区的其他块标了 —— "
                        f"它会在每个版本都出现（同一篇里可能出现两个 TOP1）。"
                    ),
                ))

    # ④ 有主推卡却没有可见竞品池：抽中这个版本时榜单只剩 TOP1。
    for hero, pools in _regions(visible):
        if hero is not None and getattr(hero, "sections", None) and not pools:
            issues.append(LintIssue(
                level="warning", code="hero_without_pool",
                block_id=hero.id, version=label,
                message=(
                    f"版本「{label}」下主推卡 '{hero.id}' 后面没有可见的竞品池 —— "
                    f"榜单只会出 TOP1。检查竞品池的版本标签。"
                ),
            ))

    # ⑤ 无主推的竞品池（该版本下）：编号会从 TOP1 开始。
    for hero, pools in _regions(visible):
        if hero is None and pools:
            issues.append(LintIssue(
                level="warning", code="pool_without_hero",
                block_id=pools[0].id, version=label,
                message=(
                    f"版本「{label}」下竞品池 '{pools[0].id}' 前面没有可见的"
                    f"主推块 —— 排位会从 TOP1 开始编号。"
                ),
            ))

    return issues


def has_errors(issues: list[LintIssue]) -> bool:
    return any(i.level == "error" for i in issues)
