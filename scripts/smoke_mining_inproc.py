# -*- coding: utf-8 -*-
"""Level-1 in-process smoke test for a single mining adapter.

Unlike scripts/smoke_run_*.py (which hit a running sidecar via HTTP),
this script imports the adapter directly and runs it in the current
Python process. Faster iteration when debugging an adapter — no
Tauri/Vite/sidecar boot required. It DOES NOT exercise the
runner/storage layer, so use the HTTP scripts for full-pipeline checks.

Pre-conditions:
  1. monitor.db must contain an enabled credential for the target
     platform (platform="<plat>_comment"). Set up via:
       - 监控中心 → 凭据管理 → 添加 (interactive login or cookie paste)
     OR run the app once and login through the existing UI.
  2. .auth/browser_profiles/ — created automatically on first run

Usage:
  python scripts/smoke_mining_inproc.py douyin "测试" 5
  python scripts/smoke_mining_inproc.py kuaishou "扫地机器人" 10
  python scripts/smoke_mining_inproc.py bilibili "测评" 5

Diagnostic hints:
  outcome.status == "needs_login"   → no cookie in monitor.db OR cookie
                                       extraction returned empty / API
                                       said session invalid
  outcome.status == "risk_control"  → captcha / IP throttle hit
  outcome.status == "failed"        → see outcome.error_message
  outcome.status == "done", cards=0 → check the logs; for Douyin this
                                       means XHR never fired (search page
                                       not interactive); for Kuaishou
                                       this means GraphQL returned no
                                       feeds; for Bilibili this means
                                       WBI API returned an empty result.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="In-process smoke test for one mining adapter.",
    )
    ap.add_argument("platform", choices=["douyin", "bilibili", "kuaishou"])
    ap.add_argument("keyword")
    ap.add_argument("target_count", type=int, nargs="?", default=5)
    args = ap.parse_args()

    # Make repo root importable when running as `python scripts/foo.py`.
    ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(ROOT))

    # UTF-8 stdout on Windows so 中文 标题 doesn't garble.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Quiet a couple of chatty libraries — keep adapter + browser_infra
    # at INFO so you can see the interesting events.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    from csm_core import config as core_config
    from csm_core.browser_infra import mining_browser

    # Use the same path the sidecar uses (lifespan.py:102). Cookies in
    # monitor.db override profile state at injection time, so even a
    # fresh profile dir works as long as monitor.db has the credential.
    profile_root = (
        core_config.default_config_dir() / ".auth" / "browser_profiles"
    )
    mining_browser.configure_profile_root(profile_root)
    print(f"profile_root: {profile_root}")

    has_cookie = mining_browser.has_login_cookie(args.platform)
    print(f"monitor.db has enabled credential for {args.platform!r}: {has_cookie}")
    if not has_cookie:
        print(
            f"\n!! No credential found. Set one up via 监控中心 → 凭据管理 "
            f"(platform={args.platform}_comment) before re-running.",
        )
        return 2

    if args.platform == "douyin":
        from csm_core.mining.platforms.douyin_search import DouyinSearchAdapter
        adapter = DouyinSearchAdapter()
    elif args.platform == "kuaishou":
        from csm_core.mining.platforms.kuaishou_search import KuaishouSearchAdapter
        adapter = KuaishouSearchAdapter()
    else:
        from csm_core.mining.platforms.bilibili_search import BilibiliSearchAdapter
        adapter = BilibiliSearchAdapter()

    print(
        f"\n=== running {args.platform} adapter "
        f"keyword={args.keyword!r} target={args.target_count} ===\n",
        flush=True,
    )

    def on_card(card) -> None:
        title = (card.title or "")[:50]
        print(
            f"  #{card.rank_in_search:>2}  {card.platform_video_id:<22}  "
            f"{title:<50}  {card.url}",
            flush=True,
        )

    def on_progress(p) -> None:
        print(f"[progress] phase={p.phase} got={p.got}/{p.target}", flush=True)

    cancel_event = threading.Event()
    try:
        outcome = adapter.search(
            keyword=args.keyword,
            target_count=args.target_count,
            on_card=on_card,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
    except KeyboardInterrupt:
        cancel_event.set()
        print("\n!! interrupted", flush=True)
        return 130
    except Exception as e:
        logging.exception("adapter raised: %s", e)
        return 1

    print(
        f"\n=== outcome: status={outcome.status} "
        f"cards_emitted={outcome.cards_emitted} "
        f"error={outcome.error_message!r} ==="
    )
    return 0 if outcome.status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
