"""Risk-control detection bridge for mining adapters.

Wraps ``csm_core.monitor.drivers.risk_detector`` so mining never imports
``monitor.drivers`` directly from the adapter code (single-direction
dependency hygiene — keep platform adapters insulated from monitor
internals; if the detector ever moves, only this file changes).

The 4-layer detection (URL / HTTP / DOM / page text) lives in the monitor
module because monitor needed it first. Mining reuses it as-is.
"""
from __future__ import annotations

from typing import Any

from csm_core.monitor.drivers import risk_detector


def detect(page: Any, response: Any = None) -> bool:
    """Run the 4-layer risk-control check on a Patchright Page.

    Returns ``True`` if any of (URL pattern / HTTP status / DOM selector /
    page text) matches. Caller should then bail with
    ``SearchOutcome.status='risk_control'``. Detection never raises —
    individual layer failures are swallowed inside the detector.
    """
    return risk_detector.detect_risk(page, response) is not None


def detect_signal(page: Any, response: Any = None):
    """Same as ``detect()`` but returns the ``RiskSignal`` on hit, else ``None``.

    Useful when the caller wants to log the layer (``url`` / ``dom`` /
    ``text`` / ``http``) and the specific detail that triggered.
    """
    return risk_detector.detect_risk(page, response)
