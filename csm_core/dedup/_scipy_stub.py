"""scipy 替身 —— 让 PyInstaller 打包时可以把 scipy 整个排除出 sidecar。

背景：``datasketch`` 包的 ``__init__`` 会无条件 import ``lsh`` / ``lsh_bloom`` /
``weighted_minhash``，这三个模块在顶层 ``import scipy`` 或
``from scipy.integrate import quad``。我们只用 ``MinHash`` + ``MinHashLSH``，整个
运行期真正会执行到的 scipy 函数只有一个：``MinHashLSH.__init__`` →
``_optimal_param`` → ``quad``，对一个光滑的概率函数在 ``[0, threshold]`` 上做
定积分。为此把 scipy（Windows 上约 13 MB 压缩后体积）打进单文件 sidecar 不值。

方案：PyInstaller spec ``excludes=["scipy"]``，并用 runtime hook
（``sidecar/pyi_rth_scipy_stub.py``）在启动时调用 :func:`install_if_missing`：
真实 scipy 能 import 就什么都不做（dev 环境），import 失败才注册一个只带
``integrate.quad`` 的替身模块。``quad`` 用复合 Simpson 实现，
``tests/core/dedup/test_scipy_stub.py`` 逐项验证它给出的 ``(b, r)`` 与 scipy 完全一致。
"""
from __future__ import annotations

import sys
import types
from typing import Callable


def simpson_quad(
    func: Callable[..., float], a: float, b: float, args: tuple = (), n: int = 2000, **_: object,
) -> tuple[float, float]:
    """``scipy.integrate.quad`` 的最小替身：复合 Simpson，返回 ``(积分值, 误差估计)``。

    只接受 quad 的位置参数语义（``func(x, *args)``）；``n`` 为等分段数（偶数）。
    误差估计固定返回 0.0 —— datasketch 只用积分值。
    """
    if n % 2:
        n += 1
    h = (b - a) / n
    total = func(a, *args) + func(b, *args)
    for i in range(1, n):
        total += (4 if i % 2 else 2) * func(a + i * h, *args)
    return total * h / 3.0, 0.0


def install_if_missing() -> bool:
    """真实 scipy 可用 → 不动，返回 False；否则注册替身，返回 True。"""
    if "scipy" in sys.modules:
        return False
    try:
        import scipy  # noqa: F401  — dev 环境有真货就用真货
        return False
    except ImportError:
        pass
    integrate = types.ModuleType("scipy.integrate")
    integrate.quad = simpson_quad  # type: ignore[attr-defined]
    scipy_mod = types.ModuleType("scipy")
    scipy_mod.__path__ = []  # type: ignore[attr-defined]  # 让 ``import scipy.integrate`` 走包语义
    scipy_mod.integrate = integrate  # type: ignore[attr-defined]
    sys.modules["scipy"] = scipy_mod
    sys.modules["scipy.integrate"] = integrate
    return True
