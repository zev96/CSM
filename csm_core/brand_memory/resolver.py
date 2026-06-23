"""Assemble a BrandModelMemory for a (品牌, 型号) from an existing VaultIndex.

Mapping (see spec §2.2): specs/certs ← 产品参数；scripts ← <品牌>推荐内容/
{核心,次要}技术（维度取文件夹+文件名，不依赖 素材类型）；endorsements ←
品牌背书；intro ← 竞品推荐内容/希喂推荐内容；tests ← 品牌产品测试结果。
"""
from __future__ import annotations
import re
from csm_core.vault.scanner import VaultIndex
from csm_core.vault.note_parser import ParsedNote
from csm_core.test_framework.section_parser import extract_brand_sections
from .identity import BRAND_ALIASES, canonical_brand, parse_brand_model
from .specs import parse_spec_table
from .model import BrandModelMemory

_CIRCLED = "".join(chr(c) for c in range(0x2460, 0x2474))  # ①..⑳
_DIM_RE = re.compile(r"(?:核心技术|次要技术)-(.+)$")
_CERT_SPLIT_RE = re.compile(r"[、,，/]+")


def _rel_parts(note: ParsedNote, index: VaultIndex) -> tuple[str, ...]:
    try:
        return note.path.relative_to(index.root).parts
    except ValueError:
        return ()


def _dimension_from_stem(stem: str) -> str | None:
    m = _DIM_RE.search(stem)
    if not m:
        return None
    return m.group(1).rstrip(_CIRCLED).strip() or None


def _brand_folder_aliases(brand: str, aliases: dict[str, list[str]]) -> list[str]:
    return aliases.get(brand, [brand])


def resolve_memory(
    brand: str, model: str, category: str, index: VaultIndex,
    *, own_brands: set[str], aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> BrandModelMemory:
    brand = canonical_brand(brand, aliases)
    role = "主推" if brand in own_brands else "竞品"
    brand_writings = {f"{a}推荐内容" for a in _brand_folder_aliases(brand, aliases)}

    specs: dict = {}
    certs: list[str] = []
    scripts: dict[str, list[str]] = {}
    endorsements: list[str] = []
    intro: list[str] = []
    tests: dict[str, str] = {}

    for note in index.notes:
        parts = _rel_parts(note, index)
        if not parts:
            continue
        # 产品参数：按文件名解析出的 (品牌,型号) 命中
        if "产品参数" in parts:
            bm = parse_brand_model(note.id, aliases)
            if bm == (brand, model):
                specs = parse_spec_table(note.raw_body)
                certs = _certs_from_specs(specs)
            continue
        # 该品牌的「<品牌>推荐内容」子树
        if brand_writings & set(parts):
            if "品牌背书" in parts:
                endorsements.extend(note.variants or [note.raw_body])
            else:
                dim = _dimension_from_stem(note.id)
                if dim:
                    scripts.setdefault(dim, []).extend(note.variants or [note.raw_body])
            continue
        # 竞品介绍
        if "竞品推荐内容" in parts and model in note.id:
            intro.extend(note.variants or [note.raw_body])
            continue
        # 品牌产品测试结果
        if "品牌产品测试结果" in parts and model in note.id:
            for sec in extract_brand_sections(note.raw_body):
                tests[sec.normalized_title] = sec.body

    coverage = {
        "has_specs": bool(specs),
        "has_tests": bool(tests),
        "script_dimensions": len(scripts),
        "empty_spec_fields": [k for k, v in specs.items() if not v.numbers and not v.raw.strip("-/")],
    }
    return BrandModelMemory(
        brand=brand, model=model, category=category, role=role,
        specs=specs, certs=certs, scripts=scripts,
        endorsements=endorsements, intro=intro, tests=tests, coverage=coverage,
    )


def _certs_from_specs(specs: dict) -> list[str]:
    cell = next((v.raw for k, v in specs.items() if "认证" in k), "")
    return [c.strip() for c in _CERT_SPLIT_RE.split(cell) if c.strip()]
