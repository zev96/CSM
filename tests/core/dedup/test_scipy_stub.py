"""scipy 替身（打包时排除 scipy）必须与真 scipy 给出完全相同的 LSH 参数。"""
from __future__ import annotations

import sys
import types

import pytest

from csm_core.dedup import _scipy_stub


def test_simpson_quad_matches_scipy_for_datasketch_optimal_param():
    scipy_integrate = pytest.importorskip("scipy.integrate")
    import datasketch.lsh as lsh_mod

    combos = [(t, p) for t in (0.2, 0.3, 0.5, 0.8) for p in (64, 128, 256)]
    original = lsh_mod.integrate
    assert original is scipy_integrate.quad
    try:
        expected = {c: lsh_mod._optimal_param(c[0], c[1], 0.5, 0.5) for c in combos}
        lsh_mod.integrate = _scipy_stub.simpson_quad
        got = {c: lsh_mod._optimal_param(c[0], c[1], 0.5, 0.5) for c in combos}
    finally:
        lsh_mod.integrate = original
    assert got == expected


def test_simpson_quad_basic_integral():
    value, err = _scipy_stub.simpson_quad(lambda x: x * x, 0.0, 3.0)
    assert abs(value - 9.0) < 1e-9
    assert err == 0.0


def test_install_if_missing_registers_stub_only_when_scipy_absent(monkeypatch):
    # 真 scipy 在 → 不动
    if "scipy" in sys.modules or _has_real_scipy():
        assert _scipy_stub.install_if_missing() is False
    # 模拟打包环境：把 scipy 从 sys.modules 摘掉并让 import 失败
    saved = {k: v for k, v in sys.modules.items() if k == "scipy" or k.startswith("scipy.")}
    for k in saved:
        monkeypatch.delitem(sys.modules, k)
    import importlib.abc

    class _Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name == "scipy" or name.startswith("scipy."):
                raise ImportError("blocked")

    blocker = _Block()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
    assert _scipy_stub.install_if_missing() is True
    import scipy.integrate as stub  # 走 sys.modules 缓存

    assert isinstance(sys.modules["scipy"], types.ModuleType)
    assert stub.quad is _scipy_stub.simpson_quad
    # 清理：monkeypatch 会还原 meta_path 与被删的条目；这里再摘掉替身
    for k in ("scipy", "scipy.integrate"):
        sys.modules.pop(k, None)
    sys.modules.update(saved)


def _has_real_scipy() -> bool:
    try:
        import scipy  # noqa: F401
        return True
    except ImportError:
        return False
