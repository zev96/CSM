# MediaCrawler 参考下的三平台关键词抓取修复方案

## Context

CSM 当前 `csm_core/mining/` 下三个平台的关键词→视频链接抓取存在两个真实 bug + 一个未验证风险:

1. **抖音**:能登录、能进搜索页,但搜索结果的视频链接抽不出来;且页面弹滑块/图形验证码后程序无感知
2. **快手**:打开搜索页直接显示"请登录",cookie 注入语义错误 + Patchright SPA 指纹双重导致
3. **B 站**:架构与上面共用同一套抓取框架,尚未真机验证

抓取契约下游对接 ranking + Excel 导出(`csm_core/mining/storage.py`),不能动数据形状。本次只动 `csm_core/mining/platforms/` 和 `csm_core/browser_infra/mining_browser.py`,**所有 monitor 侧、Baidu/Zhihu/Excel 输出层全部保持不动**。

参考开源工具:[NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)。它只用来"读架构 + vendoring 纯算法代码",不引入运行时依赖。

---

## 1. 根因诊断(代码现状 vs MediaCrawler 做法)

### 1.1 抖音 — `csm_core/mining/platforms/douyin_search.py`

**架构入口契约(必须保留)**
- 入口 `DouyinSearchAdapter.search()` 在 `douyin_search.py:32-102`
- 协议定义 `SearchAdapter` 在 `csm_core/mining/platforms/_common.py:27-38`
- 输出 DTO `VideoCard` 在 `csm_core/mining/models.py:29-44`,`SearchOutcome` 在 `models.py:57-61`
- 调用方 `MiningRunner.run()` 在 `csm_core/mining/runner.py:81-135`(adapter.search 调用点 117-123)
- 落地存储 `mining_storage.upsert_video_and_link(card, job_id)` 在 `csm_core/mining/storage.py:277-333`

**抓取策略现状**:`page.goto(search_url) → page.on("response", _on_response) → scroll 30 次 × 2s` 拦截 `/aweme/v1/web/general/search/single` 的 XHR 响应(`douyin_search.py:55-79`)。

**Bug 1: 链接抽不出 — 三个并发原因**

| # | 故障点 | CSM 现状 | MediaCrawler 做法 |
|---|---|---|---|
| a | XHR 时序竞态 | `page.goto(wait_until="domcontentloaded")` 后立刻进 scroll 循环,首个 XHR 可能还没发出 | `core.py:169-217` 用专门的 `dy_client.search_info_by_keyword(offset, ...)` 主动调 API,不依赖页面自发请求 |
| b | 响应结构狭窄 | `douyin_search.py:108` 只解析 `item.get("aweme_info")`,如果是混排视频(`aweme_mix_info.mix_items[0]`)直接跳过 | `core.py:200-209` 同时解析两种结构:`post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0]` |
| c | Cookie SameSite 错误 | `csm_core/browser_infra/mining_browser.py:244` 把所有平台 cookie 写成 `SameSite=None`,同源 XHR 在某些 Chromium 版本下被丢 | 同源场景应该用 `Lax`(参照 `csm_core/browser_infra/patchright_pool.py:414`,monitor 侧从 day 1 就是 Lax) |

**Bug 2: 验证码无处理**
- 现有检测 `_is_captcha_or_login()` 在 `douyin_search.py:147-156`,只看 URL 包不包含 `captcha`/`verify`/`passport/`,**对 SPA 弹出的滑块/图形 modal 完全无感知**(URL 不变)
- 项目里 `csm_core/monitor/drivers/risk_detector.py:46-118` 早就有完整的 4 层检测(URL + DOM 选择器 + 页面文案 + HTTP 状态码),但 mining 层完全没复用

### 1.2 快手 — `csm_core/mining/platforms/kuaishou_search.py`

**抓取策略现状**:`page.goto("https://www.kuaishou.com/search/video?searchKey=...") → page.evaluate(_EXTRACT_JS)` 抓 DOM 上的 `a[href*="/short-video/"]`(`kuaishou_search.py:48-49, 77, 228-289`)。

**头部注释(`kuaishou_search.py:42-47`)写得很诚实**:
```
# KNOWN ISSUE (defer to follow-up spec): kuaishou's SPA
# fingerprints patchright Chromium and renders search results
# as a "请登录" wall even when monitor.db cookies are injected.
# Comment API (what monitor uses) works fine; search page does not.
```

**双重根因**:
1. **Cookie 注入 `SameSite=None` 语义错** — `mining_browser.py:244` 跟抖音同一行 bug。同源请求时 `SameSite=None` 在 Chromium 强 enforce 模式下被丢
2. **SPA 指纹检测** — 即使 cookie 正确,快手搜索 SPA 仍能识别 Patchright Chromium 是自动化环境,渲染 "请登录" 兜底页

**MediaCrawler 的解法(`media_platform/kuaishou/client.py:66, 200-209`)**:**完全绕开 SPA**。Playwright 只负责建立登录态(往 BrowserContext 里塞 cookie),然后用 `utils.convert_browser_context_cookies(browser_context)`(`client.py:142-145`)把 cookie 抽出来,httpx POST 到 `https://www.kuaishou.com/graphql`:
```python
post_data = {
    "operationName": "visionSearchPhoto",
    "variables": {"keyword": keyword, "pcursor": pcursor,
                  "page": "search", "searchSessionId": search_session_id},
    "query": self.graphql.get("search_query"),
}
```

GraphQL 端点跟 SPA 共享同一套 session cookie,但不走 React 渲染、不被 SPA 指纹检测拦截。

### 1.3 B 站 — `csm_core/mining/platforms/bilibili_search.py`

**抓取策略现状**:`page.goto("https://search.bilibili.com/all?keyword=...") → page.evaluate(_EXTRACT_JS)` 抓 SSR HTML 的 DOM(`bilibili_search.py:53-69, 162-227`)。

**架构合理但未验证**:
- B 站搜索页是 SSR(server-side rendered),首屏 HTML 直出,DOM 抓取理论可行
- 但分页超过几页后会出现 wbi 签名校验或反爬节流
- MediaCrawler 走签名 API 路径(`bilibili/client.py:193-218` 的 `search_video_by_keyword`),签名实现在 `bilibili/client.py:119-135` 的 `pre_request_data` + `bilibili/help.py` 的 `BilibiliSign` 类
- 此外 `bilibili_search.py:109-137` 还遗留了一份从 wbi API 响应解析 cards 的 `_extract_cards` 死代码,可直接复用

**风险**:本次跑通验证之前不知道现有 DOM 抓取是否还有效,如果失效就需要切到 WBI 签名 API。

---

## 2. 修复方案(分阶段,每阶段一个 commit + 一次确认)

### 阶段 0 — 准备(read-only / 目录就位)

- 在仓库根 `git clone --depth=1 https://github.com/NanmiCoder/MediaCrawler.git reference/MediaCrawler`,**不当依赖**,只读
- `reference/` 整体写入 `.gitignore`
- 新建 `.auth/`(后续浏览器 profile 落这里),写入 `.gitignore`
- 新建 vendoring 目录 `csm_core/mining/platforms/_vendor/`:
  - `_vendor/__init__.py`
  - `_vendor/README.md` 写明 vendor 来源 + commit hash + NCL 1.1 attribution(MediaCrawler 实际许可证为 NON-COMMERCIAL LEARNING LICENSE 1.1,**仅限非商业学习用途**,CSM 用作个人/团队内部学习工具时合规)
  - `_vendor/mc_bilibili_sign.py` — 移植 MediaCrawler `media_platform/bilibili/help.py` 的 `BilibiliSign` 类(WBI 签名,约 80–100 行纯 Python)
  - `_vendor/mc_kuaishou_search.graphql` — 拷贝 MediaCrawler `media_platform/kuaishou/graphql/search_query.graphql` 完整字符串

### 阶段 1 — 共享层(影响三平台,低风险)

**改 profile 路径调用点 `sidecar/csm_sidecar/lifespan.py:102`**:把 `core_config.default_config_dir() / "browser_profiles"` 改为 `core_config.default_config_dir() / ".auth" / "browser_profiles"`(老 profile 不自动迁移,因为真正的登录态在 `monitor.db.platform_credentials`,profile 只是 Chromium 状态,首次启动会重建)。

**改 `csm_core/browser_infra/mining_browser.py:244`**:`"sameSite": "None"` → `"sameSite": "Lax"`(对齐 `patchright_pool.py:414`)。

**新增 helper 文件 `csm_core/mining/platforms/_http.py`**(约 50 行):
```python
def cookies_from_context(context, urls: list[str]) -> tuple[str, dict[str, str]]:
    """对齐 MediaCrawler utils.convert_browser_context_cookies。
    从 Playwright BrowserContext 抽取访问指定 URL 时浏览器会发的 cookie,
    返回 'k=v; k=v' 字符串 + 字典两种形式,给 httpx 直接用。"""

def build_httpx_client(*, cookies_str: str, user_agent: str, referer: str) -> httpx.Client:
    """带超时/重试/UA/Referer 的 httpx 同步客户端。"""
```

**新增 `csm_core/mining/platforms/_risk.py`**(约 30 行)——把 `csm_core/monitor/drivers/risk_detector.detect_risk(page, response)` 包装一层适配 mining 层的接口,避免 mining 直接 import monitor.drivers(单向依赖卫生)。

**改三个平台 adapter 入口**,在 search() 顶部加:
```python
from csm_core.browser_infra import rate_limit
pacer = rate_limit.get_pacer(self.platform)  # 已有的全局单例,默认 5–15s 抖动
breaker = rate_limit.get_breaker(self.platform)  # 已有,默认 5 次失败 / 1h 窗口 / 30 min 冷却
```
循环里每次外发请求(scroll / GraphQL POST / wbi GET)前 `pacer.wait()`,失败累计走 `breaker.record_failure()` / 成功走 `record_success()`。

### 阶段 2 — 抖音修复(`douyin_search.py`,最小范围)

只改 3 个点,不重写模块:

1. **第 108 行附近的 `_extract_cards`**:扩展为 `aweme_info` 与 `aweme_mix_info.mix_items[0]` 二选一(借鉴 MediaCrawler `douyin/core.py:200-209`)

2. **第 81-83 行**:scroll 循环开始前先 `page.wait_for_response(lambda r: "/aweme/v1/web/general/search/single" in r.url, timeout=15_000)`,首个 XHR 不到就退化为风控

3. **第 147-156 行的 `_is_captcha_or_login`** 整体替换为调用 `_risk.detect(page)`(4 层检测)。检测到风控:静默上报 `SearchOutcome.status="risk_control"`,记日志退出。**不弹窗、不重试**

### 阶段 3 — 快手切 GraphQL(`kuaishou_search.py`,核心重写但保留契约)

`kuaishou_search.py` 的 `search()` 方法实现替换,但**入口签名、回调、`SearchOutcome` 返回完全不变**。

**新流程**:
1. `has_login_cookie` 守卫不变
2. `mining_browser.launched_page("kuaishou")` 打开 Patchright 页面,`page.goto("https://www.kuaishou.com")` 触发 cookie 落盘
3. `_risk.detect(page)` 检测风控,命中就 `risk_control` 退出
4. `cookies_from_context(page.context, urls=[...])` 抽出 cookie
5. `build_httpx_client(cookies_str, ua, referer)` 建 httpx 客户端
6. 加载 `_vendor/mc_kuaishou_search.graphql` 模板
7. 循环 POST `https://www.kuaishou.com/graphql`,operationName=`visionSearchPhoto`,variables={keyword, pcursor, page="search", searchSessionId},每次 `pacer.wait()`
8. 解析 `response.data.visionSearchPhoto.feeds` → emit VideoCard
9. `pcursor=="no_more"` 或 达到 target_count 退出

**完全废弃**:`_EXTRACT_JS`(228-289)、`_extract_from_dom`、`_extract_via_bs4`(129-194,本来就是 dead code)。

### 阶段 4 — B 站健全性检查(`bilibili_search.py`)

**优先路径**:先用现有 DOM 抓取跑一次端到端测试,关键词 "测试" + target_count=5。

- ✅ 能拿到 ≥3 张卡片且 BVID 都合法 → 这一阶段就结束,不改代码,只补齐阶段 1 的 pacer/risk_detector 接入即可
- ❌ DOM 抓不出或被风控页拦截 → 切到 WBI 签名 API:
  - 复用 `_vendor.mc_bilibili_sign.BilibiliSign`(WBI 签名)
  - 先 `GET https://api.bilibili.com/x/web-interface/nav` 拿 `img_url` + `sub_url` 提取 `img_key` / `sub_key`(借鉴 MediaCrawler `bilibili/client.py:137-161`)
  - `GET https://api.bilibili.com/x/web-interface/wbi/search/type?search_type=video&keyword=...&[signed]`(借鉴 `bilibili/client.py:193-218`)
  - 解析 `response.data.result` 中 `result_type=="video"` 的条目 → emit VideoCard(直接复用现有 `_extract_cards`,line 109-137,本来就是为这个 API 响应写的)

### 阶段 5 — 验证

每个阶段交付后,跑以下检查清单:

- **单元/集成测试**:`pytest tests/mining/ -v`(如已有则补;如无,至少加 3 个 smoke test:每平台一个,target_count=5,期望 status="done" 且 cards_emitted ≥ 3)
- **手测脚本**:`python -m csm_core.mining.runner --keyword 测试 --platform douyin --target 5`(走 CLI 入口或临时 driver)
- **日志检查**:日志里能看到 `RequestPacer.wait` 间隔、风控检测命中分支、cookie 抽取成功条数
- **回归保护**:跑现有 monitor 侧的 baidu/zhihu/douyin_comment/kuaishou_comment/bilibili_comment 任意一条任务,确认没受影响

---

## 3. 新增依赖

| 依赖 | 用途 | 安装命令 |
|---|---|---|
| `httpx` | Kuaishou GraphQL POST、Bilibili WBI API GET | 已有(grep 命中 `pyproject.toml`、`csm_core/llm/providers/openai_compat.py`、`csm_core/updater_client/*`、`csm_core/monitor/base.py` 等多处) |

**不需要新增浏览器**。Patchright Chromium 已经在用,不升级版本。

---

## 4. 风险与限制

| 项 | 风险 | 缓解 |
|---|---|---|
| 抖音验证码触发频率 | 每会话连续 ≥5 个关键词后触发概率显著上升 | 单次 `MiningRunner` 跑 ≤3 个关键词;阶段 1 的 `CircuitBreaker` 设置 douyin 每天 50 次请求上限可配 |
| 快手 cookie 有效期 | 实测 7–14 天,GraphQL 端点对 cookie 校验严格,过期立刻返 `data.visionSearchPhoto = null` | 阶段 3 在 GraphQL 响应里加 null 检测,返回 `needs_login` 让用户重登;cookie 一次有效期一周以上够批量场景 |
| B 站 WBI keys 过期 | `img_key/sub_key` 24h 滚动 | 阶段 4 切签名 API 时把 key 缓存在内存,失败一次就触发重新 `GET /nav` |
| 三平台请求间隔 | 5–15s 随机(`RequestPacer` 默认)对单关键词分页够用 | 阶段 1 已经接入,不需要额外动作 |
| GraphQL 端点结构变更 | 快手 GraphQL schema 变了会立刻失败 | 阶段 5 的 smoke test 当作金丝雀;每月检查 MediaCrawler upstream commit |
| Vendor 代码同步 | 上游改 WBI 算法或 GraphQL 模板 | `_vendor/README.md` 记录 commit hash;每 3–6 个月手动 diff 一次上游 |

---

## 5. 不要做的事(明确边界)

| 不做 | 原因 |
|---|---|
| 不引入 MediaCrawler 的数据库层(MySQL/sqlite_store) | 你已有 `csm_core/mining/storage.py` + monitor 共用 SQLite |
| 不引入 MediaCrawler 的 CLI 框架(`main.py` / `cmd_args`) | 你已有 `csm_core/mining/runner.py` 入口 |
| 不动 `csm_core/mining/storage.py`(尤其 `upsert_video_and_link:277-333`) | 排名 + Excel 导出基于这层 |
| 不动 `csm_core/mining/runner.py` 的 dispatch 逻辑(81-135) | 三平台 adapter Protocol 已经统一,改 adapter 内部不影响 |
| 不动 `csm_core/monitor/platforms/baidu_keyword.py` / `zhihu_question.py` / `*_comment.py` | 监控侧独立,只读复用 `risk_detector.py` |
| 不重写整个平台模块 | 抖音/B 站只改 3 处;快手 search() 内部重写但签名/回调/契约不动 |
| 不升级 Patchright 或 Playwright 版本 | 跟当前 release 打包脚本耦合,见 CLAUDE memory 关于 PyInstaller 的坑 |

---

## 6. 实施约束(用户最初约定 + 本次细化)

- 保留项目骨架,只动 `csm_core/mining/platforms/*` 和 `csm_core/browser_infra/mining_browser.py`(1 行 SameSite)+ `sidecar/csm_sidecar/lifespan.py`(1 行 profile path)
- 登录态文件统一放在 `.auth/`(浏览器 profile);`.auth/`、`reference/` 都进 `.gitignore`
- 每个平台 adapter 的入口签名(keyword/target_count/on_card/on_progress/cancel_event → SearchOutcome)绝对不动
- `VideoCard` 字段不动,新增的 Kuaishou GraphQL 路径必须填齐 `rank_in_search`、`platform_video_id`、`url`、`title`、`author_name/id`、`cover_url`、`duration_sec`、`play_count`、`like_count`、`published_at`、`raw`
- 5–15s 随机延迟 + 单日上限通过 `csm_core/browser_infra/rate_limit.RequestPacer` + `CircuitBreaker` 实现(已存在,只接线不重写)
- 验证码命中:静默上报 `risk_control`,不弹窗、不重试

---

## 7. 关键文件清单(批准后会动这些,其它都不动)

**修改(共 5 个文件,改动量小)**
- `sidecar/csm_sidecar/lifespan.py`(1 行:profile 路径加 `.auth/` 前缀)
- `csm_core/browser_infra/mining_browser.py`(1 行:SameSite)
- `csm_core/mining/platforms/douyin_search.py`(3 处:`_extract_cards` 加 fallback + `wait_for_response` + 替换 `_is_captcha_or_login`)
- `csm_core/mining/platforms/kuaishou_search.py`(search() 主体重写,头部/契约不动)
- `csm_core/mining/platforms/bilibili_search.py`(阶段 4 视测试结果决定;阶段 1 接 pacer/risk)

**新增**
- `csm_core/mining/platforms/_http.py`(cookies_from_context + build_httpx_client,~50 行)
- `csm_core/mining/platforms/_risk.py`(包装 monitor risk_detector,~30 行)
- `csm_core/mining/platforms/_vendor/__init__.py`
- `csm_core/mining/platforms/_vendor/README.md`(vendor attribution)
- `csm_core/mining/platforms/_vendor/mc_bilibili_sign.py`(WBI 签名移植)
- `csm_core/mining/platforms/_vendor/mc_kuaishou_search.graphql`(GraphQL 模板)
- `.auth/.gitkeep`(占位)
- `.gitignore` 追加 `.auth/` 和 `reference/`

**克隆(read-only,不入仓库)**
- `reference/MediaCrawler`(git ignore)
