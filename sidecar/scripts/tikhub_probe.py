"""一次性探针:抓 TikHub 真实响应落 fixture,供评论 normalizer 测试(Task 5/8)校正字段路径。

不计入自动化,手动跑。每端点 1 次请求 = 约 $0.001。key 从环境变量读,绝不写进代码/日志。

用法(PowerShell,在 worktree 根目录):
    $env:TIKHUB_API_KEY="<你的 key>"
    & "D:\\CSM\\.venv\\Scripts\\python.exe" sidecar\\scripts\\tikhub_probe.py `
        --zhihu 23640683 `
        --douyin  "<抖音视频链接或 aweme_id>" `
        --kuaishou "<快手视频链接或 photo_id>" `
        --bilibili "<B站视频链接或 BV 号>"

各参数可传完整视频链接(自动抽 ID)或直接传 ID。B站请挑一条**有 UP 置顶评论**的视频,
以便验证 normalizer 的“置顶→rank1”。生成的 JSON 落到 sidecar/tests/tikhub/fixtures/。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import pathlib

import httpx

BASE = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.dev").rstrip("/")
KEY = os.environ.get("TIKHUB_API_KEY")
OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "tikhub" / "fixtures"


def _resolve(url: str) -> str:
    """跟随重定向把分享短链(v.douyin.com / v.kuaishou.com / b23.tv 等)展开成
    含真实 ID 的长链。优先 curl_cffi(impersonate 真浏览器,躲开快手等平台对
    裸 httpx 的指纹拦截 / SSL 握手超时),失败回退带浏览器 UA 的 httpx。"""
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    try:
        from curl_cffi import requests as _cffi  # 项目已有依赖
        r = _cffi.get(url, impersonate="chrome120", allow_redirects=True, timeout=20)
        return str(r.url)
    except Exception:  # noqa: BLE001
        pass
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": ua})
        return str(r.url)
    except Exception as e:  # noqa: BLE001
        print(f"  (短链展开失败,按原样用: {e})")
        return url


def _extract(kind: str, raw: str) -> str:
    """从视频链接里抽 ID;短链先展开;传进来已经是纯 ID 就原样返回。"""
    raw = (raw or "").strip()
    if not raw:
        return raw
    # 分享短链先展开成长链再抽 ID
    if raw.startswith("http") and any(
        s in raw for s in ("v.douyin.com", "v.kuaishou.com", "kuaishou.com/f/", "b23.tv")
    ):
        raw = _resolve(raw)
    if kind == "zhihu":
        m = re.search(r"/question/(\d+)", raw)
        return m.group(1) if m else raw
    if kind == "douyin":
        m = re.search(r"/video/(\d+)", raw) or re.search(r"\b(\d{15,})\b", raw)
        return m.group(1) if m else raw
    if kind == "kuaishou":
        m = re.search(r"/short-video/([\w-]+)", raw) or re.search(r"/f/([\w-]+)", raw)
        return m.group(1) if m else raw
    if kind == "bilibili":
        m = re.search(r"(BV[0-9A-Za-z]+)", raw)
        return m.group(1) if m else raw
    return raw


def _get(path: str, params: dict) -> dict:
    r = httpx.get(f"{BASE}{path}", params=params,
                  headers={"Authorization": f"Bearer {KEY}"}, timeout=30)
    # 只打状态与长度,绝不打 header/body(可能含回显的 key)
    print(f"[{r.status_code}] {path} -> {len(r.content)} bytes")
    r.raise_for_status()
    return r.json()


def main() -> None:
    if not KEY:
        sys.exit("先设环境变量 TIKHUB_API_KEY")
    ap = argparse.ArgumentParser()
    for p in ("zhihu", "douyin", "kuaishou", "bilibili"):
        ap.add_argument(f"--{p}")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    jobs = []
    if a.zhihu:
        jobs.append(("zhihu_answers", "/api/v1/zhihu/web/fetch_question_answers",
                     {"question_id": _extract("zhihu", a.zhihu), "limit": 20}))
    if a.douyin:
        jobs.append(("douyin_comments", "/api/v1/douyin/app/v3/fetch_video_comments",
                     {"aweme_id": _extract("douyin", a.douyin), "count": 20, "cursor": 0}))
    if a.kuaishou:
        jobs.append(("kuaishou_comments", "/api/v1/kuaishou/app/fetch_video_comment",
                     {"photo_id": _extract("kuaishou", a.kuaishou)}))
    if a.bilibili:
        jobs.append(("bilibili_comments", "/api/v1/bilibili/app/fetch_video_comments",
                     {"bv_id": _extract("bilibili", a.bilibili), "mode": 3, "next_offset": 1}))
    if not jobs:
        sys.exit("至少给一个平台参数,如 --douyin <链接>")

    for name, path, params in jobs:
        try:
            data = _get(path, params)
        except Exception as e:  # noqa: BLE001 —— 探针,任何失败都打出来供人工看
            print(f"  !! {name} 抓取失败: {e}")
            continue
        dest = OUT / f"tikhub_{name}.json"
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  saved {dest.relative_to(OUT.parents[2])}")


if __name__ == "__main__":
    main()
