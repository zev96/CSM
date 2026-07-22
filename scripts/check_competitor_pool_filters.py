"""扫描模板里 filter 为空的旧格式竞品池。

新的竞品卡（`素材类型: 竞品卡`）与旧的 `竞品-<型号>.md` 共用同一个目录。旧模板
的竞品池如果没设筛选条件，就会把新加的竞品卡也当成普通竞品笔记抽走 —— 整张卡的
markdown（含 H2 与 ①②③）会被当作一段推荐理由塞进老文章里，不报错、只是内容变得
莫名其妙。

用法：
    python -m scripts.check_competitor_pool_filters [模板目录]

不传目录则读配置里的默认模板目录。只读不改，退出码非 0 表示发现问题。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _template_dir(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1])
    try:
        from csm_sidecar.services import templates_service

        return templates_service.resolve_dir()
    except Exception:
        return Path("templates")


def scan(directory: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append(f"{path.name}: 读取失败 {e}")
            continue
        for block in data.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if block.get("kind") != "competitor_pool":
                continue
            if block.get("sections"):
                continue          # 卡片模式，schema 已强制要求 filter
            src = block.get("source") or {}
            if not src.get("filter"):
                problems.append(
                    f"{path.name} → 块 '{block.get('id')}'：竞品池没有筛选条件，"
                    f"目录 '{src.get('module', '')}' 下新增的竞品卡会被它误抽。"
                    f"建议加上 素材类型: 竞品推荐理由（或该目录里旧笔记实际用的值）。"
                )
    return problems


def main() -> int:
    directory = _template_dir(sys.argv)
    if not directory.exists():
        print(f"模板目录不存在：{directory}")
        return 2
    problems = scan(directory)
    if not problems:
        print(f"OK — {directory} 下没有发现空筛选的竞品池")
        return 0
    print(f"发现 {len(problems)} 处需要处理：")
    for p in problems:
        print(f"  · {p}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
