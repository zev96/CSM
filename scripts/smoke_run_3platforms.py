# -*- coding: utf-8 -*-
"""3-platform mining (douyin + bilibili + kuaishou) via injected monitor cookies."""
import json, sqlite3, sys, time
from pathlib import Path
import requests
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
pids = json.loads((ROOT/".csm-dev/pids.json").read_text(encoding="utf-8-sig"))
token = json.loads((ROOT/".csm-dev/sidecar.log").read_text(encoding="utf-8-sig").splitlines()[0])["token"]
base = f"http://127.0.0.1:{pids['port']}"
h = {"Authorization": f"Bearer {token}"}

DB = r"C:\Users\EDY\AppData\Local\CSM-Data\monitor.db"
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM video_source_keywords")
conn.execute("DELETE FROM videos")
conn.commit()

print("=== submitting 3-platform job ===")
body = {"keyword":"扫地机器人","platforms":["douyin","bilibili","kuaishou"],"target_per_platform":50}
r = requests.post(f"{base}/api/mining/jobs", headers={**h,"Content-Type":"application/json"},
                  data=json.dumps(body, ensure_ascii=False).encode("utf-8"))
jid = r.json()["job_id"]
print(f"job_id={jid}")

deadline = time.monotonic() + 600
last = ""
while time.monotonic() < deadline:
    time.sleep(5)
    j = requests.get(f"{base}/api/mining/jobs/{jid}", headers=h).json()
    p = j["progress"]
    s = " | ".join(f"{plat}={p.get(plat,{}).get('phase','?')}:{p.get(plat,{}).get('got',0)}"
                    for plat in ("douyin","bilibili","kuaishou"))
    line = f"  status={j['status']:13s} {s}"
    if line != last: print(line, flush=True); last = line
    if j["status"] not in ("pending","running"): break

print(f"\n=== final ===")
final = requests.get(f"{base}/api/mining/jobs/{jid}", headers=h).json()
print(f"overall: {final['status']}")
for plat in ("douyin","bilibili","kuaishou"):
    info = final["progress"][plat]
    print(f"  {plat}: phase={info['phase']}  got={info['got']}/{info['target']}  note={info.get('note','')!r}")
data = requests.get(f"{base}/api/mining/videos?commented=all&limit=300", headers=h).json()
print(f"\nvideos.total = {data['total']}")
by_plat = {}
for v in data["videos"]:
    by_plat[v["platform"]] = by_plat.get(v["platform"], 0) + 1
for plat, n in sorted(by_plat.items()):
    print(f"  {plat}: {n}")
