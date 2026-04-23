# Paragraph 高级配置对话框（恢复 filter / pick / depends / 加子块 UI）

**Date:** 2026-04-23
**Status:** Approved, awaiting implementation plan

## 背景

统一块模型（2026-04-22）迁移期间，`slot_tree_widget.py` 被整体重写，三个旧的独立对话框（`_FilterDialog` / `_PickDialog` / `_DependsDialog`）被删除。`_BlockNode` 数据模型仍然保留相应字段（`filter_cond` / `pick_notes` 的 `PickCountSpec` 形态 / `pick_variants_per_note` / `unique_notes` / `depends_on`），模板 JSON 里写的值能正确读入并回写保存——但**用户无法在 UI 里编辑这些字段**，只能手改 JSON。同时，paragraph 虽然能有 children，UI 却缺少"新增子块"按钮，空 paragraph 根本无法在 UI 里加第一个 child。

## 设计目标

- 让用户无需离开模板编辑器就能配置 paragraph 的全部高级字段。
- 保持行内控件简洁：高级字段集中到一个对话框，不在行里堆按钮。
- 支持在 UI 里新增 child paragraph。

## 适用范围

- **仅 paragraph 块**。`numbered_list` 和 `competitor_pool` 虽然也有 `filter` / `pick_notes(PickCountSpec)` 字段，本次不纳入（它们当前的简洁 UI 满足绝大多数场景；如需要可在后续单独扩）。

## 行上控件改动

paragraph 行右侧操作区：

```
之前：[↓]  [↑]  [🗑]
之后：[⚙]  [➕]  [↓]  [↑]  [🗑]
```

- **⚙ 高级**：打开 `BlockAdvancedDialog`。仅 paragraph 可见，`setVisible(kind=="paragraph")`。
- **➕ 加子块**：调用现有 `SlotTreeWidget._add_child(node)`。仅 paragraph 可见。
- 其他块（heading / numbered_list / hero_brand / competitor_pool / literal）的行保持不变。

## BlockAdvancedDialog

新文件 `csm_gui/widgets/block_advanced_dialog.py`。`MessageBoxBase` 子类，三个竖直分区，`StrongBodyLabel` 做分区小标题。

```
┌──────────────────────────────────────────────┐
│ 段落高级设置 — {block_id} ({label})         │
├──────────────────────────────────────────────┤
│ [筛选]                                        │
│   键             值                    操作  │
│   素材类型 ▼     引言痛点,引言期待 ▼   🗑   │
│   ➕ 添加键                                   │
├──────────────────────────────────────────────┤
│ [采样]                                        │
│   取笔记数        [ 3 ▲▼]  ☐ 启用随机区间   │
│   （启用时出现）  最多 [ 5 ▲▼]              │
│   每条笔记取变体数 [ 1 ▲▼]                  │
│   ☐ 整篇不重复笔记（unique_notes）📌        │
├──────────────────────────────────────────────┤
│ [依赖]                                        │
│   （🔍 搜索框，>10 个候选时显示）           │
│   ☐ block_1  段落名称预览                    │
│   ☐ block_2  段落名称预览                    │
│   ☑ block_3  段落名称预览                    │
└──────────────────────────────────────────────┘
                           [取消]  [确定]
```

### `_FilterSection`（筛选分区）

- 键值表：每行 `[键 EditableComboBox] [值 EditableComboBox(多值)] [🗑]`。
- 键候选 = `_scan_frontmatter(vault_root / node.module).keys()`；值候选 = 对应键下的 `set[str]`。允许用户手敲不在候选里的键/值（自动补全仅是辅助，不限制输入）。
- 值多选用**逗号分隔字符串**：UI 是单个 `EditableComboBox`，用户输入 `"引言痛点, 引言期待"` 时保存为 `["引言痛点", "引言期待"]`；输入 `"简单"` 时保存为 `"简单"`（单值字符串）；空字符串 → 该键不写入 `filter`。
- ➕ 按钮追加空白行；🗑 删除当前行。
- 模块变更（用户先改了主行的目录 picker，再打开对话框）时重新扫描候选——每次 `exec()` 打开对话框都重新扫一次，不缓存。

### `_SampleSection`（采样分区）

- **取笔记数**：`SpinBox`，范围 1-20，显示当前下限。
- **☐ 启用随机区间**：勾上后右侧出现第二个 `SpinBox`（上限，默认等于下限+1，范围 `[下限, 20]`）；取消勾选时 UI 回到单 SpinBox。
- 若 `_BlockNode.pick_notes` 初始就是 `{"random_between": [a, b]}`，打开时自动勾上并回显 `a`、`b`。
- 保存规则：
  - 未勾或 min == max → `int`（写入 `node.pick_notes = min`）。
  - 勾上且 max > min → `dict`（写入 `node.pick_notes = {"random_between": [min, max]}`）。
- **每条笔记取变体数**：`SpinBox`，范围 1-9，默认 1。映射 `node.pick_variants`。
- **☐ 整篇不重复笔记**：`CheckBox`，tooltip `"父段落与子段落不重复同一笔记（unique_notes）"`。映射 `node.unique_notes`（对应 `Block.constraints` 里的 `"unique_notes"` 字符串）。

### `_DependsSection`（依赖分区）

- `ListWidget`，每行是自定义的 row widget：`CheckBox + block_id（等宽）+ label 小字预览`。
- 候选来源：遍历 `SlotTreeWidget._roots` 递归收集所有 block 的 `(id, label, node_ref)`。
- 排除规则：
  - 自身：`node_ref is self_node`。
  - 所有子孙：递归遍历 `self_node.children`，以 `id is` 比较节点引用。
- 候选数 > 10 时在顶部显示 `LineEdit` 搜索框，`textChanged` 动态过滤（不区分大小写、匹配 id 或 label 任一字段）。
- 保存为 `list[str]`，顺序按 UI 勾选顺序稳定（`ListWidget` 自然顺序）。

## 数据往返

**打开对话框**：

```python
dlg = BlockAdvancedDialog(
    node=current_node,              # _BlockNode
    all_blocks=tree._collect_all(), # [(id, label, node_ref)] 全树扫描
    vault_root=vault_root,          # Path | None，用于 filter 候选
    parent=self,
)
if dlg.exec():
    # 对话框确认：node 的字段已经在 dlg 内部直接写回。
    row.data_changed.emit()
```

**取消**：对话框不改 `node` 任何字段。

**确定**：对话框内部把 UI 值回写到 `node` 上（对 `_BlockNode` 的**同一实例**直接赋值），然后 `self.accept()`。调用侧负责 `data_changed` 信号触发 `SlotTreeWidget.slots_changed`。

## 文件布局

**新建**：

```
csm_gui/widgets/block_advanced_dialog.py       (~300 行)
  - class BlockAdvancedDialog(MessageBoxBase)
  - class _FilterSection(QWidget)
  - class _SampleSection(QWidget)
  - class _DependsSection(QWidget)

tests/gui/test_block_advanced_dialog.py         (6-7 个测试)
```

**修改**：

```
csm_gui/widgets/slot_tree_widget.py
  - _BlockRow.__init__: 传入 all_blocks_getter + vault_root_getter（闭包），
    加 _gear_btn 和 _add_child_btn，仅 paragraph setVisible(True)。
  - _BlockRow.open_advanced_dialog() 测试辅助方法。
  - _BlockRow.click_add_child() 测试辅助方法。
  - SlotTreeWidget._collect_all_blocks() 辅助：递归返回 [(id, label, node_ref)]。
```

## 测试清单

`tests/gui/test_block_advanced_dialog.py`：

1. **test_dialog_loads_existing_filter_and_pick** — paragraph 带 `filter={"素材类型": ["引言痛点"]}` 和 `pick_notes={"random_between": [2,3]}` 打开对话框后，UI 正确回显键值表 + 勾上"启用随机区间"复选。
2. **test_dialog_add_and_remove_filter_row** — 点 ➕ 添加空白行；点 🗑 删除。提交后 `node.filter_cond` 反映新状态。
3. **test_dialog_pick_notes_serialization** — 不勾区间 → 保存为 `int`；勾上且 max>min → 保存为 `dict(random_between=[a,b])`；勾上但 max==min → 保存为 `int`。
4. **test_dialog_depends_excludes_self_and_descendants** — 当前 paragraph 有两层子孙，`_DependsSection` 的候选列表不包含自身与子孙。
5. **test_dialog_cancel_does_not_mutate_node** — 修改多个字段后点取消，`node` 所有字段保持原值。
6. **test_dialog_unique_notes_maps_to_constraints** — 勾上 `unique_notes`，保存后 `node.unique_notes == True`；`_BlockNode.to_block()` 生成的 `ParagraphBlock.constraints` 含 `"unique_notes"`。
7. **test_dialog_filter_empty_value_drops_key** — 键有填但值留空，保存后该键不出现在 `node.filter_cond` 里。

`tests/gui/test_slot_tree_widget.py`（扩展现有，不新建文件）：

8. **test_paragraph_row_shows_gear_and_add_child** — paragraph 行可见 gear + add_child 按钮；非 paragraph 行不可见。
9. **test_click_add_child_appends_child_and_expands** — 点 ➕ 后 `node.children` 长度 +1 且 `node.expanded==True`。

## YAGNI 边界

v1 **不做**：
- numbered_list / competitor_pool 的 filter / random_between UI。
- filter 嵌套 `$and` / `$or` / `$in` 等高级算子——schema 可能支持，但 UI 只做"键 = 值（可多选）"扁平形态。用户可继续用 JSON 写高级过滤。
- depends_on 的图形化依赖图。
- 对话框内"按当前配置试采样 3 次"预览。
- `pick_variants_per_note` 的"0 = 全部"魔法值。

等有实际需求再扩。

## 非目标

- 不动 `_BlockNode` 数据结构（已经能装下所有字段）。
- 不动 `csm_core/template/schema.py`（Pydantic 模型已就位）。
- 不动模板 JSON 加载 / 保存（`from_block` / `to_block` 已经正确处理所有字段）。
- 不触碰 reroll 流水线（v2 已完成，本任务与之独立）。
