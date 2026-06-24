# Phase 2a 设计：标题 + 角度 智能组装

- 日期：2026-06-24
- 上位文档：[创作台升级总体路线图](2026-06-23-creation-studio-upgrade-roadmap-design.md) 的 **Phase 2（头牌）**
- 前置：Phase 1 全交付（品牌型号记忆库 + 注入 + 事实核对 + skill role 字段 + 素材库只读 tab），已在真实盘上线。
- 范围（本轮）：**只做「角度智能组装」这一块**——受控词表（小映射）+ 角度模型 + 预设组合 + 混合组装 + 标题领衔 + reroll 跟随角度 + 前端 angle picker。
- **不在本轮**：skill 链多-pass（人设→去AI味→平台适配）、禁区 lint（emoji/破折号/绝对化/引流话术 确定性扫描）——各留后续轮。

---

## 0. 目标与现状

**一句话目标**：换关键词不动、只换「角度」（人群 / 卖点 / 语调 / 标题），就能产出**结构和侧重明显不同、但参数依旧接地**的文章。

**现状基线（实勘 main，2026-06-24）**：
- 主链路 6 段线性编排（[generate_service.py:130-272](../../../sidecar/csm_sidecar/services/generate_service.py)）：scan_vault → load_template → `assemble_plan`（确定性采样）→ `compose_draft` → 注入 brand_facts（Plan 3）→ `build_prompt` → LLM `complete` → factcheck 门禁 → export。
- **选材是模板驱动 + frontmatter 精确等值过滤**：`VaultIndex.query(module, filters)` 走 `n.frontmatter.get(k) == v`（[scanner.py:41](../../../csm_core/vault/scanner.py)）。今天没有任何角度概念。
- **变体纯随机**：`_pick_variant` = `rng.randrange(len(variants))`（[sampler.py:59](../../../csm_core/assembler/sampler.py)）；`ParsedNote.variants` 是裸 `list[str]`，无语调标记。
- **LLM 是「润色模式」**：「保留所有信息点和段落结构，只改进文字流畅度」（[prompts.py:29](../../../csm_core/llm/prompts.py)），不选材、不重排。
- **标题生成器已存在但没接主链路**：[title/generator.py:323 `generate_titles`](../../../csm_core/title/generator.py)（公式驱动、关键词原样保留、出 N 候选），且已有 **`POST /api/title`** 端点（[routes/article.py:16](../../../sidecar/csm_sidecar/routes/article.py)）+ 前端 `fetchTitleCandidates` 已在调。export 阶段只是 `extract_title(final_text) or keyword` 事后取首个标题。
- **reroll 重查模板静态 filter**：`reroll_pick` 用 `source.filter`（[reroll.py:62](../../../csm_core/assembler/reroll.py)）；不跟任何动态 filter。
- **关联数据库.md** 是角度→选材的现成种子：16 人群（§5 四维矩阵，**用户人群笔记有可查的 `人群分类` frontmatter**）、~12 卖点维度（§3.1/§8，对齐品牌话术维度键）、7 框架（§7 = 结构 = 模板）、4 条命名内容流预设（§4.3）、情绪钩子映射（§4.2）。**但痛点/科普是 wikilink 关联、不是 frontmatter**——只有「用户人群」一层和「品牌话术（已按维度索引）」是廉价确定性可用的。

---

## 1. 决策记录（已与用户拍板）

1. **混合路线**：确定性锁事实接地，LLM 按标题+角度选材排序/侧重/定调；不新增事实。
2. **小映射 + LLM 指令承载**：廉价确定性只做两件（人群按 `人群分类` 过滤用户人群块；卖点维度在注入时优先该维度话术）；§5 四维矩阵转成一张小配置表，用来定义预设 + 喂 LLM 角度指令块。跨模块精细选材交给 LLM。**不建完整 taxonomy 子系统、不解析 vault prose、不依赖笔记名。**
3. **语调 = LLM 改写**：Phase 2a 不动实盘 vault，不给变体打语调标记。
4. **角度收成 3 facet**：人群 / 卖点 / 语调。**结构 = 现有 template**（不做和模板选择器重复的第 4 facet）；标题类型由现有标题公式按模板自动出。
5. **预设可顺带预选 template**：`preset → {template_id?, audience?, sellpoints, tone?}`，让一条内容流成为完整起点（连框架一起带出）。预设是纯 UI 填充，请求只带解析后的 facet。
6. **LLM 契约用保守版**：「保留所有信息点 + 按角度调整**侧重/顺序/详略/语调** + 标题领衔；不新增或改动任何数字/单位/认证」。**不允许取舍删减素材**（激进版会重新引入 factcheck 不拦的「漏型号参数」静默风险，留 Phase 2.x + 完整性校验再上）。
7. **全 opt-in / 向后兼容**：不传 angle 且不传 title = 今天行为，零回归（快照测试钉死）。

---

## 2. 数据模型（新包 `csm_core/angle/`）

### 2.1 `Angle`（per-request，全可空）— `csm_core/angle/model.py`

```python
class Angle(BaseModel):
    audience: str | None = None        # 16 人群之一，如 "铲屎官"
    sellpoints: list[str] = []         # 卖点维度键，0..N，如 ["防缠绕技术", "续航时间"]
    tone: str | None = None            # "口语" | "专业" | "极客"

    def is_empty(self) -> bool:
        return not self.audience and not self.sellpoints and not self.tone
```

`is_empty()` 为真 ⇔ 等价于「不传 angle」⇔ 今天行为。

### 2.2 小映射词表 — `csm_core/angle/taxonomy.py`（版本控制，从 关联数据库.md 一次性人工转录）

```python
# 语调三档 + 每档 LLM 改写指引（语调是叠加在 skill 人设之上的修饰）
TONES: dict[str, str] = {
    "口语": "在保持人设前提下偏口语：多用短句、第二人称「你」、生活化比喻，像朋友唠嗑；少术语堆砌。",
    "专业": "在保持人设前提下偏专业：准确术语 + 参数化表达、结构清晰，像测评编辑；克制情绪化修辞。",
    "极客": "在保持人设前提下偏极客：强调原理、参数、横向对比与技术机制，面向懂行读者；可深入细节。",
}

# 卖点维度：规范值 = 品牌话术维度键（见下「⚠ 对齐」），display = 人话标签
SELLPOINT_DIMENSIONS: list[dict] = [
    {"key": "防缠绕技术", "label": "防缠绕"},
    {"key": "动力系统",   "label": "吸力/动力"},
    # ... ~12 项，Unit A 实现时用真实 vault 校准（见 §2.4）
]

# 16 人群 → 主推维度 / 痛点主题 / 科普主题（§5 四维矩阵）
AUDIENCES: dict[str, dict] = {
    "铲屎官":   {"主推维度": "防缠绕技术", "痛点主题": "缠毛困扰",   "科普主题": "防缠绕设计选购"},
    "过敏人群": {"主推维度": "过滤系统",   "痛点主题": "二次污染",   "科普主题": "过滤系统选购"},
    # ... 16 行
}

# 预设组合（§4.3 四条内容流 + 可扩）；template_id 引用现有 app 模板 id，不确定就留 None
PRESETS: list[dict] = [
    {"name": "宝妈/儿童健康", "template_id": None, "audience": "宝妈",
     "sellpoints": ["绿光显尘"], "tone": "口语"},
    {"name": "测评博主",     "template_id": None, "audience": None,
     "sellpoints": [], "tone": "专业"},
    {"name": "技术维修视角", "template_id": None, "audience": None,
     "sellpoints": [], "tone": "极客"},
    {"name": "选购困难",     "template_id": None, "audience": "通用人群",
     "sellpoints": [], "tone": "口语"},
]

AUDIENCE_MODULE_MARKER = "用户人群"   # 人群 filter 只加在 source.module 含此标记的块上
```

它是**角度选项、预设、LLM 指令文案、前端下拉**的单一来源。

### 2.3 派生函数 — `csm_core/angle/`

- **`effective_sellpoints(angle) -> list[str]`**：`angle.sellpoints` 非空就用它；否则若 `angle.audience` 命中 `AUDIENCES`，回退 `[AUDIENCES[audience]["主推维度"]]`；都没有则 `[]`。**用于注入优先 + 指令侧重**（只选人群也能驱动侧重）。
- **`effective_filters(source, angle) -> dict`**（`csm_core/angle/filters.py`）：起始 = `source.filter or {}`；若 `angle and angle.audience and AUDIENCE_MODULE_MARKER in (source.module or "")` → 并入 `{"人群分类": angle.audience}`；返回合并 dict。**采样、reroll、持久化共用这一处**（避免两边逻辑漂移）。
- **`render_angle_directive(angle, *, has_title) -> str | None`**（`csm_core/angle/directive.py`）：`angle.is_empty()` 返回 None；否则渲染一段中文指令，例如：

  > 本文面向【铲屎官】（核心痛点：缠毛困扰）。主打卖点：防缠绕、续航。语调：口语——在保持人设前提下偏口语：多用短句、第二人称「你」…。请围绕这些意图组织详略与顺序。

  - 人群行用 `AUDIENCES[audience]` 补「核心痛点」；主打卖点用 `effective_sellpoints`（display 标签）；语调取 `TONES[tone]`。
  - 宽松：facet 值不在词表 → 跳过该 facet（不硬失败）。

### 2.4 ⚠ 实现必校准：卖点维度键对齐

`render_brand_facts` 的「卖点优先」靠 `BrandModelMemory.scripts` 的 **dict 键匹配**。scripts 键由 resolver `_dimension_from_stem`（[resolver.py:28](../../../csm_core/brand_memory/resolver.py)）从 `核心技术-<维度>` / `次要技术-<维度>` 文件名解析（如 `动力系统`/`气旋技术`/`过滤系统`/`防缠绕技术`/`绿光显尘`/`机身重量`/`尘杯容量`/`续航时间`/`万向吸头`/`刷头配置`/`噪音大小`/`维护耗材`，见 关联数据库 §2.1）。

**Unit A 必须对真实 vault 跑一遍 `resolve_memory` 取 `scripts.keys()` 校准 `SELLPOINT_DIMENSIONS[*].key`**；不能照抄科普主题名（科普主题名≠话术维度键）。display 标签可人话化。

---

## 3. 混合组装流程（改 `generate_service._run_job`）

6 段不变，3 处加角度 + 1 处加标题白名单。`req` 加 `title: str|None`、`angle: Angle|None`。

| 段 | 改动 |
|---|---|
| ③ `assemble_plan(angle=…)` | 线程把 `angle` 传到 `sample_block`→`_sample_notes_source`/`_sample_source_for_block`；查询从 `index.query(module, source.filter)` 改为 `index.query(module, effective_filters(source, angle))`。**人群 filter 只在「用户人群」模块块生效**（其余块 `effective_filters` 原样返回 `source.filter`）。变体仍随机。 |
| 持久化 | `AssemblyPlan` 加 `angle: Angle\|None = None`（旧 JSON 无此字段→None，兼容）；`assemble_plan` 末尾写入。`assembler_service.cache_plan` 自然带上（它缓存整个 plan）。 |
| ⑤ 注入 | `render_brand_facts(scopes, *, variant_cap, endorsement_cap, sellpoints=[])`：`sellpoints` 非空时，命中维度话术**排最前 + 标【主打】**，其余维度仍渲染（不丢事实）。`generate_service` 传 `sellpoints=effective_sellpoints(angle)`（仅 `cfg_bm.inject` 时）。 |
| ⑥ `build_prompt` | `PromptInputs` 加 `title: str\|None`、`angle_directive: str\|None`。user prompt 新顺序：关键词 → **标题领衔行**（有 title）→ **角度指令块**（有 directive）→ 事实块 → 毛坯 → 润色指令 → 约束。**润色指令分支**：`title` 与 `angle_directive` 都空 → 用今天一字不差的原文（快照钉死）；否则用「保守版角度指令」：保留所有信息点 + 按角度调整侧重/顺序/详略/语调 + 围绕标题开篇贯穿 + 不新增/改动数字单位认证。 |
| ⑦ factcheck | `_maybe_block_for_factcheck` 的白名单源加最终 `title`：`sources = [draft] + ([title] if title else []) + ([brand_facts] if brand_facts else [])`。标题是受信源，避免标题里的合法数字自伤。 |

注入与 factcheck 的开关、white­list 超集语义、门禁 resume 全不变；LLM 只能用 draft∪facts∪title 的子集，安全。

---

## 4. 标题领衔（复用已有 `/api/title`，后端工作量小）

- **前端流程**：标题框留空时，前端用现有 `POST /api/title`（keyword + template_type）拉候选让用户选/编辑；选定后随 `generate` 提交。
- **后端只负责「有 title 就领衔」**：title 进 `build_prompt`（领衔行 + 保守指令里「围绕标题开篇贯穿」）。`export` 的 `extract_title` 仍兜底。
- 标题生成器本身 Phase 2a **不改**（仍 keyword + template_type；角度感知标题留未来）。

---

## 5. reroll 跟随角度

- `reroll_pick` 重查池：`pool = vault_index.query(module=source.module, filters=effective_filters(source, plan.angle))`，并把 `angle` 通过端点从缓存 plan 读出传入。
- Layer-2「换别的笔记」也在有效池内取 → 重随不跳出人群。
- 旧 plan 无 `angle`（None）→ `effective_filters` 退回纯 `source.filter`（兼容）。
- 语调不影响 reroll（变体随机 + LLM 定调）。
- `assembler.py` reroll 端点 body **不变**（angle 从缓存 plan 取，不让前端重传）。

---

## 6. API 改动（`sidecar/csm_sidecar/routes/`）

1. **`POST /api/generate`** `GenerateBody` += `title: str\|None = None`、`angle: Angle\|None = None`（[generate.py:35](../../../sidecar/csm_sidecar/routes/generate.py)）；透传到 `GenerateRequest`。
2. **`GET /api/angle/taxonomy`**（新，只读）：返回 `{tones, dimensions:[{key,label}], audiences:[name…], presets:[…]}`，给前端 picker 渲染——**taxonomy 单一来源在后端**，前端不重复维护 16/12/4 清单。
3. `POST /api/title`、`POST /api/assembler/reroll` **不变**。

---

## 7. 前端 UI（angle picker）

- **新组件 `AnglePicker.vue`**（`components/article/` 或 `components/home/`）：popover 内容
  - **预设组合**快选（4 张 chip）→ 选一张填充下面 facet（含 `template_id` 则一并切模板）
  - 人群 `FormSelect`（16，可空）· 卖点维度多选 chips（0..N）· 语调 `FormSelect`（可空）· 标题 `FormInput`（可空，占位「留空自动生成」）+「生成候选」按钮（调 `/api/title`）
  - 选项数据来自 `GET /api/angle/taxonomy`（启动拉一次）
- **`CreateArticleHero.vue`**（home takeoff）加「**角度**」chip（与 模板/风格 平级）打开 AnglePicker；`takeoff()` push query 带**扁平参数** `audience` / `sellpoints`（逗号连）/ `tone` / `title`。
- **`ArticleView.vue`**：`takeoff()` 从 query 重建 `Angle` + title，纳入 submit；header 显示「角度」chip（像 skill chip）；成稿 tab「换标题」复用现有 `titleCandidates`。
- **`stores/article.ts`**：`GenerateRequest` 接口 += `title?`、`angle?`（TS 镜像类型）；`submit` POST 带上；`lastRequest` 带 angle/title（`rerun` 种子 +1 时角度/标题不丢）。
- 复用 `FormSelect`/`FormInput`/`FormField`/`FormToggle`；**全程硬编码中文**（代码库无 i18n）。

---

## 8. 错误处理 & 兼容

- `angle`/`title` 皆空 → 今天行为（零回归，快照测试守 `build_prompt` 旧 prompt 不变）。
- 人群 filter 命中空池 → **回退不过滤 + warning**（别让角度把文章搞空）；`assemble_plan` 现有 `EmptyPoolError` 路径之上加「角度过滤后空 → 去掉人群 filter 重采该块」。
- 模板无「用户人群」块（如纯参数对比文）→ 人群在确定性层无 hook，但仍由 LLM 指令承载「面向 X」，优雅降级。
- 卖点/人群/语调值不在词表 → 丢弃该值 + warning，**绝不硬失败**（opt-in / 向后兼容）。
- LLM 不完全服从角度 → 混合的已知边界；factcheck 仍兜「事实增加」。
- 旧 plan JSON（无 angle）reroll → 退纯 template filter。
- **词表按品类隔离**：当前 16 人群/12 维度都是吸尘器；taxonomy 结构留 category 维度，本轮只填吸尘器，多品类是未来。
- **不加新全局配置**：角度是 per-request、按「有没有传」opt-in，无需 Plan 6 那种设置开关。

---

## 9. 测试要点（TDD）

**Unit A（纯数据）**
- 词表加载 + 引用完整性：每个 PRESET 引用的 audience/sellpoints/tone 都在词表内。
- `effective_sellpoints`：显式卖点 > 人群派生主推维度 > 空。
- `effective_filters`：用户人群块 + audience → 并入 `人群分类`；非用户人群块 → 原样；无 angle → 原样。
- `render_angle_directive`：各 facet 组合 → 期望中文（含 AUDIENCES lookup、TONES 文案）；空 angle → None；非法值 → 跳过不报错。
- **维度键对齐**：真实 vault 取 `scripts.keys()` ⊇ `SELLPOINT_DIMENSIONS[*].key`（校准守门）。

**Unit B（组装/采样/prompt/reroll）**
- `assemble_plan` 人群过滤：有用户人群块的模板 → 只采该人群；无该块 → 不受影响；空池 → 回退 + warning。
- `AssemblyPlan.angle` 持久化往返（含旧 JSON 无字段 → None）。
- `render_brand_facts` 卖点优先：命中维度排首 + 【主打】，其余仍在。
- `build_prompt`：title 领衔 + angle_directive 入 prompt；**angle/title 空 → 旧 prompt 字节级快照不变**。
- factcheck 白名单含 title 数字（标题数字不被自伤）。
- `reroll_pick` 跟随：带人群 filter 的 plan 重随 → 仍在该人群池；旧 plan 退纯 filter。

**Unit C（前端）**
- AnglePicker：预设填充 facet（+ 切模板）；taxonomy 渲染；空选 = 不传 angle。
- query 往返：Hero → ArticleView 重建 Angle + title。
- `submit`/`lastRequest`/`rerun` 带 angle+title。

**真实库回归**：`铲屎官 + 防缠绕 + 口语` vs `老年人 + 机身重量 + 专业` → 选材/侧重/语调明显不同**且参数接地**；`angle=None && title=None` 端到端 == 今天。

---

## 10. 代码影响清单

| 层 | 新增 | 必改存量 |
|---|---|---|
| `csm_core/angle/`（新包） | `model.py`(Angle)、`taxonomy.py`、`filters.py`(effective_filters)、`directive.py`、`__init__.py`(effective_sellpoints) | — |
| `csm_core/assembler/` | — | `plan.py`(AssemblyPlan.angle)、`constraints.py`(assemble_plan 传 angle)、`sampler.py`(_sample_notes_source/_sample_source_for_block 用 effective_filters)、`reroll.py`(用 effective_filters + 接 angle) |
| `csm_core/brand_memory/` | — | `inject.py`(render_brand_facts 加 sellpoints 优先) |
| `csm_core/llm/` | — | `prompts.py`(PromptInputs + build_prompt 标题/指令/零回归分支) |
| `sidecar/.../services/` | — | `generate_service.py`(GenerateRequest + 解析 angle/directive/title + 注入 sellpoints + factcheck title 源)、`assembler_service.py`(cache_plan 带 angle、reroll 取 angle) |
| `sidecar/.../routes/` | `angle.py`(GET /api/angle/taxonomy) | `generate.py`(GenerateBody += title/angle)、`assembler.py`(reroll 读缓存 angle) |
| `frontend/src/` | `components/.../AnglePicker.vue`、`stores`/类型 Angle 镜像 | `stores/article.ts`(GenerateRequest+submit+lastRequest)、`components/home/CreateArticleHero.vue`、`views/ArticleView.vue` |

---

## 11. 实现拆分（交 writing-plans）

- **Unit A — `csm_core/angle/` 词表与派生**（纯数据、测试密；含 §2.4 维度键校准）。
- **Unit B — 混合组装接线**：assemble_plan/sampler 人群过滤 + plan.angle 持久化 + 注入卖点优先 + prompts（标题/指令/零回归）+ generate_service 接线（含 factcheck title 源）+ reroll 跟随 + cache_plan + 路由（GenerateBody、GET /api/angle/taxonomy）。**B 体量大，writing-plans 可再拆 B1(csm_core 组装) + B2(sidecar 接线)。**
- **Unit C — 前端 angle picker**：Angle 类型 + GenerateRequest + submit/lastRequest + AnglePicker + CreateArticleHero chip/popover + query 串接 + ArticleView 角度 chip + 标题领衔 UI。

每 Unit 子代理驱动 + 逐单元 opus 审查 + 最终整体审查（同 Phase 1）。

---

## 12. 留给后续轮（明确不做）

- skill 链多-pass（人设→去AI味→平台适配 + role:platform + 成本/逐pass UI）。
- 禁区 lint（emoji/破折号/绝对化/引流话术 确定性扫描 + 一键清 + 可拦导出）。
- 激进版 LLM 契约（允许取舍删减 + 主推型号事实保留的完整性校验）。
- 角度感知标题、增量/缓存 vault 索引、多品类词表、反馈学习闭环。
