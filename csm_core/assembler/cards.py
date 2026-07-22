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
from csm_core.test_framework.section_parser import extract_brand_sections
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


@dataclass
class Competitor:
    """一个竞品 + 它全部覆盖合格的卡片（互为候选，采样时再选一张）。"""

    key: str
    cards: list[CompetitorCard]

    @property
    def title(self) -> str:
        return self.cards[0].title


_SECTIONS_ATTR = "_card_sections_cache"


def note_sections(note: ParsedNote) -> list:
    """卡片笔记的 H2 小节。在 raw_body 上做 —— 变体切分会吃掉 H2 行。

    结果缓存在 **ParsedNote 实例上**：建册要对每张卡 × 每个小节各查一次，
    10 竞品 × 7 小节就是 70 次全文解析，纯浪费。

    挂在实例上而不是模块级字典，是为了让缓存跟着索引一起失效 —— 笔记变了
    索引会重新解析出**新的** ParsedNote 对象，自然没有这个属性。早期版本用
    ``(路径, 正文长度)`` 做 key，而最典型的订正动作恰恰是等长编辑
    （``550`` → ``660``、``口啤`` → ``口碑``），缓存撞不到变化，已经改对的
    参数会继续被印进成稿，直到进程重启。
    """
    cached = getattr(note, _SECTIONS_ATTR, None)
    if cached is None:
        cached = extract_brand_sections(note.raw_body)
        try:
            setattr(note, _SECTIONS_ATTR, cached)
        except AttributeError:      # slots 化的笔记对象：不缓存也能跑
            pass
    return cached



def find_card_section(sections: list, topic: str):
    """在竞品卡里找匹配 ``topic`` 的 H2。精确 → topic⊂H2 → H2⊂topic。

    **不能**复用 ``find_section_for_topic``：它会先剥 ``云测/实测/测试`` +
    数字前缀（那是测试结果笔记专用的规整）。卡片里写 ``## 测试数据`` 会被
    规整成「数据」，而「数据」是「市场口碑数据」的子串 —— 一张根本没有口碑
    小节的卡就这样通过覆盖度预检，把测试数据渲染到「市场口碑数据」标签下，
    覆盖度告警还什么都不报（它只报缺什么、不报绑到了谁）。
    """
    topic = (topic or "").strip()
    if not topic or not sections:
        return None
    titles = [(s, (s.raw_title or "").strip()) for s in sections]
    for s, t in titles:
        if t == topic:
            return s
    for s, t in titles:
        if topic in t:
            return s
    for s, t in titles:
        if t and t in topic:
            return s
    return None


def section_body(note: ParsedNote, spec: CompetitorSection) -> str | None:
    """取笔记里匹配该小节的正文；没有则 None。"""
    found = find_card_section(note_sections(note), spec.topic())
    if found is None or not found.body.strip():
        return None
    return found.body


def build_roster(
    notes: list[ParsedNote], sections: list[CompetitorSection],
    *, tier_key: str = "层级标签",
) -> tuple[list[Competitor], list[str]]:
    """把候选笔记归并成竞品名册，并做覆盖度预检。

    返回 ``(名册, 告警)``。告警是运营的补素材工作清单 —— 每条都带完整
    路径，因为「口碑.md 缺 frontmatter」这种裸文件名在多竞品目录下定位
    不到是谁。

    同一竞品的多张合格卡**互为候选**（同一款产品写两版不同口吻的整卡，
    生成时随机用一张），不是「第一张不合格才用第二张」的替补。
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

    roster: list[Competitor] = []
    required = [s for s in sections if s.required]
    for key, entries in grouped.items():
        cards: list[CompetitorCard] = []
        missing_report: list[str] = []
        tiers: set[str] = set()
        for note, brand, model in entries:
            missing = [s.label for s in required if section_body(note, s) is None]
            if missing:
                missing_report.append(f"{note.path} 缺「{'、'.join(missing)}」")
                continue
            card = CompetitorCard(
                key=key, brand=brand, model=model, note=note,
                tier=str((note.frontmatter or {}).get(tier_key) or "").strip(),
            )
            for spec in sections:
                body = section_body(note, spec)
                if body is not None:
                    card.sections[spec.label] = body
            cards.append(card)
            if card.tier:
                tiers.add(card.tier)
        if not cards:
            warnings.append(
                f"竞品「{entries[0][2]}」未入册：" + "；".join(missing_report)
            )
            continue
        if len(tiers) > 1:
            # 多张卡互为候选、每次生成随机用一张，tier 跟着选中的卡走 ——
            # 所以这里不能说「取首个」（早期文案就是这么写的，让运营以为
            # 是确定值而不去修数据，实际同一竞品在不同文章里标签会漂）。
            warnings.append(
                f"竞品「{cards[0].title}」多张卡的{tier_key}不一致"
                f"（{'、'.join(sorted(tiers))}）—— 每次生成会随机用其中一张卡，"
                f"标签跟着那张卡走。要固定就把各张卡的{tier_key}改成一致。"
            )
        roster.append(Competitor(key=key, cards=cards))
    warnings.extend(_near_duplicate_warnings(roster))
    return roster, warnings


def _loose_key(key: str) -> str:
    """更宽松的同款判定 key —— 连字符/下划线也抹掉。

    ``normalize_model_key`` 刻意保留连字符（V8-Pro 与 V8Pro 可能是两款
    货），但「复制一张超集卡再改型号」时最常见的手滑就是 X9 / X-9：两张
    卡都覆盖齐全 ⇒ 都入册 ⇒ 同一款产品在十大榜单里出现两次。这里只用来
    发告警，不做自动合并（真是两款货的话合并才是灾难）。
    """
    return key.replace("-", "").replace("_", "")


def _near_duplicate_warnings(roster: list[Competitor]) -> list[str]:
    seen: dict[str, Competitor] = {}
    out: list[str] = []
    for c in roster:
        lk = _loose_key(c.key)
        prev = seen.get(lk)
        if prev is not None:
            out.append(
                f"疑似同款重复上榜：「{prev.title}」与「{c.title}」型号只差连字符/下划线，"
                f"会被当成两个竞品各占一个排位。确认是两款产品就忽略，"
                f"否则删掉其中一张卡（{c.cards[0].note.path}）"
            )
        else:
            seen[lk] = c
    return out


def pick_section_variants(
    body: str, count: int, rng: random.Random,
) -> list[tuple[int, str]]:
    """从小节正文里抽 ``count`` 个 ①②③ 候选，返回 (变体号, 文本)。

    候选够就**不重复**抽 —— 小节的 ①②③ 是「这个点的多份候选」，同一段
    印两遍没有意义。不够就有放回（保持请求数量）。
    保留行内加粗 —— 榜单卡靠 ``**703.7 m³/h**`` 这种标粗突出关键数据，
    默认解析路径会把 ``**`` 剥光。
    """
    variants = split_variants(body, keep_bold=True) or [body.strip()]
    n = max(1, count)
    if n <= len(variants):
        idx = rng.sample(range(len(variants)), n)
    else:
        idx = [rng.randrange(len(variants)) for _ in range(n)]
    return [(i, variants[i]) for i in idx]


def sample_roster(
    roster: list[Competitor], requested: int, rng: random.Random,
    *, exclude_keys: set[str], block_id: str, fixed_count: bool,
    roster_warnings: list[str], source_hint: str = "",
) -> tuple[list[CompetitorCard], str | None]:
    """抽 N 个不重复竞品，每个再随机选一张它的卡。返回 (选中卡, 容量告警)。

    卡片模式**恒不重复**：榜单里 TOP2 与 TOP3 是同一款产品毫无意义，所以
    这里不看 ``unique_notes`` 开关。跨池排除集由 assemble_plan 传入（深浅
    双池：TOP2-3 一个池、TOP4-10 另一个池，不能重复出同一款）。
    """
    available = [c for c in roster if c.key not in exclude_keys]
    excluded = len(roster) - len(available)
    if not available or (requested > len(available) and fixed_count):
        raise CardRosterError(_shortfall_message(
            block_id, requested, len(available), roster_warnings,
            total=len(roster), excluded=excluded, source_hint=source_hint,
        ))
    note = None
    if requested > len(available):
        note = (
            f"请求 {requested} 个竞品，名册仅 {len(available)} 个可用"
            + (f"（另有 {excluded} 个已被本榜单前面的池选走）" if excluded else "")
        )
        requested = len(available)
    chosen = rng.sample(available, requested)
    # 同竞品多张合格卡互为候选 —— 抽签定竞品之后再随机用哪张。
    return [rng.choice(c.cards) for c in chosen], note


def _shortfall_message(
    block_id: str, requested: int, available: int, roster_warnings: list[str],
    *, total: int, excluded: int, source_hint: str,
) -> str:
    """名册不足的报错 —— 必须能让用户当场判断根因。

    早期版本在「没有缺料告警」时无条件印「该目录下没有任何符合筛选条件的
    竞品卡」，于是深浅双池被前池抽光时（目录里躺着 9 张完好的卡）用户被
    告知「一张都没有」，照着这句话永远查不出根因。
    """
    lines = [
        f"block '{block_id}': 榜单需要 {requested} 个竞品，本池可用 {available} 个"
        f"（名册合格 {total} 个"
        + (f"，其中 {excluded} 个已被本榜单前面的池选走" if excluded else "")
        + "） —— 榜单数量对不上，已中止生成。",
    ]
    if source_hint:
        lines.append(f"素材来源：{source_hint}")
    if roster_warnings:
        lines.append("缺料清单：")
        lines.extend(f"  · {w}" for w in roster_warnings)
    elif total == 0:
        lines.append("（该目录下没有任何符合筛选条件的竞品卡）")
    return "\n".join(lines)
