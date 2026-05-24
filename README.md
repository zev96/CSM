# CSM · Content SEO Maker

> 内容 SEO 全流程工作台 —— 把"写一篇排名好的种草文"拆成 **AI 写稿 / 排名监测 / 评论留存 / 视频引流** 四条链路，本地桌面 app 一站跑。

Tauri 2 + Vue 3 前端 + Python FastAPI sidecar，Windows 单文件 NSIS 安装包，应用内自更新。

---

## 这是什么

不是又一个 ChatGPT wrapper。**CSM 是个内容运营的闭环工具**：

```
                ┌──────────────────────────────────────────┐
                │  Obsidian Vault                          │
                │  ─ 选题素材 / 框架模板 / 风格 Skill      │
                └──────────┬───────────────────────────────┘
                           │
                  ┌────────▼─────────┐
                  │   1. AI 写稿     │  两步式 · 内容查重 · 批量
                  └────────┬─────────┘
                           │ 导出 / 发布
                  ┌────────▼─────────┐
                  │   2. 排名监测     │  知乎 · 百度 · B站/抖音/快手 评论
                  └────────┬─────────┘
                           │ 跌出 Top N / 留存归零
                  ┌────────▼─────────┐
                  │   3. 引流抓取     │  抖音 / B站 / 快手 视频候选池
                  └────────┬─────────┘
                           │ 已评论反查 + 评论模板
                           ▼
                       回流到 1
```

每一环都不强制，可以只用「AI 写稿」+「批量生成」当成笔记工具，也可以只跑「监测中心」当成排名看板。

---

## 功能概览

| 模块 | 入口 | 核心能力 |
|---|---|---|
| **工作台** | `/home` | 4 张监测卡（百度 / 知乎 / 评论 / 引流）+ 一键创建文章 + 最近 7 天文档 |
| **创作区** | `/article` | 两步式 AI 写稿（填资料+提纲 → 逐段填充）、历史重复率 / 素材引用率 双指标质检 |
| **批量生成** | `/batch` | Excel 模板批量产文，错误行单独反馈不阻塞整体 |
| **监测中心** | `/monitor` | 知乎问题排名 / 百度关键词排名 / B站·抖音·快手 评论留存 三类任务统一调度 |
| **数据中心** | `/data-center` | 历史排名 trend + 评论留存 trend + 百度 SEO 分析 |
| **引流抓取** | `/mining` | 三平台视频搜索 → 全局去重 → 已评论反查 → 评论模板库一键发评 |
| **模板库** | `/templates` | 文章框架模板（段落级 schema）+ 风格 Skill（语气/示例/约束）|
| **设置** | `/settings` | 路径 / 模型 / 监测阈值 / Cookie 池 / 更新 / 排除域名 / 模板库 |

---

## AI 写稿

**两步式工作流**，避免一次性吐出 4000 字然后哪段都改不动：

1. **第一步「填资料 + 生成提纲」** — 输入关键词、参考链接、选模板 + Skill，AI 给出段落级 outline（每段标题 + 要点 bullet）。可改 / 锁段。
2. **第二步「逐段落填充」** — 一段一段填，每段独立保存。中断退出后回来从上次断点续。

**Vault 化素材库**：所有可被 AI 引用的素材都在 Obsidian Vault 里以 markdown 存（在 `属性筛选` 里按 frontmatter property 多选过滤），sidecar 启动时自动扫描索引。AI 调用时按段落需求拉相关素材进 context。

**内容查重**（默认开启）：

- **历史重复率** — 当前正文与历史文章库目录的字面重叠（避免自己抄自己）
- **素材引用率** — 润色后的成文与 vault 素材的字面重叠（衡量是否消化了原文，过高 = 直接搬运）
- 算法：13-字滑窗 shingling + MinHash/LSH 候选检索（Jaccard 阈值 0.3）+ 精算下钻段落定位
- 索引懒加载序列化到 `<config_dir>/dedup_index/`，重启不需要重建
- ⓘ 详情面板看 top 3 相似来源 + 命中段落，双击用系统默认应用打开来源文件

**导出**：md / docx，自动镜像一份到「历史索引目录」（带 frontmatter `title / keyword / template / words / exported_at`），首页「最近文档」/ 字数统计 / 日历都基于这个目录。

---

## 监测中心

三类任务在同一个调度器下并行，可分别配并发 / 限速 / 告警阈值。

### 知乎问题排名

- **抓取方案**：curl_cffi（Chrome 120 TLS 指纹）主路径 + DrissionPage 浏览器兜底，无需官方 API
- **追踪**：自己回答在每个关注问题的实时位次、Top N 的回答标题/赞数/摘要
- **告警**：跌出 Top N 即时通知，一键跳创作区预填该问题做 + 竞品摘要

### 百度关键词排名

- **抓取**：内嵌 Patchright (stealth Chromium) 模拟真实浏览器，单关键词耗时低、风控触发率低
- **可视化**：14 天日历聚合图，同一天多次跑取最后一次，缺失天 0 占位
- **全局排除域名**：设置里维护一份"不算竞品"清单（自家站 / 镜像站 / 噪声站），SERP 解析阶段过滤

### B 站 / 抖音 / 快手 评论留存

- **抓取**：API 直连（含 x-bogus / GraphQL V2 签名），失败自动降级到浏览器兜底
- **检测**：监控你在目标视频底下的评论是否还在（被删 / 被沉 / 被折叠）
- **趋势**：每条评论的留存时长 trend + 平台健康度评分

### 运行控制

- **运行中可取消**：点取消立即抛 `CancelledError` 中断当前 fetch，不是"跑完这轮再停"
- **任务进度 SSE**：前端不轮询，sidecar 直接 push `progress` / `platform_done` / `finished` 事件
- **跨页同步**：切去创作区再回来，进度条 / 当前关键词 / 剩余时间还在
- **Cookie 池**：每个平台一份 Cookie CRUD 池，按"失败次数升序、最近最少使用优先"轮询，连续失败 5 次自动停用

---

## 引流抓取

**三栏布局**：

```
┌─────────────┬───────────────┬─────────────────┐
│ TaskList    │ SubtaskList   │ VideoDetail     │
│ (任务列表)  │ (该任务视频)  │ (评论图层/图片) │
└─────────────┴───────────────┴─────────────────┘
```

1. **任务**：输入关键词 → 抖音 / B 站 / 快手 同时跑，每平台 ≈50 条，5–10 分钟出表
2. **全局去重**：按 `(platform, platform_video_id)` 去重落 SQLite，跨任务也不会重复抓
3. **已评论反查**：每条视频反查 `monitor_tasks` 中 `*_comment` 类型任务，命中则标 `already_commented=1`；默认筛选「未评论」让你看到的都是新机会
4. **评论模板库**：评论编辑器顶部 Top 5 高频模板 chips + Ctrl+/ 唤起全量抽屉，发出的评论自动入库（DAO hook + 文本归一化去重）
5. **CSV 导出**：原生保存对话框选位置；多列结构「序号 / 平台 / 视频链接 / 第 N 层评论 / 评论图片 / 评论返图」

---

## 模板库

**文章框架（Template）**：段落级 schema 描述「这种文章长什么样」—— 段落标题 / 段落字数范围 / 段落引用素材的属性约束。可以为同类话题（开箱 / 测评 / 干货合集）各做一份。

**风格 Skill**：语气 / 措辞示例 / 必须遵守的约束 / 禁用词 — 跟框架解耦，组合使用。

**首次启动自动种子**：内置样例模板 + Skills，可在「设置 → 存储路径」里调位置。

---

## 安装

### 用户：双击安装包

去 [Releases](https://github.com/zev96/CSM/releases) 下载最新 `CSM_X.Y.Z_x64-setup.exe`，运行装到默认位置即可。

- 自动写 Windows 注册表 + 卸载条目 + Start Menu / 桌面快捷方式
- 单实例锁，不会重复启动
- 安装包 ~450MB（其中 ~408MB 是 Patchright Chromium，所有评论 / 登录弹窗 / 百度排名都靠它跑）

### 应用内热更新

设置 → 关于 → 检查更新：

- 命中新版本会弹窗显示 版本号 + changelog + 文件大小 + SHA256
- 流式下载（可取消，断点不接续），下载完后台校验
- 一键关主程序 → 独立 `updater.exe` 替换安装目录 → 自动重启
- 失败静默回滚旧版（日志在 `%TEMP%\csm_update\updater.log`）

> ⚠️ 0.4.x ≤ 0.5.1 的老用户首次升级需要走一次 setup.exe（旧 updater image-lock 已修但要先装新 updater）。0.5.2+ 互升都能走热更新。

### 开发者：从源码跑

```powershell
# 一次性环境（Python 3.11 / Node 20）
pip install -e .
pip install -e ./sidecar
cd frontend
npm install            # 注意：用 npm 不要 pnpm，CI 走 npm ci
npm run tauri:dev      # 起 Tauri shell（dev 自动起 Vite + 拉 sidecar）
```

数据存储位置（不会随 install dir 一起被热更新替换）：

```
%LOCALAPPDATA%\CSM-Data\
├── settings.json
├── monitor.db            # 监测 + 引流任务和结果
├── browser_profiles\     # 各平台 Cookie 持久化
├── dedup_index\          # MinHash 索引（懒加载）
├── history\              # 历史索引（md 镜像）
├── templates\
└── skills\
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面壳 | **Tauri 2** (Rust)，单实例锁，托盘菜单，NSIS 单文件 installer |
| 前端 | **Vue 3 + Vite + TypeScript**，Pinia, vue-router, Chart.js, TipTap (rich editor), cva + clsx + tailwind-merge |
| 后端 | **FastAPI** sidecar (Python 3.11)，PyInstaller onefile 分发 |
| 浏览器自动化 | **Patchright** (stealth Playwright fork) + bundled Chromium |
| 抓取 | curl_cffi (Chrome TLS 指纹) / DrissionPage / 平台 API + 签名 |
| 存储 | SQLite (monitor + mining schema v3)、JSON (settings)、md+frontmatter (vault/history) |
| 查重 | MinHash + LSH + 13-字 shingling, Jaccard 阈值 0.3 |
| 自更新 | 独立 `updater.exe`（从 install dir copy 到 `%TEMP%\csm_update\` 跑，避免 image-lock）+ atomic rename + SHA256 校验 |

---

## 开发流程

仓库结构：

```
csm_core/        # Python 业务核心
├── assembler/   # 段落组装
├── batch/       # 批量
├── browser_infra/   # cookie_store / ua_pool / rate_limit / patchright_pool / interactive_login
├── dedup/       # MinHash / LSH
├── export/      # md / docx 导出
├── framework/   # 文章框架模板
├── keyword/     # 关键词扩展
├── llm/         # LLM 抽象层
├── mining/      # 引流抓取
├── monitor/     # 监测调度 + 平台 adapter
├── template/    # 模板加载
├── title/       # 标题生成
├── updater_client/  # 应用内更新检查 + 下载
└── vault/       # Obsidian Vault 扫描

sidecar/csm_sidecar/   # FastAPI sidecar，包 csm_core 成 HTTP
├── routes/      # 路由（每个 view 一个）
└── services/    # business logic（被 routes 调用）

frontend/
├── src/views/        # 路由顶层 view
├── src/components/   # 复用组件（home/monitor/mining/templates/ui 分类）
├── src/stores/       # Pinia store
├── src/router/       # vue-router
└── src-tauri/        # Tauri 配置 + Rust shell + NSIS installer hooks

scripts/         # release.py / build_sidecar.py / build_updater.py / build_manifest.py / ...
.github/workflows/release.yml   # tag v*.*.* 触发的发版流水线
```

### 一键发版

```powershell
python scripts/release.py 0.5.4            # 实跑
python scripts/release.py 0.5.4 --dry-run  # 预览
```

会：

1. 检查 git tree clean + main 分支 + 新版本 > 当前版本
2. 同步 bump 5 处版本号源头：
   - `frontend/src-tauri/tauri.conf.json`
   - `frontend/src-tauri/Cargo.toml`
   - `sidecar/csm_sidecar/__init__.py`
   - `frontend/package.json`
   - `frontend/package-lock.json`
3. Rename CHANGELOG `## [Unreleased]` → `## [X.Y.Z] - YYYY-MM-DD`
4. `git commit` + `git tag vX.Y.Z` + `git push origin HEAD --tags`
5. tag push 触发 `.github/workflows/release.yml`：
   - `patchright install chromium` → 拷到 `binaries/ms-playwright/`
   - `build_sidecar.py` 出 `csm-sidecar-x86_64-pc-windows-msvc.exe`
   - `build_updater.py` 出 `updater.exe`
   - `tauri build` 出 NSIS installer
   - 静默装到 `D:\stage\CSM` 校验布局 + 打 hot-update zip + SHA256 manifest
   - 创 GitHub Release，挂 zip + manifest + setup.exe

> **必备前置**：发版前在 `CHANGELOG.md` 顶部加 `## [Unreleased]` section 并填写本版改动，否则 release.py 在 step 3 卡。

### 日常开发

- **加 npm 依赖**：用 `npm install <pkg>` 不要用 pnpm（`pnpm-lock.yaml` 在 `.gitignore` 里，CI 跑 `npm ci` 认 `package-lock.json`）
- **改 frontend**：`npm run tauri:dev` 起 dev shell，热重载
- **改 sidecar**：sidecar 是 editable install，改 Python 后重启 sidecar 进程（Tauri shell 会自动拉新进程）
- **PR 流程**：所有改动开分支 → push → `gh pr create`，main 只接收 PR merge + release commit

---

## License

私有项目。第三方代码（`csm_core/_vendor/MediaCrawler` 等）按各自 LICENSE 引用 —— 商业化前必须移除衍生的非商用授权代码（如 NCL 1.1）。
