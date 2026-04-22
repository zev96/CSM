# 统一模板块模型（移除框架层）

**Date:** 2026-04-22
**Status:** Approved, awaiting implementation plan

## 背景与动机

当前架构分两层：

- **Template** 定义 slot 列表（内容原材料 + 随机采样规则）。
- **Framework** 定义文章骨架（块顺序：段落/标题/编号列表/品牌列表/固定文本），通过 `slot` 字符串引用模板里的 slot id。

实际使用中：

1. 框架与模板几乎总是 1:1 绑定，没有复用收益。
2. `slot` 跨文件引用靠字符串对齐，容易错。
3. GUI 里"框架"与"模板"两个标签页割裂，用户要来回切、手动核对 id。
4. 编号列表当前需要人工在 vault 文件里写"1. 2. 3."，无法做"随机抽 N 条自动编号"。

结论：合并。模板即骨架，WYSIWYG。

## 目标

- 模板的"模块"标签页直接编辑完整文章结构。
- 删除 framework 层（schema、loader、GUI 标签、相关代码与测试）。
- 编号列表支持"从目录随机抽 N 篇 → 渲染时自动加序号"。
- 对已有模板与框架做一次性迁移。

## 新的块模型

`Template.slots` 字段更名为 `Template.blocks`，类型从单一的 `Slot` 改为带 `kind` 判别字段的 tagged union。

### 块类型

#### 1. `paragraph`（段落）
当前 `Slot` 的直接延续：从目录/模块采样 1 篇素材作为一段正文。

```json
{
  "kind": "paragraph",
  "id": "slot_1",
  "label": "痛点共鸣",
  "source": { "type": "notes_query", "module": "吸尘器/痛点共鸣" },
  "pick_variants_per_note": 1,
  "children": [...]        // 保留现有"子变体"能力
}
```

现有 `Slot` 的 `pick_notes` / `constraints` / `depends_on` / `children` 全部保留在 `paragraph` 块上。

#### 2. `heading`（标题）

```json
{
  "kind": "heading",
  "id": "h_1",
  "level": 2,          // 1 | 2 | 3
  "index": "一、",     // 可选前缀
  "text": "{keyword}应该怎么选？"   // 支持 {keyword} 变量
}
```

不采样任何素材，直接渲染成 H1/H2/H3。

#### 3. `numbered_list`（编号列表）

```json
{
  "kind": "numbered_list",
  "id": "list_1",
  "label": "科普攻略",
  "source": { "type": "notes_query", "module": "吸尘器/科普攻略" },
  "pick_notes": { "random_between": [3, 3] },   // 抽 3 篇
  "number_style": "1.",  // "1." | "一、" | "none"
  "item_separator": "\n\n"
}
```

行为：
- 从 `source` 目录随机抽 `pick_notes` 指定数量的 .md 文件。
- 每个文件作为**一个编号项**；vault 里不要自带序号。
- 渲染时按 `number_style` 生成 `"1. "` / `"一、"` 等前缀 + 正文内容，项之间用 `item_separator` 分隔。
- `pick_notes` 复用现有 `PickCountSpec`（支持固定数、随机区间、用户可调范围）。

#### 4. `brand_reason_list`（品牌推荐列表）

```json
{
  "kind": "brand_reason_list",
  "id": "brand_1",
  "subslots": [
    { "id": "brand_1.bg", "label": "品牌背书",
      "source": { "type": "notes_query", "module": "希喂推荐内容/品牌背书" } },
    { "id": "brand_1.tech", "label": "核心技术",
      "source": { "type": "notes_query", "module": "希喂推荐内容/核心技术" } }
  ],
  "reason_label": "推荐理由："
}
```

等价于现框架的 `brand_reason_list`，但把"多个外部 slot id"改成"内嵌 subslots"——再也不用跨文件对齐 id。

#### 5. `literal`（固定文本）

```json
{ "kind": "literal", "id": "lit_1", "text": "..." }
```

原样输出，支持 `{keyword}` 变量。

### 顺序

`render_order` 字段移除。顺序由 `blocks` 数组本身决定（现在 blocks 既是声明又是顺序，和框架一致）。

## Schema 变更摘要

`csm_core/template/schema.py`：

```python
class ParagraphBlock(BaseModel):
    kind: Literal["paragraph"]
    id: str; label: str; source: SourceT
    pick_notes: PickNotes = 1
    pick_variants_per_note: int = 1
    constraints: list[str] = []
    depends_on: list[str] = []
    children: list["ParagraphBlock"] = []

class HeadingBlock(BaseModel):
    kind: Literal["heading"]; id: str
    level: Literal[1,2,3] = 2; index: str = ""; text: str

class NumberedListBlock(BaseModel):
    kind: Literal["numbered_list"]
    id: str; label: str; source: SourceT
    pick_notes: PickNotes = 3
    number_style: Literal["1.","一、","none"] = "1."
    item_separator: str = "\n\n"

class BrandReasonListBlock(BaseModel):
    kind: Literal["brand_reason_list"]; id: str
    subslots: list[_SubSlot] = Field(min_length=1)
    reason_label: str = "推荐理由："

class LiteralBlock(BaseModel):
    kind: Literal["literal"]; id: str; text: str

Block = Annotated[Union[...], Field(discriminator="kind")]

class Template(BaseModel):
    id: str; name: str; product: str; version: int = 1
    system_prompt_default: str = ""
    seo_defaults: SEODefaults
    blocks: list[Block]
    # removed: slots, render_order, default_framework
```

## 采样与渲染

- `assembler`：遍历 `blocks`，按 `kind` 分派。`paragraph` 走现有采样路径；`numbered_list` 走"批量采样 N 篇"路径（复用现有 source 解析，循环 pick）；`heading` / `literal` 直接产出文本；`brand_reason_list` 展开 subslots，每个采样 1 篇。
- `renderer`：`numbered_list` 在此处应用 `number_style` 生成前缀。vault 文件内容保持纯文本。

## 迁移

一次性迁移脚本 `scripts/migrate_framework_to_blocks.py`：

输入：所有 `templates/*.json` 和 `frameworks/*.json`。
规则：
1. 对每个 template，按 `default_framework`（若有）或按命名约定找到匹配的 framework。
2. 用 framework 的 blocks 作为新 template 的 blocks 骨架。
3. 把 framework 里的 `paragraph` / `numbered_list` 块按 `slot` 字段与 template 里的 slot 合并（复制 source / pick_notes / children 到 block 上）。
4. `brand_reason_list`：把引用的 slot 列表就地转为 subslots。
5. 写回 `templates/*.json`（新 schema），备份原文件到 `templates/_migrated_backup/`。
6. 删除 `frameworks/` 目录。

脚本需幂等（检查新 schema 已存在则跳过）。

## GUI 变更

- 删除"框架"标签页、`framework_list_panel.py`、`framework_editor_panel.py`、`framework_block_card.py`。
- `slot_tree_widget.py` 扩展为"块树"：每行顶部加一个 kind 选择器（下拉：段落/标题/编号列表/品牌推荐/固定文本），按选中 kind 展示对应字段。
- `GenerationForm` 的"框架"下拉移除（早前提交 `cc69b6c` 和 `d64ebc4` 引入的相关逻辑回滚）。

## 代码删除清单

- `csm_core/framework/`（整个目录）
- `csm_gui/widgets/framework_*.py`
- `csm_gui/pages/template_manager_page.py` 里的"框架"标签页
- `tests/**/test_framework_*.py` 与相关 fixture
- `Template.default_framework` 字段及其所有引用
- `GenerationForm` / `ArticleController` 里的 `framework_id` 参数

## 测试策略

- Schema 单元测试：每种 kind 的序列化/反序列化、验证错误。
- Assembler：每种 kind 的采样路径，特别是 numbered_list 的 "抽 3 篇 → 3 个独立 item"。
- Renderer：每种 number_style 的前缀正确性；brand_reason_list 的 subslots 展开。
- 迁移脚本：对现有 `templates/` + `frameworks/` 跑一次，断言输出与手工预期一致。
- E2E：现有"pipeline → 成品"测试改造为使用新 schema，验证无回归。

## 开放问题

无。编号列表的"子变体"能力按用户确认不需要——vault 里每篇就是一个 item，不再嵌套。
