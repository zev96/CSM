# 百度品牌别名匹配设计

> 状态：设计已确认（2026-06-15）。范围仅百度。

## 背景与问题
百度排名监测判断「搜索结果是否自家文章」用单个 `config.target_brand` 匹配。但同一品牌有多种叫法（英文 `CEWEY` / 中文「希喂」），不同文章用词不一 → 单词匹配漏判自家文章。

## 方案（改动极小）
匹配引擎 `match_brand(content, brands: list[str])`（`baidu_keyword.py:118-137`）**已支持多词 OR**：遍历 `brands`、大小写不敏感、任一命中即返回，按列表顺序返回首个命中（主品牌排前 = 优先）。当前只喂 `[target_brand]`（`:1238/1243`）。改成喂 `[target_brand, *brand_aliases]`。

### 后端（`csm_core/monitor/platforms/baidu_keyword.py`）
- `_run` 读 `config.brand_aliases`（照 GEO `geo_query.py:53`）：
  `aliases = [a.strip() for a in (cfg.get("brand_aliases") or []) if a and a.strip()]`
- `_check_block` 的两处 `[brand]` → `[brand, *aliases]`（default + news 区块）
- metric 加记 `brand_aliases`（L2 详情可显「命中：希喂」）
- `match_brand` 不动（已支持多词）

### 前端 — 任务表单（百度新建/编辑）
`target_brand` 输入框旁加「品牌别名」输入，**照 GEO 的别名 UI**（保持一致）。写入 `config.brand_aliases`。

### 前端 — 批量导入（百度 Excel）
加一列「品牌别名」（可选），解析进 `config.brand_aliases`（与表单同字段）。

## 范围
仅百度（知乎搜索/知乎问题、GEO 不动；GEO 本就有别名）。

## 测试
- 后端：`match_brand` 多词匹配已有测试；新增「config.brand_aliases → brands = [brand, *aliases]」构造的单元测（若可抽纯函数）。
- 真机：百度任务设主品牌 + 别名 → 跑监控 → 只含别名（希喂）的文章也命中自家。

## 关键实现点（writing-plans 细化）
1. 前端百度任务表单位置（`AddTaskModal` 的 baidu 分支）+ GEO 别名 UI 实现（照搬）。
2. 百度 Excel 导入解析（`csm_core/monitor/excel_import.py` baidu 分支 + `BatchImportTaskModal` 的 baidu 列定义）。
3. metric `brand_aliases` 在百度 L2 详情的展示（`BaiduRankingPage`）。
