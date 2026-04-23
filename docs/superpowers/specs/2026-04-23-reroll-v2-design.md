# Reroll v2（block 模型下的按 pick 重抽）

**Date:** 2026-04-23
**Status:** Approved, awaiting implementation plan

## 背景

`统一块模型（2026-04-22）`迁移完成后，原先基于 `Slot` 的 reroll 功能被整体删除。现在要在新的 block 模型上重新设计 reroll。

**用户场景**：生成草稿后，看到某条具体内容（某个笔记样本）不理想，希望只重抽这一条，不动其他内容。

## 设计目标

- 粒度：单个 pick（不是整个 block，不是整篇）。
- 最小扰动：优先换变体（同笔记的 ①②③），再换笔记。
- 保持约束：`unique_notes`、competitor 不重品牌。
- 不级联：paragraph 的 children 独立于父 pick。
- 候选耗尽时明确反馈：按钮禁用 + tooltip，不静默失败。

## 适用范围

| Block kind | 支持 reroll? | 说明 |
|---|---|---|
| `paragraph` | ✅ | 通常 `pick_notes=1`；`children` 不受影响 |
| `numbered_list` | ✅ | 每条独立 reroll |
| `competitor_pool` | ✅ | 排除姐妹 picks 的 note_id 保证品牌唯一 |
| `heading` | ❌ | 无采样 |
| `literal` | ❌ | 无采样 |
| `hero_brand` | ❌ | 区域标记，无采样 |

## 候选池策略

给定 `block_id` + `pick_index`，计算候选池步骤：

1. 找到 `plan.results[block_id].picks[pick_index]` 作为"当前 pick"。
2. 重新拉该 block 的 `source`（`notes_query` → `scan_notes(vault, module, filter)`）得到全量笔记池。
3. 过滤掉：
   - 同 block 内其他 picks 已占用的 `note_id`（保持 `unique_notes`）
4. 优先级分层：
   - **第一层**：当前 pick 同笔记的其他 variant（排除当前 `variant_index`）
   - **第二层**：其他笔记的所有 variant
5. 从第一层随机抽一个；第一层空则从第二层抽；两层都空 → 抛 `NoCandidatesError`。

**注**：第一层让用户点一次就换一个变体，直到变体用完才换笔记。这匹配"只想换这句话"的心智。

## 不级联

paragraph 的 `children` 在父 pick 被 reroll 时保持不变。实现上：`reroll_pick` 只替换 `BlockResult.picks[pick_index]`，不触发 children 重采。

## 持久化

reroll 修改的是**会话内** `AssemblyPlan`，不改 Template JSON 也不改 vault。调用方（Article controller）持有 `current_plan`，reroll 后替换为新 plan 并刷新视图。

## 模块划分

### 核心（纯函数）

```
csm_core/assembler/reroll.py
  - NoCandidatesError(Exception)
  - reroll_pick(
        plan: AssemblyPlan,
        block_id: str,
        pick_index: int,
        template: Template,
        vault_root: Path,
        *,
        rng: random.Random | None = None,
    ) -> AssemblyPlan
```

职责：纯函数，输入 plan + 定位信息 + 上下文，返回新 plan（复制 + 替换目标 pick）。候选耗尽抛 `NoCandidatesError`。

### GUI worker

```
csm_gui/workers/reroll.py
  - RerollWorker(QThread): 包装 reroll_pick，发 finished(plan) / failed(msg)
```

### Controller / UI

```
csm_gui/controllers/article_controller.py
  - reroll_pick(block_id: str, pick_index: int) -> None
  - reroll_completed = pyqtSignal(AssemblyPlan)
  - reroll_failed = pyqtSignal(str)

csm_gui/pages/article_page.py
  - 渲染 draft 时，每条 pick 旁挂刷新按钮
  - 点击 → 发 reroll_pick_requested(block_id, pick_index)
```

UI 侧显示 pick 列表的载体可以是 `MarkdownView` 或新增 `PickListView`——具体在 plan 阶段决定。

## 候选耗尽 UX

- `NoCandidatesError` 被 controller 转成 `reroll_failed(msg)` 信号。
- UI 侧弹 toast / 把按钮禁用 + tooltip "没有更多候选"。
- 非禁用态也可能耗尽（候选池随历史 reroll 缩小到 0）——运行时判定，不用 pre-compute。

## 测试

### 核心

`tests/core/assembler/test_reroll.py`：

- `test_reroll_numbered_list_keeps_other_picks`：numbered_list 3 个 pick，reroll 其一，另两个不变。
- `test_reroll_prefers_sibling_variant`：当前 pick 笔记有多个 variant 时，reroll 返回的 pick 仍来自同笔记但不同 variant。
- `test_reroll_falls_back_to_different_note`：当前笔记变体用尽，reroll 换到其他笔记。
- `test_reroll_respects_unique_notes`：同 block 其他 picks 的 note_id 不会被选中。
- `test_reroll_competitor_pool_keeps_unique_brands`：competitor_pool 不重 note_id。
- `test_reroll_paragraph_leaves_children_untouched`：父 paragraph reroll 后 children 原样。
- `test_reroll_raises_no_candidates`：池子只有 1 个笔记 1 个变体，reroll 抛 `NoCandidatesError`。

### GUI

- `tests/gui/test_reroll_worker.py`：基础 worker 冒烟（mock `reroll_pick`，验 finished 信号）。
- Article page UI 测试：刷新按钮点击 → 发信号，候选耗尽 → 按钮禁用（可延后）。

## YAGNI 边界

v1 **不做**：
- "换笔记" vs "换变体"两个独立按钮——只一个"重抽"，内部自动分层。
- reroll 整个 block（所有 picks 同时换）——用户可手动依次点。
- reroll 历史 / undo——用户不满意就再 reroll。

等有需求再扩。

**注**：paragraph children（嵌套 paragraph 块）的 picks 走同一机制——`AssemblyPlan.get_result(block_id)` 递归查找，`reroll_pick` 对任意深度的 block_id 都能定位。UI 按钮挂在每个 pick 上即可。
