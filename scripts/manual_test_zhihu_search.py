"""手动联调 zhihu_search adapter。

用法（PowerShell）：
    $env:ZHIHU_SECRET="<你的 Access Secret>"
    python scripts/manual_test_zhihu_search.py 扫地机器人 戴森

参数：argv[1]=关键词（可多个用引号）、最后一个=目标品牌词。
不走 keyring，直接读环境变量 ZHIHU_SECRET，方便快速验证。
"""
from __future__ import annotations

import json
import os
import sys

from csm_core.monitor.base import MonitorTask
from csm_core.monitor.platforms import zhihu_search as zs


def main() -> None:
    secret = os.environ.get("ZHIHU_SECRET", "")
    if not secret:
        print("请先设置环境变量 ZHIHU_SECRET", file=sys.stderr)
        sys.exit(1)
    if len(sys.argv) < 3:
        print("用法: python scripts/manual_test_zhihu_search.py <关键词...> <品牌词>", file=sys.stderr)
        sys.exit(1)
    *keywords, brand = sys.argv[1:]

    # monkeypatch read_api_key 直接返回环境变量里的 secret
    zs.read_api_key = lambda provider: secret  # type: ignore[assignment]

    task = MonitorTask(
        type="zhihu_search", name="manual", target_url="https://z", id=0,
        config={"search_keywords": keywords, "target_brand": brand, "count": 10},
    )
    result = zs.ADAPTER.fetch(task)
    print(f"status={result.status} rank={result.rank}")
    print(json.dumps(result.metric, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
