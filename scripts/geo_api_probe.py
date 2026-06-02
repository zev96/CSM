# scripts/geo_api_probe.py
"""真实 API 信源探针 —— 手动运行，把响应存成 fixture。

用法（需真实 key）：
    DASHSCOPE_API_KEY=sk-xxx MOONSHOT_API_KEY=sk-yyy python scripts/geo_api_probe.py

输出：
    tests/core/monitor/geo/fixtures/tongyi_search.raw.json
    tests/core/monitor/geo/fixtures/kimi_search.raw.json

拿到后人工脱敏（去掉 key/request-id），裁剪成 fixtures/tongyi_search.json /
kimi_search.json，确认 search 结果（URL+标题）落在哪个字段。
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import httpx

OUT = Path(__file__).resolve().parents[1] / "tests/core/monitor/geo/fixtures"
KEYWORD = "20万左右的新能源SUV推荐"


def probe_tongyi(key: str) -> dict:
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    body = {
        "model": "qwen-plus",
        "input": {"messages": [{"role": "user", "content": KEYWORD}]},
        "parameters": {"enable_search": True,
                       "search_options": {"enable_source": True, "enable_citation": True},
                       "result_format": "message"},
    }
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    print("tongyi http", r.status_code, "len", len(r.text))
    return r.json()


def probe_kimi(key: str) -> dict:
    url = "https://api.moonshot.cn/v1/chat/completions"
    body = {
        "model": "moonshot-v1-8k",
        "messages": [{"role": "user", "content": KEYWORD}],
        "tools": [{"type": "builtin_function", "function": {"name": "$web_search"}}],
    }
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    print("kimi http", r.status_code, "len", len(r.text))
    return r.json()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    dk = os.environ.get("DASHSCOPE_API_KEY", "")
    mk = os.environ.get("MOONSHOT_API_KEY", "")
    if dk:
        (OUT / "tongyi_search.raw.json").write_text(
            json.dumps(probe_tongyi(dk), ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print("skip tongyi: no DASHSCOPE_API_KEY")
    if mk:
        (OUT / "kimi_search.raw.json").write_text(
            json.dumps(probe_kimi(mk), ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print("skip kimi: no MOONSHOT_API_KEY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
