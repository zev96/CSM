"""Shared browser-automation primitives used by both monitor and mining.

Originally lived under ``csm_core/monitor/drivers/``; promoted to a
top-level package when the mining module was added so it could be
imported without pulling in monitor-specific code.

Re-export shims remain under ``csm_core/monitor/drivers/`` and
``csm_core/monitor/`` so existing imports continue to work unchanged.
"""

from . import mining_browser

__all__ = ["mining_browser"]
