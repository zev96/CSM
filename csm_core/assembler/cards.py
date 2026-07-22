"""榜单卡片：竞品名册构建 + 覆盖度预检 + 逐小节采样。

素材形态（与 legacy 竞品池完全不同）::

    ---
    品牌: 欧瑞达
    型号: 欧瑞达X9
    素材类型: 竞品卡
    层级标签: 热门品牌
    ---
    ## 市场口碑数据
    ① 全平台销量稳步增长……
    ② 连续两年入围双11热销榜……

    ## 品牌赛道定位
    ① 主打长效滤网的家用品牌……

一张卡 = 一个竞品；H2 = 一个「点」；节内 ①②③ = 该点的多份候选内容。
覆盖了多版本点的「超集卡」可以同时服务多个版本。

为什么是单文件多 H2 而不是「每点一个文件」：后者在 9 竞品 × 2 版本下要写
81 篇小笔记，而且 ``口碑.md`` 这种同名文件会撞 ``note.id``（= 文件名 stem，
reroll 与反馈权重全按它寻址）—— 重随会串到别家竞品、权重统计合桶。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from csm_core.brand_memory.identity import (
    normalize_model_key, note_identity, strip_competitor_prefix,
)
from csm_core.test_framework.section_parser import (
    extract_brand_sections, find_section_for_topic,
)
from csm_core.template.schema import CompetitorSection
from csm_core.vault.note_parser import ParsedNote, split_variants


class CardRosterError(Exception):
    """卡片名册不足以出榜 —— 带逐竞品缺料清单。

    榜单文里「十大」静默变「七大」是不能接受的（标题与正文数量对不上就发
    出去了），所以固定数量抽不满直接失败，并把缺什么讲清楚。
    """


@dataclass
class CompetitorCard:
    key: str                      # 归一化身份 key（分组用，不显示）
    brand: str
    model: str                    # 显示型号（已剥竞品前缀）
    tier: str                     # 层级标签（人工填写）
    note: ParsedNote              # 选中的卡片笔记
    sections: dict[str, str] = field(default_factory=dict)  # label -> 节正文

    @property
    def title(self) -> str:
        """显示标题。型号通常已含品牌（``欧瑞达X9``），不重复拼。"""
        if self.brand and not self.model.startswith(self.brand):
            return f"{self.brand} {self.model}"
        return self.model


def _note_sections(note: ParsedNote) -> list:
    """卡片笔记的 H2 小节。在 raw_body 上做 —— 变体切分会吃掉 H2 行。"""
    return extract_brand_sections(note.raw_body)


def section_body(note: ParsedNote, spec: CompetitorSection) -> str | None:
    """取笔记里匹配该小节的正文；没有则 None。

    匹配复用测试框架那套宽松规则（剥编号前缀 + 双向子串），这样卡片里写
    ``## 市场口碑数据`` 而模板小节名写「口碑数据」也能对上。
    """
    found = find_section_for_topic(_note_sections(note), spec.topic())
    if found is None or not found.body.strip():
        return None
    return found.body


def build_roster(
    notes: list[ParsedNote], sections: list[CompetitorSection],
) -> tuple[list[CompetitorCard], list[str]]:
    """把候选笔记归并成竞品名册，并做覆盖度预检。

    返回 ``(名册, 告警)``。告警是运营的补素材工作清单 —— 每条都带完整
    相对路径，因为「口碑.md 缺 frontmatter」这种裸文件名在多竞品目录下
    定位不到是谁。
    """
    warnings: list[str] = []
    grouped: dict[str, list[tuple[ParsedNote, str, str]]] = {}

    for note in sorted(notes, key=lambda n: str(n.path)):
        ident = note_identity(note.id, note.frontmatter)
        fm = note.frontmatter or {}
        # 卡片模式强制 frontmatter 定身份：文件名兜底在这里不可靠（卡片
        # 文件名要求带型号，但真漏写时兜底会拿到无意义 stem，导致幽灵竞品）。
        if not ident or not str(fm.get("品牌") or "").strip() or not str(
            fm.get("型号") or ""
        ).strip():
            warnings.append(
                f"{note.path}: 缺 品牌/型号 frontmatter，未计入竞品名册"
            )
            continue
        brand, raw_model = ident
        model = strip_competitor_prefix(raw_model)
        key = f"{normalize_model_key(brand)}::{normalize_model_key(raw_model)}"
        grouped.setdefault(key, []).append((note, brand, model))

    roster: list[CompetitorCard] = []
    required = [s for s in sections if s.required]
    for key, entries in grouped.items():
        chosen: CompetitorCard | None = None
        missing_report: list[str] = []
        for note, brand, model in entries:
            missing = [s.label for s in required if section_body(note, s) is None]
            if missing:
                missing_report.append(f"{note.path} 缺「{'、'.join(missing)}」")
                continue
            card = CompetitorCard(
                key=key, brand=brand, model=model, tier="", note=note,
            )
            for spec in sections:
                body = section_body(note, spec)
                if body is not None:
                    card.sections[spec.label] = body
            chosen = card
            break
        if chosen is None:
            warnings.append(
                f"竞品「{entries[0][2]}」未入册：" + "；".join(missing_report)
            )
        else:
            roster.append(chosen)
    return roster, warnings


def set_tier(card: CompetitorCard, tier_key: str) -> None:
    card.tier = str((card.note.frontmatter or {}).get(tier_key) or "").strip()


def pick_section_variants(
    body: str, count: int, rng: random.Random,
) -> list[tuple[int, str]]:
    """从小节正文里抽 ``count`` 个 ①②③ 候选，返回 (变体号, 文本)。

    保留行内加粗 —— 榜单卡靠 ``**703.7 m³/h**`` 这种标粗突出关键数据，
    默认解析路径会把 ``**`` 剥光。
    """
    variants = split_variants(body, keep_bold=True) or [body.strip()]
    out: list[tuple[int, str]] = []
    for _ in range(max(1, count)):
        i = rng.randrange(len(variants))
        out.append((i, variants[i]))
    return out


def sample_roster(
    roster: list[CompetitorCard], requested: int, rng: random.Random,
    *, exclude_keys: set[str], block_id: str, fixed_count: bool,
    roster_warnings: list[str],
) -> tuple[list[CompetitorCard], str | None]:
    """抽 N 个不重复竞品。返回 (选中, 容量告警)。

    卡片模式**恒不重复**：榜单里 TOP2 与 TOP3 是同一款产品毫无意义，所以
    这里不看 ``unique_notes`` 开关。跨池排除集由 assemble_plan 传入（深浅
    双池：TOP2-3 一个池、TOP4-10 另一个池，不能重复出同一款）。
    """
    available = [c for c in roster if c.key not in exclude_keys]
    if not available:
        raise CardRosterError(_shortfall_message(
            block_id, requested, 0, roster_warnings,
        ))
    if requested > len(available):
        if fixed_count:
            raise CardRosterError(_shortfall_message(
                block_id, requested, len(available), roster_warnings,
            ))
        note = (
            f"block '{block_id}': 请求 {requested} 个竞品，"
            f"名册仅 {len(available)} 个可用"
        )
        return rng.sample(available, len(available)), note
    return rng.sample(available, requested), None


def _shortfall_message(
    block_id: str, requested: int, available: int, roster_warnings: list[str],
) -> str:
    lines = [
        f"block '{block_id}': 榜单需要 {requested} 个竞品，"
        f"覆盖度合格的只有 {available} 个 —— 榜单数量对不上，已中止生成。",
    ]
    if roster_warnings:
        lines.append("缺料清单：")
        lines.extend(f"  · {w}" for w in roster_warnings)
    else:
        lines.append("（该目录下没有任何符合筛选条件的竞品卡）")
    return "\n".join(lines)
