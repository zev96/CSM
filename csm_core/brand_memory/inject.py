"""Plan 3 injection assembly.

从一份 AssemblyPlan 算出文章涉及哪些 (品牌, 型号)、resolve 各自记忆、渲染
喂给 LLM 的结构化事实块、并构建导出前事实核对用的「注入源并集」白名单。

作用域提取**以 registry 为锚**：sampler 吐出的型号串（picks 的 meta
型号/title、hero title）只有 registry 认识才采纳 —— 垃圾标题被丢、品牌由
registry 统一解析（全名型号约定，见 Plan 2）。registry 不认识的型号（只有
intro 没有产品参数的竞品）这步不贡献记忆，但其数字仍随 draft 进白名单，
故不会误拦。本模块依赖 factcheck（extract_certs）与 whitelist（normalize_
numbers/FactWhitelist）；factcheck 不反向依赖 brand_memory，无循环。
"""
from __future__ import annotations
from dataclasses import dataclass

from csm_core.assembler.plan import AssemblyPlan, BlockResult
from csm_core.vault.brand_registry import BrandRegistry
from csm_core.vault.scanner import VaultIndex
from csm_core.factcheck import extract_certs
from .identity import BRAND_ALIASES, parse_brand_model
from .model import BrandModelMemory
from .resolver import resolve_memory
from .whitelist import FactWhitelist, normalize_numbers


@dataclass
class ModelScope:
    brand: str
    model: str           # 全名型号（registry 形式 CEWEYDS18）；注意 memory.model 是品牌剥离形式（DS18）
    role: str            # 主推 | 竞品
    memory: BrandModelMemory


def _model_candidates(plan: AssemblyPlan) -> list[str]:
    """sampler 吐出的型号串，保序去重（hero text + picks meta title/型号）。"""
    out: list[str] = []
    seen: set[str] = set()

    def add(m) -> None:
        m = (m or "").strip() if isinstance(m, str) else m
        if m and m not in seen:
            seen.add(m)
            out.append(m)

    def walk(results: list[BlockResult]) -> None:
        for r in results:
            if r.kind == "hero_brand" and r.text:
                add(r.text)
            for p in r.picks:
                add(p.meta.get("title") or p.meta.get("model"))
            walk(r.children)

    walk(plan.results)
    return out


def resolve_scopes(
    plan: AssemblyPlan, index: VaultIndex, registry: BrandRegistry,
    *, own_brands: set[str], category: str,
    aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> list[ModelScope]:
    """registry 认识的涉及型号 → ModelScope（含 resolve 出的记忆）。"""
    scopes: list[ModelScope] = []
    seen: set[str] = set()
    for cand in _model_candidates(plan):
        brand = registry.brand_of(cand)
        if brand is None or cand in seen:
            continue
        seen.add(cand)
        # Registry stores full-prefix model (e.g. "CEWEYDS18"), resolver expects
        # the suffix after brand prefix (e.g. "DS18"). parse_brand_model on the
        # candidate translates between the two conventions.
        parsed = parse_brand_model(cand, aliases)
        resolver_model = parsed[1] if parsed is not None else cand
        mem = resolve_memory(
            brand, resolver_model, category, index, own_brands=own_brands, aliases=aliases,
        )
        scopes.append(ModelScope(brand=brand, model=cand, role=mem.role, memory=mem))
    return scopes


def render_brand_facts(
    scopes: list[ModelScope], *,
    variant_cap: int = 3, endorsement_cap: int = 5,
) -> str:
    """渲染注入 LLM 的事实块。

    specs **全量**、用每格 *原始* 文本（``12万转`` 原样 —— 白名单两侧同样
    归一）。scripts 每维度 ≤``variant_cap`` 变体、endorsements ≤
    ``endorsement_cap``（token 预算，spec §4.1）。竞品只给 specs/certs/intro
    （无自家话术）。背书是品牌级，同品牌只渲染一次。
    """
    blocks: list[str] = []
    brand_endorsed: set[str] = set()
    for sc in scopes:
        m = sc.memory
        lines = [f"## {sc.brand} {sc.model}（{sc.role}）"]
        if m.specs:
            lines.append("参数：")
            lines.extend(f"- {sv.field}: {sv.raw}" for sv in m.specs.values())
        if m.certs:
            lines.append(f"认证：{'、'.join(m.certs)}")
        for dim, variants in m.scripts.items():
            shown = variants[:variant_cap]
            if shown:
                lines.append(f"{dim}：")
                lines.extend(f"- {v}" for v in shown)
        if m.intro:
            lines.append("介绍：")
            lines.extend(f"- {v}" for v in m.intro[:variant_cap])
        if m.endorsements and sc.brand not in brand_endorsed:
            brand_endorsed.add(sc.brand)
            lines.append("品牌背书：")
            lines.extend(f"- {v}" for v in m.endorsements[:endorsement_cap])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_whitelist(
    scopes: list[ModelScope], *, source_texts: list[str],
) -> FactWhitelist:
    """全文级·注入源并集白名单（spec §2.3）。

    numbers = ⋃ specs 数值 ∪ normalize_numbers(源文本)；源文本 = draft +
    已注入 brand_facts。certs = ⋃ specs 认证 ∪ 源文本里出现的已知认证名
    （背书散文提到但参数表认证格没有的认证也不会被误拦）。
    """
    numbers: set[float] = set()
    certs: set[str] = set()
    for sc in scopes:
        for sv in sc.memory.specs.values():
            numbers.update(sv.numbers)
            # 真·数值规格额外按核对端口径 万-展开其原文（12万转→120000），这样
            # factcheck 开 / inject 关 时（brand_facts 不进 source_texts）也不漏。
            # 认证/占位单元格 numbers 为空 → 跳过，避免把「3C」的 3、占位「0」
            # 误入白名单（spec §2.3）。
            if sv.numbers:
                numbers |= normalize_numbers(sv.raw)
        certs.update(sc.memory.certs)
    for t in source_texts:
        numbers |= normalize_numbers(t)
        certs |= set(extract_certs(t))
    return FactWhitelist(numbers=numbers, certs=certs)
