# 历史文章查重与素材引用率检测

**Date:** 2026-05-07
**Status:** Approved, awaiting implementation plan

## 背景与动机

CSM 的 workflow 是"基于 Obsidian vault 素材组装草稿 + LLM 润色"。两个关键风险：

1. **撞稿**：润色后的成文与历史成品文章字面重复度高（同事用过的题材自己又写了一遍）
2. **AI 搬运未消化**：LLM 润色不彻底，成文中大段保留 vault 原文（创造性低）

希望在创作区右侧属性栏，**润色按钮下方**，实时呈现两个独立指标：

- **历史重复率**：当前文章 vs 用户指定的"历史文章库目录"
- **素材引用率**：润色后的成文 vs Obsidian vault 笔记

每个指标支持点击下钻，看 top 3 相似来源 + 具体重复段落高亮。

## 范围

| 项 | 在范围内 |
|---|---|
| 字面级重复检测（shingling）| ✅ |
| MinHash + LSH 候选检索 | ✅ |
| Top-K 候选精算 + 段落级命中位置 | ✅ |
| 索引懒加载 + 持久化 | ✅ |
| 索引增量更新（mtime 感知）| ✅ |
| Embedding / 语义相似度 | ❌（V2 增强） |
| AI 风味检测（perplexity / 分类器）| ❌（独立功能 4） |
| 多用户共享语料库 | ❌ |

## 数据规模

| 语料库 | 当前 | 上限预期 |
|---|---|---|
| 历史文章库 | 0–1000 篇 | 50,000 篇 |
| Obsidian vault 笔记 | ~1,000 篇 | 1,000–5,000 篇 |

## 算法选型

### 为什么是 MinHash + LSH + 精算下钻

- **纯 shingling 倒排索引**：5 万篇 × 1500 字 ≈ 750 万 shingle，纯 Python dict 占 1–2 GB 内存，**到上限会爆**
- **纯 MinHash**：返回 Jaccard 估计，**无法定位重复段落**，UI 下钻能力丧失
- **混合方案**：MinHash + LSH 做 O(1) 候选检索，对返回的 top K 候选再做精确 shingle 倒排比对，**兼得规模和诊断性**

### 算法参数

| 参数 | 值 | 说明 |
|---|---|---|
| Shingle 长度（中文字符级）| 13 | 行业默认论文查重粒度 |
| MinHash 签名维度 | 128 | datasketch 默认，速度/准度平衡 |
| LSH Jaccard 阈值 | 0.3 | 宽松候选筛选，宁可多召回不漏 |
| Top-K 候选 | 10 | 进入精算的候选篇数 |
| 重复字数命中阈值 | shingle 重叠 ≥ 60% 字符即算"命中" |
| 最短可分析文本长度 | 50 字 | 短于此显示 "—" |

### "重复率"数字含义

```
重复率 = 命中 shingle 覆盖的字符数 / 当前文章总字符数
```

直观语义：**当前文章中有 X% 的内容能在语料库找到相同/近似原句**。

## 数据流

```
首次启用 / 用户改语料目录
   │
   ▼
[Settings 页 "重建索引"] ──▶ DedupWorker.rebuild_index(corpus_kind)
   │                          扫描目录 → 读取 .md/.docx/.txt
   │                          每篇 → shingles → MinHash 签名 → 插入 LSH
   │                          进度回调 → ProgressDialog
   │
   ▼
索引序列化到 <config_dir>/dedup_index/<kind>.lsh + .meta.json

正常使用：
[润色完成] / [草稿生成完成] ──▶ DedupAnalyzer.analyze(text, kind)
                                  在后台 QThread：
                                  1. 当前文本 → MinHash
                                  2. LSH 查询 top K 候选
                                  3. 候选精算 → DuplicateReport
   │
   ▼
DedupPanel 渲染 (重复率 % + 进度条 + 颜色)

[用户点击指标] ──▶ DedupDrillDialog 弹窗
                    显示 top 3 相似来源 + 段落高亮
```

## 架构

### 文件清单

```
新增：
  csm_core/dedup/
  ├── __init__.py
  ├── shingles.py          # 中文 13-字符 shingling
  ├── corpus.py            # 目录扫描 + .md/.docx/.txt 文本提取 + mtime 增量
  ├── index.py             # MinHashLSH 索引封装（datasketch）
  ├── analyzer.py          # 编排 shingle → MinHash → LSH → 精算
  └── report.py            # DuplicateReport / SegmentHit dataclass

  csm_gui/workers/
  └── dedup_worker.py      # QThread 后台分析 / 索引构建

  csm_gui/widgets/
  ├── dedup_panel.py            # 右侧双指标面板
  └── dedup_drill_dialog.py     # 命中段落下钻

修改：
  csm_gui/pages/article_page.py # 在右侧加入 DedupPanel
  csm_gui/pages/settings_page.py # 新增"历史查重"配置区
  csm_gui/main_window.py        # 串信号：polished/generated → DedupAnalyzer
  csm_gui/config.py             # AppConfig 新增 dedup_* 字段
  pyproject.toml                # 添加 datasketch 依赖
```

### 关键数据结构

```python
# csm_core/dedup/report.py
@dataclass
class SegmentHit:
    start: int            # 当前文章中的字符起始位置
    end: int              # 字符结束位置
    text: str             # 命中片段
    source_path: str      # 命中来源文件
    source_title: str     # 来源文件标题（首个 H1 或 stem）
    source_excerpt: str   # 来源中对应片段（前后扩展 50 字上下文）

@dataclass
class TopMatch:
    source_path: str
    source_title: str
    overlap_chars: int    # 该来源贡献的命中字数
    overlap_ratio: float  # 该来源的命中字数 / 当前文章总字数

@dataclass
class DuplicateReport:
    corpus_kind: str              # "history" | "vault"
    text_length: int              # 当前文章总字符数
    duplicate_chars: int          # 命中 shingle 覆盖的字符数
    duplicate_ratio: float        # duplicate_chars / text_length，0..1
    top_matches: list[TopMatch]   # 至多 3 条
    hits: list[SegmentHit]        # 所有命中段落
    computed_at: datetime
```

### 索引存储

```
<config_dir>/dedup_index/
├── history.lsh           # pickle.dump(MinHashLSH)
├── history.meta.json     # {"files": {<path>: {"mtime": ..., "doc_id": "..."}}, "version": 1}
├── vault.lsh
└── vault.meta.json
```

`.lsh` 文件用 `datasketch.MinHashLSH` 自带的 pickle 序列化。`.meta.json` 维护 path→mtime 映射用于增量。

### 增量更新算法

```
扫描目录得到 current_files: {path: mtime}
对比 meta.files：
  - 新增（path 不在 meta）→ 计算签名插入 LSH
  - mtime 变化 → 删除旧签名，重新插入
  - 已删除（meta 有 current 没有）→ 从 LSH 删除签名
保存新 meta.json + LSH
```

## UI 设计

### 创作区右侧 DedupPanel（润色按钮下方）

```
┌──────────────────────────────────────┐
│ 润色风格 [极客风 ▼]                  │
│ [润色]  [导出]                       │
├──────────────────────────────────────┤
│ 📊 内容查重           ⟳ 重新计算     │
│                                      │
│ 历史重复率   12% ▓▓░░░░░░  ⓘ 详情   │
│ 素材引用率   38% ▓▓▓▓░░░░  ⓘ 详情   │
│                                      │
│ ─ 阈值（可在设置页调整）─            │
│ 绿 < 15%  /  黄 15–30%  /  红 > 30%  │
└──────────────────────────────────────┘
```

行为：

- 默认显示 `—`（未触发计算 / 文本过短 / 索引未启用）
- 数字颜色按阈值渲染
- ⟳ 手动触发当前文本重算
- ⓘ 详情 → 弹 DedupDrillDialog

### DedupDrillDialog（下钻）

```
┌── 历史重复率详情 ──────────────────────────────┐
│                                                │
│ 当前文章共 3,200 字，384 字（12%）在历史中找到│
│                                                │
│ Top 3 相似文章：                               │
│ 1. 《XXX 攻略》 — 156 字重叠（4.9%）  [打开]  │
│ 2. 《YYY 评测》 —  98 字重叠（3.1%）  [打开]  │
│ 3. 《ZZZ 教程》 —  74 字重叠（2.3%）  [打开]  │
│                                                │
│ ─ 命中段落（按位置排序）─                     │
│ ▶ 第 245–298 字   "..."                        │
│   来自《XXX 攻略》 | 上下文："...XXXXXX..."    │
│ ▶ 第 432–478 字   "..."                        │
│   来自《YYY 评测》 | 上下文："...YYYYYY..."    │
│                                                │
│                                  [关闭]        │
└────────────────────────────────────────────────┘
```

### 设置页"历史查重"区

```
[历史查重]
  ☐ 启用历史查重（默认关闭）
  
  历史文章库目录  [______________________]  [选择…]
  当前索引：—  最后构建：—
  [重建历史索引]
  
  Vault 索引（自动跟随 Vault 路径）
  当前索引：—  最后构建：—
  [重建 Vault 索引]
  
  阈值配置
  绿色 < [15] %     黄色 < [30] %     红色 ≥ 30%
  
  ⓘ 启用后第一次构建索引可能需要数分钟，期间可继续使用 CSM
```

## 数据模型变更

```python
# csm_gui/config.py
@dataclass
class AppConfig:
    ...
    dedup_enabled: bool = False
    dedup_history_dir: str = ""               # 历史文章库目录
    dedup_threshold_green: int = 15           # %
    dedup_threshold_yellow: int = 30          # %
    dedup_history_last_built: str = ""        # ISO timestamp
    dedup_vault_last_built: str = ""
```

## 性能预期

| 语料规模 | LSH 索引文件 | 索引内存 | 单次分析耗时 | 首次构建 |
|---|---|---|---|---|
| 1,000 篇 | ~1 MB | ~5 MB | <50 ms | 5–15 秒 |
| 10,000 篇 | ~10 MB | ~50 MB | <100 ms | 1–3 分钟 |
| 50,000 篇 | ~100 MB | ~500 MB | <300 ms | 5–15 分钟 |

加上 CSM 主程序基础内存约 250 MB，**总工作集 5 万篇规模约 500 MB**，对 8 GB+ 现代电脑无压力。**懒加载**（只在 dedup_enabled=true 且打开创作区时才把索引读入内存）保证未启用功能时零额外开销。

## 错误处理

| 场景 | 行为 |
|---|---|
| 索引文件损坏（pickle 失败）| 删除 `.lsh` + InfoBar 提示用户重建 |
| 历史目录不存在 / 失效 | 历史重复率行变灰 + "目录失效，去设置修改" |
| Vault 目录失效 | 同上 |
| 当前文本 < 50 字 | 跳过分析，显示 "—" + tooltip "文本太短无法分析" |
| 分析耗时 > 5 秒 | 不阻断，但记 warning 日志（用于诊断超出预期规模）|
| 索引构建中关闭 App | `.lsh` 写到 `.lsh.tmp`；下次启动检测到孤立 tmp → 提示"上次未完成，是否继续重建" |
| .docx 解压失败 / 编码问题 | 跳过该文件 + 写入 `<config_dir>/dedup_skipped.log` |
| datasketch 未安装（依赖缺失）| 启动时 import 失败 → 整个查重模块禁用 + 设置页提示"功能不可用" |

## 测试策略

### 单元测试（pytest）

- `shingles.py`
  - 相同文本 shingle 集合幂等
  - 空 / 超短文本边界（< 13 字符返回空集）
  - Unicode 中文处理正确
- `corpus.py`
  - 扫描目录正确递归 .md / .docx / .txt
  - mtime 变化触发增量识别
  - 二进制文件 / 编码异常被跳过
- `index.py`
  - 插入 / 查询 / 删除 LSH 行为
  - 序列化 + 反序列化往返一致
- `analyzer.py`
  - 构造 80% 重叠的两段文本，重复率落在 75–85% 区间
  - 完全无关文本，重复率 < 5%
  - top_matches 排序正确
  - hits.start/end 索引位置精确

### 集成测试

- 50 篇 fixture 语料 + 1 篇有意撞稿的文章 → 完整链路输出 DuplicateReport
- 增量：扫描后修改 1 个文件 mtime + 重跑 → 仅该文件被重新签名

### GUI 测试（pytest-qt）

- DedupPanel 接收 DuplicateReport 信号 → 数字、颜色、进度条正确
- DedupDrillDialog 渲染 top 3 + segments 列表
- 设置页"重建索引"按钮触发 worker，进度对话框正确显示

## 集成点

### 触发计算的两个时机

```python
# main_window.py
def _on_polished(self, text: str) -> None:
    ...
    # 既有逻辑
    if self.config.dedup_enabled:
        self.dedup_analyzer.analyze_async(text, kind="vault")  # 素材引用率
        self.dedup_analyzer.analyze_async(text, kind="history")  # 历史重复率

def _on_generated(self, result) -> None:
    ...
    if self.config.dedup_enabled:
        # 草稿阶段只算"历史重复率"，"素材引用率"留到润色后再算
        # 因为草稿天然包含 vault 原文，引用率 100% 无意义
        draft = compose_draft(result.plan)
        self.dedup_analyzer.analyze_async(draft, kind="history")
```

### 用户手动 ⟳ 触发

`DedupPanel` 暴露 `recalculate_requested(kind: str)` signal，主窗 connect 到 analyzer。

## Out of Scope

- Embedding / 语义相似度（V2 增强，等用户用过 V1 反馈再上）
- "AI 风味度"检测（独立功能 4）
- 段落级 block 粒度命中（V1 只做整篇 + 文本片段下钻）
- 数据库式存储（用文件级 pickle 即可）
- 多用户 / 团队共享语料库
- 跨语言（仅中文优化）
- 实时键入更新（按 polished/generated 事件触发足够）

## 实施顺序建议

1. `csm_core/dedup/` 核心算法（shingles → corpus → index → analyzer）+ 单测
2. `pyproject.toml` 加 datasketch 依赖
3. `dedup_worker.py` 后台 QThread
4. `AppConfig` 字段 + 设置页 UI（不接信号先看 UI）
5. `DedupPanel` widget + 集成到 ArticlePage 右侧
6. MainWindow 接 polished / generated 信号
7. `DedupDrillDialog` 下钻
8. PyInstaller 冒烟（核心：datasketch 在 onedir 能正常加载）
