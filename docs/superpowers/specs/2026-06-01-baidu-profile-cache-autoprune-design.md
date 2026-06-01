# 百度副本缓存自动清理（prune_profile_caches）

**Date:** 2026-06-01
**Status:** 设计待实现
**Owner:** zev96

## 问题陈述

百度抓取 B' 副本 `<config_dir>/baidu_chrome_profile_copy/` 体积会失控（实测 14.3 GB），其中 **86% / 12.4 GB 是 `Default\Service Worker\CacheStorage` 纯 HTTP 缓存**，跟登录态 / 抓取功能零关系。

根因有两个：

1. **导入侧**：`copy_profile_to`（[csm_core/monitor/drivers/chrome_detect.py:147](csm_core/monitor/drivers/chrome_detect.py)）的黑名单 `_PROFILE_CACHE_DIRS_TO_SKIP` 已跳过大部分缓存（commit `36888c6`，v0.5.9 起），但 `WebStorage\<bucket>\CacheStorage`（实测 ~650 MB）和 `Shared Dictionary`（~50 MB）**没在名单里**。
2. **运行侧（主因）**：副本不是静态快照。每轮百度监控都用副本 Chrome 跑 SERP + 开知乎 / 什么值得买文章 tab，Chrome 会持续往 `Service Worker` / `Cache` / `Code Cache` 写缓存 → **清理后还会涨回来**。

手动清理（删 `Default\` 下缓存目录，保留 `Network\Cookies`）能一次性降到 ~1.3 GB，但治标不治本：跑几周又会涨回去。

## Goals

- 副本体积**常态自动维持在 ~0.5 GB**，用户无需手动清理。
- **功能零改动**：百度登录态、知乎 / 什么值得买抓取、扩展指纹全部照旧。
- 不破坏现有任何行为：自建 profile 模式、向后兼容默认值都不动。
- 单一真相源：「什么算缓存」只维护一份名单，导入与清理共用。

## Non-goals

- ❌ 清理自建 `baidu_browser_profile`（headless + 禁图，缓存本就小，保持改动面最小）。
- ❌ UI 开关 / 新配置 / 新 API（缓存永远是垃圾，native 模式下无条件开启）。
- ❌ 阈值触发 / 定时调度（已选「每轮都清」，最简单可预测）。
- ❌ 清理 `launch-login-window` 子进程退出后的缓存（登录窗写缓存少，留作后续可选扩展）。

## 架构

### 改动点 1：扩 `_PROFILE_CACHE_DIRS_TO_SKIP` —— `chrome_detect.py`

往现有 frozenset 加两个名字：

```python
# WebStorage / Service Worker 下的 Cache Storage API 数据 —— 永远是缓存的
# HTTP 响应，绝不含 cookie / 登录态
"CacheStorage",
# 压缩字典缓存
"Shared Dictionary",
```

连带效果：`_copy_ignore_caches` 走的就是这个名单，所以**导入（`copy_profile_to`）也会跳过这两个** → 以后「重新导入」出来的副本同样是 ~0.5 GB，不只是清理时才小。

`"CacheStorage"` 按名匹配会命中任意层级的 `CacheStorage` 目录（`Service Worker\CacheStorage`、`WebStorage\<bucket>\CacheStorage`），其中 `Service Worker` 整个目录已被跳过，主要新增收益来自 `WebStorage` 下那 ~650 MB。

### 改动点 2：新函数 `prune_profile_caches` —— `chrome_detect.py`

```python
def prune_profile_caches(profile_copy_path: str) -> dict[str, Any]:
    """删除副本里的 Chrome 缓存目录，保留登录态 / 用户数据。

    与 copy_profile_to 的 _copy_ignore_caches 语义对称：删除任意层级下
    名字在 _PROFILE_CACHE_DIRS_TO_SKIP 里的目录 / 文件。best-effort ——
    逐项 try/except，被锁的文件跳过，永不抛异常。

    Returns:
        {"freed_mb": float, "elapsed_s": float}
    """
```

实现要点：

- `os.walk(base, topdown=True)`：遇到名字在名单里的目录，累加其大小后 `shutil.rmtree(..., ignore_errors=True)`，并从 `dirs[:]` 移除使其不再向下遍历；遇到名单里的文件（如 `Extension Cookies-journal`）直接 `unlink`。
- 路径不存在 → 直接返回 `{"freed_mb": 0.0, "elapsed_s": 0.0}`，no-op。
- 整体不抛异常（调用方在 finally 里、fetch 已完成，清理失败不能影响结果）。

### 改动点 3：挂载到 session 收尾 —— `baidu_browser.py`

`baidu_browser_session` 的 `finally`（[csm_core/monitor/drivers/baidu_browser.py:130](csm_core/monitor/drivers/baidu_browser.py)）在 `pw.stop()` 之后追加：

```python
finally:
    if context is not None:
        try: context.close()
        except Exception as e: logger.debug("baidu context.close raised: %s", e)
    if pw is not None:
        try: pw.stop()
        except Exception as e: logger.debug("baidu pw.stop raised: %s", e)
    # native 副本模式：Chrome 已完全关闭（无文件锁），清理本轮攒下的缓存
    if use_native_chrome:
        try:
            meta = chrome_detect.prune_profile_caches(str(target_dir))
            logger.info(
                "[baidu native] pruned profile caches: freed %s MB in %ss",
                meta["freed_mb"], meta["elapsed_s"],
            )
        except Exception as e:
            logger.debug("baidu prune_profile_caches raised: %s", e)
```

- 时机：整个 fetch 包在一个 `with baidu_browser_session(...)` 里，所以每轮监控（不管多少关键词）结束、Chrome 关闭后**恰好清理一次**。
- `target_dir` 在 native 模式 = 副本路径（`Path(user_data_dir)`），finally 作用域内可见。
- 仅 `use_native_chrome=True` 触发；自建 profile 模式完全不受影响。
- `baidu_browser.py` 当前**未** import `chrome_detect`，需在模块顶部加 `from .chrome_detect import prune_profile_caches`（两者同在 `csm_core/monitor/drivers/`，`chrome_detect` 只依赖 stdlib + winreg，无循环依赖）。`shutil` / `os` 在两个模块都已 import。

## 数据流

```
监控开始
  └─ with baidu_browser_session(use_native_chrome=True, user_data_dir=副本) as s:
        └─ fetch 100 关键词（副本 Chrome 跑 SERP + 文章 tab，写缓存）
     finally:
        context.close() → pw.stop()  (Chrome 完全退出，文件锁释放)
        prune_profile_caches(副本)   (删缓存目录，保留 Cookies/IndexedDB/...)
        log "freed N MB"
监控结束 → 副本回到 ~0.5 GB
```

## 错误处理

| 场景 | 处理 |
|---|---|
| 副本路径不存在 | `prune_profile_caches` 返回 0，no-op |
| 个别缓存文件被锁（残留 Chrome 子进程） | 该项跳过，`rmtree(ignore_errors=True)`，下轮重试 |
| prune 整体抛异常 | finally 里 try/except 吞掉 + `logger.debug`，不影响已完成的 fetch |

## 测试策略

### 单元（TDD，先写测试）

`prune_profile_caches`（新增 `tests/test_chrome_detect.py` 用例）：
- 搭临时假副本：`Default/Service Worker/CacheStorage/x`、`Default/WebStorage/1/CacheStorage/y`、`Default/Shared Dictionary/z`、`Default/Cache/c`、`Default/Network/Cookies`、`Default/IndexedDB/i`、`Default/Local Storage/l`、`Local State`。
- 调用后断言：缓存目录（Service Worker / CacheStorage / Shared Dictionary / Cache）**全删**；`Network/Cookies`、`IndexedDB`、`Local Storage`、`Local State` **全留**；`freed_mb > 0`。
- 路径不存在 → 返回 0、不抛。
- 名单扩张：断言 `_copy_ignore_caches`（或 `copy_profile_to` 行为）现在会把 `CacheStorage` / `Shared Dictionary` 列入忽略。

`baidu_browser_session` native 收尾：
- mock `launch_persistent_context` + `_sync_playwright`，给一个临时副本目录作 `user_data_dir`，预置缓存目录。
- 走完 `with ... as s: pass`，断言：`use_native_chrome=True` 时缓存被清；`use_native_chrome=False`（自建模式）时**不调** prune。

### 手动

- 真机：native 模式跑一轮百度监控 → 结束后看日志 `freed N MB` + 副本目录降回 ~0.5 GB + 百度登录态仍有效（不需重登）。

## 兼容性 / 兜底

- 自建 profile 模式（默认）行为完全不变。
- native 模式无新配置 / 无迁移：升级即生效。
- prune 失败永不影响监控结果（best-effort + finally 吞异常）。

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 误删登录态目录 | 副本要重登 | 名单只含确证为缓存的目录；测试显式断言 `Cookies`/`IndexedDB`/`Local State` 保留 |
| `CacheStorage` 含某站功能数据 | 该站下轮重新拉取 | Cache Storage API 只存缓存的 HTTP 响应，不含登录态；读取型抓取下重拉无副作用 |
| prune 拖慢 fetch 收尾 | 每轮多几秒 | 稳态下只有一轮缓存量（几百 MB），删除秒级；且 fetch 结果已产出 |

## 发版

- 走老 pipeline：CHANGELOG 加条目 + 5 处版本号 bump + PR（release.py 管 3 处 + CHANGELOG，另需手动 bump frontend/package.json + lockfile）。
- 本改动纯 `csm_core`，无前端 / Tauri 改动。
