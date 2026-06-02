"""豆包(火山方舟 Ark)联网探针 —— 手动运行，确认联网 + references 字段。

用法（需真实 key + 联网 bot_id）：
    ARK_API_KEY=xxx ARK_BOT_ID=bot-xxxx python scripts/geo_doubao_probe.py

Ark 联网走「应用(bot)」端点：POST https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions
body 用 bot_id 当 model。联网结果常在 response 的 references / 自定义字段里。
跑完人工脱敏裁剪成 tests/core/monitor/geo/fixtures/doubao_search.json，确认信源(URL+标题)落在哪个字段。
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import httpx

OUT = Path(__file__).resolve().parents[1] / "tests/core/monitor/geo/fixtures"
KEYWORD = "20万左右的新能源SUV推荐"
URL = "https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions"


def probe(key: str, bot_id: str) -> dict:
    body = {"model": bot_id, "messages": [{"role": "user", "content": KEYWORD}], "stream": False}
    r = httpx.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    print("doubao http", r.status_code, "len", len(r.text))
    print("first 800:", r.text[:800])
    return r.json()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("ARK_API_KEY", "")
    bot = os.environ.get("ARK_BOT_ID", "")
    if not key or not bot:
        print("skip: need ARK_API_KEY + ARK_BOT_ID")
        return 0
    (OUT / "doubao_search.raw.json").write_text(
        json.dumps(probe(key, bot), ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote doubao_search.raw.json -- 人工脱敏裁剪成 doubao_search.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
