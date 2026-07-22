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


def _template_dir(argv: list[str]) -> tuple[Path, bool]:
    """返回 (模板目录, 是否读到了真实配置)。

    读不到配置时会回退扫 ./templates —— 但必须让调用者知道，否则会打印一句
    「OK，没发现问题」，而用户真正的模板库根本没被扫过。
    """
    if len(argv) > 1:
        return Path(argv[1]), True
    try:
        from csm_sidecar.services import templates_service

        return templates_service.resolve_dir(), True
    except Exception:
        return Path("templates"), False


def scan(directory: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append(f"{path.name}: 读取失败 {e}")
            continue
        if not isinstance(data, dict):
            # 顶层不是对象的 .json 直接跳过 —— 早期实现在这里 AttributeError
            # 崩掉，字母序在它后面的模板一个都扫不到，而 loader 对同样的坏
            # 文件是容错的。
            problems.append(f"{path.name}: 不是模板（顶层不是 JSON 对象）")
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
    directory, resolved = _template_dir(sys.argv)
    if not resolved:
        print(
            f"注意：没能读取应用配置（csm_sidecar 不在 import 路径上），"
            f"回退扫描相对目录 {directory}。要扫真实模板库请把目录作为参数传进来。"
        )
    if not directory.exists():
        print(f"模板目录不存在：{directory}")
        return 2
    try:
        problems = scan(directory)
    except Exception as e:      # 扫描本身崩了要与「发现问题」区分开
        print(f"扫描失败：{e}")
        return 2
    if not problems:
        print(f"OK — {directory} 下没有发现空筛选的竞品池")
        return 0
    print(f"发现 {len(problems)} 处需要处理：")
    for p in problems:
        print(f"  · {p}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
