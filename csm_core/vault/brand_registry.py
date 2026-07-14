"""Build brand-model registry from 产品参数 note filenames + frontmatter."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .note_parser import parse_note
from ..brand_memory.identity import BRAND_ALIASES, note_identity


@dataclass
class BrandRegistry:
    _brand_to_models: dict[str, list[str]] = field(default_factory=dict)
    _model_to_brand: dict[str, str] = field(default_factory=dict)
    _model_to_line: dict[str, str] = field(default_factory=dict)

    def brands(self) -> list[str]:
        return sorted(self._brand_to_models.keys())

    def models(self, brand: str) -> list[str]:
        return sorted(self._brand_to_models.get(brand, []))

    def all_models(self) -> list[str]:
        return sorted(self._model_to_brand.keys())

    def brand_of(self, model: str) -> str | None:
        return self._model_to_brand.get(model)

    def line_of(self, model: str) -> str | None:
        """产品线(吸尘器/空气净化器/...);registry 不识别该型号 → None。"""
        return self._model_to_line.get(model)

    def competitors_of(self, brand: str) -> list[str]:
        return [m for m, b in self._model_to_brand.items() if b != brand]

    def add(self, brand: str, model: str, line: str = "未分类") -> None:
        self._brand_to_models.setdefault(brand, [])
        if model not in self._brand_to_models[brand]:
            self._brand_to_models[brand].append(model)
        self._model_to_brand[model] = brand
        self._model_to_line[model] = line


def _line_of_path(md: Path, vault_root: Path, frontmatter: dict) -> str:
    """产品线 = 产品参数 目录的上一段;旧扁平布局/顶层兜底 frontmatter 产品。"""
    parent = md.parent.parent
    if parent != vault_root and parent.name not in ("产品模块", ""):
        return parent.name
    return str(frontmatter.get("产品") or "").strip() or "未分类"


def build_brand_registry(
    vault_root: Path, *, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> BrandRegistry:
    """Scan <vault>/**/产品参数/*.md and construct registry.

    (品牌, 型号) 判定链见 brand_memory.identity.note_identity(frontmatter 优先、
    文件名兜底,与 resolver 共用)。型号保持 full-stem 约定(incl. brand prefix,
    e.g. CEWEYDS18)used across the assembler 型号-join (sampler.py /
    constraints.py); see plan §关键设计决定 #1。产品线取自路径
    产品模块/<产品线>/产品参数 的中间段,旧扁平布局兜底 frontmatter 产品。
    """
    registry = BrandRegistry()
    for md in sorted(vault_root.rglob("产品参数/*.md")):
        note = parse_note(md)
        ident = note_identity(md.stem, note.frontmatter, aliases)
        if ident is None:
            continue
        brand, model = ident
        registry.add(brand, model, line=_line_of_path(md, vault_root, note.frontmatter))
    return registry
