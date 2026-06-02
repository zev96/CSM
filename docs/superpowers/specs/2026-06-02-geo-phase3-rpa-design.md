# GEO 阶段 3：RPA 采集（DeepSeek / Kimi / 腾讯元宝）设计

> **状态**：设计已获用户口头批准（brainstorming 产出）。下一步 → writing-plans 出逐任务 TDD 实施计划。
> **基线**：origin/main `d34786c`（阶段 1 + 阶段 2 已合并，PR #78）。本设计从该提交切 `claude/geo-phase3`。
> **承接**：`docs/superpowers/specs/2026-05-30-ai-geo-monitoring-design.md` §13「阶段 3」。

---

## 1. 目标与范围

为 AI 卡位监控新增 **RPA（无头/有头真浏览器）采集** 通道，覆盖 **三家** API 拿不到联网信源的平台：

| 平台 | value | 登录方式 | 备注 |
|---|---|---|---|
| DeepSeek | `deepseek` | 账号/短信 | 试点（最先打通，作为基座验证场） |
| Kimi | `kimi` | 手机号 | 阶段 2 因 API 不回信源被移出 `GEO_PLATFORMS`，本阶段以 RPA 身份**重新加回** |
| 腾讯元宝 | `yuanbao` | QQ/微信扫码 | 会话过期需重扫码 |

**夸克AI 不在本阶段**（用户决定移除）。

**核心约束 —— 只新增「产出 `GeoAnswer` 的 RPA provider」**，`GeoAnswer` 之后的一切（LLM 抽取 `extract` → 信源分类 → `GeoCell` → `metrics` → `alerts` → `storage` → SSE → 前端卡位矩阵/趋势/下钻/平台对比/信源榜/引流闭环）**全部复用、零改动**。不新增 `TaskType`，不重做 UI。

本阶段交付物清单：
1. RPA 共享基座：浏览器会话层 `_session` + 交互原语 `_flow`。
2. 三个 per-site provider：`deepseek` / `kimi` / `yuanbao`。
3. `get_provider` 注册 3 个分支 + PyInstaller spec hiddenimports。
4. 登录管线：后端「开登录窗 + 查登录态」路由 + 前端设置页「RPA 登录」分组。
5. 平台选择器加这 3 家（带「需登录」提示）。
6. adapter 把 `cancel_token` 透传给 `provider.query`（让长耗时 RPA 的 Stop 生效）。
7. geo RPA 任务串行化（`concurrency=1`）。
8. CHANGELOG + 人工验收清单 + 原生测试窗（供用户真站实测后再 PR）。

---

## 2. 背景：为什么是 RPA（API 边界回顾）

阶段 2 实测确认（见 `feedback_csm_geo_phase2_platforms.md`）：

- **通义千问 + 豆包**：API 联网后老实回信源（`search_results` / `references`）→ 已走 API（阶段 1/2）。
- **Kimi（Moonshot）**：`$web_search` 确实联网（回 `search_id`、写 1797 字答案），但 `annotations` **永远为 0**，不吐信源 URL → API 拿不到信源。
- **DeepSeek / 腾讯元宝 / 夸克**：无可用「联网且回信源」的公开 API。

这些平台的**联网回答 + 来源链接只在网页端渲染**。要采集，只能驱动真浏览器开网页、开联网开关、抓 DOM。这就是阶段 3。

---

## 3. 采集机制决策

**结论：采用 A（DOM 交互）作为统一机制。** B 作为将来个别站 DOM 实在不稳时的逃生口，**不预先建**（YAGNI）。

| | **A · DOM 交互（采用）** | B · 站内 fetch 内部 API | C · 混合 |
|---|---|---|---|
| 做法 | 登录态持久档 → 打字 → 开联网开关 → 发送 → 等流式结束 → 从 DOM 抓回答 + 引用链接 | 在登录页内 `page.evaluate(fetch('/api/chat…'))` 调站点后端解析 JSON | DOM 为主，个别站有稳定 JSON 端点则用 fetch |
| 优点 | 抓的就是用户看到的回答+来源；不依赖未公开/加签私有 API；对后端改参稳健 | 结构化 JSON、抗布局改版、更快 | 每站取最稳路径 |
| 缺点 | 对 DOM 改版脆弱、需逐站选择器、要判「流式结束」、较慢 | 3 家私有端点未公开、常带加签参数、改版即挂、SSE 难用 fetch 消费 | 两条路径都要维护 |

**选 A 的理由**：交付物本就是「AI 展示给用户的回答 + 来源」，DOM 抓得最准；逆向 3 家加签私有 API 是最易静默崩、最耗时的路；项目对 baidu/zhihu 已接受有头浏览器这种脆弱性，机制一致。脆弱性用「逐站选择器集中为模块常量 + raw 落日志」来抵消可维护性损失。

---

## 4. 架构与模块

### 4.1 provider 契约（复用，零改动）

`csm_core/monitor/geo/providers/base.py` 已定义且**已为 RPA 预留**：

```python
@runtime_checkable
class GeoProvider(Protocol):
    platform: str
    mode: str  # "api" | "rpa"
    def query(self, keyword: str, *, web_search: bool,
              cancel_token: "threading.Event | None" = None) -> GeoAnswer: ...
```

`GeoAnswer`（`geo/models.py`）：`platform, keyword, answer_text, citations: list[Citation{url,title}], raw: dict, status: "ok"|"empty"|"blocked"|"error", error: str`。

RPA provider 只需产出一个填好 `answer_text` + `citations` 的 `GeoAnswer`，`status` 用既有值域。**这是 RPA 与下游的唯一接口边界。**

### 4.2 RPA 会话层 `geo/providers/rpa/_session.py`（新建）

```python
@contextmanager
def rpa_page(platform: str, *, headless: bool = False) -> Iterator[Any]:
    """打开 browser_profiles/geo_<platform>/ 持久档（登录跨次存活），yield 一个 page。"""
```

**决策：写 geo 专属会话层，不直接复用 `mining_browser.launched_page`。** 理由：`launched_page` 耦合 mining 的 `platform_credentials` 表 / cookie 注入（`has_login_cookie`），而 geo 走「持久档自带登录态」而非「cookie 注入」，语义不同；且 geo profile 命名空间 `geo_<platform>` 要与 mining/baidu 隔离（避免抢 profile 锁、避免登录态串台）。

会话层**照抄已验证的启动套路**（来自 `mining_browser.launched_page` / `baidu_browser.baidu_browser_session`）：`ensure_browsers_path()` → `launch_persistent_context(user_data_dir=browser_profiles/geo_<platform>, headless=…, args=["--no-sandbox","--disable-dev-shm-usage","--window-size=1000,700"], viewport={1000,700})`（最小 stealth args —— patchright 已在二进制层打补丁，多加 flag 反而是指纹 tell）→ `finally: context.close(); pw.stop()` → 缓存 prune（`chrome_detect.prune_profile_caches`，对齐 PR#77 防 profile 膨胀）。

### 4.3 交互原语 `geo/providers/rpa/_flow.py`（新建）

逐站选择器作**参数**传入，原语本身站点无关：

```python
def submit_query(page, *, composer_sel, send_sel, text) -> None
def ensure_web_toggle(page, *, toggle_sel, want_on=True) -> None
def wait_stream_done(page, *, done_predicate, idle_ms, timeout_s, cancel_token) -> None
    # 轮询：done_predicate 为真（发送键复位 / 「停止生成」消失→「重新生成」出现）
    # 或 DOM 静默 idle_ms；每轮 poll 间检查 cancel_token（抛 CancelledError）；超 timeout_s 抛 TimeoutError
def scrape_answer(page, *, answer_sel) -> str            # page.inner_html(sel) → parse_answer_html
def scrape_citations(page, *, cite_sel) -> list[Citation] # page.inner_html(sel) → parse_citations_html
def detect_login(page, *, logged_in_sel, login_sel) -> bool
```

**测试性关键决策 —— DOM 读取拆成纯函数 + 薄 page 包装**（对齐 api_* 的 `parse_*_response(raw)` 与 HTTP 调用分离）：

- 纯函数（吃 HTML 字符串，CI 可测）：`parse_answer_html(html) -> str`、`parse_citations_html(html) -> list[Citation]`、`is_logged_in_html(html) -> bool`。
- page 包装：`scrape_answer`/`scrape_citations`/`detect_login` 用 `page.inner_html(sel)` / `page.content()` 取 HTML 再调纯函数。

单测喂**保存的 HTML fixture** 给纯函数断言抽取结果；page 包装不进 CI。

### 4.4 per-site providers（新建 3 个）

`geo/providers/rpa/{deepseek,kimi,yuanbao}.py`，每个：

```python
class DeepSeekProvider:
    platform = "deepseek"; mode = "rpa"
    URL = "https://chat.deepseek.com/"
    SEL = {composer, web_toggle, send, answer_container, citation_items, logged_in_marker, login_marker}
    def query(self, keyword, *, web_search=True, cancel_token=None) -> GeoAnswer:
        # with rpa_page("deepseek") as page:
        #   goto URL；detect_login → 未登录 return GeoAnswer(status="blocked", error="DeepSeek 未登录，请在设置中登录")
        #   web_search → ensure_web_toggle；submit_query；wait_stream_done(cancel_token=…)
        #   answer=scrape_answer；cites=scrape_citations
        #   return GeoAnswer(status="ok"/"empty", answer_text=answer, citations=cites, raw={...})
```

错误纪律对齐 `api_kimi`：超时 → `error`；检测到验证码/反爬墙 → `blocked`；空回答 → `empty`；任何异常被 provider 兜住转成 `error`（**绝不让异常冒泡崩 adapter** —— 虽然 adapter 也有 cell 级 try，但 provider 自己也要稳）。每站 query 开头 `logger.info("[geo-rpa][%s] kw=%s ...", platform, kw)`，结束记 `http/状态/answer_len/cite_n`（silent-failure 经验：一开始就有 raw 日志）。

每站模块另导出 3 个纯解析函数（供测试）：`parse_<site>_answer(html)`、`parse_<site>_citations(html)`、`<site>_is_logged_in(html)`。

### 4.5 注册 + 打包

- `base.get_provider`：加 `deepseek`/`yuanbao` 懒加载分支；`kimi` 分支**从 `api_kimi` 改指向 `rpa.kimi`**（API `KimiProvider` 对 GEO 无用——无信源——保留模块供其既有单测，但 `get_provider('kimi')` 不再走它）。
- `sidecar/csm-sidecar.spec`：hiddenimports 加
  `csm_core.monitor.geo.providers.rpa._session`、`._flow`、`.deepseek`、`.kimi`、`.yuanbao`
  （对齐豆包 hiddenimport 修法；dev 读源码测不出漏模块，只有 onefile bundle 撞 ImportError）。

### 4.6 登录管线

**后端**（`sidecar/csm_sidecar/routes/monitor.py`，镜像现有 `POST /api/monitor/baidu/launch-login-window` + `GET /api/monitor/baidu/login-status`）：

- `POST /api/monitor/geo/rpa/{platform}/launch-login-window`
  在 worker 线程跑同步浏览器代码：开 `rpa_page(platform, headless=False)` → goto 站点 → 轮询 `detect_login(page)` 直到登录成功或超时（如 180s）→ 关闭（持久档自动存 cookie）→ 返回 `{ok, logged_in}`。
- `GET /api/monitor/geo/rpa/{platform}/login-status`
  无头快查：开 `rpa_page(platform, headless=True)` → goto → `detect_login` → 返回 `{logged_in}`（短命，对齐 `baidu_login.get_login_status` 的无头省成本思路）。

登录态判定走 **DOM marker**（composer 存在 / 登录按钮不存在），不靠单一已知 cookie（AI 站 cookie 名不稳）。`{platform}` 用 `Literal["deepseek","kimi","yuanbao"]` 或路由层白名单校验，拒绝未知平台。

**前端**：
- `frontend/src/views/SettingsView.vue`：新增「AI 卡位 · RPA 登录」分组，DeepSeek/Kimi/元宝 各一行：状态徽章（调 `login-status`，已登录/未登录）+「登录」按钮（调 `launch-login-window`，期间禁用+转圈，返回后刷新状态）。
- 调用经 `useSidecar()`（带 token），不裸 `fetch`。

### 4.7 平台选择器

`frontend/src/utils/monitor-types.ts` `GEO_PLATFORMS` 加 3 项，并给条目加可选 `mode?: "api"|"rpa"` 用于 UI 提示：

```ts
export const GEO_PLATFORMS = [
  { value: "tongyi",   label: "通义千问", mode: "api" },
  { value: "doubao",   label: "豆包",     mode: "api" },
  { value: "deepseek", label: "DeepSeek", mode: "rpa" },
  { value: "kimi",     label: "Kimi",     mode: "rpa" },
  { value: "yuanbao",  label: "腾讯元宝", mode: "rpa" },
] as const;
```

新增任务平台多选里 `mode==="rpa"` 的项尾部显示「需登录」小字提示。未登录就选了 → 运行时该 cell 回 `blocked`，前端平台对比显示「采集失败/未登录」（既有 `_block` 区分逻辑）。**注意 Kimi 在此重新加回**（阶段 2 commit `11cf688` 曾移除）。

### 4.8 adapter 改动：透传 `cancel_token`

`csm_core/monitor/platforms/geo_query.py`：`_run_cell` 现签名无 `cancel_token`，`provider.query(keyword, web_search=…)` 没传。RPA 单次 30–120s，需让 Stop 及时生效：

- `_run_cell(..., cancel_token)` 新增形参，`fetch` 调用处把自己的 `cancel_token` 传进去。
- `provider.query(keyword, web_search=web_search, cancel_token=cancel_token)`。
- API provider（tongyi/doubao；Kimi 的 API 版不再用于 geo）应已接受该 kwarg、忽略即可 —— **回归检查**：确认现有 API provider `query` 签名都有 `cancel_token=None`（base Protocol 已要求；若缺则补上，否则透传会 TypeError）。

`wait_stream_done` 在轮询间检查 token，cancel 时抛 `CancelledError`，被 adapter 现有 cell 级 try 兜成 `error`。取消是用户主动 Stop 整个 run，不构成误报场景（`notify` 在 `status!=ok` 时不发告警，已核实），故无需为取消单列状态。

### 4.9 串行化

geo RPA 会开有头 Chrome。用 `rate_limit.configure_concurrency` 把 `geo_query` 配 `concurrency=1`（对齐 baidu 的 `configure_concurrency(baidu_keyword, 1)`），防两次 geo 运行抢同一 `geo_<platform>` profile / 同时弹多个窗。单任务内 cell 循环本就顺序执行；geo 用独立 `geo_<platform>` profile，与 baidu/mining 不冲突。geo 运行频率低（日/周），全任务串行可接受。

---

## 5. 数据流

```
scheduled run → geo_query.fetch → 逐 (kw, platform) cell：
  _run_cell → get_provider(platform)            # mode="rpa"
    → provider.query(kw, web_search, cancel_token)
        with rpa_page(platform):                # 持久档有头 Chrome
          detect_login → 未登录? → GeoAnswer(blocked)
          ensure_web_toggle → submit_query → wait_stream_done
          scrape_answer + scrape_citations → GeoAnswer(ok)
    → extract(answer)  → GeoCell                # ★ 既有，复用
  → metrics.aggregate → alerts → record_run     # ★ 既有，复用
  → MonitorResult → SSE → 前端                   # ★ 既有，复用
```

`blocked`/验证码 → `GeoCell.status="blocked"` → metrics 记「采集失败」非「未提及」；既有 `ok_total` 守卫保证 notify 不误报。

---

## 6. 错误处理与状态映射

| 情形 | provider 返回 | GeoCell | 下游表现 |
|---|---|---|---|
| 未登录 | `blocked` + 「<平台>未登录，请在设置中登录」 | `blocked` | 采集失败；引导用户去设置登录 |
| 验证码/反爬墙 | `blocked` | `blocked` | 采集失败（不崩、可见） |
| 流式超时 | `error`（带已抓到的部分文本入 raw） | `error` | 采集失败 |
| 空回答 | `empty` | `error`/`empty`（对齐既有值域） | 采集失败 |
| 取消 | 抛 → cell try 兜 | `error` | （计划阶段定是否单列，避免误报） |
| 正常 | `ok` | `ok` | 正常抽取入库 |

每 cell 隔离（adapter 既有 `try`）。raw 一律 `logger.info` 记关键计量，便于 silent-failure 定位。

---

## 7. 测试策略（TDD）

**CI 安全（无真网络、无真浏览器）：**
- 纯解析函数 × 保存 HTML fixture：`parse_<site>_answer` / `parse_<site>_citations` / `<site>_is_logged_in` 各站一组 fixture（正常回答带引用、无引用、未登录页）。
- `wait_stream_done` 用 **fake page**（脚本化 poll 序列：前 N 次未完成、之后完成 / 超时 / cancel）测三条路径。
- provider 错误路径用 **monkeypatch 假会话**：未登录→blocked、超时→error、验证码→blocked（对齐 `test_providers.py` 里 kimi/doubao 的假 client 套路）。
- fixtures 放 `tests/core/monitor/geo/fixtures/`（`deepseek_answer.html` 等），测试放 `tests/core/monitor/geo/test_rpa_<site>.py`。

**人工（不进 CI）：**
- 真登录 + 真站端到端：用户在**原生测试窗**（阶段 1/2 套路：worktree 重打 sidecar → `tauri dev --no-watch`）跑通：登录 → 建 geo 任务选 RPA 平台 → run-now → 看回答+信源入库、平台对比、信源榜。
- 计划阶段产出《人工验收清单》。

---

## 8. 风险与 UX 取舍（已与用户确认）

1. **机制 A（DOM 交互）** —— 已确认。脆弱性靠逐站选择器集中 + raw 日志缓解。
2. **运行时弹有头 Chrome 窗**（反爬需要），逐 cell 顺序弹、一次一个 —— 已接受（baidu/zhihu 现也如此）。可选缓解：窗口移屏外/最小化（计划阶段评估，不阻塞）。
3. **元宝登录=扫码**（QQ/微信），会话过期需重扫 —— 已接受。
4. **落地顺序**：地基→DeepSeek（打通+实测）→登录前端→cancel/串行→Kimi→元宝→CHANGELOG+原生窗 —— 已确认。
5. **ToS**：自动化这些站点可能违反其条款；与项目既有 baidu/zhihu/mining 爬取同等风险姿态；项目非商用（见 memory）。
6. **选择器漂移**：站点改版会使选择器失效；通过纯解析函数 + fixture 让回归可测、raw 日志让线上漂移可诊断。

---

## 9. 落地顺序（单计划内分阶段，先证地基）

1. **地基**：`_session.rpa_page` + `_flow`（原语 + 纯解析骨架）+ fake-page 测试。
2. **DeepSeek provider** + fixtures/测试 + `get_provider` 分支 + spec hiddenimport。（试点，最先打通）
3. **登录管线**：后端 2 路由 + 前端设置页分组 + `GEO_PLATFORMS` 加 deepseek。→ **此时 DeepSeek 可被用户真站实测**。
4. **adapter `cancel_token` 透传 + 串行化**。
5. **Kimi provider** + fixtures/测试 + 注册 + `GEO_PLATFORMS` 加回 kimi。
6. **腾讯元宝 provider** + fixtures/测试 + 注册 + `GEO_PLATFORMS` 加 yuanbao。
7. **CHANGELOG + 人工验收清单 + 原生测试窗**（供用户实测后再 PR）。

先把地基 + DeepSeek 打通并由用户实测，再把 Kimi/元宝 作为薄适配器复制 —— 即便一个计划里交付 3 家，也先证基座。

---

## 10. 范围外（Out of scope）

- **夸克AI**（用户移除）。
- **机制 B（站内 fetch 内部 API）** 的预建 —— 仅留作将来逃生口。
- 任何新分析 UI / 新 KPI —— 全复用阶段 1/2。
- 信源榜/告警/导出/引流闭环逻辑改动 —— 全复用。
- 阶段 4 及其它平台。

---

## 11. 复用清单（具体文件 / 签名）

| 用途 | 复用对象 | 位置 |
|---|---|---|
| provider 契约 / 注册 | `GeoProvider` Protocol、`get_provider` | `csm_core/monitor/geo/providers/base.py` |
| 输出模型 | `GeoAnswer` / `Citation` | `csm_core/monitor/geo/models.py` |
| 持久档启动套路 | `launched_page` / `_profile_dir_for` | `csm_core/browser_infra/mining_browser.py:57,46` |
| 有头会话 + 缓存 prune 范式 | `baidu_browser_session` | `csm_core/monitor/drivers/baidu_browser.py` |
| 登录窗 / 登录态范式 | `open_login_window` / `get_login_status` | `csm_core/monitor/drivers/baidu_login.py:209,107` |
| 登录路由范式 | `POST /api/monitor/baidu/launch-login-window`、`GET /api/monitor/baidu/login-status` | `sidecar/csm_sidecar/routes/monitor.py:575,407` |
| 缓存 prune | `prune_profile_caches` | `csm_core/monitor/drivers/chrome_detect.py` |
| 串行化 | `rate_limit.configure_concurrency` | `csm_core/browser_infra/rate_limit.py` |
| 抽取/分类/指标/告警/存储 | `extract` / `metrics` / `alerts` / `geo.storage` | `csm_core/monitor/geo/*` |
| adapter | `GeoQueryAdapter._run_cell` / `.fetch` | `csm_core/monitor/platforms/geo_query.py` |
| 平台常量 | `GEO_PLATFORMS` | `frontend/src/utils/monitor-types.ts` |
| 设置页 | `SettingsView.vue` | `frontend/src/views/SettingsView.vue` |
