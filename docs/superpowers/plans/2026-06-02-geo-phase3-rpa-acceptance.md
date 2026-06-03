# GEO 阶段 3 RPA —— 人工验收清单（真站，不进 CI）

前置：worktree 重打 sidecar（PYTHONPATH 覆盖 editable）→ 拷 target/debug → tauri dev：
1. `set PYTHONPATH=<wt>;<wt>\sidecar & python scripts/build_sidecar.py --clean`
   （或对应 PowerShell 写法；产出 binaries/csm-sidecar-<triple>.exe）
2. 拷成 `frontend/src-tauri/target/debug/csm-sidecar.exe`；binaries 备 updater.exe + junction ms-playwright。
3. `cd frontend & npx tauri dev --no-watch`，等 stdout `sidecar handshake received: port=...`。

每个平台（DeepSeek → Kimi → 腾讯元宝）逐项：
- [ ] 设置页「AI 卡位 · RPA 登录」点「登录」→ 弹有头窗 → 完成登录（账号/短信/扫码）→ 窗口自动关 → 徽章变「已登录」。
- [ ] 关 dev、重启 → 徽章仍「已登录」（持久档生效）。
- [ ] **选择器校准**：登录态下手动在站内问一句、F12 复制回答容器 outerHTML；或临时在 provider 里 dump `page.content()` 到文件。比对 sites.py 的 answer_sel/citation_sel/composer_sel/web_toggle_sel/generating_sel/logged_in_sel/logged_out_sel，不符就改 sites.py。重点确认：
  - composer_sel 能定位输入框；web_toggle_sel 能切「联网」且 on_attr/on_value 对（不对则调 ensure_web_toggle 参数）；
  - generating_sel 在生成时在场、结束消失（wait_stream_done/make_done_predicate 据此判完成）；
  - citation_sel 容器内的来源 `<a href>` 被 extract_citations 抓到（exclude_hosts 排掉自家域名/站内导航）。
- [ ] 建 geo 任务（品牌+关键词）勾选该 RPA 平台 → run-now → 观察有头窗按预期打字/联网/等待 → 完成后：平台对比有该平台明细、信源榜有来源、答案文本入库。
- [ ] 未登录场景：删 `browser_profiles/geo_<platform>/` 或换平台未登录 → run → 该 cell 显示「采集失败/未登录」（blocked），不误报「未提及」，不崩。
- [ ] 「停止」：run 中点停止 → 当前 RPA 等待应 ~秒级中断（cancel_token 生效），不等满 120s，且不记成 error cell。

回归：`pytest tests/core/monitor/geo/ -q` 全绿；`pytest sidecar/tests/test_monitor_routes.py -k geo_rpa` 全绿。
全套（发版前）：`npx npm@10 ci` 验证 lockfile（前端）。

**校准定稿后保存回归 fixture（落实 spec §7 的 per-site fixture）：**
- 把校准时抓的「回答容器」HTML 存到 `tests/core/monitor/geo/fixtures/<platform>_answer.html`（真站真 HTML）。
- 加回归测试 `tests/core/monitor/geo/test_rpa_fixtures.py`，每站一条：
  `assert _flow.extract_citations(open(FIX/'<platform>_answer.html').read(), container_sel=SITES['<platform>'].citation_sel)` 抽到该 fixture 里你眼见的预期来源 URL（锁住选择器，站点改版回归时 CI 立刻红）。
