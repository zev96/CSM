# 视频抓取增强 + 监控批量导入修复 设计文档

**日期**：2026-05-17
**范围**：1 新能力扩展 + 3 个 bug 修复
**预计 PR 拆分**：2 个 PR

---

## 1. 背景

用户反馈了 4 个问题：

1. 抖音/快手"视频抓取"在 UI 上有但跑不出数据（卡登录页 / 结果空），用户误以为"未实现"。
2. 百度排名批量导入弹窗不会自动关闭，且任务列表不刷新，必须切 tab 才看到新任务。
3. 百度排名导入 93 个关键词的任务，点进任务详情只显 1 行关键词，等检测完才显 93 行。
4. 百家号文章抓取 25 篇左右触发验证码，应用没提示，继续硬抓导致结果偏差。

代码探索结论：

- `csm_core/mining/platforms/douyin_search.py` / `kuaishou_search.py` 都已完整实现（不是占位）。
- `csm_core/browser_infra/mining_browser.py` 已用 `launch_persistent_context` 持久化 profile，并从 `monitor.db` 注入 cookies；但 mining 用的是**独立 profile**（不是直接复用 monitor 浏览器栈）。
- 前端 `MonitorView.vue:3274` 的 `@imported` 回调没有 baidu 分支；`BatchImportTaskModal.vue:320` 的 `close()` 函数被 `submitting` flag 早退。
- `BaiduRankingPage.vue:1453` 详情页"已跑"分支直接渲染 `latestMetric.keywords`，缺少"未跑占位"。
- 没有专门的"百家号 scraper"代码——百家号是百度排名抓取过程中跟进 SERP 卡位时点开的下游页，验证码当前仅靠 `is_baidu_captcha_url()` URL 子串识别，覆盖太薄。

---

## 2. 模块 1：批量导入弹窗不关 + 列表不刷新

### 根因

1. **弹窗不关**：`BatchImportTaskModal.vue:320` `close()` 函数：
   ```js
   function close() {
     if (submitting.value) return;  // 早退
     ...
   }
   ```
   而 `submitAll()` 在 `try` 块（line 534）调 `close()` 时，`submitting.value` 仍为 `true`，要到 `finally`（line 539）才置 `false`。所以百度路径下 `close()` 等于空跑。

2. **列表不刷新**：`MonitorView.vue:3274`
   ```vue
   @imported="loadTasks(activeTab === 'zhihu' ? 'zhihu_question' : PLATFORM_TYPE[commentSubtab])"
   ```
   只覆盖 `zhihu` 和评论三平台。`baidu` 和 `report+baidu` 时调用的是 `PLATFORM_TYPE[commentSubtab]`，刷的是评论 tab 的列表，baidu 列表不动。

### 修复

**a. 修 `submitAll()`**：在 `try` 块调 `close()` **之前**显式置 `submitting.value = false;`。`finally` 里的同名赋值**保留**——错误路径（POST 失败）仍需要它把 flag 复位，不能删。

**b. 修 `@imported` handler**：抽 `currentTaskType` computed，让 `<BatchImportTaskModal :default-type=...>` 和 `@imported` 共用同一份映射，避免再次错位：
```js
const currentTaskType = computed(() => {
  if (activeTab.value === 'zhihu') return 'zhihu_question';
  if (activeTab.value === 'baidu') return 'baidu_keyword';
  if (activeTab.value === 'report' && historySubtab.value === 'baidu') return 'baidu_keyword';
  return PLATFORM_TYPE[commentSubtab.value];
});

function onImportedReload() {
  loadTasks(currentTaskType.value);
}
```
Modal 的 `:default-type` 直接绑 `currentTaskType`，`@imported` 绑 `onImportedReload`。

### 验证

手动场景：在 baidu tab 批量导入 5 个关键词。
- 期望：弹窗自动关闭；任务列表立刻多出 1 个新任务（不需切 tab）。

---

## 3. 模块 2：任务详情只显 1 关键词（检测完才显 93）

### 根因

`BaiduRankingPage.vue:1384-1453` 详情页关键词表两个分支：

- `!latestMetric` → 渲染 `selectedTask.config.search_keywords`（93 行 ✓）
- `latestMetric` 存在 → 渲染 `latestMetric.keywords`（只有已检关键词）

`latestMetric = history[0].metric`（line 422-428）。检测中途已经写了一条 MonitorResult，其 `keywords` 数组只有刚检测完的几个；前端误把"有任何结果"等同于"全部完成"，分支切到 `latestMetric` 后丢了未检测占位。等所有 93 个都跑完，`latestMetric.keywords.length === 93`，看起来"全部显示"。

### 修复（采纳方案 A，合并渲染源）

删除"无 latestMetric / 有 latestMetric"双分支，改成**单一渲染源 `keywordRows`**——以 `config.search_keywords` 为基准 93 行不变，按 keyword 名从 `latestMetric.keywords` 做 dict 查找填充每行结果列；未匹配到的关键词渲染 "未跑" Pill。

```js
const keywordRows = computed(() => {
  const base = selectedTask.value?.config?.search_keywords ?? [];
  const map = new Map((latestMetric.value?.keywords ?? []).map(k => [k.keyword, k]));
  return base.map(name => ({ keyword: name, result: map.get(name) ?? null }));
});
```

模板：
```vue
<div v-for="(row, i) in keywordRows" :key="row.keyword + '-' + i">
  <div>{{ row.keyword }}</div>
  <div>{{ row.result?.default_first_rank ?? '—' }}</div>
  <div>{{ row.result?.news_first_rank ?? '—' }}</div>
  <Pill :tone="row.result ? 'success' : 'info'">{{ row.result ? '已检' : '未跑' }}</Pill>
</div>
```

现有依赖 `latestMetric` 的统计卡（命中率、卡位数）保持不动——它们对"已检子集"统计是正确的语义。

### 验证

导入 10 个关键词的任务 → 立即点详情：应看到 10 行"未跑"。
检测跑到第 3 个后中断 → 详情：3 行"已检"，7 行"未跑"，原排序不变。

---

## 4. 模块 3：抖音/快手视频抓取卡登录页 / 结果空

### 根因（5 条叠加）

1. **目标页面不同**：评论抓取走视频详情页 + 评论 API（风控宽松）；视频抓取驱动**搜索结果页**（高价值反爬目标）。同一份 cookies 在评论端口能过、搜索端口被卡是常态。

2. **签名参数差异**：抖音搜索 XHR 带 `_signature` / `X-Bogus`（前端 JS 实时算），任意指纹不匹配即拒；评论 API 不查这套。

3. **快手 SPA 反指纹**（[kuaishou_search.py:42-47](../../../csm_core/mining/platforms/kuaishou_search.py:42) KNOWN ISSUE）：哪怕带正确 cookies，搜索路由仍强制弹登录墙。

4. **两套独立浏览器封装**：监控走 `patchright_pool`（含 reaper / UA 轮换 / stealth 调优）；视频抓取走 `mining_browser`（[mining_browser.py:88-92](../../../csm_core/browser_infra/mining_browser.py:88) launch_args 只有 3 个参数，没注入 UA、没 init_script）。

5. **mining 不是真正共享 monitor 登录态**：把 monitor cookies **重新注入**到全新 profile（[mining_browser.py:111](../../../csm_core/browser_infra/mining_browser.py:111)），不是直接复用 monitor 浏览器 profile。注入 cookies ≠ 完整登录态：新 profile 的 `localStorage` / `sessionStorage` / `IndexedDB` / 浏览器指纹全空，平台风控认定"老账户新设备 + 缺前端状态"触发拦截。

### 修复（5 层方案）

#### 第 1 层：前端预检 + 友好错误（必做，PR 2）

- 新增 `GET /api/mining/credentials?platform=douyin` 返回 `{has_cookies: bool, last_used: timestamp}`
- `StartJobModal` 提交前预检：
  - 无 cookies → 引导跳"监控中心 → 凭据管理"
  - cookies 存在但 last_used > 7 天 → 黄色 warning
- 后端 mining runner 落到登录墙时 `SearchOutcome` 新增 `status: "login_required" | "captcha" | "ok"`，SSE 透传前端
- 前端任务卡片新增 `login_required` 状态徽章 + "重新登录"按钮
- 抓取进度 0% 卡住 10s 后弹"看起来卡住了，可能是登录失效"提示

#### 第 2 层 + 第 4 层：mining 复用 monitor 的 patchright_pool，pool 侧统一加固反指纹（治本，PR 2）

第 2 层（反指纹增强）和第 4 层（共享浏览器栈）合并实施——把反指纹配置统一沉到 `patchright_pool`，mining 改成从 pool 借页，自动继承所有 stealth 配置。

**第 4 层的实施**：

把 `csm_core/browser_infra/mining_browser.py` 从「独立 profile launcher」改造成「patchright_pool 适配层」：
- `launched_page(platform, headless)` 改成从 `patchright_pool.acquire(platform=...)` 借页
- 保留原文件里的 `_inject_monitor_cookies()` 和 `_kill_process_tree()` 复用调用（pool 接口对齐后这两个工具仍要用）
- 涉及生命周期：mining adapter 调用方从"每任务 launch/close"改成"pool 里借页"，调用方代码改动约 30 行
- 评论 + 视频 + 百度排名都走同一个浏览器栈，cookie / storage / 浏览器指纹完全一致

**第 2 层的实施**（沉到 pool 里，所有调用方继承）：

`patchright_pool.launched_context()` 内部 launch_args 补：
```python
"--disable-blink-features=AutomationControlled",
"--disable-features=IsolateOrigins,site-per-process",
f"--user-agent={ua_pool.pick()}",
```
context 创建后注入 `init_script` 屏蔽 `navigator.webdriver` / `window.chrome` / `window.cdc_*`；`extra_http_headers` 补 `Accept-Language` / `sec-ch-ua` 一致性 headers；viewport 在 `1280×800 / 1440×900 / 1366×768` 三档随机化。

→ 评论抓取/百度排名/视频抓取**全部受益**，反指纹只在 pool 维护一次。

#### 第 5a 层：搜索页 DOM 直读降级（PR 2）

当 XHR 拦截 0 条时自动降级走 DOM 解析：`page.locator('a[href*="/video/"]').all()` 抽 href。
- adapter 增加 `fallback_mode="dom"` 配置
- 拿不到 XHR 才有的精确播放/互动详情字段（用 `None` 占位）
- 速度比 XHR 慢 ~30%

#### 第 5b 层：可视点击降级（进 backlog，不在本次范围）

最重保底：开**可见浏览器**，逐卡片点击 → 等详情 → 抓地址栏 URL → 返回。
- 100 个视频约需 5-8 分钟
- 强制 `headless=False`、前台窗口
- 任务卡显示"预计 X 分钟，请勿关闭浏览器"
- 用户配置"抓取强度"下拉：自动 / 强制 DOM / 强制可视慢速

**抓取模式优先级链**（自动模式默认）：
```
XHR 抓 → 失败/0 条 → 5a DOM 直读 → 失败 → 提示用户切 5b 可视慢速
```

### 验证

- 在监控中心未配抖音 cookies 时启动视频抓取 → 预检拦截弹出引导（不进浏览器）
- 配过 cookies 但故意改坏 → 任务卡显示"重新登录"红色徽章
- 抖音抓取正常时 → 完成度 ≥ 评论抓取（基线对比）
- 快手抓取：XHR 失败自动降到 5a，至少能抓出搜索页可见的视频 URL

---

## 5. 模块 4：百家号验证码无提示 + 结果偏差

### 前置事实

代码侧没有"baijiahao"专属 scraper。百家号被访问的场景：百度排名抓取里命中百家号文章 SERP 卡位后，跟进点开 `baijiahao.baidu.com` 文章页确认品牌词命中——这一步触发风控。当前仅 `is_baidu_captcha_url()` URL 子串检测，太薄，命中不到 DOM/页面文案/HTTP 状态等其他风控信号，被当作"正常空文章"继续抓，导致结果偏差。

### 修复（3 个方向叠加，PR 2）

#### 一、四层风控信号检测（必做）

新建 `csm_core/monitor/drivers/risk_detector.py`，提供 `detect_risk(page, response) -> RiskSignal | None`：

1. **URL 模式扩展** — `_BAIDU_CAPTCHA_DOMAINS` 加：
   - `passport.baidu.com`
   - `baijiahao.baidu.com/safetycheck`
   - `mbd.baidu.com/safe`
   - `*.baidu.com/captcha`

2. **DOM 元素检测** — 命中即风控：
   - 通用：`#captcha-mask` / `.passmod` / `[id^="wappass"]` / `.security-check`
   - 百家号特有：`.mod-error` / `.error-page`

3. **页面文案匹配** — `page.content()` 后正则：`/(验证码|请完成验证|安全验证|网络异常|系统繁忙)/`

4. **HTTP 状态与响应头** — `response.status ∈ {403, 451, 503}` 或 `set-cookie` 含 `BAIDUID_BFESS=deleted`（cookie 被废）

**命中后行为**：
- adapter 抛 `RiskControlException(signal=...)`，runner 捕获后任务标 `risk_control` 暂停
- SSE 事件 `{type: "risk_control", platform, task_id, signal, message, progress}` 推前端
- 前端 toast + 任务卡标红 + 任务详情顶部 banner 提示
- **已抓的结果保留不丢**；monitor_results 记录 `last_resumed_keyword`，用户点"重试"时从该断点续抓（断点续抓需求已确认）

#### 二、浏览器指纹伪装（搭模块 3 第 4 层做）

mining 接入 patchright_pool 后，百家号会继承 pool 的 stealth 配置。pool 侧统一注入 init_script：
```js
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
```
屏蔽 `window.cdc_*` 等 ChromeDriver 残留变量；viewport 随机化；Accept-Language 与 cookies 区域一致。

#### 三、IP 代理池（用户自备代理）

新增 `<config_dir>/proxies.json`：
```json
{
  "enabled": true,
  "rotation_strategy": "on_risk_control",
  "proxies": [
    {"server": "http://user:pass@1.2.3.4:8080", "tags": ["cn", "residential"]},
    {"server": "http://user:pass@5.6.7.8:8080", "tags": ["cn"]}
  ]
}
```

- `patchright_pool.launched_context()` 启动时按 `rotation_strategy` 取一个 proxy
- 策略 `on_risk_control`（默认推荐）：命中风控后下一次启动换 proxy；正常情况复用上次
- 备选策略：`per_request` / `per_task` / `daily`
- **代理由用户自备**（不内置）—— 配置入口「设置 → 风控与代理」（已确认入口位置）
- 失效自动剔除：连续 3 次握手失败 → `tags` 加 `disabled` 跳过

### 验证

- 命中验证码：任务卡变红、详情页 banner 出现、SSE 事件能在浏览器 devtools network 看到
- 断点续抓：跑到第 50/93 命中风控 → 点重试 → 从第 51 开始；前 50 个的结果不丢
- 启用代理池后：命中风控自动换 IP 重试一次，仍失败才暂停任务

---

## 6. PR 拆分

### PR 1（前端 only，约 80 行改动）

- 模块 1：`BatchImportTaskModal.vue` close 修复 + `MonitorView.vue` `@imported` handler 重构（抽 `currentTaskType` computed）
- 模块 2：`BaiduRankingPage.vue` 合并渲染源 `keywordRows`

### PR 2（前后端，约 600 行改动）

- 模块 3：第 1 层（预检 + 错误透传）+ 第 2+4 层合并（共享 patchright_pool + pool 侧 stealth 加固）+ 第 5a 层（DOM 降级）
- 模块 4：`risk_detector.py` + SSE 风控事件 + 断点续抓 + 代理池配置

### Backlog（不在本次范围）

- 模块 3 第 5b 层：可视点击降级模式
- 自动化用户引导（cookies 过期自动跳登录流程）

---

## 7. 改动文件清单（参考）

### 前端

- `frontend/src/components/monitor/BatchImportTaskModal.vue`（模块 1a）
- `frontend/src/views/MonitorView.vue`（模块 1b：抽 `currentTaskType` computed）
- `frontend/src/components/monitor/history/BaiduRankingPage.vue`（模块 2）
- `frontend/src/components/mining/StartJobModal.vue`（模块 3 预检）
- `frontend/src/views/MiningView.vue`（模块 3 任务卡状态徽章）
- `frontend/src/views/SettingsView.vue` 或新增「风控与代理」面板（模块 4 代理池入口）

### 后端

- `csm_core/browser_infra/mining_browser.py`（模块 3 第 4 层：改造成 pool 适配层，保留 cookie 注入和进程清理工具）
- `csm_core/browser_infra/patchright_pool.py`（模块 3 第 2/4 层：init_script、proxy 注入）
- `csm_core/browser_infra/ua_pool.py`（已存在，扩展使用面）
- `csm_core/mining/runner.py`（模块 3 SearchOutcome status 字段）
- `csm_core/mining/platforms/douyin_search.py` / `kuaishou_search.py`（模块 3 第 5a 层 DOM fallback）
- `csm_core/monitor/drivers/risk_detector.py`（**新增**，模块 4 一）
- `csm_core/monitor/drivers/incognito_session.py`（模块 4 一：URL 模式扩展或迁出）
- `csm_core/monitor/platforms/baidu_keyword.py`（模块 4 一：调用 risk_detector + 断点续抓字段）
- `csm_core/monitor/storage.py`（模块 4 一：`last_resumed_keyword` 字段）
- `csm_core/config.py`（模块 4 三：proxies.json 加载）
- `sidecar/csm_sidecar/routes/mining.py`（模块 3 第 1 层 `/api/mining/credentials`）
- `sidecar/csm_sidecar/services/monitor_service.py`（模块 4 一 SSE 事件）

---

## 8. 不在本次范围

- 真实"百家号 scraper"（用户没要求独立的百家号抓取器）
- 浏览器指纹机器学习级别的对抗（成本远高于收益）
- 代理服务集成（用户自备，不做付费代理对接）
- 模块 3 第 5b 层可视点击降级（进 backlog）
