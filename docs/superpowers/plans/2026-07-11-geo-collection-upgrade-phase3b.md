# GEO 采集升级 Phase 3b —— RPA 韧性 + 答后节奏 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans 逐任务实施。步骤用 `- [ ]` 复选框跟踪。本计划由主 agent 内联 TDD 实施 + 收尾对抗性审查。

**Goal:** 让 Kimi/DeepSeek/元宝 三站 RPA 采集更抗漂移、抗慢站、抗睡眠唤醒,并在每题之间加入可被 Stop 打断的「思考间隔」+ 每日变序,降低采集失败率与单账号软封指纹。

**Architecture:** 全部改动收敛在 RPA 驱动层(`providers/rpa/_flow.py` + `_driver.py` + 三站 `session()`)与批量车道(`geo_query.py` 的 `_rpa_batch`/`fetch`),不碰 runner 契约、不碰 DB、不碰前端。热轮询用 `page.evaluate` 取答案容器文本长度替代 `page.content()`+bs4;超时先验尸(抓内容)再有限重试;睡眠/时钟跳变归「中断」不重试不计连败;答后 jitter 与关键词洗牌是纯逻辑 + 确定性种子。

**Tech Stack:** Python 3.12 · patchright(Playwright API)· bs4 · pytest。测试命令(worktree 覆盖主仓):
```
PYTHONPATH="D:/CSM/.claude/worktrees/objective-moore-ecce71;D:/CSM/.claude/worktrees/objective-moore-ecce71/sidecar" \
  python -m pytest tests/core/monitor/geo -q
```

**范围边界(本计划**不含**):** §4.2 的「启动抖动 0–20min」「run-window 迟到守卫」落在**通用** `csm_core/monitor/scheduler.py`(baidu/zhihu/comment 共用、纯函数每 tick 调用),加随机需确定性种子 + 按任务类型 gating,属共享调度基建改动 → 单列 **Phase 3c** 另设计,交付 Phase 3b 后向用户说明定夺。会话重置(每题 goto)已在 Phase 2 交付。

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `csm_core/monitor/geo/providers/rpa/_flow.py` | RPA 交互原语 + 纯解析 | 加 `answer_text_len`、`StreamInterrupted`;`submit_query` 发送键多候选+Enter 兜底;`wait_stream_done` 加 `length_fn`/`_now`/`_sleep` 注入 + 跳变检测(睡眠唤醒→StreamInterrupted);`make_done_predicate` 内容分支改用 `answer_text_len` |
| `csm_core/monitor/geo/providers/rpa/_driver.py` | 规格驱动 per-keyword 流程 | `run_one_keyword` 包成 retry 循环:超时/中断先验尸(抓内容够长即救回),真失败 retry×N,中断不 retry;传 `length_fn` 给 `wait_stream_done` |
| `csm_core/monitor/geo/providers/rpa/sites.py` | 每站选择器常量 | `SiteSpec.send_sel` 类型放宽为 `str \| tuple[str,...] \| None`(不新增推测选择器) |
| `csm_core/monitor/geo/providers/rpa/{kimi,deepseek,yuanbao}.py` | 三站 provider | `session()` 加 `retry` 参数透传 `run_one_keyword` |
| `csm_core/monitor/platforms/geo_query.py` | 批量车道 + fetch | `_shuffled_keywords`(确定性洗牌)、`_sleep_jitter`(可取消思考间隔);`fetch` 读 `geo_rpa_retry`/`geo_rpa_jitter_min/max` + 洗牌;`_rpa_batch` 连败短路排除中断 + 答后 jitter + 透传 retry |
| `tests/core/monitor/geo/test_rpa_flow.py` | flow 单测 | 更新 submit_query/done_predicate 测;加 answer_text_len/跳变/验尸测 |
| `tests/core/monitor/geo/test_rpa_driver.py` | driver 单测 | 加 retry/验尸救回/中断不重试测 |
| `tests/core/monitor/geo/test_geo_query_adapter.py` | 车道/fetch 单测 | 加洗牌稳定性/中断不喂连败/jitter 测 |

---

## Task 1: 选择器兜底 —— submit_query 多候选发送键 + Enter

**Files:** Modify `providers/rpa/_flow.py`(`submit_query`)、`providers/rpa/sites.py`(类型注解);Test `tests/core/monitor/geo/test_rpa_flow.py`

**设计:** 发送键选择器漂移是 RPA 采集失败大头(元宝/Kimi 改版)。`send_sel` 放宽为「单个 / 多候选元组 / None」:逐候选 `click(timeout)`,任一成功即返回;全失败(或本就 None)→ `keyboard.press("Enter")` 兜底。DeepSeek/元宝(send_sel=None)行为不变;Kimi 多一层 Enter 兜底。

- [ ] **Step 1: 更新 `_FakePage.click` 接受并忽略 kwargs(容纳 timeout=)**

```python
    def click(self, sel, **kwargs):
        self.clicked.append(sel)
```

- [ ] **Step 2: 写失败用测(TDD)** —— 加到 test_rpa_flow.py:

```python
class _FlakyClickPage(_FakePage):
    """指定 selector 的 click 抛异常(模拟发送键选择器漂移),验证 Enter 兜底/下一候选。"""
    def __init__(self, contents, fail_sels=()):
        super().__init__(contents)
        self._fail = set(fail_sels)
    def click(self, sel, **kwargs):
        if sel in self._fail:
            raise RuntimeError(f"click timeout: {sel}")
        self.clicked.append(sel)


def test_submit_query_falls_back_to_enter_when_send_click_fails():
    page = _FlakyClickPage(["<html></html>"], fail_sels={"button.send"})
    _flow.submit_query(page, composer_sel="textarea", send_sel="button.send", text="k")
    assert page.clicked == ["textarea"]              # composer 聚焦成功、发送键失败
    assert page.pressed == [("<kbd>", "Enter")]      # 回落 Enter


def test_submit_query_tries_second_candidate_before_enter():
    page = _FlakyClickPage(["<html></html>"], fail_sels={"button.a"})
    _flow.submit_query(page, composer_sel="textarea",
                       send_sel=("button.a", "button.b"), text="k")
    assert page.clicked == ["textarea", "button.b"]  # 首候选失败→次候选成功
    assert page.pressed == []                         # 无需 Enter
```

- [ ] **Step 3: 运行 → 失败**(submit_query 尚不接受 tuple / 不兜底)。

- [ ] **Step 4: 实现** —— 替换 `_flow.submit_query` 末段:

```python
def submit_query(page: Any, *, composer_sel: str, send_sel, text: str,
                 focus_ms: int = 250, key_delay_ms: int = 20, commit_ms: int = 400,
                 send_timeout_ms: int = 4000) -> None:
    """聚焦 composer + 真键盘逐字打字(带节流),再点发送键;发送键多候选逐个尝试,
    全失败(或 send_sel=None)→ 键盘 Enter 兜底。

    send_sel: 单个选择器 / 多候选元组 / None。站点改版把某发送键打漂时不再整条关键词
    失败(选择器漂 = 采集失败大头),退化为 Enter 提交。

    **必须带延时**(富文本编辑器,见原注释):focus_ms→逐字→commit_ms。
    """
    page.click(composer_sel)
    page.wait_for_timeout(focus_ms)
    page.keyboard.type(text, delay=key_delay_ms)
    page.wait_for_timeout(commit_ms)
    candidates = (send_sel,) if isinstance(send_sel, str) else tuple(send_sel or ())
    for sel in candidates:
        try:
            page.click(sel, timeout=send_timeout_ms)
            return
        except Exception as e:                        # 选择器漂/超时:试下一候选,最终回落 Enter
            logger.info("submit_query: 发送键 %r 点击失败(试下一候选/Enter): %s", sel, e)
    page.keyboard.press("Enter")
```

`sites.py`:`send_sel: str | None` → `send_sel: "str | tuple[str, ...] | None"`(注解 + 注释「None→Enter;元组→多候选逐试再 Enter」)。不新增推测选择器。

- [ ] **Step 5: 运行全 flow 测 → 通过**(旧 `test_submit_query_types_and_clicks_send`/`_enters_when_no_send_sel` 仍绿:单串走首候选成功、None 走 Enter)。

- [ ] **Step 6: Commit** `feat(geo): submit_query 发送键多候选 + Enter 兜底(P3b.1)`

---

## Task 2: 轮询降本 —— page.evaluate 取答案容器 textContent 长度

**Files:** Modify `_flow.py`(新 `answer_text_len`、`make_done_predicate`、`wait_stream_done` 加 `length_fn`)、`_driver.py`(传 length_fn);Test test_rpa_flow.py

**设计:** 3 车道并发时 `wait_stream_done` 每 500ms 两处 `page.content()`+bs4 打满 GIL。新增 `answer_text_len(page, sel)` 走 `page.evaluate` 只取答案容器 `textContent.length`(不过 bs4);`make_done_predicate` 内容分支 + `run_one_keyword` 传给 `wait_stream_done` 的静默信号都用它;bs4(`extract_answer_text`/`extract_citations`)只在 `run_one_keyword` 结尾跑一次。`wait_stream_done` 加 `length_fn` 注入,**默认仍是** `len(page.content())` → 既有测试与默认语义不变。三站 `answer_sel` 均为合法 querySelectorAll CSS(`div.markdown` / 复合类 / `:not([class*='-cot'])`),可直接喂 evaluate。

- [ ] **Step 1: 写测(TDD)** —— 扩展 `_FakePage` 支持 evaluate 返回序列 + 新测:

```python
# _FakePage.__init__ 末尾加:self._eval_seq = None
# _FakePage.evaluate 改:
    def evaluate(self, expression, arg=None):
        self.evaluated.append((expression, arg))
        if self._eval_seq is not None:
            return self._eval_seq.pop(0) if len(self._eval_seq) > 1 else self._eval_seq[0]
        return self._eval_return


def test_answer_text_len_uses_evaluate_and_guards_errors():
    page = _FakePage(["x"]); page._eval_seq = [123]
    assert _flow.answer_text_len(page, "div.a") == 123
    boom = _FakePage(["x"])
    def _raise(*a, **k): raise RuntimeError("eval boom")
    boom.evaluate = _raise
    assert _flow.answer_text_len(boom, "div.a") == 0        # 出错→0,不外抛


def test_make_done_predicate_answer_growth_uses_evaluate():
    # 内容分支改走 answer_text_len(evaluate):空→仍空→出文>基线+30 判「已开始」
    page = _FakePage(["x"]); page._eval_seq = [0, 0, 200]
    done = _flow.make_done_predicate(page, generating_sel=None, answer_sel="div.a")
    assert done() is False   # 基线 0
    assert done() is False   # 仍 0
    assert done() is True    # 200 > 0+30 → started
```

- [ ] **Step 2: 运行 → 失败**(`answer_text_len` 未定义;make_done_predicate 仍用 content())。

- [ ] **Step 3: 实现 `_flow.py`** —— 新函数 + 改两处:

```python
def answer_text_len(page: Any, answer_sel: str) -> int:
    """答案容器可见文本长度(page 端 textContent 求和,不过 bs4)。缺失/出错→0。
    热轮询(每 500ms × 3 车道)用它替代 page.content()+bs4,省 GIL/整页序列化。"""
    try:
        return int(page.evaluate(
            """(sel) => { let n = 0;
                 for (const el of document.querySelectorAll(sel)) n += (el.textContent || '').length;
                 return n; }""",
            answer_sel))
    except Exception:
        return 0
```

`make_done_predicate` 内容分支(`generating_sel` 为 None 时,三站都走此支)把
`cur = len(extract_answer_text(page.content(), container_sel=answer_sel))`
改为 `cur = answer_text_len(page, answer_sel)`(其余守卫逻辑不变)。

`wait_stream_done` 签名加 `length_fn: "Callable[[], int] | None" = None`,默认闭包保持原语义:

```python
def wait_stream_done(page: Any, *, done_predicate, idle_ms: int = 1500,
                     timeout_s: float = 90.0, poll_ms: int = 500,
                     cancel_token: "Any | None" = None,
                     length_fn: "Callable[[], int] | None" = None) -> None:
    if length_fn is None:
        def length_fn():                      # 默认:整页长度(与旧版逐字节等价,保既有测试)
            return len(page.content())
    ...
        try:
            cur_len = length_fn()
        except Exception:
            cur_len = last_len                # page.content()/evaluate 抛 → 视作静默(同旧版)
```

- [ ] **Step 4: 实现 `_driver.run_one_keyword`** —— 给 `wait_stream_done` 注入便宜信号:

```python
    _flow.wait_stream_done(page, done_predicate=done_pred, idle_ms=1500,
                           timeout_s=spec.stream_timeout_s, cancel_token=cancel_token,
                           length_fn=lambda: _flow.answer_text_len(page, spec.answer_sel))
```

- [ ] **Step 5: 运行全 flow+driver 测 → 通过**(旧 `test_wait_stream_done_*` 走默认 length_fn 不变;旧内容分支测已在 Step 1 改写)。

- [ ] **Step 6: Commit** `perf(geo): 热轮询改 page.evaluate textContent 长度,bs4 只收尾跑(P3b.2)`

---

## Task 3: 超时先验尸再重试(retry×1)

**Files:** Modify `_driver.py`(`run_one_keyword` retry 循环)、三站 `session()`(retry 透传)、`geo_query.py`(读 `geo_rpa_retry` + 透传);Test test_rpa_driver.py

**设计:** `wait_stream_done` 抛 `TimeoutError` 后,先**验尸**:抓 `page.content()` 抽答案,若已 ≥ `_SALVAGE_MIN_CHARS`(80 字,GEO 答案都长,空/失败仅几字)→ 当成功用(慢站在 deadline 后一拍才静默,直接抛会丢弃完整答案+触发无谓 retry)。验尸不足 = 确失败 → 整流程(goto+toggles+submit+wait)重跑,至多 `retry` 次(config `geo_rpa_retry` 默认 1);仍失败才抛。

- [ ] **Step 1: 写测(TDD)** —— test_rpa_driver.py。`_FakePage` 需能让 wait_stream_done 抛超时并保留可抽取 html:

```python
import pytest
from csm_core.monitor.geo.providers.rpa import _driver, _flow


def test_run_one_keyword_salvages_on_timeout(monkeypatch):
    # wait_stream_done 抛超时,但页面已有长答案 → 验尸救回、不 retry、status=ok
    monkeypatch.setattr(_flow, "wait_stream_done",
                        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("exceeded")))
    html = ('<textarea></textarea>'
            '<div class="ds-markdown ds-assistant-message-main-content">' + "推荐小鹏G6。" * 20 +
            '</div>')
    page = _FakePage(html)
    ans = _driver.run_one_keyword(page, SITES["deepseek"], "k",
                                  web_search=True, cancel_token=None, logged_in=True, retry=1)
    assert ans.status == "ok"
    assert page.gotos == ["https://chat.deepseek.com/"]        # 只跑一次(未 retry)


def test_run_one_keyword_retries_then_raises_on_confirmed_timeout(monkeypatch):
    # wait_stream_done 恒超时 + 页面无答案(验尸不足) → retry 用尽后抛 TimeoutError
    monkeypatch.setattr(_flow, "wait_stream_done",
                        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("exceeded")))
    page = _FakePage('<textarea></textarea>'
                     '<div class="ds-markdown ds-assistant-message-main-content"></div>')
    with pytest.raises(TimeoutError):
        _driver.run_one_keyword(page, SITES["deepseek"], "k",
                                web_search=True, cancel_token=None, logged_in=True, retry=1)
    assert page.gotos == ["https://chat.deepseek.com/"] * 2    # 首跑 + 1 retry = 2 次 goto
```

(`_FakePage` 已有 `gotos` 累积;`content()` 恒返回同一 html。)

- [ ] **Step 2: 运行 → 失败**(run_one_keyword 无 retry 参数、无验尸,超时直接冒泡且只 goto 一次)。

- [ ] **Step 3: 实现 `_driver.run_one_keyword`** —— 包成 retry 循环(顶部加常量 `_SALVAGE_MIN_CHARS = 80`):

```python
def run_one_keyword(page, spec, keyword, *, web_search, cancel_token, logged_in,
                    retry: int = 1) -> GeoAnswer:
    if not logged_in:
        return GeoAnswer(platform=spec.platform, keyword=keyword, status="blocked",
                         error=spec.login_blocked_msg)
    attempt = 0
    while True:
        page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
        if spec.new_chat_sel:
            _flow.start_new_chat(page, new_chat_sel=spec.new_chat_sel, answer_sel=spec.answer_sel)
            if spec.post_new_chat_wait_ms:
                page.wait_for_timeout(spec.post_new_chat_wait_ms)
        maybe_cancel(cancel_token)
        if spec.deep_think:
            _flow.enable_toggle_by_text(page, text="深度思考")
        if web_search and spec.web_toggle_sel:
            _flow.ensure_web_toggle(page, toggle_sel=spec.web_toggle_sel, want_on=True)
        if web_search and spec.tool_web_search:
            _flow.enable_tool_web_search(page, tool_sel=spec.tool_web_search[0],
                                         item_text=spec.tool_web_search[1])
        maybe_cancel(cancel_token)
        _flow.submit_query(page, composer_sel=spec.composer_sel, send_sel=spec.send_sel, text=keyword)
        done_pred = _flow.make_done_predicate(page, generating_sel=spec.generating_sel,
                                              answer_sel=spec.answer_sel)
        try:
            _flow.wait_stream_done(page, done_predicate=done_pred, idle_ms=1500,
                                   timeout_s=spec.stream_timeout_s, cancel_token=cancel_token,
                                   length_fn=lambda: _flow.answer_text_len(page, spec.answer_sel))
            break                                          # 正常完成
        except (TimeoutError, _flow.StreamInterrupted) as e:   # StreamInterrupted 见 Task 4
            interrupted = isinstance(e, _flow.StreamInterrupted)
            try:
                salvaged = _flow.extract_answer_text(page.content(), container_sel=spec.answer_sel)
            except Exception:
                salvaged = ""
            if len(salvaged) >= _SALVAGE_MIN_CHARS:         # 验尸救回:慢站已出完整答案
                logger.info("[geo-rpa][%s] kw=%s %s 但答案已 %d 字,验尸救回",
                            spec.platform, keyword, type(e).__name__, len(salvaged))
                break
            if interrupted or attempt >= retry:             # 中断不 retry;retry 用尽 → 抛
                raise
            attempt += 1
            logger.info("[geo-rpa][%s] kw=%s 超时且答案不足(%d字),第 %d 次重试",
                        spec.platform, keyword, len(salvaged), attempt)
            maybe_cancel(cancel_token)
    # ── 抽取(正常完成 or 验尸救回)──
    html = page.content()
    answer = _flow.extract_answer_text(html, container_sel=spec.answer_sel)
    if spec.toolcall_sel:
        _flow.expand_search_toolcalls(page, toolcall_sel=spec.toolcall_sel)
        html = page.content()
        cites = _flow.extract_citations(html, container_sel=None, exclude_hosts=spec.exclude_hosts)
    elif spec.source_text_sel:
        cites = _flow.parse_source_items(html, item_sel=spec.source_text_sel)
    else:
        cites = _flow.extract_citations(html, container_sel=spec.citation_sel,
                                        exclude_hosts=spec.exclude_hosts)
    logger.info("[geo-rpa][%s] kw=%s answer_len=%d cite_n=%d",
                spec.platform, keyword, len(answer), len(cites))
    return GeoAnswer(platform=spec.platform, keyword=keyword, answer_text=answer,
                     citations=cites, status="ok" if answer else "empty",
                     raw={"html_len": len(html), "cite_n": len(cites)})
```

(`StreamInterrupted` 在 Task 4 定义;本任务先只测 `TimeoutError` 两条路径 —— Task 4 补中断测。为让本任务独立编译,Task 4 与本任务连续实现;若严格分步,可先在 `_flow` 顶部加空 `class StreamInterrupted(Exception): ...` 占位。)

- [ ] **Step 4: 三站 `session()` 透传 retry** —— kimi.py/deepseek.py/yuanbao.py 同款:

```python
    def session(self, *, web_search: bool = True,
                cancel_token: "threading.Event | None" = None, retry: int = 1):
        ...
            def query_one(keyword: str) -> GeoAnswer:
                return _driver.run_one_keyword(page, spec, keyword, web_search=web_search,
                                               cancel_token=cancel_token, logged_in=logged_in,
                                               retry=retry)
            yield query_one
```

(`query()` 单发保持默认 `retry=1`,不改签名。)

- [ ] **Step 5: geo_query.fetch 读 config + 透传** —— `rpa_retry = _int_cfg("geo_rpa_retry", 1, 5)`;`_rpa_batch` 加 `rpa_retry` 形参,`provider.session(..., retry=rpa_retry)`;fetch 的 `rpa_batch=` lambda 传 `rpa_retry=rpa_retry`。

- [ ] **Step 6: 运行 driver+adapter 测 → 通过。Commit** `harden(geo): 超时先验尸抓内容再 retry×1(P3b.3)`

---

## Task 4: 中断分类 —— 睡眠/时钟跳变检测

**Files:** Modify `_flow.py`(`StreamInterrupted` + `wait_stream_done` 跳变检测)、`geo_query.py`(`_rpa_batch` 连败排除中断);Test test_rpa_flow.py、test_geo_query_adapter.py

**设计:** Win `time.monotonic()` 含睡眠时间:睡 30min 醒来瞬间越过 deadline → 假超时风暴。在 `wait_stream_done` 检测**单轮** monotonic 跳变 ≫ 轮询间隔(> `jump_threshold_s`,默认 30s)→ 标记 `slept`;到 deadline 时 `slept` 则抛 `StreamInterrupted`(消息含「睡眠唤醒」→ 3a `classify_fail_reason` 已映射 interrupted),否则抛 `TimeoutError`。`run_one_keyword`(Task 3)对 `StreamInterrupted` 先验尸、不足则不 retry 直接抛。`_rpa_batch` 对 `fail_reason=="interrupted"` 的 cell **不喂连败计数**(既不+1也不清零,机器睡眠与平台健康无关)。用 `_now`/`_sleep` 注入做确定性测试。

- [ ] **Step 1: 写测(TDD)** —— test_rpa_flow.py:

```python
def test_wait_stream_done_sleep_wake_raises_interrupted():
    # monotonic 单轮从 1→61 跳变(睡眠),越 deadline 时归 StreamInterrupted 而非 TimeoutError
    times = iter([0.0, 0.0, 1.0, 61.0, 130.0, 130.0])   # start, last_tick, iter1, iter2(跳变), iter3(越界)
    page = _FakePage(["<a>"])
    with pytest.raises(_flow.StreamInterrupted):
        _flow.wait_stream_done(page, done_predicate=lambda: False, idle_ms=1, timeout_s=120,
                               poll_ms=1, jump_threshold_s=30,
                               _now=lambda: next(times), _sleep=lambda s: None)


def test_wait_stream_done_normal_timeout_is_not_interrupted():
    # 平稳推进无跳变 → 仍是 TimeoutError(不误判中断)
    times = iter([0.0, 0.0, 1.0, 2.0, 200.0, 200.0])
    page = _FakePage(["<a>"])
    with pytest.raises(TimeoutError) as ei:
        _flow.wait_stream_done(page, done_predicate=lambda: False, idle_ms=1, timeout_s=120,
                               poll_ms=1, jump_threshold_s=30,
                               _now=lambda: next(times), _sleep=lambda s: None)
    assert not isinstance(ei.value, _flow.StreamInterrupted)
```

- [ ] **Step 2: 运行 → 失败**(无 StreamInterrupted/跳变检测)。

- [ ] **Step 3: 实现 `_flow.py`** —— 顶部加异常类,`wait_stream_done` 加注入 + 跳变:

```python
class StreamInterrupted(Exception):
    """流式等待期间检出 monotonic 跳变(机器睡眠/挂起唤醒)—— 非站点故障。
    不 retry、不计入连败短路;classify_fail_reason 归 'interrupted'。"""


def wait_stream_done(page, *, done_predicate, idle_ms=1500, timeout_s=90.0, poll_ms=500,
                     cancel_token=None, length_fn=None,
                     jump_threshold_s: float = 30.0,
                     _now=time.monotonic, _sleep=time.sleep) -> None:
    if length_fn is None:
        def length_fn():
            return len(page.content())
    deadline = _now() + timeout_s
    stable_since = None
    last_len = -1
    last_tick = _now()
    slept = False
    while True:
        maybe_cancel(cancel_token)
        now = _now()
        if now - last_tick > jump_threshold_s:     # 单轮跳变 ≫ 轮询间隔 = 睡眠/挂起过
            slept = True
        last_tick = now
        if now > deadline:
            if slept:
                raise StreamInterrupted(
                    f"wait_stream_done 检出睡眠唤醒/时钟跳变(interrupted),窗口 {timeout_s}s")
            raise TimeoutError(f"wait_stream_done exceeded {timeout_s}s")
        try:
            done = bool(done_predicate())
        except Exception as e:
            logger.debug("done_predicate raised: %s", e)
            done = False
        try:
            cur_len = length_fn()
        except Exception:
            cur_len = last_len
        quiet = cur_len == last_len
        last_len = cur_len
        if done and quiet:
            if stable_since is None:
                stable_since = now
            elif (now - stable_since) * 1000 >= idle_ms:
                return
        else:
            stable_since = None
        _sleep(poll_ms / 1000.0)
```

(既有 `test_wait_stream_done_timeout_raises` / `_honors_cancel_token` 用真 `time.monotonic`/`time.sleep` 默认注入,不受影响。)

- [ ] **Step 4: 写「中断不喂连败」测** —— test_geo_query_adapter.py(仿该文件既有 `_rpa_batch` 测风格,stub get_provider/session,让某平台连续产 interrupted error cell,断言不短路、无合成 cell):

```python
def test_rpa_batch_interrupt_does_not_feed_consecutive_skip(monkeypatch):
    # 连续 interrupted(睡眠唤醒)error cell 不喂连败计数 → 不短路、逐个照跑到底
    from csm_core.monitor.platforms import geo_query as gq
    kws = ["k0", "k1", "k2", "k3"]

    class _Prov:
        mode = "rpa"
        def session(self, *, web_search, cancel_token, retry=1):
            import contextlib
            @contextlib.contextmanager
            def _cm():
                yield lambda kw: GeoAnswer(platform="kimi", keyword=kw,
                                           status="error", error="睡眠唤醒 interrupted")
            return _cm()
    monkeypatch.setattr(gq, "get_provider", lambda p: _Prov())
    # extract 不会被调(error 分支直接返回);client 传 None
    out = list(ADAPTER._rpa_batch("kimi", kws, None, web_search=True, brand="b",
                                  aliases=[], client=None, consec_skip=2,
                                  rpa_retry=1, jitter_min=0, jitter_max=0))
    assert [li for li, _ in out] == [0, 1, 2, 3]                 # 四个都真跑,无短路提前 return
    assert all(c.fail_reason == "interrupted" for _, c in out)
    assert not any(c.raw.get("synthetic") for _, c in out)      # 未产合成 cell
```

(`GeoAnswer`/`ADAPTER` 按该测试文件既有 import 补齐。`_run_cell_on_session` 对 error answer 会调 `classify_fail_reason(status="error", error="睡眠唤醒 interrupted")` → "interrupted"。)

- [ ] **Step 5: 实现 `_rpa_batch` 连败排除中断** —— 改判定段:

```python
                failed = cell.status in ("error", "blocked")
                is_interrupt = cell.fail_reason == "interrupted"
                if li == 0 and cell.status == "blocked":
                    for li2, syn in _synthetic(li + 1, cell.fail_reason or "not_logged_in",
                                               f"{plat} 首关键词未登录,跳过剩余关键词"):
                        produced = li2 + 1
                        yield li2, syn
                    return
                if failed and not is_interrupt:
                    consec += 1
                elif not failed:
                    consec = 0
                # 中断(睡眠唤醒):consec 不变 —— 机器睡眠与平台健康无关,不喂短路计数。
                if failed and not is_interrupt and consec >= consec_skip:
                    for li2, syn in _synthetic(li + 1, cell.fail_reason or "unknown",
                                               f"{plat} 连续 {consec} 个关键词失败,短路跳过剩余"):
                        produced = li2 + 1
                        yield li2, syn
                    return
```

- [ ] **Step 6: 运行 flow+adapter 测 → 通过。Commit** `harden(geo): 睡眠/时钟跳变归中断,不重试不喂连败(P3b.4)`

---

## Task 5: 答后 jitter(可取消思考间隔)

**Files:** Modify `geo_query.py`(新 `_sleep_jitter` + `_rpa_batch` 插入 + fetch 读 config);Test test_geo_query_adapter.py

**设计:** 每个**成功**关键词(status ok/empty)答完、且非该平台末个关键词时,插入 `U(jitter_min, jitter_max)` 秒「思考间隔」防固定节奏指纹。用 `cancel_token.wait(delay)` 实现——命中 Stop 立即返回并 `maybe_cancel` 抛出,不会让用户等满 45s。失败/合成 cell 不 jitter(加速短路/收尾)。config `geo_rpa_jitter_min/max` 默认 15/45(允许 0 关闭)。

- [ ] **Step 1: 写测(TDD)** —— test_geo_query_adapter.py:

```python
def test_sleep_jitter_waits_random_delay_and_is_cancelable():
    from csm_core.monitor.platforms import geo_query as gq
    import threading
    calls = {}
    tok = threading.Event()
    def _fake_wait(d):
        calls["delay"] = d
        return False                       # 未取消:睡满
    tok.wait = _fake_wait                   # type: ignore
    gq._sleep_jitter(tok, 10, 20, _rand=lambda a, b: 12.5)
    assert calls["delay"] == 12.5          # 用 random.uniform 的值去 wait

    # 命中取消:wait 返回 True → maybe_cancel 抛
    tok2 = threading.Event(); tok2.set()
    import pytest
    with pytest.raises(Exception):
        gq._sleep_jitter(tok2, 10, 20, _rand=lambda a, b: 1.0)


def test_sleep_jitter_zero_max_is_noop():
    from csm_core.monitor.platforms import geo_query as gq
    gq._sleep_jitter(None, 0, 0)           # 不抛、直接返回(禁用 jitter)
```

- [ ] **Step 2: 运行 → 失败**(`_sleep_jitter` 未定义)。

- [ ] **Step 3: 实现 `geo_query.py`** —— 模块级函数(顶部 `import random`, `import time`):

```python
def _sleep_jitter(tok, lo: float, hi: float, *, _rand=random.uniform) -> None:
    """答后「思考间隔」:睡 U(lo,hi) 秒,可被 cancel_token 立即打断(Stop 不等满)。
    hi<=0 视作禁用。用 Event.wait(timeout):命中 Stop 返回 True → maybe_cancel 抛取消。"""
    if hi <= 0:
        return
    delay = _rand(min(lo, hi), max(lo, hi))
    if tok is not None:
        if tok.wait(delay):                 # 期间被 set → 立即抛取消,别再问下一个关键词
            maybe_cancel(tok)
    else:
        time.sleep(delay)
```

`_rpa_batch` 签名加 `jitter_min, jitter_max`;循环末(短路/gate 的 `return` 之后)插入:

```python
                # 答后 jitter:仅成功答案 + 非该平台末个关键词(失败/合成不 jitter)。
                if cell.status in ("ok", "empty") and li < len(plat_keywords) - 1:
                    _sleep_jitter(tok, jitter_min, jitter_max)
```

fetch:加 0-允许读法 + 透传:

```python
        def _int_cfg0(key: str, default: int, hi: int) -> int:   # 允许 0(禁用)
            try:
                v = int(cfg.get(key, default))
            except (TypeError, ValueError):
                v = default
            return max(0, min(v, hi))
        jitter_min = _int_cfg0("geo_rpa_jitter_min", 15, 600)
        jitter_max = _int_cfg0("geo_rpa_jitter_max", 45, 600)
```

`rpa_batch=` lambda 增 `jitter_min=jitter_min, jitter_max=jitter_max`。

- [ ] **Step 4: 运行 adapter 测 → 通过**(既有 `_rpa_batch` 测都传 `jitter_min=0, jitter_max=0` → jitter 关,不改其行为)。

- [ ] **Step 5: Commit** `feat(geo): 答后可取消 jitter 思考间隔 15-45s(P3b.5)`

---

## Task 6: 关键词洗牌(resume 安全)

**Files:** Modify `geo_query.py`(新 `_shuffled_keywords` + fetch 调用);Test test_geo_query_adapter.py

**设计:** 每轮打乱关键词顺序防「同账号同序同刻」指纹。用 `(task_id, UTC 日期)` 经 **sha256** 定确定性 int 种子(不用 `hash(str)`——进程间被 PYTHONHASHSEED 随机化,会破断点续跑),故**同一天内(含崩溃续跑)复现同序**,linear `resume_from` 索引仍成立;**跨天变序**。

- [ ] **Step 1: 写测(TDD)** —— test_geo_query_adapter.py:

```python
def test_shuffled_keywords_stable_within_day_varies_across_days():
    from datetime import date
    from csm_core.monitor.platforms import geo_query as gq
    kws = ["k0", "k1", "k2", "k3", "k4", "k5", "k6", "k7"]
    a = gq._shuffled_keywords(kws, 7, date(2026, 7, 11))
    b = gq._shuffled_keywords(kws, 7, date(2026, 7, 11))
    c = gq._shuffled_keywords(kws, 7, date(2026, 7, 12))
    assert a == b                     # 同 task+同日 → 稳定(断点续跑 resume 安全)
    assert sorted(a) == sorted(kws)   # 只换序、不增删
    assert a != c                     # 跨天变序(8 元素撞同序概率 1/8! 可忽略)


def test_fetch_shuffles_keywords_into_cells_plan(monkeypatch):
    # 验证 fetch 真的把洗牌后的顺序喂给调度器(而非只定义了函数没接线)
    from datetime import date
    from csm_core.monitor.platforms import geo_query as gq
    from csm_core.monitor.base import MonitorTask
    seen = {}
    def _fake_runner(cells_plan, run_cell, **kw):
        seen["order"] = [k for k, _ in cells_plan]
        return []
    monkeypatch.setattr(gq.geo_runner, "run_cells_dual_lane", _fake_runner)
    monkeypatch.setattr(gq, "build_extract_client", lambda p: object())
    monkeypatch.setattr(gq.metrics, "aggregate", lambda cells: {})
    monkeypatch.setattr(gq.metrics, "representative_rank", lambda cells: -1)
    monkeypatch.setattr(gq.geo_storage, "record_run", lambda *a, **k: None)
    monkeypatch.setattr(gq, "get_provider", lambda p: type("P", (), {"mode": "api"})())
    kws = ["k0", "k1", "k2", "k3", "k4", "k5", "k6", "k7"]
    task = MonitorTask(id=7, type="geo_query",
                       config={"brand": "b", "keywords": kws, "platforms": ["doubao"]})
    ADAPTER.fetch(task)
    expected = gq._shuffled_keywords(kws, 7, __import__("datetime").datetime.utcnow().date())
    assert seen["order"] == expected            # cells_plan 用了洗牌序
```

- [ ] **Step 2: 运行 → 失败**(`_shuffled_keywords` 未定义 / fetch 未洗牌)。

- [ ] **Step 3: 实现 `geo_query.py`**(顶部 `import hashlib`):

```python
def _shuffled_keywords(keywords: list, task_id: int, checked_day) -> list:
    """确定性洗牌:种子 = sha256(task_id:UTC日期)。同日复现同序(resume 安全),跨日变序。
    用 sha256 而非 hash(str)——后者被 PYTHONHASHSEED 随机化,跨进程/续跑会变序破断点。"""
    key = f"{task_id}:{checked_day.isoformat()}".encode()
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    out = list(keywords)
    random.Random(seed).shuffle(out)
    return out
```

fetch 中 `keywords = [...]` 之后、`cells_plan = ...` 之前:

```python
        # 关键词顺序洗牌(防固定顺序指纹);确定性种子保当日断点续跑 resume_from 仍有效。
        keywords = _shuffled_keywords(keywords, task.id or 0, datetime.utcnow().date())
```

- [ ] **Step 4: 运行 adapter 测 → 通过**(既有结果类断言 order-independent、progress 单调断言不受序影响)。

- [ ] **Step 5: Commit** `feat(geo): 关键词确定性洗牌防指纹(当日 resume 安全)(P3b.6)`

---

## Task 7: 全量回归 + 对抗性审查

- [ ] **Step 1:** 跑 `tests/core/monitor/geo` 全绿;`pytest sidecar/tests/ -k geo` 全绿;前端不涉及(本 Phase 无前端改动),但仍跑 `npm run test:unit -- geo` 确认未误伤。
- [ ] **Step 2:** 派 2–3 独立 subagent 对抗审查(视角:①正确性/契约——retry/验尸/中断分支与 runner「每关键词一 cell」契约;②并发时序/取消——jitter 的 cancel_token.wait、length_fn 闭包捕获、多车道 GIL;③风控/资源与 resume——洗牌种子跨进程稳定性、跨午夜续跑、jitter 关闭边界)。指令为「设法证伪」。
- [ ] **Step 3:** 发现逐条核实,真问题修复后复审,误报说明理由。
- [ ] **Step 4:** 更新记忆 `project_csm_geo_collection_upgrade.md` + `MEMORY.md`(Phase 3b 交付、Phase 3c 待定、Phase 4 待做)。

---

## Self-Review(对照 §4.2/§4.3 spec)

| spec 条目 | 覆盖 | 备注 |
|---|---|---|
| §4.3 选择器兜底(多候选+Enter) | Task 1 | 不新增推测选择器,只加 Enter 兜底能力 |
| §4.3 超时先验尸再重试 | Task 3 | 验尸=抓内容≥80字即救回;确失败 retry×`geo_rpa_retry` |
| §4.3 中断分类(睡眠/时钟跳变) | Task 4 | monotonic 跳变→StreamInterrupted→分类 interrupted;不 retry/不喂连败 |
| §4.3 轮询降本(evaluate textContent) | Task 2 | bs4 只收尾一次;wait_stream_done 默认语义不变(注入式) |
| §4.2 答后 jitter 15–45s | Task 5 | 仅成功答案;cancel_token.wait 可打断;允许 0 关闭 |
| §4.2 顺序洗牌 | Task 6 | 确定性种子 → 当日 resume 安全 |
| §4.2 启动抖动 0–20min | **Phase 3c** | 通用 scheduler,需确定性种子+类型 gating,单列 |
| §4.2 run-window 守卫 | **Phase 3c** | 同上,通用 scheduler 改动 |
| §4.2 会话重置(每题 goto) | 已 Phase 2 | — |
| §4.3 连败短路 / 登录 gate / 合成 cell | 已 Phase 3a | Task 4 仅补「中断不喂连败」 |

**Type/签名一致性:** `run_one_keyword(..., retry=1)`、`session(..., retry=1)`、`wait_stream_done(..., length_fn=None, jump_threshold_s=30.0, _now=, _sleep=)`、`_rpa_batch(..., consec_skip, rpa_retry, jitter_min, jitter_max)`、`_sleep_jitter(tok, lo, hi, *, _rand=)`、`_shuffled_keywords(keywords, task_id, checked_day)`、`answer_text_len(page, answer_sel)`、`StreamInterrupted` —— 全计划内自洽。

**No placeholders:** 所有代码步含完整实现;测试含真实断言。
