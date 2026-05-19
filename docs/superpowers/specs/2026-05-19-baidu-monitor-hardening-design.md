# 百度监测 3 项加固 — Design

**日期**: 2026-05-19
**作者**: brainstorm session (CSM v0.4.x)
**范围**: 百度关键词监测的 3 个独立问题修复 + 反爬增强
**前置 spec**: [2026-05-15-baidu-keyword-monitor-design.md](2026-05-15-baidu-keyword-monitor-design.md)

---

## 1. 背景与问题

用户反馈 3 个独立但相关的问题：

1. **抓 10 个关键词就被百度风控拦截** — 主动伪装基本没有，被动节流+检测不够
2. **新建任务的「域名设置」希望复用应用设置里的域名名单** — UI 缺一个跳转/查看入口
3. **设置面板改完「默认排除域名」后，浏览器抓取仍然不过滤** — 配置改了不重启不生效

三者各自独立，但都围绕"百度任务抓取行为"这条主线，一并设计。

### 1.1 现状摸排

**反爬策略对比**（Bug 1 相关）：

| 反爬维度 | CSM 当前 | bilibili_comment 已做 | 高杠杆 |
|---|---|---|---|
| UA 轮换 | ❌ 硬写 `chrome120` | ✅ 3+ UA 池循环 | 🔴 高 |
| Cookie / Session 复用 | ❌ curl_cffi 每次无状态请求 | ✅ Session + CookieStore.pick | 🔴 高 |
| Header 完整伪装（Sec-Fetch-*） | 默认拼齐 | ✅ 完整集 | 🟡 中 |
| Proxy IP 池 | ❌ | ❌ | 🟡 中（复杂） |
| 命中后指数退避 | ❌（固定 600s 冷却） | ❌ | 🟢 低 |

**配置链路**（Bug 3 相关）：

- `SettingsView` → PATCH `/api/config` → `config_service.patch()` 写盘 + 改内存 ✅
- 但 `BAIDU_ADAPTER.apply_settings()` 只在 [monitor_lifecycle.py:59-71](../../sidecar/csm_sidecar/services/monitor_lifecycle.py) 启动时调一次
- `routes/config.py::patch_config` ([line 27-43](../../sidecar/csm_sidecar/routes/config.py)) 不触发任何 reconfigure
- 用户改设置必须重启 sidecar 才生效 → 用户感知为「我设了但没过滤」

**域名 UI 现状**（Bug 2 相关）：

- 应用设置只有 `monitor.baidu_keyword.default_excluded_domains` 一份「全局默认排除域名」list（textarea）
- 新建任务（`AddTaskModal`）只有 `baiduExcludeDomainsRaw` textarea + `baiduUseDefaultExcludes` 一个不透明 checkbox
- 后端 `_build_exclude_set` 逻辑上已经合并 global + task，但 UI 不暴露"全局名单当前内容"

---

## 2. 设计目标

| 编号 | 目标 | 验证 |
|---|---|---|
| G1 | 让百度监测「连续 10 个关键词」的风控率从约 60% 降到 20% 以内 | 实跑 + 风控触发次数计数 |
| G2 | 让用户在 AddTaskModal 一眼看到全局名单内容，并能一键跳到设置编辑 | UX 验收 |
| G3 | 让 `monitor.*` 字段在 Settings 改完立即生效，不需重启 sidecar | PATCH + 单测 |
| G4 | 不引入新依赖、不打破现有单测、不动现有数据库 schema | 跑全套 pytest |

---

## 3. 总览：3 节修法

| 顺序 | 范围 | 改动量 | 关键文件 |
|---|---|---|---|
| 第 1 节 | Bug 3 — Settings 热更新 | 后端约 80 行 + 单测 | `monitor_lifecycle.py` / `routes/config.py` |
| 第 2 节 | Bug 2 — AddTaskModal 复用名单 UX | 前端约 60 行 | `AddTaskModal.vue` / `SettingsView.vue`（加锚） |
| 第 3 节 | Bug 1 — UA 池 + Session 复用反爬 | 后端约 200 行 + 单测 | `baidu_keyword.py` |

依赖关系：3 节相互独立，可任意顺序实现。建议按表格顺序——简单的先落地，验证 reconfigure 链路通了之后再做反爬。

---

## 4. Section 1 — Bug 3: Settings 热更新

### 4.1 修法核心

从 `monitor_lifecycle.py` 抽出 `_apply_runtime_settings(cfg)` 函数，`start()` 与新增的 `reconfigure(cfg)` 共享。`PATCH /api/config` 检测到 `monitor` 字段变化后调用 `reconfigure`。

### 4.2 monitor_lifecycle.py 改动

新增 `_apply_runtime_settings` 私有函数（把现有 `start()` 里 line 47-71 的内容抽出来）：

```python
def _apply_runtime_settings(cfg: AppConfig) -> None:
    """Push runtime-mutable monitor settings into the live adapters.

    Called from start() (first time) and reconfigure() (every PATCH that
    touches monitor.*). NEVER raises — invalid config logs & old values
    stay in place, so PATCH /api/config still returns 200 with whatever
    the user wrote, and we don't surprise them with stale runtime state
    after a partial failure.
    """
    mcfg = cfg.monitor
    try:
        browser_driver.configure(mcfg.browser_engine, mcfg.chrome_path or "")
    except Exception as e:
        logger.exception("browser_driver.configure failed: %s", e)
    try:
        ZHIHU_ADAPTER.apply_settings(
            engine=mcfg.browser_engine,
            rotation_enabled=mcfg.multi_account_rotation,
            tasks_per_account=mcfg.tasks_per_account,
            cooldown_seconds=mcfg.cookie_cooldown_minutes * 60,
        )
    except Exception as e:
        logger.exception("ZHIHU_ADAPTER.apply_settings failed: %s", e)
    try:
        bcfg = mcfg.baidu_keyword
        BAIDU_ADAPTER.apply_settings(
            headless_default=bcfg.headless_default,
            captcha_visible_timeout_s=bcfg.captcha_visible_timeout_s,
            captcha_max_promotions=bcfg.captcha_max_promotions,
            serp_pacing_seconds=bcfg.serp_pacing_seconds,
            article_pacing_seconds=bcfg.article_pacing_seconds,
            baijiahao_pacing_seconds=bcfg.baijiahao_pacing_seconds,
            breaker_failures=bcfg.breaker_failures,
            breaker_cooldown_seconds=bcfg.breaker_cooldown_seconds,
            default_excluded_domains=bcfg.default_excluded_domains,
        )
    except Exception as e:
        logger.exception("BAIDU_ADAPTER.apply_settings failed: %s", e)
```

`start()` 内调用改为：

```python
def start(*, db_path: Path | None = None) -> MonitorLoop:
    ...
    cfg = config_service.load()
    _apply_runtime_settings(cfg)
    _loop = MonitorLoop(
        event_sink=monitor_bus.publish,
        alert_top_n=cfg.monitor.alert_top_n,
        cooldown_hours=cfg.monitor.alert_cooldown_hours,
    )
    _loop.start()
    return _loop
```

新增 `reconfigure()`：

```python
def reconfigure(cfg: AppConfig | None = None) -> None:
    """Re-push monitor settings into adapters without restarting the loop.

    No-op if start() hasn't been called yet (lifespan order ensures
    start() runs before HTTP routes accept requests, but defensive).
    """
    if _loop is None:
        return
    _apply_runtime_settings(cfg or config_service.load())
```

> **MonitorLoop 不重建的理由**：`alert_top_n` / `alert_cooldown_hours` 改了，用户期望是「下一次告警判定时生效」，不是「立刻重启 scheduler」。MonitorLoop 内部读这两项值时去 cfg 现读即可（这是个后续小改造，本 spec 范围内可不动——MonitorLoop 改设需要重启 sidecar 是可接受的，因为告警阈值不算高频修改项）。本 spec 只覆盖 adapter-level 配置热更新。

### 4.3 routes/config.py 改动

```python
@router.patch("/api/config", response_model=AppConfig)
async def patch_config(updates: dict[str, Any]) -> AppConfig:
    try:
        new_cfg = config_service.patch(updates)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    # Push monitor.* changes into live adapters so users don't need to
    # restart sidecar after editing default_excluded_domains, pacing,
    # breaker thresholds, etc. Idempotent + no-op if loop is down.
    if "monitor" in updates:
        from ..services import monitor_lifecycle
        monitor_lifecycle.reconfigure(new_cfg)
    return new_cfg
```

### 4.4 测试

`sidecar/tests/routes/test_config.py` 新增（或已有则增补）：

- `test_patch_monitor_reconfigures_adapter`：
  - mock `monitor_lifecycle.reconfigure`
  - PATCH `{"monitor": {"baidu_keyword": {"default_excluded_domains": ["a.com"]}}}`
  - 断言 mock 被调用一次，参数 cfg.monitor.baidu_keyword.default_excluded_domains == ("a.com",)
- `test_patch_non_monitor_skips_reconfigure`：
  - PATCH `{"vault_root": "/x"}` 不触发 reconfigure
- `test_patch_reconfigure_swallows_exception`：
  - mock reconfigure raise → PATCH 仍返回 200 + 新 cfg（reconfigure 内部 try/except 兜底）

集成测（端到端）：
- `test_default_excluded_domains_hot_reload`：
  - PATCH 改 default_excluded_domains
  - 立刻拿 `csm_core.monitor.platforms.baidu_keyword.ADAPTER._default_excluded_domains`
  - 断言新值

### 4.5 边界 / YAGNI

- 只在 `"monitor" in updates` 时调 reconfigure，避免改 `vault_root` 等无关字段白跑
- `_apply_runtime_settings` 每个 adapter 单独 try/except，单项失败不卡住其他
- `browser_engine` / `chrome_path` 改了 reconfigure 后：新任务用新引擎；正在跑的任务保持旧 context（incognito_session 是 per-task 创建，自然切换）
- MonitorLoop 本身不重建 → `alert_top_n` 改要重启（可接受，告警阈值不高频改）

---

## 5. Section 2 — Bug 2: AddTaskModal 复用应用设置域名名单

### 5.1 修法核心

保持后端逻辑和数据结构完全不变（沿用 `_build_exclude_set` 的 global + task 合并）。只在 AddTaskModal 的 `baiduUseDefaultExcludes` toggle 旁加按钮，弹 modal 显示全局名单（只读 + 跳转 Settings 编辑）。

### 5.2 AddTaskModal.vue 改动

#### 5.2.1 toggle 行旁加按钮

替换 [line 439-445](../../frontend/src/components/monitor/AddTaskModal.vue) 的 FormField：

```vue
<FormField
  label="启用默认电商/B2B 黑名单"
  hint="默认过滤 jd / 1688 / taobao / pinduoduo 等采购与电商站点（这些命中目标品牌也不是软文）。如果你确实要监测这些站，关掉。"
  inline
>
  <div class="flex items-center gap-2">
    <FormToggle v-model="baiduUseDefaultExcludes" />
    <button
      type="button"
      class="text-[11px] text-[var(--ink-2)] hover:text-[var(--primary-deep)] underline-offset-2 hover:underline"
      @click="showDefaultDomainsPopover = true"
    >
      查看名单（{{ defaultExcludeDomains.length }}）
    </button>
  </div>
</FormField>
```

#### 5.2.2 script setup 新增 state + computed

```ts
import { useConfig } from "@/stores/config";
import { useRouter } from "vue-router";

const cfgStore = useConfig();
const router = useRouter();
const showDefaultDomainsPopover = ref(false);
const defaultExcludeDomains = computed<string[]>(
  () => cfgStore.data?.monitor?.baidu_keyword?.default_excluded_domains ?? []
);

function goToSettingsExcludeDomains() {
  showDefaultDomainsPopover.value = false;
  emit("close");  // 关闭当前 AddTaskModal
  router.push({ name: "settings", hash: "#baidu-default-excludes" });
}
```

> 依赖：`useConfig` (Pinia store, [frontend/src/stores/config.ts](../../frontend/src/stores/config.ts)) 应在 boot 时已经调过 `load()` 拉过 `/api/config`。如有 ref 时机问题，AddTaskModal 的 `onMounted` 兜底 `if (!cfgStore.data) await cfgStore.load();`。

#### 5.2.3 popover 子 modal（同文件 inline）

放在 AddTaskModal 主 modal 内部底部：

```vue
<!-- 默认名单展示弹层 -->
<div
  v-if="showDefaultDomainsPopover"
  class="fixed inset-0 z-[60] flex items-center justify-center bg-black/30"
  @click.self="showDefaultDomainsPopover = false"
>
  <div class="w-[400px] max-h-[60vh] flex flex-col rounded-lg bg-[var(--card)] p-4 shadow-xl">
    <div class="flex items-center justify-between mb-3">
      <div class="text-[13px] font-medium">默认排除域名（{{ defaultExcludeDomains.length }}）</div>
      <button class="text-[16px]" @click="showDefaultDomainsPopover = false">×</button>
    </div>

    <div class="flex-1 overflow-auto text-[12px] font-mono space-y-1">
      <div v-if="defaultExcludeDomains.length === 0" class="text-[var(--ink-3)]">
        （空 —— 去应用设置里添加）
      </div>
      <div v-for="d in defaultExcludeDomains" :key="d">{{ d }}</div>
    </div>

    <div class="mt-3 pt-3 border-t border-[var(--line)] flex justify-between">
      <button
        class="text-[11.5px] text-[var(--primary-deep)] hover:underline"
        @click="goToSettingsExcludeDomains"
      >
        去应用设置编辑 →
      </button>
      <button
        class="text-[11.5px] px-3 py-1 rounded bg-[var(--card-2)]"
        @click="showDefaultDomainsPopover = false"
      >
        关闭
      </button>
    </div>
  </div>
</div>
```

#### 5.2.4 hint 文字补充

在 `自定义排除域名` 那个 FormField hint 末尾加一句：「会和上方"默认黑名单"合并去重」。

### 5.3 SettingsView.vue 改动

在 `default_excluded_domains` 那个 FormField 的最外层加 `id="baidu-default-excludes"`，让 `router.push({ hash: ... })` 能锚到位置。

### 5.4 测试

- 手测：AddTaskModal 打开 → 看见「查看名单（N）」按钮 → 点击弹层显示全部内容 → 「去应用设置编辑」→ 跳到 SettingsView 对应锚点
- 单测可选（Vue 组件测试在本项目较少，可不强制）

### 5.5 边界 / YAGNI

- 不在 popover 内编辑（编辑回 Settings）—— 避免「modal 里改了要不要保存？关闭算不算保存？」语义陷阱
- 不展示「task 级 exclude_domains 怎么和全局合并」的 preview—— hint 文字一句话足够
- 不做 autocomplete / 标签输入 —— toggle + 弹层够了，新概念会增加学习成本
- modal-in-modal 用 `z-[60]` 高于 AddTaskModal 的 z-50

---

## 6. Section 3 — Bug 1: UA 池 + curl_cffi Session 复用

### 6.1 关键洞察

bilibili_comment 已验证了 curl_cffi 反爬模式（[bilibili_comment.py:60-66](../../csm_core/monitor/platforms/bilibili_comment.py)）：
- `impersonate="chrome120"` 保持不变 → 控制 TLS/H2 fingerprint
- `session.headers["User-Agent"]` 在 Chrome 子版本间轮换 → 控制可见 UA

**TLS 指纹和 UA 头跨大版本切换反而更可疑**（Chrome120 的 TLS 配 Firefox 的 UA 头 = bot 标志），所以只在 Chrome 子版本里轮转 UA，impersonate 保持 chrome120。

### 6.2 baidu_keyword.py 改动

#### 6.2.1 module-level 加 UA 池

```python
# Chrome 子版本 UA 轮换池。curl_cffi 的 impersonate="chrome120" 保持
# 不变（控制 TLS/H2 fingerprint，跨大版本切会让 TLS 与 UA header 矛盾
# 更可疑），只换 User-Agent header 在 Chrome 119-122 间轮转。
_UA_POOL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
```

#### 6.2.2 BaiduKeywordAdapter.__init__ 加状态

```python
import threading
...
def __init__(self) -> None:
    ...  # 现有 init
    self._ua_idx = 0
    self._http_sessions: dict[int, Any] = {}      # task_id -> curl_cffi.Session
    self._http_sessions_lock = threading.Lock()
```

#### 6.2.3 Session 工厂 + drop

```python
def _next_ua(self) -> str:
    ua = _UA_POOL[self._ua_idx % len(_UA_POOL)]
    self._ua_idx += 1
    return ua


def _get_session(self, task_id: int) -> Any:
    """Per-task Session reuse. 第一次创建时 warm-up GET baidu.com 拿 baseline cookie。

    线程安全：BAIDU_ADAPTER 是 module singleton，ThreadPool 里多 task 并发，
    用 _http_sessions_lock 保护字典；同一 task 内串行使用 session（curl_cffi
    Session 在 task 内单线程使用无问题）。
    """
    with self._http_sessions_lock:
        sess = self._http_sessions.get(task_id)
        if sess is not None:
            return sess
        from curl_cffi import requests as cc_requests
        sess = cc_requests.Session(impersonate="chrome120")
        sess.headers.update({
            "User-Agent": self._next_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })
        # warm-up：拿 BAIDUID/BIDUPSID baseline cookie。失败不致命，后续请
        # 求自然会建立 cookie，warm-up 只减少首个真实请求的"裸 cookie"风险。
        try:
            sess.get("https://www.baidu.com/", timeout=8)
        except Exception as e:
            logger.info("baidu session warmup failed (task=%d): %s", task_id, e)
        self._http_sessions[task_id] = sess
        return sess


def _drop_session(self, task_id: int) -> None:
    """命中风控或任务结束时丢弃 session。脏 cookie 不能继续用。"""
    with self._http_sessions_lock:
        sess = self._http_sessions.pop(task_id, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
```

#### 6.2.4 `_cc_get` 透传 session

保留 `_cc_get` module-level（单测 monkeypatch 友好），加可选 session：

```python
def _cc_get(url: str, *, session: Any = None, **kwargs: Any) -> Any:
    """No session → 旧行为（无状态单次）；with session → session.get 保 cookie。"""
    if session is not None:
        # session 已固定 impersonate，调用方不该再传
        kwargs.pop("impersonate", None)
        return session.get(url, **kwargs)
    from curl_cffi import requests as cc_requests
    return cc_requests.get(url, **kwargs)
```

#### 6.2.5 `resolve_baidu_link` / `fetch_article_http` 接受 session

```python
def resolve_baidu_link(url: str, *, session: Any = None) -> str:
    ...
    resp = _cc_get(url, session=session, impersonate="chrome120",
                    allow_redirects=True, timeout=10)
    ...


def fetch_article_http(url: str, *, session: Any = None) -> dict[str, Any]:
    ...
    resp = _cc_get(url, session=session, impersonate="chrome120",
                   allow_redirects=True, timeout=15)
    ...
```

#### 6.2.6 adapter 主循环注入 + 风控时 drop

`BaiduKeywordAdapter.fetch(task)`（在 fetch 入口）：

```python
def fetch(self, task: MonitorTask) -> MonitorResult:
    sess = self._get_session(task.id)
    try:
        # ... 原有 SERP + article 循环；所有 _cc_get / resolve_baidu_link /
        # fetch_article_http 调用加 session=sess 形参
        ...
        return result
    finally:
        # 任务结束（含正常返回 / 抛 RiskControlException / 抛其他异常）
        # 都丢 session。理由：
        # 1) 命中风控时 cookie 已脏，不能复用
        # 2) 正常结束也丢——「per-task 复用 + 结束销毁」是"模拟真实用户
        #    短会话行为" + "不暴露长寿命账号"的折衷；百度对单 cookie
        #    请求总量也有阈值，长寿命 session 早晚被识别
        # _drop_session 用 pop(..., None) idempotent，重复调安全
        self._drop_session(task.id)
```

### 6.3 测试

`sidecar/tests/test_baidu_keyword.py` 新增 5 条：

- `test_get_session_creates_and_caches_per_task`：
  - 同 task_id 调两次 `_get_session` 返回同一对象
  - 不同 task_id 返回不同对象
- `test_get_session_warmup_failure_not_fatal`：
  - mock `cc_requests.Session().get("https://www.baidu.com/")` raise
  - 验证 `_get_session` 仍返回 session 对象
- `test_ua_pool_rotates`：
  - 连续 5 次 `_next_ua()`
  - 断言至少覆盖 3 个不同 UA
- `test_drop_session_on_risk`：
  - mock fetch 路径命中 `RiskControlException`
  - 验证 `_http_sessions[task_id]` 被清空
- `test_fetch_propagates_session_to_helpers`：
  - mock `_cc_get`
  - 断言 fetch 内部调用带 `session=<对象>` kwarg

### 6.4 范围之外（YAGNI）

- ❌ Proxy 池 — 用户没选；不预留实现
- ❌ UA 池扩到 firefox / safari — TLS 指纹要跟着切，复杂度暴增
- ❌ session 磁盘持久化 — in-memory 够
- ❌ "session 已用 N 次自动 rotate" — per-task 销毁已够保护
- ❌ Sec-CH-UA Client Hints — Chrome 100+ 才用，多一项可能更可疑
- ❌ 「命中风控后动态加长 baijiahao_pacing」— 实现独立，可挪 Phase 2。先做 6.1-6.3 实战验证效果，仍触发再做

---

## 7. 实施建议

### 7.1 落地顺序

1. **第 1 节** — Bug 3 hot-reload（最简单 + 隔离）
   - 修完即可在跑应用时立刻验证：改 Settings 不重启，看 BAIDU_ADAPTER._default_excluded_domains 是否变
2. **第 2 节** — Bug 2 UX
   - 纯前端，与后端解耦，可独立 PR
3. **第 3 节** — Bug 1 反爬增强
   - 最大改动，最后做。借第 1 节验证过的 hot-reload，方便用户改完节流/UA 立刻试

### 7.2 验证策略

- **单测**：全部按 spec 6.3 / 4.4 写。`cd sidecar && python -m pytest tests/ -x` 必过
- **类型**：`cd frontend && npm run typecheck` 必过
- **构建**：`cd frontend && npm run build` 必过
- **实战**：装应用，新建一个含 5+ keyword 的百度任务，连跑 3 次（保证至少 30 条 article fetch），统计 risk_control 触发次数：
  - 改造前 baseline：约 ~60% 任务会触发
  - 改造后目标：≤ 20%（G1）

### 7.3 回归点

- 单 task 流程（既有单测）不能破坏
- `_cc_get` module-level 调用 path（其他地方 import 的）保持向后兼容（session 是可选 kwarg）
- 现有 monitor_lifecycle.start() 调用方不受影响（_apply_runtime_settings 是从 start 抽出来的，外部行为不变）

---

## 8. 改动文件清单

| 文件 | 改动 |
|---|---|
| `sidecar/csm_sidecar/services/monitor_lifecycle.py` | 抽 `_apply_runtime_settings`；加 `reconfigure(cfg)` |
| `sidecar/csm_sidecar/routes/config.py` | `patch_config` 在 monitor 字段变化时调 `reconfigure` |
| `sidecar/tests/routes/test_config.py` | 加 3 个 reconfigure 测 |
| `csm_core/monitor/platforms/baidu_keyword.py` | 加 `_UA_POOL` / `_next_ua` / `_get_session` / `_drop_session`；`_cc_get` 支持 `session=` kwarg；`resolve_baidu_link` / `fetch_article_http` 透传 session；`fetch()` try/finally drop |
| `sidecar/tests/test_baidu_keyword.py` | 加 5 条 session/UA 测 |
| `frontend/src/components/monitor/AddTaskModal.vue` | toggle 行旁加「查看名单」按钮；popover modal；store import + computed + 跳转函数 |
| `frontend/src/views/SettingsView.vue` | default_excluded_domains FormField 加 `id="baidu-default-excludes"` 锚点 |

---

## 9. 未涵盖 / 后续

- MonitorLoop 内部 `alert_top_n` / `alert_cooldown_hours` 的热更新（本 spec 范围内 adapter 是焦点）
- 命中风控后动态调高 baijiahao_pacing（6.4 已说明可挪 Phase 2）
- Proxy 池（用户暂不需要）
- 「全局品牌域名白名单」新概念（用户暂未选择该方向）
