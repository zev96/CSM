"""Brand/model memory — resolve structured per-model facts from the vault."""
from .model import BrandModelMemory, SpecValue
from .resolver import resolve_memory
from .whitelist import FactWhitelist, build_fact_whitelist, normalize_numbers

__all__ = [
    "BrandModelMemory",
    "SpecValue",
    "resolve_memory",
    "FactWhitelist",
    "build_fact_whitelist",
    "normalize_numbers",
]
