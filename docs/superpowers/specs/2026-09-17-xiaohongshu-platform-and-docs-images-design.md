# 小红书接入（评论留存 + 引流采集）与腾讯文档评论图片直传 —— 设计记录

> 状态：已实现（2026-09-17）。三项需求来自用户：① 评论留存率查询加小红书；② 引流平台加小红书；③ 引流评论楼层里的图片同步进腾讯文档。
> 涉及模块：`csm_core/monitor`（TikHub 评论适配器 / 注册表）、`csm_core/mining`（TikHub 搜索适配器 / 模型 / runner / 预筛 / storage）、`csm_core/sync/tencent_docs`、sidecar 分派与服务、前端 monitor / mining / settings。

## 1. 决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 小红书**只走 TikHub**（评论 `app_v2/get_note_comments`，搜索 `app_v2/search_notes`），不做本地路径 | 小红书 web 接口全程 x-s/x-t 签名 + `xsec_token`，本地免费实现不可用；TikHub 已是抖音评论 / 四平台搜索的既定通道（key 已配） |
| D2 | 评论留存对 `xiaohongshu_comment` **忽略「抓取数据源」全局开关**（`monitor_loop.API_ONLY_TYPES`） | 开关切 local 时回落本地只会必然失败；沿用预筛里"抖音有 key 就走 TikHub"的先例。其它类型仍严格按开关分派 |
| D3 | 评论排序用 `like_count`（热门） | 与三平台"热评序里的排名"口径一致；官方明说 `default` 翻页会丢/重，`latest_v2` 是时间倒序、排名会漂移 |
| D4 | 翻页游标 = `{cursor, index, pageArea}` 三元组打包成 dict，当 `paginate()` 的不透明 cursor | 不改 `paginate()` 契约；`build_params` / `parse_page` 各自拆装 |
| D5 | 采集 local 模式下小红书返回**占位适配器**（立刻 failed + 提示切 TikHub），不抛 ValueError | 抛出去会让 job 线程崩掉、其它平台一起没结果；runner 同时把 `get_adapter` 包进 try |
| D6 | 规范链接 `xiaohongshu.com/explore/{note_id}`，结果里带 `xsec_token` 时拼进链接 | 网页端没有 token 打不开笔记；App 两种都能开。`platform_video_id` = 24 位 hex 笔记 ID |
| D7 | 腾讯文档图片：sheet-mcp `insert_image {file_id, sheet_id, row_index, col_index, content(base64)}` 逐张插进贴图格；工具缺席 / 开关关 / 单张失败 → 该格回落「有图，另发」 | 参数名来自官方 sheetagent 桥接层对 `insert_image` 的转发（本机 workbuddy 插件缓存实证）；fail-open 保证有图评论在表格里永远有痕迹 |
| D8 | 一格多图叠放同一格（不改列结构） | 表格列结构由用户维护；叠放可拖开，比"只插第一张"少丢信息 |

## 2. 字段路径实测状态

抖音 / B站 / 快手 的 TikHub 响应是 2026-09-01 用真实 token 落 fixture 实测的；**小红书两个端点尚未实测**（本次无 key 可用，且每次调用计费）。归一化按小红书 App 接口公开形态写并逐层兜底：

- 评论：`raw.data`（小红书信封 `{code, success, msg, data}`）→ `raw.data.data.{comments[], cursor, index, pageArea, has_more}`；信封摊平（`raw.data.comments`）也认。`success=false` / `code≠0` 抛 `TikHubError`（TikHub 文档：笔记不存在照常计费、HTTP 200）。
- 搜索：`raw.data(.data).items[]`，每项 `{model_type:"note", note:{...}}` 或字段摊平；翻页 `page+1` + 首页回传的 `search_id` / `search_session_id`。
- 首跑请执行 `sidecar/scripts/tikhub_probe.py --xhs <笔记链接> --xhs-search <关键词>` 落 fixture，对照 `csm_core/monitor/tikhub/normalize.py` 与 `csm_core/mining/platforms/tikhub_normalize.py` 校正；`sidecar/tests/tikhub/test_xiaohongshu.py` 末尾的 real-fixture 用例在 fixture 存在时自动生效。

## 3. 改动清单（按层）

- 核心：`monitor/base.py` TaskType；`monitor/tikhub/{normalize,comment_adapter,__init__}.py`；新 `monitor/platforms/xiaohongshu_comment.py`（占位 + 链接解析）；`mining/{models,runner,comment_prefilter,storage}.py`；`mining/platforms/{tikhub_normalize,tikhub_search}.py`；`config.py`（`sheet_map` 加小红书、`tencent_docs.sync_images`）；`sync/tencent_docs/sheet.py`（`insert_image` / `write_cell_text`）；`monitor/excel_import.py`。
- sidecar：`monitor_loop.py`（`API_ONLY_TYPES` / `_uses_api`）、`monitor_service.py`、`history_service.py`、`routes/mining.py`（CSV 平台标签）、`tencent_docs_service.py`（插图 + 计数 + 测试连接报告）、`scripts/tikhub_probe.py`。
- 前端：monitor 平台枚举六处 + 新建任务提示；mining 平台类型 / 筛选块 / 平台卡（API-only 态）/ 芯片 / 列表；`TencentDocsCard` 开关与能力提示；`MiningView` 同步结果提示；`SettingsView` 文案。
- 测试：`sidecar/tests/tikhub/test_xiaohongshu.py`（新）、`test_tencent_docs_sync.py`（插图用例）、`test_dispatch.py`（五类适配器 + API-only 分派）、`tests/core/monitor/test_excel_import.py`（模板 6 行）。

## 4. 已知限制 / 后续

- 小红书搜索不回播放数（`play_count` 恒 None）；点赞数可能是 "1.2万" 展示态，已兜底。
- `insert_image` 单张上限本地取 4MB（上传本就封顶 5MB）；超限按插入失败计数并回落标记。
- Cookie 池 / 扫码登录不含小红书（无本地路径，无需 cookie）。
- 一格多图叠放的视觉效果、以及插图后的行高，等真实表格验证后再决定是否加 `set_dimension_size`。

## 5. 补充（同日）：表头识别按链接读取 + 逐列确认

用户反馈：有的表格评论列和图片列不相邻、有的只有 3 层评论列，希望粘贴链接就把表头识别出来、确认后再同步。

| # | 决策 |
|---|---|
| D9 | 「识别表头」（`POST /api/mining/tencent_docs/inspect`，可带 `doc_url` 在保存前先看）读**每一张**子表首行，逐列给出角色（`describe_columns`）与平台路由；保存链接后自动跑一次 |
| D10 | 识别只认列名不认位置：`classify_header` 兼容 字母 / 数字 / 中文数字 / 圈号 的层号写法、楼层写法、括注；`截图 / 返图 / 执行 / 回填 / 状态 / 备注` 排除；层号上限 5，一角色多列取靠前 |
| D11 | 手动映射存 `tencent_docs.sheet_col_overrides["{file_id}:{sheet_id}"] = {mapping, header}`（`PUT /mapping` 整份替换、`DELETE` 恢复自动）；同一列两个角色 / 未知角色 / 越界列号在保存时拒绝 |
| D12 | 同步与识别共用 `_column_map_for`：自动识别 → 叠加覆盖。覆盖保存的表头快照与当前表头逐列比对，被指定的列文本对不上即整份作废（`override_stale`），退回自动识别并在同步结果 `mapping_stale` 里报出——宁可少写，也不把评论写进已经不是那一列的格子 |
| D13 | 只对会被写入的子表要求必需列齐全；闲置子表缺列不算错。层数以该子表实际列数为准（3 层就写 3 层，多出的楼层留在 app 内并计 `skipped_extra_tiers`） |
