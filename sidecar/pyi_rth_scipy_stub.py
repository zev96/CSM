# PyInstaller runtime hook —— 在入口脚本之前执行。
# scipy 已从 bundle 排除（spec ``excludes``），datasketch 顶层 import 需要一个
# 只带 ``integrate.quad`` 的替身；实现与说明见 csm_core/dedup/_scipy_stub.py。
from csm_core.dedup._scipy_stub import install_if_missing

install_if_missing()
