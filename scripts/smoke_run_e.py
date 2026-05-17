# -*- coding: utf-8 -*-
"""Smoke E: start a bilibili job at target=200, cancel after a few
seconds, verify status=cancelled and partial cards persisted.
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

# Reset videos so we can measure what was emitted during the partial run.
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM video_source_keywords")
conn.execute("DELETE FROM videos")
conn.commit()

print("=== submitting bilibili job target=200 (then cancelling soon) ===")
body = {"keyword": "扫地机器人", "platforms": ["bilibili"], "target_per_platform": 200}
r = requests.post(
    f"{base}/api/mining/jobs",
    headers={**h, "Content-Type": "application/json"},
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
)
job_id = r.json()["job_id"]
print(f"  job_id={job_id}")

# Wait 7s then cancel — should be mid-scroll on page 2 or 3.
# (mining browser launches in ~4s, page 1 finishes ~7s emitting 50 cards.)
time.sleep(7)
print("\n=== sending cancel ===")
r = requests.post(f"{base}/api/mining/jobs/{job_id}/cancel", headers=h)
print(f"  cancel HTTP {r.status_code}  body={r.text[:120]}")

# Poll until finished.
deadline = time.monotonic() + 60
last_phase = None
last_got = -1
while time.monotonic() < deadline:
    time.sleep(2)
    j = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h).json()
    p = j["progress"]["bilibili"]
    if p["phase"] != last_phase or p["got"] != last_got:
        print(f"  status={j['status']} phase={p['phase']} got={p['got']}", flush=True)
        last_phase, last_got = p["phase"], p["got"]
    if j["status"] not in ("pending", "running"):
        break

# Verify.
print("\n=== verification ===")
final = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h).json()
print(f"  overall status: {final['status']}")
print(f"  finished_at: {final['finished_at']}")
print(f"  bilibili final: phase={final['progress']['bilibili']['phase']} got={final['progress']['bilibili']['got']}")

videos = requests.get(f"{base}/api/mining/videos?commented=all&limit=300", headers=h).json()
print(f"  videos table count: {videos['total']}  (partial — should be > 0 and < 200)")

assert final["status"] == "cancelled", f"expected status=cancelled, got {final['status']}"
assert videos["total"] > 0, "should have partial cards persisted from before cancel"
assert videos["total"] < 200, f"shouldn't reach full target; got {videos['total']}"
print("\n✅ E scenario passed — cancel honored, partial data retained")
