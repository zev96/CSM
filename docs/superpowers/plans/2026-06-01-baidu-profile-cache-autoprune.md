# 百度副本缓存自动清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** native 副本模式下每轮百度监控结束后自动清理 Chrome 缓存目录，使副本常态维持在 ~0.5GB，登录态与抓取功能零改动。

**Architecture:** 在 `chrome_detect.py` 复用现有 `_PROFILE_CACHE_DIRS_TO_SKIP`（先补两个缓存名）新增 `prune_profile_caches(copy_path)`，按名删除任意层级缓存目录/文件、保留登录态、best-effort 不抛；挂到 `baidu_browser_session` 的 `finally`（`pw.stop()` 之后、仅 `use_native_chrome=True`），Chrome 已完全关闭无文件锁。

**Tech Stack:** Python 3.11 / `os.walk` + `shutil.rmtree` / pytest（`tmp_path`, `monkeypatch`, `unittest.mock.MagicMock`）。纯 `csm_core`，无前端/Tauri 改动。

**测试命令（从 worktree 根目录、项目 Python 环境下运行）：**
`python -m pytest sidecar/tests/test_chrome_detect.py sidecar/tests/test_baidu_browser.py -v`
（`python -m pytest` 会把 CWD=worktree 根加到 sys.path 前面，`import csm_core` 解析到本 worktree 的代码而非主仓安装；首次运行前可 `python -c "import csm_core, pathlib; print(csm_core.__file__)"` 确认指向本 worktree。）

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `csm_core/monitor/drivers/chrome_detect.py` | Chrome 探测 + 副本复制/清理 | 扩 skip 名单 2 项；新增 `_path_size` + `prune_profile_caches` |
| `csm_core/monitor/drivers/baidu_browser.py` | 百度抓取持久 session 生命周期 | 顶部 import；finally 加 native prune 调用 |
| `sidecar/tests/test_chrome_detect.py` | chrome_detect 单元测试 | 加 1 个 copy 用例 + 1 个 `TestPruneProfileCaches` 类 |
| `sidecar/tests/test_baidu_browser.py` | session 单元测试 | 加 2 个 prune 集成用例 |
| `CHANGELOG.md` | 变更日志 | 顶部加 v0.5.11 条目 |

---

### Task 1: 扩 `_PROFILE_CACHE_DIRS_TO_SKIP`（CacheStorage + Shared Dictionary）

**Files:**
- Modify: `csm_core/monitor/drivers/chrome_detect.py:24-46`
- Test: `sidecar/tests/test_chrome_detect.py`（`TestCopyProfileTo` 类内追加）

- [ ] **Step 1: 写失败测试**

在 `sidecar/tests/test_chrome_detect.py` 的 `class TestCopyProfileTo:` 末尾（`test_copy_profile_to_skips_cache_dirs` 之后）追加：

```python
    def test_copy_profile_to_skips_cachestorage_and_shared_dictionary(self, tmp_path):
        """WebStorage 下的 CacheStorage 和 Shared Dictionary 也跳过（纯缓存），
        同 bucket 的非缓存数据（leveldb）保留。"""
        src_user_data = tmp_path / "src_user_data"
        src_default = src_user_data / "Default"
        src_default.mkdir(parents=True)
        (src_default / "Cookies").write_text("cookies-data")
        (src_user_data / "Local State").write_text('{"os_crypt":{}}')
        # WebStorage/<bucket>/CacheStorage —— 缓存，跳过
        cs = src_default / "WebStorage" / "1" / "CacheStorage"
        cs.mkdir(parents=True)
        (cs / "blob").write_text("cache-blob")
        # WebStorage/<bucket>/leveldb —— 非缓存，保留
        other = src_default / "WebStorage" / "1" / "leveldb"
        other.mkdir(parents=True)
        (other / "000001.log").write_text("real-data")
        # Shared Dictionary —— 缓存，跳过
        sd = src_default / "Shared Dictionary"
        sd.mkdir()
        (sd / "db").write_text("dict-cache")

        target = tmp_path / "target"
        chrome_detect.copy_profile_to(
            source_user_data_dir=str(src_user_data),
            source_profile_name="Default",
            target_path=str(target),
        )
        assert (target / "Default" / "Cookies").exists()
        # CacheStorage 任意层级都不复制
        assert not (target / "Default" / "WebStorage" / "1" / "CacheStorage").exists()
        # 同 bucket 的非缓存数据保留
        assert (target / "Default" / "WebStorage" / "1" / "leveldb" / "000001.log").exists()
        # Shared Dictionary 不复制
        assert not (target / "Default" / "Shared Dictionary").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest "sidecar/tests/test_chrome_detect.py::TestCopyProfileTo::test_copy_profile_to_skips_cachestorage_and_shared_dictionary" -v`
Expected: FAIL —— 断言 `WebStorage/1/CacheStorage` 不存在失败（当前会被复制过去）。

- [ ] **Step 3: 改实现（加 2 个缓存名）**

在 `csm_core/monitor/drivers/chrome_detect.py` 的 `_PROFILE_CACHE_DIRS_TO_SKIP` frozenset 里，在 `"PnaclTranslationCache",` 之后、`# extension caches` 注释之前插入：

```python
    # Cache Storage API 数据（Service Worker\CacheStorage、WebStorage\<bucket>\CacheStorage）
    # —— 永远是缓存的 HTTP 响应，不含 cookie / 登录态
    "CacheStorage",
    # 压缩字典缓存
    "Shared Dictionary",
```

（按名匹配，`_copy_ignore_caches` 在 copytree 每层都会调用，所以任意层级的 `CacheStorage` / `Shared Dictionary` 都会被跳过。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest "sidecar/tests/test_chrome_detect.py::TestCopyProfileTo" -v`
Expected: PASS（新用例 + 原有 `test_copy_profile_to_skips_cache_dirs` 等全绿）。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/drivers/chrome_detect.py sidecar/tests/test_chrome_detect.py
git commit -m "perf(monitor): copy_profile_to 跳过 CacheStorage / Shared Dictionary

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 新增 `prune_profile_caches`

**Files:**
- Modify: `csm_core/monitor/drivers/chrome_detect.py`（在 `copy_profile_to` 后、`_read_account_email` 前插入，约 :209-211 之间）
- Test: `sidecar/tests/test_chrome_detect.py`（文件末尾新增 `TestPruneProfileCaches` 类）

- [ ] **Step 1: 写失败测试**

在 `sidecar/tests/test_chrome_detect.py` 文件末尾追加：

```python
# ── prune_profile_caches ──────────────────────────────────────────
class TestPruneProfileCaches:
    def _make_copy(self, tmp_path):
        """造一个带缓存 + 登录态的假副本。"""
        copy = tmp_path / "baidu_chrome_profile_copy"
        default = copy / "Default"
        default.mkdir(parents=True)
        # 缓存（应删）
        sw = default / "Service Worker" / "CacheStorage"
        sw.mkdir(parents=True)
        (sw / "blob").write_bytes(b"x" * 4096)
        (default / "Cache").mkdir()
        (default / "Cache" / "data_0").write_bytes(b"y" * 4096)
        ws_cs = default / "WebStorage" / "1" / "CacheStorage"
        ws_cs.mkdir(parents=True)
        (ws_cs / "blob").write_bytes(b"z" * 4096)
        (default / "Shared Dictionary").mkdir()
        (default / "Shared Dictionary" / "db").write_bytes(b"w" * 4096)
        # 登录态 / 用户数据（应留）
        (default / "Network").mkdir()
        (default / "Network" / "Cookies").write_bytes(b"login-cookies")
        (default / "IndexedDB").mkdir()
        (default / "IndexedDB" / "data").write_bytes(b"idb")
        (default / "Local Storage").mkdir()
        (default / "Local Storage" / "leveldb").write_bytes(b"ls")
        (copy / "Local State").write_text('{"os_crypt":{}}')
        return copy, default

    def test_removes_caches_keeps_login_state(self, tmp_path):
        copy, default = self._make_copy(tmp_path)
        meta = chrome_detect.prune_profile_caches(str(copy))
        # 缓存删了（含任意层级 CacheStorage）
        assert not (default / "Service Worker").exists()
        assert not (default / "Cache").exists()
        assert not (default / "WebStorage" / "1" / "CacheStorage").exists()
        assert not (default / "Shared Dictionary").exists()
        # 登录态 / 用户数据留着
        assert (default / "Network" / "Cookies").exists()
        assert (default / "IndexedDB" / "data").exists()
        assert (default / "Local Storage" / "leveldb").exists()
        assert (copy / "Local State").exists()
        # 返回释放量元数据
        assert meta["freed_mb"] >= 0
        assert "elapsed_s" in meta

    def test_nonexistent_path_is_noop(self, tmp_path):
        meta = chrome_detect.prune_profile_caches(str(tmp_path / "nope"))
        assert meta == {"freed_mb": 0.0, "elapsed_s": 0.0}

    def test_does_not_raise_when_removal_fails(self, tmp_path, monkeypatch):
        """rmtree 抛错（模拟文件锁）时整体不冒泡。"""
        copy, _ = self._make_copy(tmp_path)

        def boom(*a, **k):
            raise OSError("locked")

        monkeypatch.setattr(chrome_detect.shutil, "rmtree", boom)
        meta = chrome_detect.prune_profile_caches(str(copy))  # 不应抛
        assert "freed_mb" in meta and "elapsed_s" in meta
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest "sidecar/tests/test_chrome_detect.py::TestPruneProfileCaches" -v`
Expected: FAIL —— `AttributeError: module 'csm_core.monitor.drivers.chrome_detect' has no attribute 'prune_profile_caches'`。

- [ ] **Step 3: 写实现**

在 `csm_core/monitor/drivers/chrome_detect.py` 的 `copy_profile_to` 函数 `return {...}` 之后、`def _read_account_email` 之前插入：

```python
def _path_size(path: Path) -> int:
    """递归累加目录下所有文件字节数；读不到的项跳过。"""
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def prune_profile_caches(profile_copy_path: str) -> dict[str, Any]:
    """删除副本里的 Chrome 缓存目录 / 文件，保留登录态与用户数据。

    与 copy_profile_to 的 _copy_ignore_caches 语义对称：删除任意层级下
    名字在 _PROFILE_CACHE_DIRS_TO_SKIP 里的目录 / 文件。best-effort ——
    逐项 try/except，被锁的项跳过，整体永不抛异常（调用方在 session
    finally 里，fetch 已完成，清理失败不能影响结果）。

    Args:
        profile_copy_path: 副本根目录（<config_dir>/baidu_chrome_profile_copy）。

    Returns:
        {"freed_mb": float, "elapsed_s": float}。路径不存在 → 全 0。
    """
    base = Path(profile_copy_path)
    if not base.is_dir():
        return {"freed_mb": 0.0, "elapsed_s": 0.0}

    start = time.monotonic()
    freed = 0
    for root, dirs, files in os.walk(base, topdown=True):
        root_path = Path(root)
        # 删匹配的文件（如 Extension Cookies-journal）
        for fname in files:
            if fname in _PROFILE_CACHE_DIRS_TO_SKIP:
                fp = root_path / fname
                try:
                    freed += fp.stat().st_size
                    fp.unlink()
                except OSError as e:
                    logger.debug("prune unlink failed %s: %s", fp, e)
        # 删匹配的目录，并从遍历里剔除（不再下探）
        keep = []
        for d in dirs:
            if d in _PROFILE_CACHE_DIRS_TO_SKIP:
                dp = root_path / d
                try:
                    freed += _path_size(dp)
                    shutil.rmtree(dp, ignore_errors=True)
                except OSError as e:
                    logger.debug("prune rmtree failed %s: %s", dp, e)
            else:
                keep.append(d)
        dirs[:] = keep

    elapsed = time.monotonic() - start
    return {"freed_mb": round(freed / 1024 / 1024, 1), "elapsed_s": round(elapsed, 1)}
```

（`os` / `shutil` / `time` / `Path` / `Any` 在 chrome_detect.py 顶部已 import，无需新增。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest "sidecar/tests/test_chrome_detect.py::TestPruneProfileCaches" -v`
Expected: PASS（3 个用例全绿）。

- [ ] **Step 5: 提交**

```bash
git add csm_core/monitor/drivers/chrome_detect.py sidecar/tests/test_chrome_detect.py
git commit -m "perf(monitor): 新增 prune_profile_caches 清理副本缓存

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 挂到 `baidu_browser_session` finally（仅 native）

**Files:**
- Modify: `csm_core/monitor/drivers/baidu_browser.py`（顶部 import 区 + finally :130-140）
- Test: `sidecar/tests/test_baidu_browser.py`（文件末尾追加 2 个用例）

- [ ] **Step 1: 写失败测试**

在 `sidecar/tests/test_baidu_browser.py` 文件末尾追加：

```python
def test_baidu_browser_session_native_prunes_caches_on_exit(monkeypatch, tmp_path):
    """native 模式：session 退出（Chrome 已关）后清理副本缓存，保留登录态。"""
    from csm_core.monitor.drivers import baidu_browser

    copy = tmp_path  # 充当副本根
    default = copy / "Default"
    default.mkdir()
    (default / "Service Worker").mkdir()
    (default / "Service Worker" / "x").write_bytes(b"cache" * 200)
    (default / "Network").mkdir()
    (default / "Network" / "Cookies").write_bytes(b"login")

    fake_context = MagicMock()
    fake_context.pages = [MagicMock()]
    fake_context.cookies.return_value = []
    fake_chromium = MagicMock()
    fake_chromium.launch_persistent_context = lambda **kw: fake_context
    fake_pw = MagicMock()
    fake_pw.chromium = fake_chromium
    monkeypatch.setattr(baidu_browser, "_sync_playwright", lambda: MagicMock(start=lambda: fake_pw))
    monkeypatch.setattr(baidu_browser, "ensure_browsers_path", lambda: None)

    with baidu_browser.baidu_browser_session(
        headless=False,
        user_data_dir=copy,
        use_native_chrome=True,
        chrome_executable_path="C:/test/chrome.exe",
        chrome_profile_name="Default",
    ):
        pass

    # 缓存被清，登录态保留
    assert not (default / "Service Worker").exists()
    assert (default / "Network" / "Cookies").exists()


def test_baidu_browser_session_self_built_does_not_prune(fake_pw, tmp_path):
    """自建 profile 模式：不清缓存（prune 只针对 native 副本）。"""
    from csm_core.monitor.drivers import baidu_browser

    profile = tmp_path / "p"
    profile.mkdir()
    (profile / "Service Worker").mkdir()
    (profile / "Service Worker" / "x").write_bytes(b"cache")

    with baidu_browser.baidu_browser_session(headless=True, user_data_dir=profile):
        pass

    # 自建模式缓存原样保留
    assert (profile / "Service Worker").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest "sidecar/tests/test_baidu_browser.py::test_baidu_browser_session_native_prunes_caches_on_exit" -v`
Expected: FAIL —— session 退出后 `Service Worker` 仍存在（prune 尚未接入）。

- [ ] **Step 3: 写实现**

(a) 在 `csm_core/monitor/drivers/baidu_browser.py` 顶部 import 区（`from .patchright_pool import ensure_browsers_path` 那一行 :25 之后）加：

```python
from .chrome_detect import prune_profile_caches
```

(b) 把 finally 块（:130-140）替换为——在 `pw.stop()` 之后追加 native prune：

```python
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as e:
                logger.debug("baidu context.close raised: %s", e)
        if pw is not None:
            try:
                pw.stop()
            except Exception as e:
                logger.debug("baidu pw.stop raised: %s", e)
        # native 副本模式：Chrome 已完全关闭（无文件锁），清理本轮攒下的缓存，
        # 使副本常态维持 ~0.5GB。best-effort，失败只 log 不影响已完成的 fetch。
        if use_native_chrome:
            try:
                meta = prune_profile_caches(str(target_dir))
                logger.info(
                    "[baidu native] pruned profile caches: freed %s MB in %ss",
                    meta["freed_mb"], meta["elapsed_s"],
                )
            except Exception as e:
                logger.debug("baidu prune_profile_caches raised: %s", e)
```

（`target_dir` 与 `use_native_chrome` 在函数体开头已绑定，finally 作用域可见；native 分支下 `target_dir = Path(user_data_dir)` 即副本路径。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest "sidecar/tests/test_baidu_browser.py" -v`
Expected: PASS（新 2 个 + 原有 session 用例全绿——尤其 `test_baidu_browser_session_self_built_mode_unchanged` / `test_baidu_browser_session_closes_on_exit` 不回归）。

- [ ] **Step 5: 跑两个测试文件全量回归**

Run: `python -m pytest sidecar/tests/test_chrome_detect.py sidecar/tests/test_baidu_browser.py -v`
Expected: 全 PASS。

- [ ] **Step 6: 提交**

```bash
git add csm_core/monitor/drivers/baidu_browser.py sidecar/tests/test_baidu_browser.py
git commit -m "perf(monitor): 每轮 native 监控结束后自动清理副本缓存

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: CHANGELOG 条目

**Files:**
- Modify: `CHANGELOG.md:5`（在 `## [0.5.10] - 2026-05-29` 之上插入新版本块）

- [ ] **Step 1: 加条目**

在 `CHANGELOG.md` 第 5 行 `## [0.5.10] - 2026-05-29` 之前插入：

```markdown
## [0.5.11] - 2026-06-01

### Changed
- **百度「原生 Chrome 副本」缓存自动清理**：每轮百度监控结束、副本 Chrome 完全关闭后，自动删除副本里的 Chrome 缓存目录（`Service Worker` / `Cache` / `Code Cache` / `CacheStorage` / `Shared Dictionary` 等），使副本常态维持 ~0.5GB，不再随监控运行无限增长。仅清缓存，保留 `Network\Cookies` 登录态、`Local State`、IndexedDB / Local Storage / Extensions，无需重新登录、功能零改动。`copy_profile_to` 导入时同步纳入 `CacheStorage` / `Shared Dictionary` 跳过名单。

```

- [ ] **Step 2: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): v0.5.11 百度副本缓存自动清理

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 完成后（发版，待用户说「上线」再做）

不在本计划编码任务内，等用户确认发布时执行（参见发版教训记忆）：
- 版本号 5 处 bump：`release.py` 管 3 处 + `CHANGELOG`；另需手动 bump `frontend/package.json` + `package-lock.json`（lockfile 用 `npx npm@10 install` 同步，避免 release `npm ci` 炸）。
- 走 PR 流程：push 分支 + `gh pr create` + 返回 URL，停在网页 merge。

---

## Self-Review（计划自查）

- **Spec coverage**：① 扩 skip 名单 → Task 1；② `prune_profile_caches` → Task 2；③ 挂 session finally（仅 native）→ Task 3；④ 测试策略（prune 单元 + native/self-built 集成）→ Task 1-3 各步；⑤ 发版 → 「完成后」段。无遗漏。
- **Placeholder scan**：无 TBD / TODO；每个 code step 给了完整代码。
- **Type consistency**：`prune_profile_caches(profile_copy_path: str) -> dict` 返回 `{"freed_mb", "elapsed_s"}`，Task 2 测试与 Task 3 调用一致；`_path_size(path: Path) -> int` 内部一致；finally 用的 `target_dir` / `use_native_chrome` 是 `baidu_browser_session` 现有变量名。
