# -*- coding: utf-8 -*-
"""Smoke C: verify already_commented reverse-lookup.

We test the exact code path the mining runner takes when upserting a new
video — but we drive it directly with a known-good VideoCard so we don't
depend on bilibili's search ranking returning the same BVs we expect.
"""
import json
import sqlite3
import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
pids = json.loads((ROOT / ".csm-dev/pids.json").read_text(encoding="utf-8-sig"))
token = json.loads(
    (ROOT / ".csm-dev/sidecar.log").read_text(encoding="utf-8-sig").splitlines()[0]
)["token"]
port = pids["port"]
base = f"http://127.0.0.1:{port}"
h = {"Authorization": f"Bearer {token}"}

DB = r"C:\Users\EDY\AppData\Local\CSM-Data\monitor.db"
TARGET_BV = "BV9smokeC0001"   # synthetic — guaranteed unique
OTHER_BV = "BV9smokeC0002"    # control — not in monitor_tasks

# 1. Reset tables.
print("=== resetting tables ===")
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM video_source_keywords")
conn.execute("DELETE FROM videos")
# Remove any prior smoke marker tasks; keep the user's real monitor tasks.
conn.execute(
    "DELETE FROM monitor_tasks WHERE name='smoke C marker'"
)
conn.commit()

# 2. Insert monitor_task pointing at TARGET_BV.
print(f"=== inserting monitor_task for {TARGET_BV} ===")
conn.execute(
    """
    INSERT INTO monitor_tasks(
        type, name, target_url, config_json, schedule_cron, last_check_at, last_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    (
        "bilibili_comment",
        "smoke C marker",
        f"https://www.bilibili.com/video/{TARGET_BV}",
        "{}",
        "manual",
        "2026-05-17T00:00:00Z",
        "ok",
    ),
)
conn.commit()
print(f"  monitor_task inserted")

# 3. Create a mining job (so the upsert has a valid job_id FK target).
body = {"keyword": "扫地机器人 (smoke C)", "platforms": ["bilibili"], "target_per_platform": 50}
r = requests.post(
    f"{base}/api/mining/jobs",
    headers={**h, "Content-Type": "application/json"},
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
)
# We don't care about HTTP status — the job will run and fail because
# the synthetic keyword won't find anything, but we just need the row.
job_id = None
try:
    job_id = r.json().get("job_id")
except Exception:
    pass
# Fallback: read the latest job_id.
if job_id is None:
    job_id = conn.execute("SELECT MAX(id) FROM mining_jobs").fetchone()[0]
print(f"  using job_id={job_id}")

# 4. Directly call upsert_video_and_link for the two BVs — same code path
#    the runner uses. Tests _check_already_commented exactly.
print("\n=== calling upsert_video_and_link directly ===")
sys.path.insert(0, str(ROOT))
from csm_core.mining import storage as ms
from csm_core.mining.models import VideoCard
from csm_core.monitor import storage as monitor_storage
monitor_storage.init_db(Path(DB))

ms.upsert_video_and_link(
    VideoCard(
        platform="bilibili",
        platform_video_id=TARGET_BV,
        url=f"https://www.bilibili.com/video/{TARGET_BV}",
        title="smoke C target — should be flagged already_commented",
        author_name="smoke-bot",
        rank_in_search=1,
    ),
    job_id,
)
ms.upsert_video_and_link(
    VideoCard(
        platform="bilibili",
        platform_video_id=OTHER_BV,
        url=f"https://www.bilibili.com/video/{OTHER_BV}",
        title="smoke C control — no monitor_task points here",
        author_name="smoke-bot",
        rank_in_search=2,
    ),
    job_id,
)
print("  2 videos upserted")

# 5. Verify state.
print("\n=== verification ===")
target_row = conn.execute(
    "SELECT already_commented, commented_source, commented_at "
    "FROM videos WHERE platform_video_id=?", (TARGET_BV,),
).fetchone()
other_row = conn.execute(
    "SELECT already_commented, commented_source "
    "FROM videos WHERE platform_video_id=?", (OTHER_BV,),
).fetchone()
print(f"  {TARGET_BV}: already_commented={target_row[0]}  source={target_row[1]}  at={target_row[2]}")
print(f"  {OTHER_BV}:  already_commented={other_row[0]}  source={other_row[1]}")

assert target_row[0] == 1, f"TARGET expected 1, got {target_row[0]}"
assert target_row[1] == "monitor_task", f"TARGET source mismatch: {target_row[1]!r}"
assert target_row[2] == "2026-05-17T00:00:00Z", f"TARGET timestamp mismatch: {target_row[2]!r}"
assert other_row[0] == 0, f"OTHER should NOT be marked, got {other_row[0]}"

# 6. Verify ?commented= API filter.
uncommented = requests.get(f"{base}/api/mining/videos?commented=0&limit=100", headers=h).json()
commented_only = requests.get(f"{base}/api/mining/videos?commented=1&limit=100", headers=h).json()
print(f"\n  ?commented=0 total={uncommented['total']}  (should NOT include TARGET)")
print(f"  ?commented=1 total={commented_only['total']}  (should include TARGET)")
bv_in = lambda lst, bv: any(v["platform_video_id"] == bv for v in lst["videos"])
assert not bv_in(uncommented, TARGET_BV)
assert bv_in(commented_only, TARGET_BV)
assert bv_in(uncommented, OTHER_BV)
assert not bv_in(commented_only, OTHER_BV)
print("\n✅ C scenario passed — reverse-lookup + filter both work")
