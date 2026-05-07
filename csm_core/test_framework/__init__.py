"""Random test-framework block — random N test items × per-brand fill-in.

Public entry-point: :func:`sample_test_framework_block`. Used by the assembler
when it encounters a ``TestFrameworkBlock`` in a template.
"""
from .section_parser import (
    NORMALIZED_PREFIXES,
    BrandSection,
    extract_brand_sections,
    find_section_for_topic,
    normalize_section_title,
)
from .sampler import TestFrameworkConfig, sample_test_framework_block

__all__ = [
    "BrandSection",
    "NORMALIZED_PREFIXES",
    "TestFrameworkConfig",
    "extract_brand_sections",
    "find_section_for_topic",
    "normalize_section_title",
    "sample_test_framework_block",
]
