"""Pydantic models for the unified block-based template DSL."""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


# 模板分类 — 与首页 / 模板库的筛选 UI 对齐。新增分类时：
#   1. 在这里加 Literal 值
#   2. 在 csm_gui.widgets.template_library_panel.TEMPLATE_TYPES 同步加上
#   3. 为旧模板提供默认（这里用 None，UI 端在保存时会回填）
TemplateType = Literal["导购文", "对比文", "单品文", "长文"]


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


class TestFrameworkBlock(BaseModel):
    """随机抽 N 个测试项框架 + 自动填入 hero/pool 选中产品的对应结果。

    每篇框架笔记里写好"测试原理 / 测试方法 / 测试数据图 / 测试总结"等
    通用方法论，并用 ``主推 测试部分：`` / ``竞品A 测试部分：`` /
    ``竞品B 测试部分：`` 这样的占位行标记品牌段落。生成时每条占位行会
    被替换为该产品在对应测试项下的实际结果（按品牌结果笔记里的 H2
    section 匹配）。
    """

    kind: Literal["test_framework"] = "test_framework"
    id: str
    label: str = ""
    framework_module: str           # 测试项框架笔记所在目录
    results_module: str             # 品牌结果笔记所在目录
    follow_slot: str                # "hero_a+pool_a" — 跟随哪些 block 选的产品
    pick_count: PickNotes = 3       # 抽几个测试项；同一篇文章不重复抽
    hero_slot: str = "主推"          # 框架笔记里识别"主推 测试部分：" 行的标签
    competitor_slots: list[str] = Field(
        default_factory=lambda: ["竞品A", "竞品B"],
    )
    # 测试项编号样式 — 渲染为 "## 1. xxx" / "## 一、xxx" / "## xxx"。
    number_style: NumberStyle = "1."
    constraints: list[str] = Field(default_factory=lambda: ["unique_notes"])


Block = Annotated[
    Union[
        ParagraphBlock, HeadingBlock, NumberedListBlock,
        HeroBrandBlock, CompetitorPoolBlock, LiteralBlock,
        TestFrameworkBlock,
    ],
    Field(discriminator="kind"),
]


# ── Template ──────────────────────────────────────────────────────────
class Template(BaseModel):
    # extra='ignore' tolerates legacy JSONs that still carry
    # version/system_prompt_default/seo_defaults after migration; new saves
    # won't emit those fields because they're not declared here.
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    product: str
    # ``template_type`` 旧模板没有这个字段 — 默认 None，UI 端按需补默认值。
    template_type: TemplateType | None = None
    default_skill_id: str | None = None
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
