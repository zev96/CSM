# -*- coding: utf-8 -*-
"""Smoke test B: start a bilibili mining job for '扫地机器人', poll progress."""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
pids = json.loads((ROOT / ".csm-dev/pids.json").read_text(encoding="utf-8-sig"))
token = json.loads(
    (ROOT / ".csm-dev/sidecar.log").read_text(encoding="utf-8-sig").splitlines()[0]
)["token"]
port = pids["port"]
base = f"http://127.0.0.1:{port}"
h = {"Authorization": f"Bearer {token}"}

body = {
    "keyword": "扫地机器人",
    "platforms": ["bilibili"],
    "target_per_platform": 50,
}
r = requests.post(
    f"{base}/api/mining/jobs",
    headers={**h, "Content-Type": "application/json"},
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
)
print(f"start_job HTTP {r.status_code}", flush=True)
if r.status_code != 201:
    print(r.text, flush=True)
    sys.exit(1)

job = r.json()
job_id = job["job_id"]
print(f"new job_id={job_id}  keyword stored as: {job['job']['keyword']!r}", flush=True)

deadline = time.monotonic() + 240
last_phase, last_got = "", -1
while time.monotonic() < deadline:
    time.sleep(5)
    r = requests.get(f"{base}/api/mining/jobs/{job_id}", headers=h)
    j = r.json()
    p = j.get("progress", {}).get("bilibili", {})
    got, target, phase = p.get("got", 0), p.get("target", 50), p.get("phase", "?")
    if phase != last_phase or got != last_got:
        print(
            f"  [{time.strftime('%H:%M:%S')}] status={j['status']}  "
            f"bilibili phase={phase} got={got}/{target}",
            flush=True,
        )
        last_phase, last_got = phase, got
    if j["status"] not in ("pending", "running"):
        print(f"\n*** job finished: status={j['status']} ***", flush=True)
        if j.get("error_message"):
            print(f"error: {j['error_message']}", flush=True)
        break

r = requests.get(f"{base}/api/mining/videos?commented=all&limit=10", headers=h)
data = r.json()
print(f"\nvideos.total={data['total']}", flush=True)
for v in data["videos"][:5]:
    print(
        f"  rank={v.get('rank_in_search','?')}  #{v['platform_video_id']}  "
        f"{v['title'][:50]}  by {v['author_name']}",
        flush=True,
    )
