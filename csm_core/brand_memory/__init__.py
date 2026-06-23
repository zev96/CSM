"""Brand/model memory — resolve structured per-model facts from the vault."""
from .model import BrandModelMemory, SpecValue
from .resolver import resolve_memory

__all__ = ["BrandModelMemory", "SpecValue", "resolve_memory"]
