# 变更日志

本项目所有可见变更都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Fixed
- **其他用户装 release 包后浏览器相关功能全炸 —— 评论抓取、Cookie 内置浏览器登录、百度账号登录弹窗一起报错**：根因是 NSIS 安装包从来没带过 Chromium 二进制。Patchright 的 `collect_data_files("patchright")` 只 bundle 了 `driver/node.exe`（Node.js 驱动），真正的 Chromium 浏览器二进制位于 `%LOCALAPPDATA%\ms-playwright\chromium-XXXX\`，由 `patchright install chromium` 单独装。dev 机有这个目录（开发时跑过一次），fresh 用户机没有 —— 所以每次 `pw.chromium.launch_persistent_context(...)` 都炸 `Executable doesn't exist`，前端看到 503 / 弹窗失败 / 评论抓取无果。本次：① release.yml 加 `python -m patchright install chromium` 步骤；② 把 `chromium-XXXX/` 目录（~408MB，跳过 headless-shell）通过 Tauri `bundle.resources` 拷到 NSIS 安装包的 `<install>/binaries/ms-playwright/`；③ `csm_core/browser_infra/patchright_pool.ensure_browsers_path` 加优先级：env var → `<sidecar-exe-dir>/binaries/ms-playwright/`（release） → `%LOCALAPPDATA%\ms-playwright`（dev/legacy）。**体积变化**：NSIS 安装包从 ~50MB 涨到 ~450MB；热更新 zip 同步变大（updater `zf.extractall()` + atomic rename 包含整个 install dir，所以 chromium 会随 hot-update 一起替换 —— 从 0.5.2 → 0.5.3 的热更新下载量会突涨到 ~450MB，但后续 0.5.3 → 0.5.4 同样涨，**目前没做"chromium 不变就跳过"的分层 zip 优化**，后续若需可在 `build_manifest.py` 加 chromium hash 字段 + updater 走条件下载）。0.5.1 及以下用户仍按 v0.5.2 CHANGELOG 说明走一次 NSIS setup.exe（旧 updater image-lock bug）。

## [0.5.2] - 2026-05-20

### Fixed
- **应用内热更新依然失败 (WinError 32)，v0.4.9 那次"修"没修干净**：v0.4.9 给 updater 加了 `taskkill /F /IM csm-sidecar.exe`，但实测 v0.4.9 → v0.5.1 升级照样 rename `<install>` → `<install>.bak` 失败 18 秒后回滚到旧版（关于页一直停在 v0.4.9）。真正的根因是 **updater.exe 自己跑在 `<install>/binaries/updater.exe`** —— Windows 把 running `.exe` 映像 mmap 成 image section 持有 deny-write/deny-delete handle 直到进程退出，install dir 在 updater 退出前永远 rename 不动，这跟 sidecar 是否被 kill 完全无关。本次让 updater spawn 前先把 `<install>/binaries/updater.exe` copy 到 `%TEMP%\csm_update\updater-<pid>.exe`，从 install dir **外面**跑，install dir 里就没有正在运行的 image 占用。**老用户 0.4.x → 0.5.1 装的需要走一次 NSIS setup.exe 重装到最新版**——他们机器里的旧 updater.exe 在 install dir 里跑，下次热更新还会撞同样的 image lock。

## [0.5.1] - 2026-05-20

### Added
- **评论模板库（mining）**：评论编辑器上方新增模板 chips 行（Top 5 高频/精选 + 抽屉按钮），右侧抽屉支持全量浏览/搜索/标签筛选/inline 管理（Ctrl+/ 快捷键唤起）。设置 → 评论模板库 提供完整 CRUD + 批量导入 + JSON 导出 + 隐藏切换 + 标签过滤 + 分页。已发出的评论通过 DAO 钩子自动入库（文本归一化去重）。

## [0.5.0] - 2026-05-17

### Added
- **视频引流抓取（mining）**：新建独立「引流」view，输入关键词后从抖音/B站/快手三平台搜索抓视频列表，全局按 `(platform, platform_video_id)` 去重落 SQLite。每平台 ≈50 条，5-10 分钟出表。
- **已评论反查**：抓回的视频反查 `monitor_tasks` 中 `*_comment` 类型任务，命中则标 `already_commented=1`；前端默认筛选"未评论"看不到，切到"已评论"看到 + 绿色徽章 + 来源 tooltip。
- **平台登录 UI**：首次手动登录浏览器、cookie 持久化到 `<config_dir>/browser_profiles/<platform>/`，下次抓取自动复用。
- **任务进度 SSE**：mining 任务运行时通过 SSE 实时推 `job.progress` / `job.platform_done` / `job.finished` 事件到前端进度卡。

### Changed
- 共享浏览器基建（`cookie_store` / `ua_pool` / `rate_limit` / `patchright_pool` / `interactive_login`）从 `csm_core/monitor/` 上提到新的顶层 `csm_core/browser_infra/` 包；`monitor` 包内保留 re-export 薄层以兼容现有调用方。
- monitor SQLite schema 升级到 v3（新增 `mining_jobs` / `videos` / `video_source_keywords` 三张表）。

## [0.4.9] - 2026-05-16

### Fixed
- **应用内热更新从来没真正 work 过 —— rename 安装目录失败 (WinError 32)**：v0.4.1 起 hot-update 路径就埋了这个 bug，只是之前没人实际触发过（多数用户走 NSIS setup.exe 升级）。updater 等 csm-tauri.exe 退出后立即 rename 安装目录，但 **csm-sidecar.exe 是 Tauri sidecar 子进程，主进程退出后没被一起 kill**，仍锁着 `<install>/csm-sidecar.exe` → rename 失败 → updater 静默回滚到旧版（关于页一直停在升级前的版本号，并伴随 csm-sidecar 重启时 PyInstaller `_MEI*` 解压撞文件的 dll Error 弹窗）。本次给 `updater/main.py` 在 rename 之前加 `taskkill /F /IM csm-sidecar.exe /T`（同款 `csm-tauri.exe` 防御），跟 NSIS PREINSTALL 钩子对齐。**老用户 0.4.7 / 0.4.8 装的需要走一次 NSIS setup.exe 重装到 0.4.9**——他们机器里的旧 updater.exe 没修，下次热更新还会撞同样的锁。

## [0.4.8] - 2026-05-16

### Fixed
- **设置 → 关于 显示版本号比实际安装的低一位**：v0.4.7 安装包装好后关于页显示 v0.4.6（热更新升级也一样）。原因是发版时只 bump 了 `tauri.conf.json` / `Cargo.toml` / `package.json` 三处，漏了 sidecar `__version__`——而关于页的版本号是 sidecar `/api/system/version` 实时返回。v0.4.8 把 sidecar 自报版本号补齐为 0.4.8。**老用户 0.4.7 → 0.4.8 热更新后关于页就会正确显示**。下次发版应该用 `python scripts/release.py X.Y.Z` 一键脚本，它会同时 bump 全部 4 处源头。

## [0.4.7] - 2026-05-16

### Added
- **百度关键词排名工作台**：监测中心新增"百度排名"页签（监测中心 → 百度），按任务组聚合每日排名快照，并提供 14 天日历聚合图表（同一天多次跑取最后一次、缺失天用 0 占位），可直观看到品牌词在各关键词上的卡位 / 跌出趋势。配套独立任务类型 `baidu_keyword`，与知乎 / 评论任务在同一调度器下并行运行。
- **全局排除域名**：设置 → 监测 新增"全局排除域名"弹窗，统一管理百度 SERP 抓取里要忽略的站点（自家站 / 镜像站 / 噪声站）。前端列表 + 校验 + 持久化，后端在 SERP 解析阶段过滤，避免误把自家域名当成"竞品卡位"。
- **运行中任务可取消**：监测中心进入运行态后顶部出现「取消」按钮，调用 `/api/monitor/cancel` 立即停止当前任务循环（不影响已写盘的数据）。

### Changed
- **monitor 任务进度跨页同步**：抽出 `monitorStatus` Pinia store，订阅 sidecar `progress` SSE 事件 + `/api/monitor/running` 状态端点，"创作 / 历史 / 设置"任意切页再回到监测中心都能看到正确的运行 / 进度 / 取消状态，不再因为切走而显示成"空闲"。
- **任务表单 UI 重排**：新增任务弹窗 + 批量导入弹窗按"类型 → 标识 → 关键词 → 调度"重排字段顺序，跟列表卡片的信息层级对齐；批量导入模板同步更新。
- **百度 SERP 抓取性能优化**：内嵌 Chromium 改用 stealth 假隐藏窗口策略（无可见窗口但带完整 UA + 字体指纹），单关键词抓取耗时下降，被风控/验证码触发率显著降低。

### Fixed
- **百度二级页头部对齐 B 站简洁版**：之前百度 Level 2 比 B 站 Level 2 多一道分隔 + padding 不一致，现在视觉重量对齐。
- **关键词选中态去掉橙色左竖条**：列表选中态只用底色 + 字色变化（跟 B 站列表统一），fallback 关键词行同样可选。

## [0.4.6] - 2026-05-15

### Fixed
- **NSIS 安装包遇到运行中的 CSM 会弹「Error opening file for writing」**：之前装包覆盖时 csm-sidecar.exe / csm-tauri.exe 还活着，文件被锁，NSIS 弹「中止/重试/忽略」对话框困住用户。加 NSIS PREINSTALL 钩子（`frontend/src-tauri/installer-hooks.nsh`）在拷贝文件前自动 `taskkill /f /im csm-*.exe`，500ms 等 Windows 释放句柄。下次双击 setup.exe 不会再卡这步。

## [0.4.5] - 2026-05-15

### Fixed
- **热更新会破坏用户数据 + rename 失败（致命）**：pre-v0.4.5 的用户数据目录是 `%LocalAppData%\CSM\CSM\`，而 NSIS 把应用装到 `%LocalAppData%\CSM\` —— **数据目录是安装目录的子级**。updater 把 install dir 整个重命名时会把数据一起搬走，再删 backup 时会**静默删光用户的 settings / cookies / 历史 / monitor db**。v0.4.4 的 rename 失败（"另一个进程正在使用此文件"）反而保住了数据。v0.4.5 把数据目录搬到 `%LocalAppData%\CSM-Data\`，跟 install dir 完全分离；老用户首次启动 v0.4.5 时会自动 `shutil.copytree` 把 `CSM\CSM\` 内容复制到 `CSM-Data\`（老目录保留作为备份，不删）。
- **Updater 安装时弹出黑色命令行窗口**：`updater.spec` 改 `console=False`，安装过程现在静默执行。日志仍写到 `%TEMP%\csm_update\updater.log`。失败时 app 静默回到旧版本（如果将来需要错误弹窗反馈再考虑加 MessageBox）。

### Changed
- **托盘右键菜单**加 "Content SEO Maker" 品牌头 + 分隔符 + 显示主窗口/退出的快捷键提示（Ctrl+Shift+C / Ctrl+Q），让 2 行的裸菜单看起来更"成型"。Windows 原生菜单无法直接套主界面的暖米色 + 圆角 + 字体（OS 接管渲染），所以视觉上仍是 Windows 原生灰白色，但信息密度跟主品牌指示提升。完全自定义渲染需要起一个透明 webview 小窗口，留给后续迭代。

## [0.4.3] - 2026-05-15

### Fixed
- **应用内热更新「立即重启」失败**：下载完成后点「立即重启」会弹「启动安装失败：zip_path is empty」，更新装不上。原因是 modal 的 resolveFinal 同步清空了 reactive state（包括 targetPath），SettingsView 在 await 之后再读已经是空。改为在 SSE done 回调里本地捕获 zip 路径，invoke Tauri 时用本地变量。
- **首次启动欢迎页「下一步」按钮不明显**：之前是个 46×46 px 的小空心圆只放一个 → 箭头，没文字、按下后没 loading 反馈。sidecar 第一次冷启动慢的话 patch 要好几秒，用户以为卡死就 force-quit。改为带「下一步」文字 + spinner 的实心按钮 + 按 Enter 也能提交 + 提交期间 disable 防连点。

## [0.4.2] - 2026-05-15

### Fixed
- 设置 → 关于 显示的版本号、以及「检查更新」弹窗里的「当前 vX.Y.Z」终于跟实际安装的版本号一致 —— 以前 sidecar `__version__` 一直停在 `0.0.1`、前端 `APP_VERSION` 常量停在 `0.4.0`，发版时 release.py 没把这两处一起 bump。改后版本号统一从 sidecar `/api/version` 实时读，release.py 也同时 bump sidecar `__init__.py`。

## [0.4.1] - 2026-05-14

### Added
- **桌面壳从 PyQt6 迁移到 Tauri 2 + Vue 3 + FastAPI sidecar 架构**：新的前端在浏览器/Tauri shell 中都能跑，UI 改进大量，启动更快，安装包更小。
- **应用内热更新**：设置 → 关于 → 检查更新，发现新版本自动弹窗显示版本号 / changelog / 文件大小；用户确认后流式下载（带 SHA256 校验、可取消），完成后一键关闭主程序、由独立 updater 替换安装目录、自动重启。
- **文章生成两步式流程**：拆分为「填资料 + 生成提纲」和「逐段落填充」两步，每一步独立保存，中断后可恢复；右侧栏新增「质检报告」面板显示历史重复率 + 素材引用率 + Top 3 相似来源。
- **历史报告页**（导航 → 历史报告）：知乎排名 trend、评论留存 trend 两块 LineChart 视图，全量历史数据可看。
- **批量导入**：监测任务支持 Excel 模板批量导入，错误行单独反馈不影响整体；模板下载入口在批量导入弹窗内。
- **NSIS 安装器**：首装走标准 Windows 安装包，自动写注册表 + 卸载条目 + Start Menu 快捷方式。

### Changed
- 段落筛选属性下拉在配置 Vault 后零额外操作即可使用（sidecar 启动时自动扫描素材库；前端在 409 时自愈重试 scan + 重新拉取）；value 支持多选（属性 `sample_values` 不超过 20 时渲染下拉，否则保留手填）。
- 新增「历史索引目录」概念：导出文章会自动以 `.md` 镜像到该目录（带 frontmatter `title / keyword / template / words / exported_at / source_format`），首页「最近文档」/ 字数统计 / 日历改用此目录作为数据源。**旧用户首次启动后，已有 `out_dir` 下的旧导出不会出现在最近文档中——历史归零是预期行为。**
- Templates / Skills / History 三个目录在首次启动自动建好（位于 `%LOCALAPPDATA%\CSM\CSM\` 下，macOS / Linux 对应位置同），内置样例模板 / Skills 自动种子；用户仍可在「设置 → 存储路径」修改位置。
- 「设置 → 历史查重」section 中的「历史索引目录」降级为只读地址（统一编辑入口到「存储路径」），重建按钮保留。

### Fixed
- 最近文档点击改为用系统默认应用打开文件（VS Code / Typora / Notepad），代替之前跳转到空白创作区的占位行为。
- 快手评论 /f/ 短链解析 + GraphQL V2 字段切换，快手内置账号登录器 cookie 检测与诊断改进。
- release 安装包不再把开发期 sidecar URL 烙进 Vite bundle（之前导致 release app 启动时回连一个早就死掉的开发机地址）。
- NSIS 首装链路串通 + UI 启动闪屏抖动修复。

## [0.3.0] - 2026-05-09

### Added
- 监测中心：新增一级导航页，整合 Case-6 知乎问题排名监测与 Case-8 多平台评论留存检测，建立"生成 → 投放 → 监测 → 反馈 → 再生成"闭环。
- 知乎抓取：curl_cffi（chrome120 TLS 指纹）主路径 + DrissionPage 兜底的双层方案，无需官方 API。
- 评论平台：B 站 / 抖音 / 快手 评论留存检测，API 直连（含 x-bogus / GraphQL 签名），失败自动降级到浏览器兜底。
- 调度与限流：QTimer 60s tick 单例调度器，平台级令牌桶 + RequestPacer + CircuitBreaker，主线程零阻塞。
- AI 联动：排名跌出 Top N 自动告警 + 一键跳转 ArticlePage 预填关键词 / 竞品摘要；评论情感与相关度 LLM 分类；Top 回答摘要落盘到 Vault。
- Cookie 管理：4 平台 Cookie 池 CRUD，按"失败次数升序、最近最少使用优先"轮询，连续失败 5 次自动停用。
- Excel 批量导入：监测任务支持模板下载 + 批量录入，错误行单独反馈不影响整体导入。
- 设置页「监测」分组：并发 / 限速 / 告警阈值 / 浏览器兜底路径 / AI 联动开关 / Cookie 管理入口。

### Fixed
- 设置页模型选择问题。
- 洗稿流程未调用 AI 的问题。

## [0.2.0] - 2026-05-07

### Added
- 系统托盘后台运行：关闭按钮默认最小化到托盘，托盘菜单提供新建文章 / 模板 / Skill / 设置 / 退出快捷操作。
- 单实例锁：避免重复双击启动多份 CSM 进程。
- 内容查重：创作区右侧润色按钮下方显示「历史重复率」+「素材引用率」双指标，支持下钻查看 top 3 相似来源 + 命中段落（MinHash + LSH 候选检索 + 13-字 shingling 精算）。
- 应用热更新：启动时静默检查 GitHub 私有仓库的最新 Release，发现新版本即弹窗提示，一键升级（独立 updater.exe 接管文件替换 + 失败回滚）。
- 设置页「关于 CSM」区块：显示当前版本 + 「检查更新」按钮 + 更新仓库配置。
- 自动化发版流水线：`scripts/release.py` 一键发版 + GitHub Actions 自动构建 + 抽 CHANGELOG 段落填充 Release notes。

## [0.1.0] - 2026-04-15

### Added
- 项目初版。
</content>
</invoke>