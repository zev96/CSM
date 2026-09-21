# CSM · Content SEO Maker

> 内容 SEO 运营工作台 —— **排名监测 / 评论留存 / 视频引流 / 小红书笔记** 四条链路，本地桌面 app 一站跑。

Tauri 2 + Vue 3 前端 + Python FastAPI sidecar，Windows 单文件 NSIS 安装包，应用内自更新。

---

## 这是什么

**CSM 是个内容运营的闭环工具**：

```
                  ┌──────────────────┐
                  │   1. 排名监测     │  知乎问题 / 知乎搜索 · 百度 · GEO
                  │      评论留存     │  B站 / 抖音 / 快手 / 小红书
                  └────────┬─────────┘
                           │ 跌出 Top N / 留存归零
                  ┌────────▼─────────┐
                  │   2. 引流抓取     │  抖音 / B站 / 快手 / 小红书 视频候选池
                  └────────┬─────────┘
                           │ 已评论反查 + 评论模板 / AI 批量评论 + 人工审核
                  ┌────────▼─────────┐
                  │   3. 同步 / 回流  │  腾讯文档协作表 · 同步回监测任务
                  └────────┬─────────┘
                           ▼
                       回流到 1
```

每一环都不强制：可以只跑「监测中心」当排名看板，也可以只用「引流」当视频候选池 + 评论工作台，或只用「小红书」编辑器写笔记。

> 「创作区」（AI 写稿 / 批量生成）、「素材库」、「模板库」三个页面及其后端已下线（见 CHANGELOG）。

---

## 功能概览

| 模块 | 入口 | 核心能力 |
|---|---|---|
| **工作台** | `/home` | 监测数字卡（百度 SEO / 知乎问题 / 知乎搜索）+ 评论留存率 + GEO 曝光 + 高权重信源 + 最近 7 天文档（只读旧版导出的历史目录） |
| **监测中心** | `/monitor` | 知乎问题排名 / 百度关键词排名 / B站·抖音·快手·小红书 评论留存 三类任务统一调度 |
| **数据中心** | `/data-center` | 历史排名 trend + 评论留存 trend + 百度 SEO 分析 |
| **引流抓取** | `/mining` | 四平台（抖音 / B站 / 快手 / 小红书）视频搜索 → 全局去重 → 已评论反查 → 评论模板库一键发评 |
| **小红书** | `/xhs` | 图文笔记编辑器：素材面板 + 手机预览 + AI 生成 / 润色（走设置里的模型 Key）|
| **设置** | `/settings` | 模型 API Key / 监测 · 百度抓取 / Cookie 池 / 排除域名 / 评论模板库 / 腾讯文档同步 / 更新 |

---

## 监测中心

三类任务在同一个调度器下并行，可分别配并发 / 限速 / 告警阈值。

### 知乎问题排名

- **抓取方案**：curl_cffi（Chrome 120 TLS 指纹）主路径 + DrissionPage 浏览器兜底，无需官方 API
- **追踪**：自己回答在每个关注问题的实时位次、Top N 的回答标题/赞数/摘要
- **告警**：跌出 Top N 即时通知，附竞品回答摘要

### 百度关键词排名

- **抓取**：内嵌 Patchright (stealth Chromium) 模拟真实浏览器，单关键词耗时低、风控触发率低
- **可视化**：14 天日历聚合图，同一天多次跑取最后一次，缺失天 0 占位
- **全局排除域名**：设置里维护一份"不算竞品"清单（自家站 / 镜像站 / 噪声站），SERP 解析阶段过滤

### B 站 / 抖音 / 快手 / 小红书 评论留存

- **抓取**：API 直连（含 x-bogus / GraphQL V2 签名），失败自动降级到浏览器兜底；小红书没有本地路径，固定走 TikHub 付费 API（需配置 Key）
- **检测**：监控你在目标视频底下的评论是否还在（被删 / 被沉 / 被折叠）
- **趋势**：每条评论的留存时长 trend + 平台健康度评分

### 运行控制

- **运行中可取消**：点取消立即抛 `CancelledError` 中断当前 fetch，不是"跑完这轮再停"
- **任务进度 SSE**：前端不轮询，sidecar 直接 push `progress` / `platform_done` / `finished` 事件
- **跨页同步**：切去别的页面再回来，进度条 / 当前关键词 / 剩余时间还在
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

1. **任务**：输入关键词 → 抖音 / B 站 / 快手 / 小红书 同时跑（小红书仅 TikHub 采集模式可选），每平台 ≈50 条，5–10 分钟出表
2. **全局去重**：按 `(platform, platform_video_id)` 去重落 SQLite，跨任务也不会重复抓
3. **已评论反查**：每条视频反查 `monitor_tasks` 中 `*_comment` 类型任务，命中则标 `already_commented=1`；默认筛选「未评论」让你看到的都是新机会
   - **精选评论跳过（B站）**：UP 主开启了评论精选（评论框提示「评论被up主精选后，对所有人可见」）的视频，评论发了也没人看得见——抓取后自动识别并排除，跳过条数见任务状态提示 / 完成通知
4. **评论模板库**：评论编辑器顶部 Top 5 高频模板 chips + Ctrl+/ 唤起全量抽屉，发出的评论自动入库（DAO hook + 文本归一化去重）
5. **CSV 导出**：原生保存对话框选位置；多列结构「序号 / 平台 / 视频链接 / 第 N 层评论 / 评论图片 / 评论返图」
6. **同步腾讯文档**：审核通过的评论按平台子表追加到共享在线表格，楼层挂图直接插进对应贴图列（服务端不支持时回落「有图，另发」标记）

---

## 安装

### 用户：双击安装包

去 [Releases](https://github.com/zev96/CSM/releases) 下载最新 `CSM_X.Y.Z_x64-setup.exe`，运行装到默认位置即可。

- 自动写 Windows 注册表 + 卸载条目 + Start Menu / 桌面快捷方式
- 单实例锁，不会重复启动
- 安装包 ~260MB（v0.8.3 实测 259MB；解压后 ~408MB 是 Patchright Chromium，所有评论 / 登录弹窗 / 百度排名都靠它跑）

### 应用内热更新

设置 → 关于 → 检查更新：

- 命中新版本会弹窗显示 版本号 + changelog + 文件大小 + SHA256
- 每个 release 挂两个热更新包：完整包 `CSM-vX.Y.Z.zip`（含 Chromium）和增量包 `CSM-vX.Y.Z-lite.upd`（不含 `binaries/ms-playwright`，体积约为完整包的一半）。客户端在本机已装的 `chromium-XXXX` 目录与 `manifest.json` 登记一致时自动选增量包，`updater.exe` 换目录时把旧安装里的 Chromium 原样搬进新目录；不一致（升级了 patchright）就退回完整包。≤0.8.3 的老客户端只认 `.zip`，看不到增量包
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
└── History\              # 旧版本导出的文章镜像（首页「最近文档」只读这里，新版不再写入；新装机不会创建）
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面壳 | **Tauri 2** (Rust)，单实例锁，托盘菜单，NSIS 单文件 installer |
| 前端 | **Vue 3 + Vite + TypeScript**，Pinia, vue-router, Chart.js, class-variance-authority |
| 后端 | **FastAPI** sidecar (Python 3.11)，PyInstaller onefile 分发 |
| 浏览器自动化 | **Patchright** (stealth Playwright fork) + bundled Chromium |
| 抓取 | curl_cffi (Chrome TLS 指纹) / DrissionPage / 平台 API + 签名 |
| 存储 | SQLite (monitor + mining + xhs)、JSON (settings)、md+frontmatter (旧版导出的历史文档) |
| 自更新 | 独立 `updater.exe`（从 install dir copy 到 `%TEMP%\csm_update\` 跑，避免 image-lock）+ atomic rename + SHA256 校验 |

---

## 开发流程

仓库结构：

```
csm_core/        # Python 业务核心
├── browser_infra/   # cookie_store / ua_pool / rate_limit / patchright_pool / interactive_login
├── llm/             # LLM client + providers 抽象层（小红书 AI / 引流 AI 评论）
├── mining/          # 引流抓取
├── monitor/         # 监测调度 + 平台 adapter + GEO
├── scoring/         # AI 味启发式评分（引流 AI 评论用）
├── sync/            # 腾讯文档同步
├── updater_client/  # 应用内更新检查 + 下载
└── xhs/             # 小红书笔记草稿存储

sidecar/csm_sidecar/   # FastAPI sidecar，包 csm_core 成 HTTP
├── routes/      # 路由（每个 view 一个）
└── services/    # business logic（被 routes 调用）

frontend/
├── src/views/        # 路由顶层 view
├── src/components/   # 复用组件（home/monitor/mining/xhs/settings/forms/ui 分类）
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
