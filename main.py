"""CSM — Content SEO Maker  启动入口

直接运行：
    python main.py
或双击此文件（配合 .venv 或系统 Python）即可启动应用。
"""
import sys
import traceback
from pathlib import Path

# PyInstaller 冻结后用 exe 同目录；源码运行用项目根目录。
ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    try:
        from csm_gui.app import run
        sys.exit(run())
    except BaseException:
        tb = traceback.format_exc()
        try:
            (ROOT / "csm_crash.log").write_text(tb, encoding="utf-8")
        except Exception:
            pass
        try:
            sys.stderr.write(tb)
            sys.stderr.flush()
        except Exception:
            pass
        # 控制台版防闪退：等用户看完再关
        try:
            input("按回车关闭...")
        except Exception:
            pass
        sys.exit(1)
