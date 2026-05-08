"""Auto-title generation — pulls formulas from the vault, asks the LLM,
returns 3 validated candidate titles with mechanical fallback."""
from .generator import (
    TitleFormula,
    build_title_prompt,
    fallback_title,
    generate_titles,
    load_formulas,
    parse_title_response,
    validate_title,
)

__all__ = [
    "TitleFormula",
    "build_title_prompt",
    "fallback_title",
    "generate_titles",
    "load_formulas",
    "parse_title_response",
    "validate_title",
]
