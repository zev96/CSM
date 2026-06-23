"""Export-time fact check — flag numbers/certs in a finished article that
aren't in the per-generation whitelist (= the LLM invented them)."""
from .model import FactCheckReport, Violation
from .extract import (
    CERT_VOCAB, UNITS, extract_certs, extract_number_mentions, split_sentences,
)
from .checker import check_facts

__all__ = [
    "FactCheckReport", "Violation",
    "extract_number_mentions", "extract_certs", "split_sentences",
    "UNITS", "CERT_VOCAB",
    "check_facts",
]
