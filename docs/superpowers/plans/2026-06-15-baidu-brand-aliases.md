# 百度品牌别名匹配 Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development 或 inline。Steps `- [ ]`.

**Goal:** 百度排名监测的自家品牌判断支持多别名（`brand_aliases`），任一命中即自家。
**Architecture:** `match_brand(content, brands: list)` 已支持多词 OR（大小写不敏感、按序首个命中）；config 加 `brand_aliases` → 喂 `[brand, *aliases]`。前端表单/批量导入加别名输入，照 GEO 同款。
**Tech:** Python(csm_core), Vue3, pytest, vue-tsc。范围仅百度。

---

## Task 1: 后端 — baidu config `brand_aliases` 接入
**File:** `csm_core/monitor/platforms/baidu_keyword.py`
- [ ] `_run`（`:930` `brand = ...` 后）加：`aliases = [a.strip() for a in (cfg.get("brand_aliases") or []) if a and a.strip()]`
- [ ] `_check_block` 两处（`:1238` default / `:1243` news）`[brand]` → `[brand, *aliases]`
- [ ] metric（`:1275` `"target_brand": brand` 旁）加 `"brand_aliases": aliases`
- [ ] `D:/CSM/.venv/Scripts/python.exe -m py_compile csm_core/monitor/platforms/baidu_keyword.py` + commit

## Task 2: 前端任务表单 — AddTaskModal baidu 别名输入（照 GEO）
**File:** `frontend/src/components/monitor/AddTaskModal.vue`
GEO 模板：别名 UI（`:632-638`）+ config split（`:344-347` `/[，,]/`）+ hydration join（`:217` `"，"`）。
- [ ] 加 `const baiduAliasesText = ref("")`（geoAliasesText 旁，`~:84`）
- [ ] baidu `target_brand` 字段（`:537`）后插 `<FormField label="品牌别名" hint="逗号分隔；命中任一别名的结果也算自家（如：CEWEY，希喂）"><FormInput v-model="baiduAliasesText" placeholder="如：CEWEY，希喂" debounce="live" /></FormField>`
- [ ] baidu config assembly（`:387-394`）加 `brand_aliases: baiduAliasesText.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean),`
- [ ] baidu 编辑反填（hydration `~:212`）加 `baiduAliasesText.value = ((editingTask.config?.brand_aliases as string[]) ?? []).join("，");`
- [ ] `close()` reset（`:166`）加 `baiduAliasesText.value = "";`
- [ ] `cd frontend && npx vue-tsc -b` + commit

## Task 3: 批量导入 — BatchImportTaskModal + excel
**Files:** `frontend/src/components/monitor/BatchImportTaskModal.vue`, `csm_core/monitor/excel_import.py`
百度批量导入：品牌+别名是**批次级**（一个任务 = N 关键词 × 1 品牌组），别名输入在 modal（不在 excel 逐行）。
- [ ] BatchImportTaskModal：baidu 在 `targetBrand`（`:517` 批次级输入）旁加 `baiduAliasesText` ref + 别名输入框（照 Task 2）；baidu config（`:538-542`）加 `brand_aliases: baiduAliasesText.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean)`
- [ ] excel_import.py：`_HEADERS`（`:67-74`）加 `"brand_aliases": ["品牌别名", "别名"]`；baidu 分支（`:250-273`）若该列存在则 `config["brand_aliases"] = [a.strip() for a in str(val).split("|") if a.strip()]`（pipe 分隔，与 search_keywords 一致）
- [ ] `pytest tests/core/monitor/test_excel_import.py -v`（若有）+ vue-tsc + commit

## Task 4: L2 展示 — BaiduRankingPage brand_aliases
**File:** `frontend/src/components/monitor/history/BaiduRankingPage.vue`
- [ ] 目标品牌 KPI 卡（`:1451-1457`）后加：`<div v-if="previewTask.config?.brand_aliases?.length" class="mt-2 text-[11px]" :style="{ color: 'var(--ink-3)' }">别名：{{ previewTask.config.brand_aliases.join('、') }}</div>`（确认 previewTask 作用域；L2 详情若另有品牌展示处同样补）
- [ ] vue-tsc + commit

## Task 5: 验证 + PR
- [ ] `D:/CSM/.venv/Scripts/python.exe -m pytest tests/core/monitor/ -q`（baidu/excel 不回归）+ `cd frontend && npx vue-tsc -b` + `npx vitest run`（136）
- [ ] push + `gh pr create --base main`
- [ ] 真机 QA：百度任务设主品牌 + 别名（如 CEWEY / 希喂）→ 跑监控 → 只含别名「希喂」的文章也标「自家」；L2 显示别名

## Self-Review
- spec 覆盖：后端匹配=T1、表单=T2、批量导入=T3、L2 展示=T4 ✓
- `match_brand` 多词已有，核心改动=接 `aliases` 进 `brands`（T1 三处）。
- 别名 = 批次级（百度一任务一品牌组，所有关键词共享）。excel 用 pipe 分隔列（与 search_keywords 一致）。
- 风险小：纯增量字段（`brand_aliases` 缺省 = 空 list = 退化为单 brand 现状），向后兼容。
