# 监测模块故障排查手册

服务的是：知乎排名 / 小红书 / B 站 / 抖音 / 快手 评论抓取。本文档记录这套抓取链路一路调出来的所有坑、当前架构、诊断手段、以及给同事新机器装机时的最佳实践。

---

## 1. 当前架构（30 秒过一遍）

```
zhihu_question.py (adapter)
    │
    ├─→ self._cookies.pick()              # CookieStore：轮换 + 冷却
    │       └─→ storage.list_credentials(skip_cooldown=True)
    │               └─→ sqlite (platform_credentials 表，含 cooldown_until 列)
    │
    ├─→ Fast path: curl_cffi.get(...)     # 模拟 TLS 指纹的快速通道，常见 403/400 兜底
    │
    └─→ Browser path: driver.navigate(...)
            └─→ browser_driver.get_driver(engine)
                    ├─→ PatchrightDriver  (默认，推荐)
                    │       └─→ patchright_pool.get_page()
                    │               ├─ ThreadLocal state，per-worker browser 实例
                    │               ├─ Node 子进程 PID 跟踪
                    │               └─ idle reaper (30s)：
                    │                   ├─ OS-kill Node (跨线程安全)
                    │                   └─ 标 close_requested，owner thread 同线程清 asyncio loop
                    │
                    └─→ DrissionDriver    (兜底，留给 Patchright 跑不起的环境)
                            └─→ drission_pool.get_page()

interactive_login.py
    └─→ 用户在 CSM 自己的 Chromium 里登录
        └─→ 抓 cookie + UA 一起存进 platform_credentials
        (重要：cookie 在抓取环境本身签发，指纹一致，存活时间最长)
```

关键设计要点：

1. **Patchright 用 thread-local pool** —— Playwright sync API 的 greenlet 跟创建线程绑死。原本想做全局 singleton 跨 ThreadPoolExecutor 共用，但 worker_0 创建的 page 在 worker_1 用就 `Cannot switch to a different thread`。改成 per-thread 后每个 worker 最多 4 个 Chromium。
2. **Idle 清理两步走** —— Reaper 跨线程只能 OS-kill 进程（psutil）+ 标记 `close_requested`；Playwright 的 `pw.stop()` 必须在 owner 线程 `get_page()` 时同线程调用，否则留下孤儿 asyncio loop，下次启动报 `Sync API inside the asyncio loop`。
3. **Cookie 注入：clear → inject → readback** —— 持久 user_data_dir 会留旧 cookie，必须先 `clear_cookies("zhihu")` 再注入，且**只注一次** `.zhihu.com`（Playwright 不归一化前缀点，注两次 = 两套撞车）。
4. **不要给 Patchright 加"反爬保险"** —— `--disable-blink-features=AutomationControlled`、`--blink-settings=imagesEnabled=false`、强制 UA Chrome 148 这三个加上反而**暴露自动化痕迹**。Patchright 内置 stealth 已经够了，画蛇添足害死人。

---

## 2. 常见错误对照表

按 sidecar 日志关键词查：

```powershell
Get-Content D:\CSM\.csm-dev\sidecar.err.log -Tail 80 | clip
```

| 日志关键词 | 含义 | 怎么修 |
|---|---|---|
| `Sync API inside the asyncio loop` | Worker 线程上残留 Playwright 孤儿 loop（reaper 跨线程清理留下的）| 已修。如重现 → 重启 sidecar |
| `Cannot switch to a different thread` | Playwright handle 跨线程调用 | 已修。确认 `patchright_pool` 走 thread-local 不要回 singleton |
| `Execution context was destroyed` | 页面导航中途想 evaluate JS，DOM 上下文换了 | 加 wait_for selector 再 evaluate；或忽略（CSS 注入失败 non-fatal）|
| `zhihu browser fallback unavailable: patchright start() failed` | Patchright 没装 / Chromium binary 缺 | `patchright install chromium` |
| `failed to launch Chromium: Executable doesn't exist` | 同上 | 同上 |
| `landed on login page` | zhihu 服务端拒识别 cookie | 看下一行 `z_c0_landed` 字段，定位是注入失败还是 cookie 服务端失效 |
| `z_c0_landed=DROPPED_BY_BROWSER` | 浏览器拒收（cookie value 含非法字符）| 重抓 cookie，最好走「内置浏览器登录」 |
| `z_c0_landed=yes` 但仍跳 signin | cookie 服务端已死（用户在别处登过 / 主动登出 / 风控踢了）| 重抓 cookie |
| `dropped_by_browser=['xxx']` | Playwright 静默丢的 cookie 名 | 一般是非关键 cookie，看是否影响 `z_c0` |
| `unhuman` / `/account/unhuman` | 触发 zhihu 反爬墙 | 等 30~60min，或换 cookie，或换 IP |
| `zhihu fast path HTTP 403` | curl_cffi 路径被 zhihu 拒（缺 x-zse-96 签名）| 正常，会自动 fallback 到 browser |
| `zhihu fast path HTTP 400` | curl_cffi 路径请求参数 / cookie 问题 | 同上，会 fallback |
| `0 AnswerItem cards` | 页面加载了但 DOM 上没找到 `.AnswerItem` 节点 | 1) 登录墙 2) zhihu 改了 class 名 3) 反爬墙 |
| `circuit breaker open for zhihu_question` | 短时间内连续 N 次失败，熔断 | 等几分钟；或重启 sidecar 强制重置 |
| `browser fallback has no cookie` | CookieStore.pick() 返回 None | 池里没号 / 全在冷却 / 全被禁用 — 跑下面的诊断脚本 |
| `Patchright idle on thread id=X — OS-killing browser tree` | Reaper 关闭空闲浏览器（正常）| 无需处理 |

---

## 3. 诊断命令速查

### 实时跟随日志（新 PowerShell）

```powershell
Get-Content D:\CSM\.csm-dev\sidecar.err.log -Tail 50 -Wait
```

> 注意：Python `logging` 默认输出到 **stderr**，所以日志在 `sidecar.err.log` 而不是 `sidecar.log`。`sidecar.log` 是 stdout，只有启动握手 JSON 那一行。

### 看 cookie 池当前状态

```powershell
python -c "
import sqlite3, time
from pathlib import Path
db = Path.home() / 'AppData/Local/CSM/CSM/monitor.db'
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row
now = int(time.time())
print(f'{\"id\":<4} {\"platform\":<20} {\"label\":<14} enabled fail cooldown_remain last_used')
print('-' * 100)
for r in conn.execute('SELECT id, platform, label, enabled, fail_count, cooldown_until, last_used_at FROM platform_credentials ORDER BY platform, id'):
    cd = max(0, r['cooldown_until'] - now)
    cd_str = f'{cd//60}m{cd%60}s' if cd else '-'
    print(f'{r[\"id\"]:<4} {r[\"platform\"]:<20} {(r[\"label\"] or \"\"):<14} {r[\"enabled\"]:<7} {r[\"fail_count\"]:<4} {cd_str:<15} {r[\"last_used_at\"] or \"\"}')"
```

### 紧急重置所有 cookie 的冷却/禁用状态

如果错误地禁用了一堆 cookie（比如测试时反复触发风控），一键复活：

```powershell
python -c "
import sqlite3
from pathlib import Path
db = Path.home() / 'AppData/Local/CSM/CSM/monitor.db'
conn = sqlite3.connect(str(db))
n = conn.execute('UPDATE platform_credentials SET cooldown_until=0, fail_count=0, enabled=1').rowcount
conn.commit()
print(f're-enabled / cleared cooldown on {n} rows')"
```

### 验证 Patchright 安装

```powershell
python -c "
from patchright.sync_api import sync_playwright
pw = sync_playwright().start()
print('chromium:', pw.chromium.executable_path)
pw.stop()
print('OK')"
```

如果报 `Executable doesn't exist`：

```powershell
patchright install chromium
```

### 验证 cookie 是否被 zhihu 服务端接受（绕过 CSM）

跑独立 probe 脚本：

```powershell
python D:\CSM\scripts\probe_zhihu_cookie.py 386440684
```

会读 monitor.db 里优先级最高的那条 zhihu cookie，独立开 Chromium 实测能不能登上。日志直接给结论 `OK — cookie works` 或 `FAIL — cookie did NOT yield answers`。

### 杀掉孤儿 Chromium（万一发生）

如果 sidecar 异常退出留下游离 Chromium 进程：

```powershell
# 列出所有 csm-patchright 相关 Chromium
Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*ms-playwright*" } | Format-Table Id, ProcessName, StartTime

# 全杀（确认没有正常运行的 Patchright 任务）
Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*ms-playwright*" } | Stop-Process -Force
```

---

## 4. Cookie 使用最佳实践

### 核心规则

**Cookie 不绑设备，但绑「会话状态」。** 你日常 Chrome 里登录 zhihu 复制出来的 cookie 字符串技术上能在任意机器使用，但 zhihu 服务端会基于 IP、浏览器指纹、登录设备等做风险评分。一旦评分超过阈值，z_c0 会被服务端作废，cookie 看着完整其实已经死了。

会让已复制的 cookie 当场作废的行为：

| 行为 | 影响 |
|---|---|
| **点了"退出登录"** | ★ 致命，所有此 session 的 z_c0 立刻作废 |
| **同账号在别处再登一次** | 旧 z_c0 大概率被踢，新设备签发新 token |
| **网页弹"账号异常"** | 账号被风控，所有历史 z_c0 全死 |
| **太久没用**（1~2 周）| zhihu 主动过期 |
| **同一 z_c0 短时间高频请求** | 风控触发，强制踢下线 |

### 多账号最优实践

**优选：用 CSM 内置浏览器登录。** Cookie 管理器 → 内置浏览器登录 → 填账号备注 → 弹出窗口手动登录 → cookie 自动入库。

- 优势：cookie 由 CSM 自己的 Patchright Chromium 签发，**指纹与抓取时完全一致**，理论上能稳跑几周到几个月
- 缺点：需要每个号挨个登（但比 F12 复制粘贴还省事）

**次选：Chrome 多 Profile 复制粘贴。**

1. Chrome 头像 → 添加 → 创建 4 个 profile（命名「号1」~「号4」）
2. 每个 profile 各自登 zhihu 一个号，**只关 Chrome 别点退出登录**
3. F12 → Application → Cookies → 全选复制（或装 EditThisCookie 一键导出）
4. CSM Cookie 池 → 手动粘贴

注意：每个 profile 关掉 Chrome 后 cookie 仍然活着，**只有点"退出登录"**才会作废。

### Cookie 分发给同事

**不要分发自己的 cookie 给同事。** 两个原因：

1. **会被秒踢** —— 同一 z_c0 突然从你家 IP 切到他公司 IP，zhihu 风控当场踢下线
2. **账号被盗用风险** —— cookie ≈ 完整登录态，别人拿到能改密码、发私信、买盐选

正确做法：

- 应用本身（CSM 安装包）不需要任何账号，monitor.db 在新机器上是空的
- 同事自己登录 zhihu（至少 1 个号），自己抓 cookie
- 推荐每个同事至少 2 个 zhihu 小号开「多账号轮换」

### 多账号轮换设置

设置 → 监测 → 多账号轮换 开启 + 每账号任务数 = 2~3

| Cookie 数 | 推荐 | 备注 |
|---|---|---|
| 1 个 | 关闭轮换 | 一个号挂了全停，但够用 |
| 2~3 个 | 开启，N=2 | 中等容错 |
| 4+ 个 | 开启，N=2~3 | 最稳，能扛短时风控 |

---

## 5. 设计决策备忘（下次别再踩）

### 5.1 为什么用 Patchright 不用别的

- **DrissionPage**：API 在 3.x→4.x 之间大改（`css:` 前缀必须、cookie API 变了），headless 跟新版 Chrome 148+ 不兼容。我们留作兜底。
- **vanilla Playwright**：headless 几个 tab 就被 zhihu 踢 /unhuman。Stealth 补丁要自己加，维护成本高。
- **Selenium**：要管 ChromeDriver 版本匹配，原 Case-6 就吃过这亏。
- **nodriver / undetected-chromedriver**：考虑过，比 Patchright 维护节奏慢，patchright 已经够稳了。

### 5.2 为什么 Patchright 用 thread-local 不用全局 singleton

Playwright sync API 用 greenlet 桥接 async 内核，handle 跟创建线程绑死。`ThreadPoolExecutor` 起 worker_0~3 这些 worker，第一个 worker 创建的 page 在第二个 worker 用时直接 `Cannot switch to a different thread`。Thread-local 后每个 worker 最多 4 个 Chromium（idle reaper 30s 内会收）。

### 5.3 为什么 idle reaper 拆成两步

```python
# Step 1：跨线程安全（psutil 只跟 OS 说话）
psutil.Process(node_pid).terminate()
state.close_requested = True

# Step 2：必须在 owner 线程（get_page 入口）
if state.close_requested:
    state.playwright.stop()
    state.playwright = None
```

试过一步到位 → reaper 直接调 `pw.stop()` 跨线程 → 报 greenlet 错 → 被 try/except 吞掉 → Node 没死、loop 也没清。**两个 bug 叠加，浏览器既不关也下次起不来**。

### 5.4 为什么 cookie 必须先 clear 再注入

`launch_persistent_context` 用持久 user_data_dir 给页面缓存提速。但持久 = 跨进程保留旧 cookie，上次跑剩的"游客 cookie"或被踢的旧 z_c0 会跟新注入的撞，浏览器发请求时 Cookie header 里两个 z_c0，zhihu 后端拒识别 → 永远登录页。

### 5.5 为什么冷却阈值改成 "连续 3 次失败"

最初是"1 次失败立即冷却 30 分钟"。但单号用户测试时偶尔抽风一次就被锁 30 分钟，UX 灾难。改成「连续 3 次」之后单号用户偶发故障能容忍，真出问题（zhihu 持续拒绝）也能及时停手。

### 5.6 为什么 Patchright 启动参数要"反向精简"

走 Patchright 这条路是为了"看起来像普通 Chrome"。每加一个非标 flag 都是反爬的足迹：

- `--disable-blink-features=AutomationControlled` 跟 Patchright 自己的 CDP 补丁重复，反而让 Blink 运行时呈现可识别状态
- `--blink-settings=imagesEnabled=false` 真实用户不会这么用，FingerprintJS 类库会标记
- 强制 UA 改 Chrome 148，但 Patchright Chromium 实际是 131 → `navigator.userAgent` 改了但 `navigator.userAgentData.brands` 还是 131 → **内部自相矛盾 = 反爬硬信号**

现在的 launch_args 只剩 `--no-sandbox --disable-dev-shm-usage --window-size`，全是无害的标准 CI 配置。

---

## 6. 一次完整故障复盘示例（参考用）

**症状**：用户「立刻监测」点了几次后开始一直显示「任务异常」，浏览器窗口能弹出但抓不到内容。

**诊断步骤**：

1. **查日志**：
   ```
   zhihu browser fallback has no cookie; will likely hit login redirect.
   ```
   `pick()` 返回 None。

2. **查 cookie 池状态**（跑第 3 节那个诊断脚本）：
   ```
   id=17  label=号-1  enabled=1  fail=1  cooldown_remain=24m6s
   ```
   池里就 1 条 cookie，正在 24 分钟冷却中。

3. **根因**：之前测试时反复跳 signin，每次失败给 cookie 设 30 分钟冷却 → 现在所有 cookie 都不可用 → `pick()` 返回 None → 适配器跑无 cookie 模式 → zhihu 当游客踢出去 → 用户看到「异常」。

4. **修复**：
   - 短期：跑第 3 节的"紧急重置"命令，清掉冷却
   - 中期：把冷却阈值从「1 次失败」改为「连续 3 次」（已合入）
   - 长期：UI 上显示「冷却中还剩 X 分钟」（已合入），让用户能直接看到状态而不是黑盒

---

## 7. 给同事新机器装 CSM 时该做的事

```text
1. 安装 CSM（你给的安装包）
2. 第一次启动 sidecar 会自动建 monitor.db（空的）
3. 必须装 Patchright 浏览器：
     patchright install chromium
   （约 170MB 下载，一次性）
4. CSM 启动后：设置 → 监测 → 浏览器引擎 = Patchright（默认）
5. Cookie 池管理 → 内置浏览器登录
6. 填备注「号-1」→ 点「打开登录窗口」→ 手动登 zhihu
7. 重复 N 次得到 N 个号
8. 设置 → 监测 → 多账号轮换 开启，每账号任务数=2
9. 添加监测任务 → 立刻监测 验证
```

**FAQ：**

- Q：必须 4 个号吗？ A：不必。1 个号能用，多号是为了风控容错。
- Q：能不能用同事自己的 zhihu 主账号？ A：技术上能，但抓取行为可能触发主账号的风控，建议小号。
- Q：cookie 多久要换一次？ A：用「内置浏览器登录」抓的能稳 1~2 个月；F12 手动复制的可能 1~2 周。UI 上看到 cookie 状态变红（"可能失效"）就重抓。
