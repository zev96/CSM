# -*- coding: utf-8 -*-
"""Run 2-platform mining (bilibili + kuaishou) for '扫地机器人'."""
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

# Fresh start
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM video_source_keywords")
conn.execute("DELETE FROM videos")
conn.commit()

print("=== submitting mining job: bilibili + kuaishou, target=50 each ===")
body = {
    "keyword": "扫地机器人",
    "platforms": ["bilibili", "kuaishou"],
    "target_per_platform": 50,
}
r = requests.post(
    f"{base}/api/mining/jobs",
    headers={**h, "Content-Type": "application/json"},
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
)
print(f"HTTP {r.status_code}  job_id={r.json()['job_id']}")
job_id = r.json()["job_id"]

# Poll up to 8 min (kuaishou may be slower than bilibili).
deadline = time.monotonic() + 480
last = ""
while time.monotonic() < deadline:
    time.sleep(5)
    j = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h).json()
    p = j["progress"]
    summary = " | ".join(
        f"{plat}={p.get(plat,{}).get('phase','?')}:{p.get(plat,{}).get('got',0)}/{p.get(plat,{}).get('target',50)}"
        for plat in ("bilibili", "kuaishou")
    )
    line = f"  status={j['status']:13s} {summary}"
    if line != last:
        print(line, flush=True)
        last = line
    if j["status"] not in ("pending", "running"):
        break

print("\n=== final state ===")
final = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h).json()
print(f"overall: {final['status']}")
for plat in ("bilibili", "kuaishou"):
    info = final["progress"][plat]
    print(f"  {plat}: phase={info['phase']}  got={info['got']}/{info['target']}  note={info.get('note','')!r}")

# Counts
data = requests.get(f"{base}/api/mining/videos?commented=all&limit=200", headers=h).json()
print(f"\nvideos.total = {data['total']}")
by_plat = {}
for v in data["videos"]:
    by_plat[v["platform"]] = by_plat.get(v["platform"], 0) + 1
for plat, n in by_plat.items():
    print(f"  {plat}: {n}")
