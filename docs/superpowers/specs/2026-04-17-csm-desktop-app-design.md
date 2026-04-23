# CSM · Content SEO Maker — 设计文档

**日期**: 2026-04-17
**作者**: 与 Claude 协作 brainstorming 产出
**状态**: 待实现

---

## 1. 项目目标

开发一款本地 PyQt6 桌面应用，基于 Obsidian Vault (`D:\OSM`) 的原子化营销素材库，快速产出 SEO 文章。核心能力：

- 关键词 + 模板驱动，从 Vault 自动抽取素材并按规则随机组合
- AI 洗稿（润色模式，保留信息）
- 支持**单篇精修**（可视化逐槽重掷/手改）与**批量生成**（多关键词共用模板）两种模式
- 多 LLM provider 可切换（Claude / OpenAI / DeepSeek 等）

工作目录：`D:\CSM`（项目代码与产物）；Vault 只读引用 `D:\OSM\营销资料库`。

---

## 2. 核心工作流

```
关键词 + 模板选择
  → VaultIndex（笔记池 / 品牌字典 / 变体缓存）
  → Assembler（按模板 DSL 规则采样 → AssemblyPlan）
  → [单篇模式：UI 展示，允许逐槽重掷/手改]
  → Renderer（AssemblyPlan → 毛坯 Markdown）
  → LLMClient（三层 prompt 叠加：模板默认 + 用户 skill + SEO 约束）
  → Exporter（.md + 同名 .assembly.json 存档）
```

---

## 3. 关键设计决策

| 项目 | 决策 | 理由 |
|------|------|------|
| 架构 | 核心引擎 + PyQt6 壳分层（`csm_core/` + `csm_gui/`） | 核心逻辑可独立 TDD；批量跑在 QThread；未来可加 CLI/Web 壳 |
| 素材粒度 | 一笔记多变体（①②③），保持 Vault 现状 | 与 CLAUDE.md §6.2 规范一致；采样算法为"选 N 笔记 → 每笔记抽 1 变体"两级 |
| 模板存储 | JSON 存应用侧 `templates/`，GUI 可视化编辑 | 跨槽位依赖用 JSON 表达力强；纯素材和逻辑规则职责分离 |
| 框架 md 处理 | 首次启动一次性把 `框架模块/*.md` 转成 JSON 模板作起点，之后 JSON 为权威 | md 是人类文案说明，不是机器执行规则 |
| 板块格式渲染 | **v1 固定一种渲染；v1.5 加可切换板块格式** | 先跑通主流程，渲染器插件化是增量增强 |
| 品牌识别 | 目录路径 + 文件名前缀（如 `戴森V15-产品参数.md`）作天然主键；frontmatter `品牌` 字段作校验 | 扫产品参数目录即可生成品牌-型号字典，无需改 Vault |
| 跨槽位依赖 | 对比文测试槽位 `depends_on` 品牌槽位，按型号名匹配 `品牌产品测试结果/{型号}-测试结果.md` | 两个目录文件名一一对应，天然可对齐 |
| LLM | 多 provider 可切换；统一 `LLMClient` 接口 | 批量成本和可用性考虑 |
| 洗稿 prompt | 三层叠加：模板默认 `system_prompt` + 用户选的 `prompts/*.md` skill + SEO 约束 | 模板定风格骨架、用户 skill 微调、SEO 结构化控制 |
| SEO 约束 | 字数范围、关键词密度、长尾关键词、H2/H3 强制、口吻风格 | 用户要求全量支持 |
| 洗稿模式 | 润色（保留信息、改文字），不做深度重写 | 素材完整性优先 |
| 输出 | 导出到用户指定目录，`.md`（v1）/ `.docx`（v1.5），旁边附 `.assembly.json` | 不写回 Vault，保持 Vault 纯净 |
| 可复现 | 每篇产物带 `.assembly.json`（装配计划 + 引用笔记清单 + prompt 快照） | 可复盘"这篇是怎么来的"，也便于批量复现风格 |

---

## 4. 模块划分

```
D:\CSM\
├─ csm_core/                    # 纯 Python，零 Qt 依赖
│  ├─ vault/
│  │  ├─ scanner.py             # 扫描 Vault → 笔记元数据池
│  │  ├─ note_parser.py         # frontmatter + ①②③ 变体拆段
│  │  └─ brand_registry.py      # 品牌-型号字典（扫 产品参数/ 文件名）
│  ├─ template/
│  │  ├─ schema.py              # Pydantic 模型 + 校验（跨槽位闭环、品牌存在性）
│  │  ├─ loader.py              # 加载/保存 templates/*.json
│  │  └─ importer.py            # 一次性：框架模块 md → JSON 模板
│  ├─ assembler/
│  │  ├─ sampler.py             # 两级采样：选笔记 → 抽变体
│  │  ├─ constraints.py         # 跨槽位依赖按拓扑序求解
│  │  └─ plan.py                # AssemblyPlan 数据结构
│  ├─ llm/
│  │  ├─ client.py              # 统一 LLMClient 接口
│  │  ├─ providers/             # anthropic.py / openai.py / deepseek.py ...
│  │  └─ prompts.py             # 三层 prompt 组合
│  ├─ export/
│  │  └─ markdown.py            # v1：.md；v1.5：.docx
│  └─ pipeline.py               # 编排：keyword + template → Article
│
├─ csm_gui/                     # PyQt6 + qfluentwidgets 壳
│  ├─ app.py                    # QApplication 入口；setTheme + setThemeColor
│  ├─ main_window.py            # MainWindow(FluentWindow)，左侧 NavigationInterface
│  ├─ views/
│  │  ├─ single_refine.py       # 单篇精修视图
│  │  ├─ batch_generate.py      # 批量生成视图
│  │  ├─ template_manager.py    # 模板管理视图（新建/编辑/删除/复制）
│  │  └─ setting.py             # 设置视图（SettingCardGroup）
│  ├─ workers/                  # QThread 封装：assemble / llm
│  ├─ widgets/                  # 槽位 CardWidget、素材选择 MessageBoxBase 等
│  └─ theme.py                  # 主色常量、FluentIcon 映射表（集中管理）
│
├─ templates/                   # JSON 模板库（GUI 管理，人类可备份/Git）
├─ prompts/                     # 用户自定义洗稿 skill（.md）
├─ config/settings.json         # API keys / provider / Vault 路径 / 导出目录
├─ tests/
│  ├─ core/                     # 每个 core 子模块对应单元测试
│  └─ fixtures/mini_vault/      # 小而全的 Vault 样本，Git 管理
└─ pyproject.toml
```

**硬性约束**：`csm_core` 禁止 import 任何 Qt 模块。GUI 层只做信号↔core 调用翻译。

---

## 5. 模板 JSON DSL

### 5.1 总体结构

```json
{
  "id": "daogou-changjing-renqun",
  "name": "导购文-场景人群型",
  "product": "吸尘器",
  "version": 1,
  "system_prompt_default": "你是资深家电导购编辑...",
  "seo_defaults": {
    "target_word_count": [1500, 2000],
    "keyword_density": [5, 8],
    "long_tail_keywords": [],
    "tone": "小红书笔记体",
    "force_h2": true
  },
  "slots": [ /* 见 5.2 */ ],
  "render_order": ["intro", "keypoints", "brand_self", "brand_competitors"]
}
```

### 5.2 槽位字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` / `label` | str | 槽位标识 / UI 显示名 |
| `source.type` | enum | 四种：`notes_query` / `brand_fixed` / `brand_pool` / `test_results_aligned` |
| `source.module` | str | 相对 Vault 路径，如 `引言模块` |
| `source.filter` | dict | frontmatter 条件匹配，如 `{"组件类型":"痛点共鸣"}` |
| `pick_notes` | int \| `{random_between:[n,m]}` \| `{user_configurable:true,default,range}` | 采样笔记数 |
| `pick_variants_per_note` | int | 通常 1（笔记内抽一段 ①/②/③） |
| `constraints` | list[str] | 如 `unique_notes` |
| `depends_on` | list[str] | 跨槽位依赖的槽位 id |

### 5.3 跨槽位依赖示例（对比文测试对齐）

```json
{
  "id": "test_results",
  "source": {
    "type": "test_results_aligned",
    "follow_slot": "brand_competitors+brand_self",
    "module": "测试项目模块/品牌产品测试结果"
  },
  "depends_on": ["brand_self", "brand_competitors"]
}
```

Assembler 按拓扑序采样：先解前置槽位 → 收集品牌+型号 → 去测试目录拉对应笔记。

### 5.4 Schema 校验规则（保存时触发）

- 跨槽位依赖必须无环
- `brand_fixed` 的型号必须存在于 `brand_registry`
- `render_order` 必须是 `slots[].id` 的一个全排列
- `test_results_aligned` 的 `depends_on` 必须包含对应品牌槽位

---

## 6. 数据流（详细）

### 6.1 VaultIndex 构建（启动一次）

- 扫 `D:\OSM\营销资料库` 下所有 `.md`
- 解析 frontmatter（产品 / 素材类型 / 核心关键词 / 组件类型 / 品牌 / 人群分类）
- 拆变体（识别以 `①`/`②`/`③` 起始的段落），失败则整篇作为单变体并标警告
- 扫 `产品参数/` 建品牌字典：`{"戴森":["V8","V10","V12","V15"], "CEWEY":["CEWEYDS18"], ...}`
- 结果缓存到内存 + `config/vault_index.cache.json`，下次启动差异更新

### 6.2 Assembler 采样

1. 解析模板槽位，构建依赖 DAG
2. 按拓扑序处理每个槽位：
   - 拉候选池（按 source 规则）
   - 池为空 → 抛 `EmptyPoolError`，UI 提示用户修改模板/补充素材
   - 按 `pick_notes` 随机采样（支持 seed 复现）
   - 每笔记内抽 `pick_variants_per_note` 段变体
   - 检查 `constraints`（如 unique_notes）
3. 产出 `AssemblyPlan`（可序列化 JSON）

### 6.3 Renderer（v1）

- 按 `render_order` 拼接各槽位选中变体的纯文本
- 在槽位间插入 `\n\n` 分隔
- v1 不做板块格式变换；v1.5 接入 `csm_core/render/` 可插拔渲染器

### 6.4 LLMClient 调用

Prompt 组合：

```
system = [模板.system_prompt_default]
       + (可选) 用户当次选择的 prompts/*.md 内容
       + SEO 约束格式化文本（字数、密度、H2、口吻等）

user   = 毛坯文 + 关键词 + "请按润色模式重写：保留所有信息和结构，只改进文字流畅度和风格一致性"
```

统一接口：

```python
class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, stream: bool=False) -> Iterator[str] | str: ...
```

每 provider 实现自己的 `providers/*.py`，配置在 `settings.json`。

### 6.5 Exporter

- 导出到用户指定目录：
  - `{关键词}.md` — 成品正文
  - `{关键词}.assembly.json` — 装配计划快照（plan + prompt 层 + provider + model + seed + timestamp）

---

## 7. UI 概要

### Tab 1 单篇精修
- 顶部：关键词输入 / 模板下拉 / provider + skill 下拉 / "装配" 按钮
- 装配结果区：每个槽位一张卡片，显示选中笔记与变体文本，带 🎲（单槽重掷）/ ✎（手改弹窗选候选）/ ✗（从槽位移除）按钮
- `user_configurable` 字段渲染为滑块（如竞品数量 2-9）
- 底部：预览毛坯 / AI 洗稿（流式输出）/ 导出

### Tab 2 批量生成
- 左：多行关键词输入 / 导入 txt/csv
- 右：模板 / provider / skill / 导出目录 / 并发数 / 开始按钮
- 下：进度列表（每行状态 + 字数 + 查看 + 重跑按钮）
- 失败项隔离，不影响队列其他任务

### Tab 3 模板管理
- 左：模板列表（新建/复制/删除，删除走 `templates/.trash/` 软删除）
- 右：模板编辑区 — 基本信息 / SEO 默认 / 槽位列表（拖拽排序，每槽位 ⚙ 弹窗覆盖 §5 所有字段）
- 保存前触发 Schema 校验，失败弹错

---

## 8. 错误处理

| 失败场景 | 策略 |
|---------|------|
| 笔记 frontmatter 缺字段/格式错 | 收集到"Vault 健康报告"面板，不阻断扫描 |
| 变体解析失败 | 降级：整篇作单变体 + 警告 |
| 槽位候选池为空 | 停止装配，弹窗跳转模板编辑器 |
| 跨槽位约束无解（某品牌无测试笔记） | 允许继续，占位"缺数据"；记录进 assembly.json |
| LLM API 失败 | 指数退避重试 3 次；最终失败保留毛坯文，允许换 provider 重试 |
| 批量模式单篇失败 | 隔离失败，不影响队列；标红 + 显示原因 + 重跑按钮 |
| 导出目录不可写 | 保存前校验；不丢内容 |
| settings.json 损坏 | 回退默认值 + 原文件备份 `.bak` |

---

## 9. 测试策略

**TDD 驱动 `csm_core`，目标覆盖率 80%+**

- `tests/core/`：按子模块组织（vault / template / assembler / llm / export）
- `tests/fixtures/mini_vault/`：小而全的 Vault 样本（每模块 2-3 笔记），Git 管理
- LLM 调用在单元测试里全部 mock；保留少量 `@pytest.mark.integration` 真实调用
- GUI 用 `pytest-qt` 测关键交互（按钮→信号→core 接口）
- 端到端 `docs/e2e-checklist.md` 人工清单，每次 release 走一遍

---

## 10. 版本范围

### v1（MVP，本次实现）
- 单篇精修 + 批量生成两模式
- 模板增删改查（GUI）
- VaultIndex、Assembler（含跨槽位依赖）、LLMClient（至少 Claude + 一个国内 provider）
- Renderer 固定一种（直接嵌入变体文本）
- 导出 .md + .assembly.json
- 框架模块 md → JSON 模板一次性导入工具

### v1.5（增量）
- 板块格式可切换渲染器
- 导出 .docx
- 产品参数笔记 frontmatter 结构化规范化（配合板块格式）

### v2+（未规划）
- 其他产品线（宠物空气净化器/食物料理机/空气净化器）
- 风格学习（从已有爆款文 fine-tune prompt）
- 定时批量（CLI + cron）

---

## 11. UI/UX 视觉规范（Win11 Fluent，基于 PyQt-Fluent-Widgets）

### 11.1 UI 库选型（强制）

**全部 GUI 组件必须使用 [PyQt-Fluent-Widgets (qfluentwidgets)](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)**，禁止手写 `QPushButton` 等原生控件或自绘 QSS。

- 依赖：`PyQt-Fluent-Widgets[full]>=1.7`（pyproject.toml 固定）
- 理由：官方实现了完整的 Win11 Fluent 控件族（按钮、输入、导航、对话框、滚动、进度、消息条），视觉一致性由库保证；自绘 QSS 会出现细节不一致（圆角、阴影、动画）
- **一致性硬性要求**：任何按钮必须是 `PrimaryPushButton`/`PushButton`/`TransparentPushButton`；任何输入框必须是 `LineEdit`/`TextEdit`/`SearchLineEdit`；弹窗必须是 `MessageBox`/`Dialog`；列表必须是 `ListWidget`/`TableWidget` 的 Fluent 版。code review 时发现裸 Qt 控件视为缺陷。

### 11.2 主题配置（应用启动时一次）

```python
from qfluentwidgets import setTheme, Theme, setThemeColor

setTheme(Theme.LIGHT)          # v1 固定浅色；v1.5 加 Theme.AUTO
setThemeColor('#0067C0')       # Win11 系统默认蓝
```

- 主色 `#0067C0`、悬停/按压态由库自动派生
- 深色模式：v1 不做，v1.5 开启 `Theme.AUTO` 跟随系统
- 字体：库默认用 Segoe UI Variable / 微软雅黑 UI，无需手配

### 11.3 关键组件映射

| 交互需求 | qfluentwidgets 组件 |
|---------|---------------------|
| 主窗架构（左侧导航 + 内容区） | `FluentWindow` + `NavigationInterface`（或顶部 `Pivot`） |
| 主按钮（装配、AI 洗稿、开始批量） | `PrimaryPushButton` |
| 次要按钮 | `PushButton` |
| 图标按钮（重掷、删除） | `TransparentToolButton` + `FluentIcon` |
| 关键词输入 | `LineEdit` / `SearchLineEdit` |
| 多行关键词（批量） | `TextEdit` 或 `PlainTextEdit` |
| 模板/provider 下拉 | `ComboBox` / `EditableComboBox` |
| 竞品数量滑块 | `Slider` + `SpinBox` 组合 |
| 批量进度行 | `ListWidget` + 自绘行内元素 / `ProgressBar` + `IndeterminateProgressBar` |
| 装配结果槽位卡片 | `CardWidget` 或 `ElevatedCardWidget`（内置 Fluent 阴影） |
| 模板管理列表 | `ListWidget`（带多级选中）+ `SegmentedWidget`（分类过滤） |
| 槽位参数弹窗 | `MessageBoxBase`（带标题+内容+底栏按钮） |
| 洗稿流式预览 | `PlainTextEdit`（只读）+ 顶部 `InfoBar` 状态提示 |
| Vault 健康报告 | `InfoBar.warning(...)` + `ListWidget` |
| 错误提示 | `InfoBar.error(...)` 而非系统弹窗 |
| 文件路径选择 | 内置 `FolderListSettingCard` / 或 `QFileDialog` + `LineEdit` 回显 |
| 应用设置 | `ScrollArea` + `SettingCardGroup`（API keys、Vault 路径、导出目录） |

### 11.4 图标规范

- **图标全部来自 `qfluentwidgets.FluentIcon` 枚举**（库内置 Fluent UI System Icons）
- 禁止 emoji

| 动作 | FluentIcon 枚举 |
|------|----------------|
| 重掷 | `FluentIcon.SYNC` |
| 手改 | `FluentIcon.EDIT` |
| 删除/移除 | `FluentIcon.DELETE` / `FluentIcon.CLOSE` |
| 保存 | `FluentIcon.SAVE` |
| 导出 | `FluentIcon.SHARE` / `FluentIcon.FOLDER_ADD` |
| 打开文件夹 | `FluentIcon.FOLDER` |
| 添加 | `FluentIcon.ADD` |
| 校验/警告 | `FluentIcon.INFO` / 警告用 InfoBar |
| 收藏/默认 | `FluentIcon.HEART` |
| 重新索引 | `FluentIcon.UPDATE` |
| 设置 | `FluentIcon.SETTING` |
| 单篇模式 tab | `FluentIcon.EDIT` |
| 批量模式 tab | `FluentIcon.LIBRARY` |
| 模板管理 tab | `FluentIcon.DOCUMENT` |

### 11.5 主窗结构

采用 `FluentWindow` + 左侧 `NavigationInterface`（Win11 Settings App 风格），三个导航项对应三个子界面：

```python
class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.singleRefineView = SingleRefineView(self)
        self.batchGenerateView = BatchGenerateView(self)
        self.templateManagerView = TemplateManagerView(self)
        self.settingView = SettingView(self)

        self.addSubInterface(self.singleRefineView, FluentIcon.EDIT, '单篇精修')
        self.addSubInterface(self.batchGenerateView, FluentIcon.LIBRARY, '批量生成')
        self.addSubInterface(self.templateManagerView, FluentIcon.DOCUMENT, '模板管理')
        self.addSubInterface(self.settingView, FluentIcon.SETTING, '设置',
                             NavigationItemPosition.BOTTOM)
```

- 初始尺寸 1280×800，最小 1024×720
- 左侧导航可展开/折叠（库内置），折叠后只显示图标

### 11.6 布局原则

- **间距**：8 的倍数（8/16/24/32）
- **卡片间距**：16px；卡片内部 padding 12-16px
- **栅格**：`QGridLayout` / `QVBoxLayout` / `QHBoxLayout` + 标准 Spacer
- **响应式**：用 `FlowLayout`（库内置）处理标签云、竞品型号列表等不定宽元素

### 11.7 反馈与状态

- 所有长任务（装配、洗稿、批量）必须有进度反馈：`IndeterminateProgressBar` 或 `ProgressBar`
- 操作成功 → `InfoBar.success(...)` 顶部横幅，2 秒自动消失
- 操作失败 → `InfoBar.error(...)`，需用户点击关闭
- 危险操作（删除模板）→ `MessageBox` 二次确认，按钮文案明确（"删除" / "取消"，不用 OK/Cancel）

### 11.8 无障碍与细节

- 所有交互控件保留 Tab 焦点顺序（库默认支持）
- 不禁用系统缩放（高 DPI 友好，库已适配）
- 快捷键：`Ctrl+Enter` 触发装配/AI 洗稿；`Ctrl+S` 保存模板；`Esc` 关闭弹窗

### 11.9 参考

- qfluentwidgets 官方示例：https://qfluentwidgets.com/pages/examples
- 组件文档：https://qfluentwidgets.com/pages/components
- Win11 Fluent 设计规范：https://learn.microsoft.com/en-us/windows/apps/design/

---

## 12. 未决 & 待澄清



| 项 | 待确认 |
|----|--------|
| `prompts/` skill 文件是否要支持元数据头（如适用模板白名单） | 实现时按"纯 md 文件 + 文件名选择"的最简方案起步 |
| 批量模式并发上限 | 默认 3，配置在 settings.json |
| VaultIndex 缓存失效策略 | v1 手动"重新索引"按钮；v1.5 可加文件变更监听 |
| 首次运行向导 | v1 简化为"弹窗提示配置 API key + Vault 路径 + 导出目录" |
