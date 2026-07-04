# 百度关键词排名监控 · 设计

- 状态：已与用户对齐，待生成实施计划
- 日期：2026-05-15
- 工作树：`.claude/worktrees/brave-elbakyan-0d5933`（分支 `claude/brave-elbakyan-0d5933`）
- 相关代码栈：Tauri shell + Vue 前端 + Python sidecar，沿用 `csm_core/monitor/` 现有平台 adapter 范式

## 1. 目标与边界

在「监控中心」里新增一种监控类型 `baidu_keyword`：

- 用户给定一个百度搜索关键词 + 一到多个目标品牌词
- 系统操控本地 Chromium（patchright，默认 headless）打开 `https://www.baidu.com/s?wd=<keyword>`
- 提取「默认搜索」和「最新资讯」两个区块下文章的 `href`
  （2026-07-03 修订：百度改版删除卡片 class 里的 `result` token，用户原始
  XPath 0 命中。默认区块选择器改为 token 级 class 匹配 + `_EXCLUDED_TPLS`
  黑名单 + content_left 兜底 + 0 命中/部分漂移/资讯区诊断告警，见
  `_XPATH_DEFAULT`；另加百度自有垂类 host 守卫（百科/自搜索/图片/好看等
  永不计入排名，见 `_NON_ARTICLE_HOSTS`））
- 逐篇文章打开、读全文、判断是否包含任一目标品牌词
- 命中 → 标「自家品牌软文」；不命中 → 标「竞品」；抓取失败 → 标 `fetch_error`
- 两个区块输出严格分开
- 入历史库、画趋势、支持 Excel 导出

**非目标（明确不做）：**

- 不识别具体竞品品牌名（只标"非自家"布尔位）
- 不翻页（只看第一页 Top 10 + 最新资讯最多 3 篇）
- 不监控其他搜索引擎（Google / Bing / 360 / Sogou 不在本次范围）
- 不做付费推广位识别（选择器按 `_EXCLUDED_TPLS` tpl 黑名单排除推广 /
  视频 / 聚合类杂卡，两套模板桶的已知杂卡均覆盖）

## 2. 关键决策（已与用户对齐）

| 维度 | 决策 |
|---|---|
| 运行模式 | 纳入现有定时监控（schedule_cron + run-now），不做独立一次性工具 |
| 任务粒度 | 一条搜索关键词 = 一个 task；批量导入 = 一次建 N 个 task |
| 识别深度 | 全部打开原文判断（HTTP-first + SPA fallback 浏览器） |
| 竞品识别 | 只标「非自家」，不维护竞品词库 |
| 浏览器可见性 | 默认 headless；命中验证码 → 自动升级可见，等用户 90s 内过验证 |
| 排名范围 | 只第一页（Top 10 + 最新资讯最多 3 篇） |
| 输出 | 纳入现有历史页 + 30 天趋势图 + Excel 导出 |
| 文章预览 | 详情页 160 字摘要默认折叠，点击展开 |
| 无痕模式 | 每次 fetch 新建临时 BrowserContext，结束销毁；不持久化 cookie |

## 3. 架构与模块边界

### 3.1 后端（Python）

```
csm_core/monitor/
├── base.py                          ← TaskType Literal 加 "baidu_keyword"
├── platforms/
│   ├── __init__.py                  ← 注册 BAIDU adapter
│   └── baidu_keyword.py             ← 新增：BaiduKeywordAdapter
└── drivers/
    ├── browser_driver.py            ← 微扩展：incognito_context / detect_captcha
    └── ua_pool.py                   ← 新文件：抽取 zhihu 的 _UA_POOL，跨平台共享

sidecar/csm_sidecar/
├── routes/monitor.py                ← 不动（泛型路由已覆盖）
├── services/monitor_lifecycle.py    ← 启动时调 BaiduKeywordAdapter.apply_settings
└── events.py                        ← 加 monitor.captcha_* 事件类型 Literal
```

### 3.2 前端（Vue）

```
frontend/src/
├── components/monitor/
│   ├── AddTaskModal.vue                  ← +baidu_keyword 分支
│   └── BatchImportTaskModal.vue          ← +百度 Excel 模板
├── components/monitor/history/
│   └── BaiduRankingPage.vue              ← 新增（仿 ZhihuRankingPage）
├── views/MonitorView.vue                 ← +百度历史 tab 路由
└── views/SettingsView.vue                ← +「百度关键词」设置折叠面板
```

### 3.3 Adapter 内部分层

**引擎选型**：`BaiduKeywordAdapter` 硬绑 `patchright` 引擎，不暴露 drission 选项。理由：

- 无痕模式只在 patchright 上实现（`browser.new_context()` 走 BrowserContext API）
- patchright 自带反检测补丁，百度反爬比知乎严
- drission 用 `launch_persistent_context`，与"无痕"语义冲突

`BaiduKeywordAdapter.fetch(task)` 流程：

1. `_breaker.allow()` — 熔断检查（连续失败 3 次 → 熔断 10 分钟）
2. `_pacer.wait()` — 跨任务 SERP 节流（默认 5s 间隔）
3. `_search_serp(keyword, headless)` — patchright 无痕 context 打开百度搜索
   - 命中验证码 → `_promote_to_visible()`（单 task 最多 1 次，超时 90s）
   - 用两条 XPath 提 `href` 列表（默认搜索 + 最新资讯）
4. `_resolve_redirects(hrefs)` — `baidu.com/link?url=...` → 真实 URL（HTTP 跟随 redirect）
5. `_check_articles(urls, brands)` — 对每条 URL：
   - HTTP-first：curl_cffi + `impersonate="chrome120"` + readability-lxml 提正文
   - HTTP 失败条件（status≥400 / 非 text/html / readability 正文 < 200 字 / SPA marker）→ patchright fallback 一个 tab
   - 大小写不敏感匹配任一品牌词
6. `_build_metric(...)` — 拼成 `default_results[]` + `news_results[]`
7. `_breaker.record_success() / record_failure()`
8. 返回 `MonitorResult`

## 4. 数据模型

### 4.1 TaskType 扩展

```python
TaskType = Literal[
    "zhihu_question",
    "bilibili_comment",
    "douyin_comment",
    "kuaishou_comment",
    "baidu_keyword",
]
```

### 4.2 `MonitorTask`

- `target_url` 复用，存 `https://www.baidu.com/s?wd=<urlencoded(keyword)>`。**单一真相源是 `config.search_keyword`**，`target_url` 在创建 / 更新任务时由 sidecar 路由层从 keyword 派生，避免两处脏写不一致。
- `config`：

```json
{
  "search_keyword": "Claude Code 教程",
  "target_brands": ["Claude", "Anthropic", "我的品牌名"],
  "headless": true
}
```

- `schedule_cron` 复用 zhihu 同款（`"manual"` 或 `"HH:MM"`）

### 4.3 `MonitorResult`

- `rank` 复用 1-based 约定：取 `default_results` 区块中**首个命中自家**的位置；不命中 = -1。
- 「最新资讯首条命中位置」单独存 `metric.news_first_rank`，不参与 task 表的告警逻辑。

### 4.4 `MonitorResult.metric`

```json
{
  "search_keyword": "Claude Code 教程",
  "target_brands": ["Claude", "Anthropic"],
  "serp_url": "https://www.baidu.com/s?wd=...",
  "default_results": [
    {
      "rank": 1,
      "title": "...",
      "url": "https://...",
      "host": "zhihu.com",
      "matches_brand": true,
      "matched_brand": "Claude",
      "source": "http",
      "content_preview": "...160 字...",
      "fetch_error": null
    }
  ],
  "news_results": [],
  "default_matched_count": 2,
  "default_first_rank": 3,
  "news_first_rank": -1,
  "news_present": false,
  "engine": "patchright",
  "headless": true,
  "captcha_hit": false
}
```

边界处理：

- 单篇文章抓取失败 → `matches_brand=false`，记 `fetch_error`，不让单篇拖垮整 task
- 原文不入库，只存 160 字 `content_preview`，避免 result 行膨胀
- 跨平台 `MonitorResult.rank` 字段语义保持一致 → 现有 sparkline / rank-fell-out 告警直接复用

## 5. 浏览器层与反爬

### 5.1 无痕 context

在 `csm_core/monitor/drivers/browser_driver.py` 加 `with_incognito(*, headless: bool) -> BrowserContext` 接口（仅 patchright 引擎实现，drission 不支持）：

```python
# 伪代码
with browser_driver.with_incognito(headless=True) as ctx:
    page = ctx.new_page()
    page.goto(serp_url)
    ...
# ctx.close() + browser.close() 自动调用
```

每次 fetch 冷启 2–4s，但避免反爬指纹累积。

### 5.2 验证码检测与升级

**检测时机**：每次 `page.goto()` 完成后调用 `_detect_captcha(page)`。

**检测条件**（任一命中）：

- 落地 URL 含 `wappass.baidu.com/static/captcha` / `passport.baidu.com` / `verify.baidu.com`
- DOM 中存在 `#captcha-img` / `.passport-login-pop`

**升级流程**：

1. 通过 `monitor_bus` 推 `monitor.captcha_required` 事件 → 前端弹 Toast
2. `context.close()` → `browser.close()`
3. 用 `headless=False` 重启同一 task 的 SERP step
4. 在新 page 上轮询验证码标志，最多 90s（`settings.baidu_keyword.captcha_visible_timeout_s`）
5. 过验证 → 推 `monitor.captcha_resolved`，继续后续 `_check_articles`
6. 超时 → 推 `monitor.captcha_timeout`，结束任务 `status="risk_control"`, `metric.captcha_hit=true`
7. 单 task 最多升级 1 次（`captcha_max_promotions=1`），第二次直接判失败

### 5.3 patchright stealth

复用 patchright 现有反检测补丁，额外注入：

- 真实 viewport `1366×768`
- UA 从 `csm_core/monitor/drivers/ua_pool.py`（新文件，抽取 zhihu 现有 `_UA_POOL`）

### 5.4 HTTP-first 抓正文

- `curl_cffi.requests.get(url, impersonate="chrome120", allow_redirects=True, timeout=15)`
- 正文提取：`readability-lxml`（**新依赖**，加到 `sidecar/pyproject.toml`）
- Fallback 到浏览器的条件：
  - HTTP 状态码 ≥ 400
  - `Content-Type` 不是 `text/html`
  - readability 提到正文 < 200 字
  - 响应含 SPA marker（`<noscript>请打开 JS</noscript>` 等）

### 5.5 节流与熔断

复用 `csm_core/monitor/rate_limit.py`：

- `get_pacer("baidu_keyword", min_interval=5)` — 跨 task SERP 间隔
- `get_breaker("baidu_keyword", failures=3, cooldown=600)` — 连续 3 次失败 → 熔断 10 分钟

### 5.6 百度跳转链接处理

百度 SERP 的 `href` 一般是 `https://www.baidu.com/link?url=...`。处理顺序：

1. HTTP-first 抓正文时 `allow_redirects=True` 自然解掉 302
2. 若 HTTP 阶段未 follow 成功（少数需 cookie 的跳转），用浏览器解析 `data-tools` 属性提原始 URL

## 6. 前端 UI

### 6.1 AddTaskModal 百度分支

字段：

- 任务名称（必填，对应 `MonitorTask.name`）
- 搜索关键词（必填，对应 `config.search_keyword`）
- 目标品牌词列表（至少 1 条，多行输入，对应 `config.target_brands[]`）
- 调度（沿用同款 `manual` / `"HH:MM"` 组件）
- 高级折叠：强制可见浏览器（对应 `config.headless = false`）

### 6.2 BatchImportTaskModal 百度模板

Excel 列：`任务名称 | 搜索关键词 | 目标品牌词（| 分隔） | 调度`。模板下载按钮在弹窗右上角，与其他平台一致。复用 `csm_core/monitor/excel_import.py`，加百度列映射。

### 6.3 BaiduRankingPage.vue（新）

仿 `ZhihuRankingPage.vue` 的左侧任务列表 + 右侧详情布局。详情区块自上而下：

1. **任务标头**：搜索 URL · 上次检查 · headless / captcha 状态 · 操作按钮（立即执行 / 导出 Excel / 编辑 / 删除）
2. **趋势卡**：30 天 X 轴，双线（自家命中数 + 首条排名），最新资讯命中徽章（出现/缺席）
3. **当前结果 · 默认搜索**：表格 10 行，列 `排名 | 标题 | 域名 | 自家?`，行底色区分自家/竞品/失败，预览 160 字默认折叠
4. **当前结果 · 最新资讯**：`news_present=true` 时显示，最多 3 行；为 `false` 时整面板隐藏，趋势图标 ⊘

**视觉规则**：

- 自家行：行底色淡绿 + Pill `命中: <matched_brand>`
- 竞品行：默认底色 + Pill `<host>`
- 失败行：行底色淡灰 + Pill `抓取失败`

### 6.4 Excel 导出（前端，依赖 `xlsx` 已存在）

一键导出当次结果：

- Sheet1「默认搜索」：10 行
- Sheet2「最新资讯」：0–3 行
- 列：`排名 | 区块 | 标题 | 链接 | 域名 | 是否自家 | 命中品牌 | 抓取来源 | 抓取错误`

### 6.5 失败 / 验证码反馈

- 任务进行中：列表行加 spinner（订阅 SSE `monitor.task_started/finished`）
- 命中验证码：非阻塞 Toast「百度要求验证码 — 浏览器已弹出，请在 90 秒内完成验证」
- 熔断中：行右侧红色 Pill「已熔断，N 分钟后恢复」

### 6.6 CookieManagerModal 排除

在 platform 下拉里**隐藏** `baidu_keyword`，避免误以为需要登录百度。

## 7. 设置与生命周期

### 7.1 `settings.json` 新增字段

```jsonc
{
  "monitor": {
    "baidu_keyword": {
      "headless_default": true,
      "captcha_visible_timeout_s": 90,
      "captcha_max_promotions": 1,
      "serp_pacing_seconds": 5,
      "breaker_failures": 3,
      "breaker_cooldown_seconds": 600
    }
  }
}
```

`SettingsView.vue` 加「百度关键词」折叠面板（与现有「知乎」「B站」并排），用 `FormToggle / FormInput / FormSlider`。

### 7.2 `BaiduKeywordAdapter.apply_settings`

签名仿 `ZhihuQuestionAdapter.apply_settings`，把 6 项设置注入到 adapter 单例的 `self._*` 字段。在 `monitor_lifecycle.start()` 与设置页保存时各调一次。

### 7.3 SSE 事件类型扩展

在 `csm_sidecar/events.py` 的事件类型 Literal 中加：

- `monitor.captcha_required`，payload `{task_id, platform, headless_was, prompt_url}`
- `monitor.captcha_resolved`
- `monitor.captcha_timeout`

`monitor_bus.py` 本身泛型，不动。

### 7.4 打包

- `csm-sidecar.spec`：现有 `collect_data_files("patchright")` 不动
- 新依赖 `readability-lxml`：加到 `sidecar/pyproject.toml`，需在 `tauri build --release` 后实跑验证 onefile 不丢
- `PLAYWRIGHT_BROWSERS_PATH` 已在 sidecar 启动时强设，复用现有逻辑

## 8. 测试策略

### 8.1 单元测试（`sidecar/tests/test_baidu_keyword.py`）

- `test_parse_serp_default_only` — 真实 SERP fixture（无最新资讯）→ 10 条 `href` + `news_present=false`
- `test_parse_serp_with_news` — 含最新资讯 fixture → 两组 list 分别拿到，不混排
- `test_brand_match_case_insensitive` — `target_brands=["Claude"]` + 正文 `"i love claude"` → 命中 + `matched_brand="Claude"`
- `test_brand_match_multiple` — 多个品牌词，命中靠前的那个
- `test_rank_when_no_match` — 全不命中 → `rank=-1`, `default_first_rank=-1`
- `test_http_fallback_too_short` — mock curl_cffi 返回 100 字 HTML → 标记 fallback 路径
- `test_captcha_url_detection` — 几个真实百度验证码 URL → 识别正确
- `test_baidu_link_redirect_unwrap` — `baidu.com/link?url=...` 在解 redirect 后 host 正确

Fixtures 放 `sidecar/tests/fixtures/baidu/`，含 2–3 份脱敏后真实 SERP HTML。

### 8.2 手动集成测试

`scripts/manual_test_baidu.py`：独立调用 `BaiduKeywordAdapter.fetch()`，输出 metric JSON 到 stdout。

验证清单：

- [ ] 默认 headless 跑通 10 条结果
- [ ] 热点关键词触发「最新资讯」，两组分开
- [ ] 连跑 20 次同关键词触发验证码 → 升级可见 + Toast + 用户过验证
- [ ] 不存在品牌词 → `rank=-1`
- [ ] 百家号 / 微信公众号链接 → HTTP-first 失败 + 浏览器 fallback 成功

### 8.3 Release 实跑（必须，按过往教训）

`tauri build --release` 后：

- [ ] 创建 baidu_keyword 任务 → 立即执行 → 历史页看到结果
- [ ] 批量导入 Excel 5 行 → 5 个任务建出来
- [ ] 跑完导出 Excel，链接可点、列对齐
- [ ] 验证 patchright onefile 不爆 0xc0000409
- [ ] `PLAYWRIGHT_BROWSERS_PATH` 在解压目录正常工作

## 9. 上线节奏

分两个 PR：

**PR #1 — 后端 + 单测**

- `csm_core/monitor/base.py`（TaskType 扩展）
- `csm_core/monitor/platforms/baidu_keyword.py`（新）
- `csm_core/monitor/platforms/__init__.py`（注册）
- `csm_core/monitor/drivers/browser_driver.py`（incognito + captcha 检测）
- `csm_core/monitor/drivers/ua_pool.py`（新，抽取共享 UA）
- `csm_sidecar/services/monitor_lifecycle.py`（apply_settings 挂接）
- `csm_sidecar/events.py`（captcha 事件 Literal）
- `sidecar/pyproject.toml`（+ readability-lxml）
- `sidecar/tests/test_baidu_keyword.py`（单测 + fixtures）
- 验收：单测全绿 + `scripts/manual_test_baidu.py` 跑出合法 metric

**PR #2 — 前端 + 端到端**

- `frontend/src/components/monitor/AddTaskModal.vue`（百度分支）
- `frontend/src/components/monitor/BatchImportTaskModal.vue`（百度模板）
- `frontend/src/components/monitor/history/BaiduRankingPage.vue`（新）
- `frontend/src/views/MonitorView.vue`（路由）
- `frontend/src/views/SettingsView.vue`（百度面板）
- `csm_core/monitor/excel_import.py`（百度列映射）
- 验收：release 实跑清单全过 → 合并即发版

## 10. 已识别的风险

| 风险 | 缓解 |
|---|---|
| 百度反爬升级，XPath 失效 | 用户提供的 XPath 已经基于最新百度 SERP；fixture 保留多份，监测变更 |
| readability-lxml 在 PyInstaller onefile 下静默丢失 | 加入手动 release 跑测清单；必要时切换 trafilatura |
| Headless 命中验证码频率超预期 | 默认 headless + 升级可见 + 90s 用户窗口 + 单 task 1 次硬上限 + 熔断兜底 |
| 单任务 90s+ 拖慢 monitor_loop | 与其他平台同 worker，monitor_loop 已是 thread-per-task 模型，不阻塞别的 task |
| 无痕模式与 zhihu 持久化模式互相干扰 | 无痕用 `browser.new_context()`（独立 BrowserContext），不复用 zhihu 的 `launch_persistent_context` |
| 百度跳转 URL 解不出真实 host | HTTP follow-redirect 兜底 + `data-tools` 二次解析；解不出时 `host="baidu.com"`、`fetch_error="redirect_unresolved"` |
