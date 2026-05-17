# Video Mining MVP — Smoke Test Runbook

Run after the v0.5 build is installed. All steps performed manually in the app.

## Setup

1. Start the CSM desktop app.
2. Open Settings → confirm `default_config_dir` exists; verify `<config_dir>/browser_profiles/` was created on first sidecar startup.

## A. Login flow (each platform once)

For each `<platform>` in {bilibili, douyin, kuaishou}:

1. Navigate LeftNav → 引流.
2. Click "⚙ 平台登录"; confirm 3 rows visible; all show "未登录" initially.
3. Click "登录 / 重新登录" for `<platform>`.
4. A headed Patchright Chromium window opens at the platform homepage.
5. Sign in normally (QR scan / username+password).
6. Click "我登好了" in CSM.
7. Verify the row updates to "已登录".

## B. First mining job

1. With at least bilibili logged in, click "+ 新任务".
2. Keyword: "扫地机器人"; platforms: bilibili only; target: 50.
3. Submit → modal closes, JobProgressCard appears at top.
4. Watch the bilibili progress bar tick up over 1-3 minutes.
5. When "job.finished" arrives, status badge flips to "完成".
6. Verify video table populates with ≥30 unique bilibili videos.
7. Click a row's "打开" → opens in default browser.
8. Filter "未评论" should equal the full count (nothing pre-existing in monitor_tasks).

## C. Already-commented marker

1. In monitor view, create a `bilibili_comment` task targeting one of the BV-ids you saw in B.
2. Return to 引流, click "+ 新任务" with the SAME keyword.
3. Submit; let it finish.
4. With filter "未评论": the previously-monitored video should NOT appear.
5. Switch filter to "已评论": that one row appears with the green "已评论" badge; tooltip says "来自评论监控任务...".

## D. Multi-platform run + partial failure

1. Delete the douyin profile folder (forces needs_login).
2. Run a mining job with all 3 platforms checked.
3. Verify:
   - bilibili + kuaishou complete normally.
   - douyin row shows "需登录" phase.
   - Overall job status: "部分完成".

## E. Cancel mid-job

1. Start a fresh job, any keyword.
2. Click "取消" within the first minute.
3. Verify status flips to "已取消", already-emitted videos remain visible.

## F. Export

1. With table populated, click "⏬ 导出 CSV".
2. Open in Excel, confirm Chinese text renders correctly (BOM works).
3. Confirm "already_commented" column reflects the filter.

## G. Sidecar restart safety

1. Start a job, immediately kill the sidecar process (Task Manager).
2. Restart the app.
3. Verify that the previous job's status is "interrupted" (not "running").
