# GEO 采集升级 Phase 3c + Phase 4 part2 实施计划

- 日期:2026-07-13
- 分支:`claude/geo-phase3c-sampling`(基于合并后 origin/main 82bae9b9,含 PR #164 + #167)
- 设计稿:`docs/superpowers/specs/2026-07-09-geo-collection-upgrade-design.md` §4.2(剩余调度节奏)+ §4.6(多采样)
- 范围:两块**互相独立**、可分别发布的收尾切片。用户 2026-07-13 明确要求继续做这两项(此前缓做,现放行)。

---

## Phase 3c — 启动抖动 + run-window 守卫(§4.2 剩余)

**根本需求**:定时任务「固定时刻 + 固定顺序 + 零阅读」= 周期性机器人指纹;睡眠/关机后开机会让错过的任务**瞬间全速补跑**(3 个有头 Chrome 一起冲)。

**落点**:通用 `csm_core/monitor/scheduler.py`(baidu/zhihu/comment/geo 共用的纯判定函数,每 tick 由 monitor_loop 调 `select_due`)。

**两个不变量(第一性)**:
1. **确定性种子**:抖动偏移必须是 `(task_id, 当日)` 的纯函数,**不能读 `now`**。否则每次 tick 重算不同偏移 → 到点判定 flicker(可能永不触发或乱触发)。种子 = `sha256("{task_id}:{date}:start_jitter")`(与 `_shuffled_keywords` 同款,免 `hash()` 被 PYTHONHASHSEED 随机化)。
2. **类型门控**:抖动默认值按 `task.type` 给(`geo_query`→20min,其余→0)。非 geo 任务偏移恒 0 → 调度**逐字节不变**,不回归其他 adapter。数据驱动的默认表 `_START_JITTER_DEFAULT_MIN`,不散落 `if`。

**设计细节**:
- `_jitter_offset_seconds(task_id, date, jitter_max_min, target)`:偏移 ∈ [0, max]。**forward-only**(只延后,是「启动延迟」)+ **clamp 同日**:`max_sec = min(jitter_max*60, 到当日午夜前的秒数-1)`,避免 23:5x 的 target 抖过午夜后当天永不触发(在 day N 算出的 day N+1 实例第二天不会被看见)。
- `_effective_target(now.date, target, task)` = `combine(date, target) + timedelta(seconds=offset)`。
- `_due_for_target` 用**抖动后**的 today_at 判 `now < today_at` 与 `last < today_at`。
- **run-window 守卫**:`geo_run_window_hours`(默认 **None=关**,opt-in)。设了且 `now - today_at(抖动后) > window` → 不 due(本周期跳过,等下一周期)。默认关的理由:静默跳过一次计划运行对用户是意外;睡眠唤醒的错误风暴 Phase 3b 已用中断分类处理,run-window 只剩「开机late资源峰」这个次要项,让用户按需开。
- 更新 `TestWeeklySchedule._wtask` 加 `geo_start_jitter_max: 0` 隔离(该组测的是通用周调度语义,不该被 geo 抖动缠上);`TestIsTaskDue`/`TestSelectDue` 用 zhihu_question 天然不受影响。

---

## Phase 4 part2 — 多采样 K + 投票 + 翻转复核(§4.6)

**根本需求**:单次采样有温度噪声,单日结论可能因一次抖动误翻转。多采样 + 投票抑制噪声;但**默认 K=1 = 现状零成本**,K>1 与翻转复核 opt-in。

**核心洞见**:多采样在 **cell 级**发生 —— 每个 (关键词,平台) 采 K 次投票产出**一个** GeoCell,runner「每关键词一 cell」契约天然保持。

**新模块 `csm_core/monitor/geo/sampling.py`(纯函数,可单测)**:
- `vote_cell(samples: list[GeoCell], prev_mentioned: bool|None) -> GeoCell`:
  - `len==1` → 原样返回(K=1 逐字节等价今天,零成本向后兼容)。
  - 只对 `status=="ok"` 的样本投票;全失败 → 返回首个失败样本(附 samples 摘要)。
  - **mention**:ok 样本多数;平局 → `prev_mentioned`(缺省 False)。
  - **rank**:命中(mentioned 且 rank>0)样本的 rank 中位 `int()`(匹配 `rank INTEGER`);无命中 → -1。
  - **sentiment**:ok 且 mentioned 样本的多数;平局/空 → `na`。
  - **信源/答案/recommended/summary**:取**首个 ok 样本**(§4.6 致命修复④:绝不并集,否则 geo_citations 行数×K 污染信源榜权重与卡片「引用 N」)。
  - voted mention=False → 强制 rank=-1、senti=na(一致性;仅 ≥2 样本的新路径,不动 K=1)。
- `majority_sentiment`、`samples_digest`(每样本 {status,mentioned,rank,sentiment,fail_reason} 进 raw["samples"])。
- `sampled_cell(sample_fn, *, k, flip_recheck, prev_mentioned, cancel_token) -> GeoCell`:跑 K 次 `sample_fn()`(每次前 `maybe_cancel`)→ `vote_cell`;若 `flip_recheck 且 prev 已知 且 voted.status==ok 且 voted.mentioned != prev` → 补采 1 次再投票(翻转复核=确认;补采后若平局→prev,即「翻转未确认则维持上轮」)。

**fetch() 接线**:
- 读 `geo_sample_count`(默认1,夹 1..5)、`geo_flip_recheck`(默认true)。
- 跑前从 `geo_storage.cells_for_latest_run(task.id)` 建 `prev_map{(plat,kw): bool}`,**只收上轮 status==ok 的 cell**(错误上轮无可信 mention 基线 → 不参与翻转)。
- API 车道 `_cell` 与 RPA `_rpa_batch` 均把单样本函数包进 `sampled_cell`,透传 k/flip/`prev_map.get((plat,kw))`;`_rpa_batch` 新增 k/flip_recheck/prev_map 参数。
- `agg["sample_count"] = k`(可观测,前端暂不消费)。
- **RPA K>1 无样本间 jitter**:默认 K=1 无影响;K>1 主要给 API 快平台(§4.6 note:同分钟样本高相关,RPA 建议留 K=1),样本间节奏留待 P2.6 真机。

---

## 测试与验收

- **单测**:scheduler 抖动确定性/跨天变/clamp 午夜/run-window 守卫;sampling vote 各分支(mention 多数/平局、rank 中位取整、sentiment 平局 na、信源只取首样本、K=1 不变、全失败)+ sampled_cell 翻转补采;fetch 适配器(K>1 投票落库、翻转、K=1 回归)。
- **回归**:geo 全量 + `test_scheduler.py` + sidecar geo,`PYTHONPATH=<worktree>;<worktree>/sidecar`。
- **对抗性审查**:2-3 独立 subagent 证伪(正确性/契约、并发时序取消、resume/风控/软封 + prev_map 时序)。

## 决策(第一性,附理由待用户否决)

- **run-window 默认关**(opt-in):静默跳过计划运行=意外;睡眠错误风暴已由 3b 治。
- **启动抖动 geo 默认 20min 开**:纯延后 + 确定性 per-day,对后台监控无感,反指纹刚需;`geo_start_jitter_max: 0` 可关。
- **K 默认 1、翻转复核默认开**:遵设计稿;K=1 零成本;翻转复核只在真翻转时多花 1 次,抑制误翻转性价比高。
