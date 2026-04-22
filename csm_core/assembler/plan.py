"""AssemblyPlan — serializable result of block-level sampling."""
from __future__ import annotations
import json
from typing import Any, Literal
from pydantic import BaseModel, Field


class PickedVariant(BaseModel):
    note_id: str
    variant_index: int
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)


BlockKind = Literal[
    "paragraph", "heading", "numbered_list",
    "hero_brand", "competitor_pool", "literal",
]


class BlockResult(BaseModel):
    """Sampler output for one block.

    - paragraph / numbered_list: populated ``picks`` from vault sampling.
    - competitor_pool: ``picks`` where each pick's ``meta['title']`` holds
      the competitor title (from 型号 frontmatter) and ``text`` is the chosen
      candidate reason.
    - heading / literal / hero_brand: ``text`` holds the literal rendered
      string (``text`` for heading, ``title`` for hero_brand, raw ``text``
      for literal). ``picks`` is empty.
    - The block's own meta (number_style, reason_label, level, index) is
      copied into ``meta`` so the renderer doesn't need the original Block.
    """
    block_id: str
    kind: BlockKind
    picks: list[PickedVariant] = Field(default_factory=list)
    text: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    children: list["BlockResult"] = Field(default_factory=list)


class AssemblyPlan(BaseModel):
    keyword: str
    template_id: str
    seed: int
    results: list[BlockResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, payload: str) -> "AssemblyPlan":
        return cls.model_validate(json.loads(payload))

    def get_result(self, block_id: str) -> BlockResult | None:
        def search(items: list[BlockResult]) -> BlockResult | None:
            for r in items:
                if r.block_id == block_id:
                    return r
                found = search(r.children)
                if found is not None:
                    return found
            return None
        return search(self.results)
