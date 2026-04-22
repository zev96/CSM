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

#### 4. `hero_brand`（主品区域起点）+ `competitor_pool`（竞品池 / 区域闭合）

替代旧 `brand_reason_list`。用"区域标记"两块配合使用，好处是**不破坏模板里现有 paragraph slot 的随机采样**——它们仍然独立设置，只是在渲染阶段被"吞"进主品的推荐理由段。

```json
{
  "kind": "hero_brand",
  "id": "hero_1",
  "title": "CEWEY DS18无线吸尘器",
  "reason_label": "推荐理由：",
  "number_style": "1."
}
```

```json
{
  "kind": "competitor_pool",
  "id": "comp_1",
  "source": { "type": "notes_query", "module": "吸尘器/竞品推荐内容" },
  "pick_notes": { "random_between": [2, 2] },
  "reason_label": "推荐理由："
}
```

**区域语义**：

- `hero_brand` 开启一个区域。从它之后到下一个 `competitor_pool` / `hero_brand` / blocks 末尾之间的所有 `paragraph` 块，其采样行为完全不变；但**它们的输出被聚合为主品的"推荐理由"正文**，不再作为顶层独立段落。
- `competitor_pool` 闭合上一个 `hero_brand` 区域；然后从 `source` 池随机抽 `pick_notes` 个不重复的 .md 文件，每个展开为一条编号项，**沿用 `hero_brand.number_style` 连续编号**（主品是 1，竞品继续 2、3）。之后恢复顶层块渲染。
- 若模板里没有 `hero_brand`，只有 `competitor_pool`，则后者独立充当一个普通编号推荐列表（从 1 开始）。

**竞品 .md 文件约定**：

```
---
型号: 戴森V8
产品: 吸尘器
素材类型: 竞品推荐理由
核心关键词: [戴森V8, 戴森吸尘器, 高端吸尘器]
---

① 作为家电领域的先锋品牌，戴森V8吸尘器算是戴森的经典产品了 …
② 相信戴森这个牌子大家应该都不陌生吧 …
③ 说起家电，戴森算是挺有口碑的品牌了 …
```

- `title` 取 frontmatter 的 `型号` 字段。
- 正文按正则 `^[①②③④⑤⑥⑦⑧⑨⑩]\s+` 切分为多个候选段，**随机挑 1 个**作为本条的推荐理由正文。
- 若文件无 ①②③ 标记，整个正文作为单一理由文本。

**`number_style` 支持值（v1）**：`"1."` / `"一、"` / `"none"`。默认 `"1."`。后续可扩展带文字的样式（如 `"推荐一"`），通过在此枚举中追加成员实现，不影响现有数据。

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

class HeroBrandBlock(BaseModel):
    kind: Literal["hero_brand"]; id: str
    title: str                             # literal, GUI-entered
    reason_label: str = "推荐理由："
    number_style: Literal["1.","一、","none"] = "1."

class CompetitorPoolBlock(BaseModel):
    kind: Literal["competitor_pool"]; id: str
    source: SourceT
    pick_notes: PickNotes = 2
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

**两阶段**：

1. **Assembler（采样阶段）**：线性遍历 `blocks`，按 `kind` 分派。
   - `paragraph`：走现有采样路径（source + pick_notes + children 子变体），不变。
   - `numbered_list`：从 source 批量采样 N 个 .md，产出 N 条 item 文本。
   - `heading` / `literal`：直接产出文本（解析 `{keyword}` 变量）。
   - `hero_brand`：不采样，只输出一个"区域起点"标记节点，携带 title / reason_label / number_style。
   - `competitor_pool`：从 source 抽 N 个 .md；对每个文件解析 frontmatter 的 `型号` 字段作为 title；正文按 `^[①②③④⑤⑥⑦⑧⑨⑩]\s+` 切分为候选段后随机挑 1 段作为 reason。产出 N 条 `(title, reason)` 结构 + 区域闭合标记。

2. **Renderer（排版阶段）**：遍历 assembler 输出，按顺序拼接文本。
   - 遇到 `hero_brand` 起点 → 进入"hero 收编模式"，开一个缓冲区暂存后续 `paragraph` / `numbered_list` 的输出。
   - 遇到 `competitor_pool`（或另一个 `hero_brand` / blocks 末尾）→ 闭合 hero 区域：
     - 输出 `"{number_style(1)} {hero.title}\n{reason_label}\n{收编的段落正文}"`
     - 再输出 `competitor_pool` 的 N 条：`"{number_style(2)} {comp.title}\n{reason_label}{comp.reason}"` … 连续编号。
   - 不在任何区域内的 `paragraph` / `numbered_list` / `heading` / `literal` 正常输出。
   - `numbered_list` 的 `number_style` 独立于 `hero_brand`——它是块内自己的小列表。

**number_style 实现**：用一个 `_format_index(i, style)` 工具函数，`"1."` → `f"{i}."`，`"一、"` → 中文数字映射，`"none"` → 空串。新样式后续只需在此函数加分支。

## 迁移

一次性迁移脚本 `scripts/migrate_framework_to_blocks.py`：

输入：所有 `templates/*.json` 和 `frameworks/*.json`。
规则：
1. 对每个 template，按 `default_framework`（若有）或按命名约定找到匹配的 framework。
2. 用 framework 的 blocks 顺序作为新 template 的 blocks 骨架。
3. framework 的 `paragraph` / `numbered_list` 块按 `slot` 字段合并进 template 里对应的 slot（source / pick_notes / children 复制到 block 上）。
4. framework 的 `brand_reason_list`：转换为 `hero_brand` + `competitor_pool` 两个新块。迁移脚本无法推断哪个是"主品"——遇到此情况**打印警告并跳过该 template**，要求用户手工重建这部分（我们库里目前只有 1 个模板，手工处理成本低）。
5. 写回 `templates/*.json`（新 schema），备份原文件到 `templates/_migrated_backup/`。
6. 删除 `frameworks/` 目录。

脚本需幂等（检查新 schema 已存在则跳过）。

## GUI 变更

- 删除"框架"标签页、`framework_list_panel.py`、`framework_editor_panel.py`、`framework_block_card.py`。
- `slot_tree_widget.py` 扩展为"块树"：每行顶部加一个 kind 选择器（下拉：段落/标题/编号列表/主品区域/竞品池/固定文本），按选中 kind 展示对应字段。
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
- Assembler：每种 kind 的采样路径，特别是 numbered_list 的"抽 N 篇 → N 个独立 item"、`competitor_pool` 的 frontmatter 解析 + ①②③ 候选段切分与随机挑选。
- Renderer：
  - 每种 `number_style` 的前缀正确性。
  - `hero_brand` 区域收编：`paragraph` / `numbered_list` 在区域内不作为顶层段落、正确聚合进主品 reason。
  - `hero_brand` + `competitor_pool` 的连续编号（hero=1, comp=2,3,…）。
  - 无 `hero_brand` 时 `competitor_pool` 独立从 1 编号。
- 迁移脚本：对现有 `templates/` + `frameworks/` 跑一次，`brand_reason_list` 的跳过警告行为正确；其他块迁移输出与手工预期一致。
- E2E：现有"pipeline → 成品"测试改造为使用新 schema，验证无回归。

## 开放问题

无。
- 编号列表的"子变体"能力按用户确认不需要——vault 里每篇就是一个 item，不再嵌套。
- 主品区域的 title 初版为 GUI 字面量输入；未来若要支持"从 vault 采样主品名"再扩展。
- `number_style` 初版只支持 `1.` / `一、` / `none`；带文字的样式（如 `推荐一`）后续在同一枚举扩展。
