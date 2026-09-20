"""Brand-section parser for 竞品卡 notes.

The random test-framework sampler that used to live here went away with
the article generator; :mod:`csm_core.assembler.cards` still relies on
:func:`extract_brand_sections`.
"""
from .section_parser import (
    NORMALIZED_PREFIXES,
    BrandSection,
    extract_brand_sections,
    find_section_for_topic,
    normalize_section_title,
)

__all__ = [
    "BrandSection",
    "NORMALIZED_PREFIXES",
    "extract_brand_sections",
    "find_section_for_topic",
    "normalize_section_title",
]
