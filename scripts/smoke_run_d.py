# -*- coding: utf-8 -*-
"""Smoke D: multi-platform job with douyin/kuaishou not logged in →
overall status partial_done; bilibili emits videos, the other two skip.
"""
import json
import sqlite3
import sys
import time
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

# Verify login status precondition.
print("=== login status precondition ===")
status = requests.get(f"{base}/api/mining/login/status", headers=h).json()
for p in ("douyin", "bilibili", "kuaishou"):
    print(f"  {p}: logged_in={status[p]['logged_in']}")
assert status["bilibili"]["logged_in"] is True, "B站 must be logged in for D"
assert status["douyin"]["logged_in"] is False, "douyin should be NOT logged in to test partial"
assert status["kuaishou"]["logged_in"] is False, "kuaishou should be NOT logged in to test partial"

# Clear tables for a clean run.
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM video_source_keywords")
conn.execute("DELETE FROM videos")
conn.execute("DELETE FROM monitor_tasks WHERE name='smoke C marker'")
conn.commit()
print("\n=== submitting 3-platform mining job ===")

body = {
    "keyword": "扫地机器人",
    "platforms": ["douyin", "bilibili", "kuaishou"],
    "target_per_platform": 50,
}
r = requests.post(
    f"{base}/api/mining/jobs",
    headers={**h, "Content-Type": "application/json"},
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
)
job_id = r.json()["job_id"]
print(f"  job_id={job_id}")

# Poll for 4 minutes.
deadline = time.monotonic() + 240
last = ""
while time.monotonic() < deadline:
    time.sleep(4)
    j = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h).json()
    progress = j.get("progress", {})
    summary = " ".join(
        f"{p}={progress.get(p,{}).get('phase','?')}:{progress.get(p,{}).get('got',0)}"
        for p in ("douyin", "bilibili", "kuaishou")
    )
    line = f"  status={j['status']}  {summary}"
    if line != last:
        print(line, flush=True)
        last = line
    if j["status"] not in ("pending", "running"):
        break

# Final verification.
print("\n=== verification ===")
final = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h).json()
prog = final["progress"]
print(f"  overall status: {final['status']}")
for p in ("douyin", "bilibili", "kuaishou"):
    print(f"  {p}: phase={prog[p]['phase']} got={prog[p]['got']}/{prog[p]['target']}")

assert final["status"] == "partial_done", f"expected partial_done, got {final['status']}"
assert prog["bilibili"]["phase"] == "done", f"bilibili should be done, got {prog['bilibili']['phase']}"
assert prog["bilibili"]["got"] > 0, "bilibili should have emitted cards"
assert prog["douyin"]["phase"] == "needs_login", f"douyin should be needs_login"
assert prog["kuaishou"]["phase"] == "needs_login", f"kuaishou should be needs_login"

videos = requests.get(f"{base}/api/mining/videos?commented=all&limit=100", headers=h).json()
print(f"  videos.total={videos['total']}  (all from bilibili)")
platforms = {v["platform"] for v in videos["videos"]}
print(f"  distinct platforms seen: {platforms}")
assert platforms == {"bilibili"}, f"only bilibili should have videos, got {platforms}"

print("\n✅ D scenario passed — bilibili ran, douyin/kuaishou skipped with needs_login, overall=partial_done")
