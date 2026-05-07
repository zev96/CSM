"""Long-tail keyword decomposition.

A search keyword is what the user types ("无线吸尘器哪款好用"); a core
keyword is the bare product term inside it ("无线吸尘器"). They serve
different roles — long-tail goes into the SEO title, core goes into the
article body — so the rest of the pipeline needs both.
"""
from .extractor import extract_core, TAIL_PATTERNS, LEADING_PATTERNS

__all__ = ["extract_core", "TAIL_PATTERNS", "LEADING_PATTERNS"]
