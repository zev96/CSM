"""手动跑一次百度 keyword 任务，不进 monitor_loop，结果打 stdout。

用法：
    cd <repo-root>
    python scripts/manual_test_baidu.py "Claude Code 教程" "Claude,Anthropic"

可选环境变量：
    BAIDU_HEADLESS=0    # 默认 1
"""
from __future__ import annotations

import json
import os
import sys

# 让脚本能 import 项目内的 csm_core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms.baidu_keyword import ADAPTER


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    keyword = argv[1]
    brands = [b.strip() for b in argv[2].split(",") if b.strip()]
    headless = os.environ.get("BAIDU_HEADLESS", "1") == "1"

    ADAPTER.apply_settings(
        headless_default=headless,
        captcha_visible_timeout_s=90,
        captcha_max_promotions=1,
        serp_pacing_seconds=5,
        breaker_failures=3,
        breaker_cooldown_seconds=600,
    )

    task = MonitorTask(
        id=999,
        type="baidu_keyword",
        name=f"manual-{keyword}",
        target_url=f"https://www.baidu.com/s?wd={keyword}",
        config={"search_keyword": keyword, "target_brands": brands},
    )

    print(f">> headless={headless} keyword={keyword!r} brands={brands}")
    result = ADAPTER.fetch(task)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
