"""Build brand-model registry from 产品参数 note filenames + frontmatter."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .note_parser import parse_note
from ..brand_memory.identity import BRAND_ALIASES, canonical_brand, parse_brand_model


@dataclass
class BrandRegistry:
    _brand_to_models: dict[str, list[str]] = field(default_factory=dict)
    _model_to_brand: dict[str, str] = field(default_factory=dict)

    def brands(self) -> list[str]:
        return sorted(self._brand_to_models.keys())

    def models(self, brand: str) -> list[str]:
        return sorted(self._brand_to_models.get(brand, []))

    def all_models(self) -> list[str]:
        return sorted(self._model_to_brand.keys())

    def brand_of(self, model: str) -> str | None:
        return self._model_to_brand.get(model)

    def competitors_of(self, brand: str) -> list[str]:
        return [m for m, b in self._model_to_brand.items() if b != brand]

    def add(self, brand: str, model: str) -> None:
        self._brand_to_models.setdefault(brand, [])
        if model not in self._brand_to_models[brand]:
            self._brand_to_models[brand].append(model)
        self._model_to_brand[model] = brand


def build_brand_registry(
    vault_root: Path, *, aliases: dict[str, list[str]] = BRAND_ALIASES,
) -> BrandRegistry:
    """Scan <vault>/**/产品参数/*.md and construct registry.

    品牌 is folded to canonical (米家->小米, 希喂->CEWEY). When a note lacks
    品牌/型号 frontmatter (the real vault today), we fall back to parsing the
    filename via brand_memory.identity.parse_brand_model — so the registry is
    non-empty even before the one-shot backfill runs. 型号 keeps the full-stem
    convention (incl. brand prefix, e.g. CEWEYDS18) used across the assembler
    型号-join (sampler.py / constraints.py); see plan §关键设计决定 #1.
    """
    registry = BrandRegistry()
    for md in sorted(vault_root.rglob("产品参数/*.md")):
        note = parse_note(md)
        parsed = parse_brand_model(md.stem, aliases)
        brand = note.frontmatter.get("品牌") or (parsed[0] if parsed else None)
        model = str(note.frontmatter.get("型号") or md.stem.split("-")[0]).strip()
        if not brand or not model:
            continue
        registry.add(canonical_brand(str(brand), aliases), model)
    return registry
