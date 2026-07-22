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


# ── Version groups ────────────────────────────────────────────────────
class VersionGroup(BaseModel):
    """一组互斥的文章结构版本（如 版本1·口碑权威型 / 版本2·功能拆解型）。

    生成时每个组抽一次签，抽中的 option 决定哪些块可见。主推与竞品因此
    永远同版本 —— 它们消费的是同一次抽签结果，而不是各自随机对齐。
    权重按用户拍板不做：恒均匀随机。
    """

    id: str = Field(min_length=1)
    label: str = ""
    options: list[str] = Field(min_length=1)
    # 素材还没铺齐的版本先禁用，不进抽签池（避免抽中后整区无内容）。
    disabled_options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"version group '{self.id}': duplicate options")
        unknown = [o for o in self.disabled_options if o not in self.options]
        if unknown:
            raise ValueError(
                f"version group '{self.id}': disabled_options {unknown} not in options"
            )
        if not self.enabled_options():
            raise ValueError(
                f"version group '{self.id}': all options disabled — 至少留一个可用版本"
            )
        return self

    def enabled_options(self) -> list[str]:
        return [o for o in self.options if o not in self.disabled_options]


# ── Block types ───────────────────────────────────────────────────────
class BlockBase(BaseModel):
    """所有块共享的版本可见性字段。

    ``versions`` 为空 = 全版本可见（旧模板天然如此，零迁移）。
    ``version_group`` 只有多版本组时才需要填；单组模板留空即可。
    """

    versions: list[str] = Field(default_factory=list)
    version_group: str | None = None


class ParagraphBlock(BlockBase):
    kind: Literal["paragraph"] = "paragraph"
    id: str
    label: str = ""
    source: SourceT
    pick_notes: PickNotes = 1
    pick_variants_per_note: int = 1
    constraints: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    children: list["ParagraphBlock"] = Field(default_factory=list)


class HeadingBlock(BlockBase):
    kind: Literal["heading"] = "heading"
    id: str
    level: Literal[1, 2, 3] = 2
    index: str = ""
    text: str = Field(min_length=1)


class NumberedListBlock(BlockBase):
    kind: Literal["numbered_list"] = "numbered_list"
    id: str
    label: str = ""
    source: SourceT
    pick_notes: PickNotes = 3
    # 每篇笔记抽几个变体（同 paragraph）。历史 sampler 里硬编码 1，把它
    # 显式暴露出来后用户可以在 BlockEditor 里调，旧模板没声明就走默认 1。
    pick_variants_per_note: int = 1
    # 历史 sampler 给 numbered_list 强制塞了 ["unique_notes"]；保留这个
    # 默认（旧模板没填 constraints 就吃这条），同时让 UI 可以取消勾选改
    # 成允许重复素材。
    constraints: list[str] = Field(default_factory=lambda: ["unique_notes"])
    number_style: NumberStyle = "1."
    item_separator: str = "\n\n"


class HeroBrandBlock(BlockBase):
    kind: Literal["hero_brand"] = "hero_brand"
    id: str
    title: str = Field(min_length=1)
    reason_label: str = "推荐理由："
    number_style: NumberStyle = "1."


class CompetitorPoolBlock(BlockBase):
    kind: Literal["competitor_pool"] = "competitor_pool"
    id: str
    source: SourceT
    pick_notes: PickNotes = 2
    # 同 NumberedListBlock — 把历史 sampler 里硬编码的 1 / unique_notes
    # 暴露出来，让 BlockEditor 上的「子素材随机数量 / 不重复素材」开关
    # 也能控制对比池。旧模板没填这两个字段就走默认，与历史行为一致。
    pick_variants_per_note: int = 1
    constraints: list[str] = Field(default_factory=lambda: ["unique_notes"])
    reason_label: str = "推荐理由："


class LiteralBlock(BlockBase):
    kind: Literal["literal"] = "literal"
    id: str
    text: str = Field(min_length=1)


class TestFrameworkBlock(BlockBase):
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
    # 版本组 — 空 = 没有版本概念（旧模板），过滤恒真、输出逐字节不变。
    version_groups: list[VersionGroup] = Field(default_factory=list)
    blocks: list[Block] = Field(min_length=1)

    def group_of(self, block) -> VersionGroup | None:
        """返回块所属的版本组。未显式指定且只有一个组时默认那个组。"""
        if not self.version_groups:
            return None
        gid = getattr(block, "version_group", None)
        if gid:
            return next((g for g in self.version_groups if g.id == gid), None)
        if len(self.version_groups) == 1:
            return self.version_groups[0]
        return None

    def is_visible(self, block, choices: dict[str, str]) -> bool:
        """块在本次抽签结果下是否可见。无版本标签 = 全版本可见。"""
        versions = getattr(block, "versions", None) or []
        if not versions:
            return True
        group = self.group_of(block)
        if group is None:
            return True
        return choices.get(group.id) in versions

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
        self._validate_versions()
        return self

    def _validate_versions(self) -> None:
        """版本组引用完整性 —— 悬空 option / 未知组 / 多组歧义。

        结构性问题（漏标、跨版本引用等）不在这里判：那需要模拟过滤后的
        序列，放在 ``csm_core.template.lint`` 里做，保存时以警告呈现，
        不阻断加载旧模板。
        """
        group_ids = [g.id for g in self.version_groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("duplicate version group id")

        def walk(items: list) -> None:
            for b in items:
                versions = getattr(b, "versions", None) or []
                gid = getattr(b, "version_group", None)
                if gid and gid not in group_ids:
                    raise ValueError(
                        f"block '{b.id}' version_group unknown id '{gid}'"
                    )
                if versions:
                    if not self.version_groups:
                        raise ValueError(
                            f"block '{b.id}' 标了版本 {versions} 但模板没有声明 version_groups"
                        )
                    group = self.group_of(b)
                    if group is None:
                        raise ValueError(
                            f"block '{b.id}' 标了版本但没指明 version_group"
                            f"（模板有 {len(self.version_groups)} 个版本组，必须显式指定）"
                        )
                    unknown = [v for v in versions if v not in group.options]
                    if unknown:
                        raise ValueError(
                            f"block '{b.id}' versions {unknown} 不在版本组 "
                            f"'{group.id}' 的 options 里"
                        )
                if isinstance(b, ParagraphBlock):
                    walk(b.children)

        walk(self.blocks)
