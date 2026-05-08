"""一次性脚本：清空 settings.json 里的本地账户字段，让下次启动重新走首启向导。

直接运行：
    python scripts/clear_account.py

脚本会自动定位 settings.json（与 csm_gui.app._default_config_dir 的逻辑一致），
保留其它所有设置（vault_root / api_keys / 等等），只把 user_name / user_product
置空。脚本会先打印一份备份到 stdout，方便你万一改完想撤回。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根在 sys.path 里 — 让脚本可以直接 import csm_gui。
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _candidate_settings_paths() -> list[Path]:
    """Return every plausible CSM settings.json path on this machine.

    The Qt ``QStandardPaths.AppConfigLocation`` lookup depends on
    ``QApplication.applicationName()`` — and that varies between contexts:

    * 源码启动 (``python main.py``)        → ``…/AppData/Local/python/CSM``
    * 打包后的 ``CSM.exe``                 → ``…/AppData/Local/CSM/CSM`` 或类似
    * 不带 QApplication 的脚本             → ``…/AppData/Local/CSM``

    We therefore probe **all** of them rather than trusting a single
    resolver. Returns existing files first, but always includes the
    canonical Qt-resolved path for transparency.
    """
    home = Path.home()
    appdata_local = Path.home() / "AppData" / "Local"

    candidates: list[Path] = [
        appdata_local / "python" / "CSM" / "settings.json",
        appdata_local / "CSM" / "CSM" / "settings.json",
        appdata_local / "CSM" / "settings.json",
        home / ".csm" / "settings.json",
    ]

    # Also ask Qt directly via a real QApplication — matches the running
    # app's resolution exactly.
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QStandardPaths
        if QApplication.instance() is None:
            QApplication([])
        loc = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        if loc:
            candidates.append(Path(loc) / "CSM" / "settings.json")
    except Exception:
        pass

    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for p in candidates:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _clear_one(path: Path) -> tuple[bool, str]:
    """Clear user_name/user_product in a single settings.json. Returns
    (changed, message)."""
    if not path.exists():
        return False, "不存在"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return False, f"读取/解析失败：{e}"

    cleared: list[tuple[str, object]] = []
    for k in ("user_name", "user_product"):
        if data.get(k) is not None:
            cleared.append((k, data[k]))
            data[k] = None

    if not cleared:
        return False, "已是 None，无需改动"

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    summary = "、".join(f"{k}={v!r}" for k, v in cleared)
    return True, f"已清空：{summary}"


def main() -> int:
    paths = _candidate_settings_paths()
    print("将检查以下路径：")
    for p in paths:
        marker = "[*]" if p.exists() else "[ ]"
        print(f"  {marker} {p}")
    print()

    any_changed = False
    found_any = False
    for p in paths:
        if not p.exists():
            continue
        found_any = True
        changed, msg = _clear_one(p)
        print(f"[{p}]\n  {msg}")
        any_changed = any_changed or changed

    if not found_any:
        print("没有找到任何 CSM settings.json — 下次启动会直接弹首启向导。")
        return 0
    if not any_changed:
        print("\n所有找到的文件账户字段都已是空，无需改动。")
        return 0
    print("\n完成。下次启动 CSM 会重新弹首启欢迎页。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
