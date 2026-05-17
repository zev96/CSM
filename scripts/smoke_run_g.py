# -*- coding: utf-8 -*-
"""Smoke G: start a job, kill the sidecar mid-flight, restart, verify the
stranded running job is flipped to status=interrupted (mark_interrupted_jobs).
"""
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
DB = r"C:\Users\EDY\AppData\Local\CSM-Data\monitor.db"


def load_session():
    pids = json.loads((ROOT / ".csm-dev/pids.json").read_text(encoding="utf-8-sig"))
    token = json.loads(
        (ROOT / ".csm-dev/sidecar.log").read_text(encoding="utf-8-sig").splitlines()[0]
    )["token"]
    return pids, f"http://127.0.0.1:{pids['port']}", {"Authorization": f"Bearer {token}"}


pids, base, h = load_session()

# Clear tables for a clean slate.
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM video_source_keywords")
conn.execute("DELETE FROM videos")
conn.commit()

print("=== submitting a bilibili job (target=200) ===")
body = {"keyword": "扫地机器人", "platforms": ["bilibili"], "target_per_platform": 200}
r = requests.post(
    f"{base}/api/mining/jobs",
    headers={**h, "Content-Type": "application/json"},
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
)
job_id = r.json()["job_id"]
print(f"  job_id={job_id}")

# Wait a couple seconds for runner to enter `running` state.
time.sleep(3)
mid_state = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h).json()
print(f"  mid-run status before kill: {mid_state['status']}")
assert mid_state["status"] == "running"

# Hard-kill sidecar process (cross-platform via taskkill on Windows).
print(f"\n=== killing sidecar PID {pids['sidecar']} ===")
subprocess.run(
    ["taskkill", "/F", "/T", "/PID", str(pids["sidecar"])],
    capture_output=True, text=True,
)
time.sleep(2)

# Verify DB row is still in 'running' (sidecar can't have flipped it on exit
# since we hard-killed). This proves the mark_interrupted_jobs sweep is what
# we're testing, not graceful shutdown.
db_state = sqlite3.connect(DB).execute(
    "SELECT status FROM mining_jobs WHERE id=?", (job_id,),
).fetchone()
print(f"  job {job_id} DB status right after kill: {db_state[0]}")
assert db_state[0] == "running", "row should still be 'running' after a hard kill"

# Restart sidecar via dev.ps1 (no -SidecarOnly flag — it'll restart Vite too,
# but that's fine for our purposes; the running browser app may show a
# transient connection error which is expected).
print("\n=== restarting sidecar ===")
subprocess.run(
    ["powershell", "-NoProfile", "-File", "scripts/dev.ps1", "-Stop"],
    capture_output=True, text=True, cwd=ROOT,
)
time.sleep(2)
subprocess.Popen(
    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-File", "scripts/dev.ps1"],
    cwd=ROOT,
)
time.sleep(10)
pids2, base2, h2 = load_session()
print(f"  new sidecar pid={pids2['sidecar']}  port={pids2['port']}")

# Hit /api/mining/jobs/{id} on the fresh sidecar.
final = requests.get(f"{base2}/api/mining/jobs/{job_id}", headers=h2).json()
print(f"\n  job {job_id} status after restart: {final['status']}")
print(f"  finished_at: {final['finished_at']}")
assert final["status"] == "interrupted", (
    f"expected status=interrupted after restart, got {final['status']}"
)
assert final["finished_at"] is not None, "interrupted jobs should have finished_at stamped"
print("\n✅ G scenario passed — orphan running job swept to interrupted on restart")
