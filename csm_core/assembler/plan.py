"""AssemblyPlan — serializable result of sampling."""
from __future__ import annotations
import json
from typing import Any
from pydantic import BaseModel, Field


class PickedVariant(BaseModel):
    note_id: str
    variant_index: int  # 0-based index into ParsedNote.variants
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)  # brand/model/etc.


class SlotAssignment(BaseModel):
    slot_id: str
    picks: list[PickedVariant] = Field(default_factory=list)
    note: str = ""  # warnings like "缺数据"


class AssemblyPlan(BaseModel):
    keyword: str
    template_id: str
    seed: int
    slots: list[SlotAssignment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, payload: str) -> "AssemblyPlan":
        return cls.model_validate(json.loads(payload))

    def get_slot(self, slot_id: str) -> SlotAssignment | None:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return None

    def models_in_slot(self, slot_id: str) -> list[str]:
        slot = self.get_slot(slot_id)
        if not slot:
            return []
        return [p.meta.get("model") for p in slot.picks if p.meta.get("model")]
