"""Re-export shim. Real implementation in csm_core.browser_infra.rate_limit."""
from csm_core.browser_infra.rate_limit import *  # noqa: F401,F403
from csm_core.browser_infra.rate_limit import (  # noqa: F401
    RequestPacer, CircuitBreaker, slot,
    get_pacer, get_breaker, configure_pacing, configure_concurrency,
    acquire_slot, release_slot,
)
