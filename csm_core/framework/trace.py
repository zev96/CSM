"""Diagnostic trace collected while rendering a Framework."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FrameworkTrace:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def skipped_empty_slot(self, slot_id: str, block_index: int) -> None:
        self.entries.append({
            "event": "skipped_empty_slot",
            "slot_id": slot_id,
            "block_index": block_index,
        })

    def missing_meta(self, block_index: int, pick_index: int, missing_keys: list[str]) -> None:
        self.entries.append({
            "event": "missing_meta",
            "block_index": block_index,
            "pick_index": pick_index,
            "missing_keys": list(missing_keys),
        })

    def to_dict(self) -> dict[str, Any]:
        return {"entries": list(self.entries)}
