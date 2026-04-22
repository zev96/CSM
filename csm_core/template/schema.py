"""Pydantic models for template DSL."""
from __future__ import annotations
from typing import Any, Literal, Union
from pydantic import BaseModel, Field, model_validator


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
    __test__ = False  # prevent pytest from collecting this as a test class
    type: Literal["test_results_aligned"] = "test_results_aligned"
    follow_slot: str
    module: str


SourceT = Union[
    NotesQuerySource, BrandFixedSource, BrandPoolSource, TestResultsAlignedSource
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


class Slot(BaseModel):
    id: str
    label: str
    source: SourceT = Field(discriminator="type")
    pick_notes: PickNotes = 1
    pick_variants_per_note: int = 1
    constraints: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


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
    slots: list[Slot]
    render_order: list[str]
    default_framework: str | None = None

    @model_validator(mode="after")
    def _validate_structure(self):
        slot_ids = {s.id for s in self.slots}

        if set(self.render_order) != slot_ids:
            raise ValueError(
                f"render_order {self.render_order} must match slot ids {sorted(slot_ids)}"
            )

        for s in self.slots:
            for dep in s.depends_on:
                if dep not in slot_ids:
                    raise ValueError(
                        f"slot '{s.id}' depends_on '{dep}' which does not exist"
                    )

        # Kahn's topo sort for cycle detection
        in_degree = {s.id: 0 for s in self.slots}
        graph: dict[str, list[str]] = {s.id: [] for s in self.slots}
        for s in self.slots:
            for dep in s.depends_on:
                graph[dep].append(s.id)
                in_degree[s.id] += 1
        queue = [sid for sid, d in in_degree.items() if d == 0]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for nxt in graph[node]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
        if visited != len(self.slots):
            raise ValueError("depends_on graph contains a cycle")
        return self
