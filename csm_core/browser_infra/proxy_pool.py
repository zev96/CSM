"""User-supplied HTTP/SOCKS proxy pool with rotation strategies.

Config file: <config_dir>/proxies.json (path comes from AppConfig.proxies_path)

{
  "enabled": true,
  "rotation_strategy": "on_risk_control" | "per_task" | "per_request" | "daily",
  "proxies": [
    {"server": "http://user:pass@1.2.3.4:8080", "tags": ["cn", "residential"]},
    {"server": "http://5.6.7.8:8080"}
  ]
}

Default strategy: on_risk_control -- sticky, only rotates after caller signals
risk via mark_failed(). For most scrape sessions this means one proxy per pool
lifetime; rotation happens only when detection fires.
"""
from __future__ import annotations

import json
import logging
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

RotationStrategy = Literal["on_risk_control", "per_task", "per_request", "daily"]

_MAX_CONSECUTIVE_FAILURES = 3


class ProxyPool:
    """Thread-safe proxy chooser.

    Reads <config_path>/proxies.json on construction; no live reloading.
    Restart the sidecar to pick up config changes.
    """

    def __init__(self, config_path: Path) -> None:
        self._lock = threading.Lock()
        self._path = Path(config_path)
        self._fail_counts: dict[str, int] = {}
        self._disabled: set[str] = set()
        self._current: str | None = None
        self._current_pinned_at: datetime | None = None
        self._last_failed: str | None = None  # avoid re-picking same server after single failure
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self.enabled = False
            self._proxies: list[dict[str, Any]] = []
            self._strategy: RotationStrategy = "on_risk_control"
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("proxy_pool: failed to parse %s: %s", self._path, e)
            self.enabled = False
            self._proxies = []
            self._strategy = "on_risk_control"
            return
        self.enabled = bool(data.get("enabled", False))
        self._strategy = data.get("rotation_strategy", "on_risk_control")
        self._proxies = list(data.get("proxies", []))

    def available_proxies(self) -> list[dict[str, Any]]:
        """List of proxy dicts not in the disabled set."""
        with self._lock:
            return [p for p in self._proxies if p["server"] not in self._disabled]

    def pick(self) -> str | None:
        """Return current proxy server URL per rotation strategy.
        Returns None if disabled or no usable proxies."""
        if not self.enabled:
            return None
        with self._lock:
            available = [p for p in self._proxies if p["server"] not in self._disabled]
            if not available:
                return None

            if self._strategy == "on_risk_control":
                if self._current and self._current not in self._disabled:
                    return self._current
                # Prefer a proxy other than the last failed one so rotation is meaningful.
                candidates = [p for p in available if p["server"] != self._last_failed]
                if not candidates:
                    candidates = available  # only one proxy left; accept it
                choice = random.choice(candidates)
                self._current = choice["server"]
                self._last_failed = None
                return self._current

            if self._strategy == "per_request":
                return random.choice(available)["server"]

            if self._strategy == "per_task":
                # Same as on_risk_control sticky -- caller decides when "task" boundary is.
                # Tasks typically last 5-10 min, much shorter than reaper idle.
                if self._current and self._current not in self._disabled:
                    return self._current
                # Prefer a proxy other than the last failed one so rotation is meaningful.
                candidates = [p for p in available if p["server"] != self._last_failed]
                if not candidates:
                    candidates = available
                choice = random.choice(candidates)
                self._current = choice["server"]
                self._last_failed = None
                return self._current

            if self._strategy == "daily":
                # Rotate once per UTC day. Pin current_pinned_at; if same UTC date,
                # return current. Otherwise re-pick.
                now = datetime.now(timezone.utc)
                if (
                    self._current_pinned_at
                    and self._current
                    and self._current not in self._disabled
                    and self._current_pinned_at.date() == now.date()
                ):
                    return self._current
                choice = random.choice(available)
                self._current = choice["server"]
                self._current_pinned_at = now
                return self._current

            # Unknown strategy: random
            return random.choice(available)["server"]

    def mark_failed(self, server: str) -> None:
        """Record a failure. After 3 consecutive failures, the proxy goes to _disabled.
        Sticky strategies (on_risk_control, per_task) clear _current so next pick rotates."""
        with self._lock:
            self._fail_counts[server] = self._fail_counts.get(server, 0) + 1
            if self._fail_counts[server] >= _MAX_CONSECUTIVE_FAILURES:
                self._disabled.add(server)
                logger.warning(
                    "proxy_pool: disabled %s after %d failures", server, _MAX_CONSECUTIVE_FAILURES
                )
            if self._current == server:
                self._current = None
                self._current_pinned_at = None
            self._last_failed = server

    def mark_success(self, server: str) -> None:
        """Reset failure counter for a proxy."""
        with self._lock:
            self._fail_counts.pop(server, None)
