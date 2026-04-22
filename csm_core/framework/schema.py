"""Pydantic models for framework DSL."""
from __future__ import annotations
import re
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1)]

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class ParagraphBlock(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    slot: NonEmptyStr


class HeadingBlock(BaseModel):
    kind: Literal["heading"] = "heading"
    level: Literal[1, 2, 3] = 2
    index: str = ""
    text: NonEmptyStr


class NumberedListBlock(BaseModel):
    kind: Literal["numbered_list"] = "numbered_list"
    slot: NonEmptyStr


class BrandReasonListBlock(BaseModel):
    kind: Literal["brand_reason_list"] = "brand_reason_list"
    slots: list[NonEmptyStr] = Field(min_length=1)
    reason_label: str = "推荐理由："


class LiteralBlock(BaseModel):
    kind: Literal["literal"] = "literal"
    text: NonEmptyStr


Block = Annotated[
    Union[ParagraphBlock, HeadingBlock, NumberedListBlock, BrandReasonListBlock, LiteralBlock],
    Field(discriminator="kind"),
]


class Framework(BaseModel):
    id: NonEmptyStr
    name: NonEmptyStr
    description: str = ""
    variables: list[str] = Field(default_factory=list)
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_variable_tokens(self):
        allowed = set(self.variables)
        for i, b in enumerate(self.blocks):
            text = getattr(b, "text", None)
            if not text:
                continue
            for var in _VAR_RE.findall(text):
                if var not in allowed:
                    raise ValueError(
                        f"block[{i}] uses unknown variable '{{{var}}}' "
                        f"(declared variables: {sorted(allowed) or 'none'})"
                    )
        return self
