"""手动跑一次百度 keyword 任务，不进 monitor_loop，结果打 stdout。

用法：
    cd <repo-root>
    python scripts/manual_test_baidu.py "<keyword1,keyword2>" "<single brand>"

    第一个参数：逗号分隔的多个关键词
    第二个参数：单个品牌词

示例：
    python scripts/manual_test_baidu.py "Claude Code 教程,Claude API 使用" "Claude"

可选环境变量：
    BAIDU_HEADLESS=0    # 默认 1
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import quote

# 让脚本能 import 项目内的 csm_core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms.baidu_keyword import ADAPTER


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    keywords = [k.strip() for k in argv[1].split(",") if k.strip()]
    brand = argv[2].strip()
    headless = os.environ.get("BAIDU_HEADLESS", "1") == "1"

    if not keywords:
        print("ERROR: 关键词列表为空", file=sys.stderr)
        return 2
    if not brand:
        print("ERROR: 品牌词为空", file=sys.stderr)
        return 2

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
        name=f"manual-{keywords[0]}",
        target_url=f"https://www.baidu.com/s?wd={quote(keywords[0])}",
        config={"search_keywords": keywords, "target_brand": brand},
    )

    print(f">> headless={headless} keywords={keywords!r} brand={brand!r}")
    result = ADAPTER.fetch(task)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
