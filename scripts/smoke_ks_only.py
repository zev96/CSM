# -*- coding: utf-8 -*-
"""Just run kuaishou alone for debugging."""
import json, sys, time
from pathlib import Path
import requests
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
pids = json.loads((ROOT/".csm-dev/pids.json").read_text(encoding="utf-8-sig"))
token = json.loads((ROOT/".csm-dev/sidecar.log").read_text(encoding="utf-8-sig").splitlines()[0])["token"]
base = f"http://127.0.0.1:{pids['port']}"
h = {"Authorization": f"Bearer {token}"}
body = {"keyword":"扫地机器人","platforms":["kuaishou"],"target_per_platform":50}
r = requests.post(f"{base}/api/mining/jobs", headers={**h,"Content-Type":"application/json"},
                  data=json.dumps(body, ensure_ascii=False).encode("utf-8"))
jid = r.json()["job_id"]
print(f"job_id={jid}")
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    time.sleep(4)
    j = requests.get(f"{base}/api/mining/jobs/{jid}", headers=h).json()
    p = j["progress"]["kuaishou"]
    print(f"  status={j['status']} phase={p['phase']} got={p['got']}", flush=True)
    if j["status"] not in ("pending","running"): break
