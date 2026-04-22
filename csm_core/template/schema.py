"""Pydantic models for the unified block-based template DSL."""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, Field, model_validator


# ── Sources ───────────────────────────────────────────────
class NotesQuerySource(BaseModel):
    type: Literal["notes_query"] = "notes_query"
    module: str
    filter: dict[str, Any] = Field(default_factory=dict)


class BrandFixedSource(BaseModel):
    type: Literal["brand_fixed"] = "brand_fixed"
    brand: str
    model: str


class BrandPoolSource(BaseModel):
    type: Literal["brand_pool"] = "brand_pool"
    exclude_brands: list[str] = Field(default_factory=list)


class TestResultsAlignedSource(BaseModel):
    __test__ = False
    type: Literal["test_results_aligned"] = "test_results_aligned"
    follow_slot: str
    module: str


SourceT = Annotated[
    Union[NotesQuerySource, BrandFixedSource, BrandPoolSource, TestResultsAlignedSource],
    Field(discriminator="type"),
]


class PickCountSpec(BaseModel):
    random_between: list[int] | None = None
    user_configurable: bool = False
    default: int | None = None
    range: list[int] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.random_between and len(self.random_between) != 2:
            raise ValueError("random_between must be [min, max]")
        if self.user_configurable and (self.default is None or self.range is None):
            raise ValueError("user_configurable requires default + range")
        return self


PickNotes = Union[int, PickCountSpec]
NumberStyle = Literal["1.", "一、", "none"]


# ── Block types ───────────────────────────────────────────────────────
class ParagraphBlock(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    id: str
    label: str = ""
    source: SourceT
    pick_notes: PickNotes = 1
    pick_variants_per_note: int = 1
    constraints: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    children: list["ParagraphBlock"] = Field(default_factory=list)


class HeadingBlock(BaseModel):
    kind: Literal["heading"] = "heading"
    id: str
    level: Literal[1, 2, 3] = 2
    index: str = ""
    text: str = Field(min_length=1)


class NumberedListBlock(BaseModel):
    kind: Literal["numbered_list"] = "numbered_list"
    id: str
    label: str = ""
    source: SourceT
    pick_notes: PickNotes = 3
    number_style: NumberStyle = "1."
    item_separator: str = "\n\n"


class HeroBrandBlock(BaseModel):
    kind: Literal["hero_brand"] = "hero_brand"
    id: str
    title: str = Field(min_length=1)
    reason_label: str = "推荐理由："
    number_style: NumberStyle = "1."


class CompetitorPoolBlock(BaseModel):
    kind: Literal["competitor_pool"] = "competitor_pool"
    id: str
    source: SourceT
    pick_notes: PickNotes = 2
    reason_label: str = "推荐理由："


class LiteralBlock(BaseModel):
    kind: Literal["literal"] = "literal"
    id: str
    text: str = Field(min_length=1)


Block = Annotated[
    Union[
        ParagraphBlock, HeadingBlock, NumberedListBlock,
        HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
    ],
    Field(discriminator="kind"),
]


# ── Template ──────────────────────────────────────────────────────────
class SEODefaults(BaseModel):
    target_word_count: list[int] = Field(default_factory=lambda: [1500, 2000])
    keyword_density: list[int] = Field(default_factory=lambda: [5, 8])
    long_tail_keywords: list[str] = Field(default_factory=list)
    tone: str = "小红书笔记体"
    force_h2: bool = True


class Template(BaseModel):
    id: str
    name: str
    product: str
    version: int = 1
    system_prompt_default: str = ""
    seo_defaults: SEODefaults = Field(default_factory=SEODefaults)
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_structure(self):
        ids: set[str] = set()

        def walk(items: list) -> None:
            for b in items:
                if b.id in ids:
                    raise ValueError(f"duplicate block id '{b.id}'")
                ids.add(b.id)
                if isinstance(b, ParagraphBlock):
                    walk(b.children)

        walk(self.blocks)

        def paragraph_ids(items: list) -> set[str]:
            out: set[str] = set()
            for b in items:
                if isinstance(b, ParagraphBlock):
                    out.add(b.id)
                    out |= paragraph_ids(b.children)
            return out

        known = paragraph_ids(self.blocks)

        def check_deps(items: list) -> None:
            for b in items:
                if isinstance(b, ParagraphBlock):
                    for dep in b.depends_on:
                        if dep not in known:
                            raise ValueError(
                                f"block '{b.id}' depends_on unknown id '{dep}'"
                            )
                    check_deps(b.children)

        check_deps(self.blocks)
        return self
