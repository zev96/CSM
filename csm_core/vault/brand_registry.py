"""Build brand-model registry from 产品参数 note filenames + frontmatter."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .note_parser import parse_note


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


def build_brand_registry(vault_root: Path) -> BrandRegistry:
    """Scan <vault>/**/产品参数/*.md and construct registry."""
    registry = BrandRegistry()
    for md in vault_root.rglob("产品参数/*.md"):
        note = parse_note(md)
        brand = note.frontmatter.get("品牌")
        model = note.frontmatter.get("型号")
        if not model:
            model = md.stem.split("-")[0]
        if not brand:
            continue
        registry.add(brand, model)
    return registry
