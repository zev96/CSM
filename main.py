"""CSM — Content SEO Maker  启动入口

直接运行：
    python main.py
或双击此文件（配合 .venv 或系统 Python）即可启动应用。
"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中（双击运行时工作目录可能不同）
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csm_gui.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
