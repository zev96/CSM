"""Bearer-token auth for the local sidecar.

The sidecar is bound to 127.0.0.1 only, but a token is still required so
that other processes on the same machine cannot drive the API. Tauri
captures the token from the sidecar's first stdout line at spawn time and
attaches it to every request.

Two delivery channels are accepted:

* ``Authorization: Bearer <token>`` header — for normal HTTP requests
  (axios attaches it automatically via the sidecar store).
* ``?token=<token>`` query string — needed for SSE endpoints because the
  browser's ``EventSource`` API does not let JS set custom headers. Only
  GET routes ever read the query token; mutating routes still require
  the header.
"""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, status

_TOKEN: str | None = None


def generate_token() -> str:
    """Mint a fresh 32-byte URL-safe token. Call once during startup."""
    global _TOKEN
    _TOKEN = secrets.token_urlsafe(32)
    return _TOKEN


def get_token() -> str:
    if _TOKEN is None:
        raise RuntimeError("auth.generate_token() was never called")
    return _TOKEN


async def require_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> None:
    """FastAPI dependency: enforce a valid token on either channel.

    Header is checked first (it's the normal path). Query string is only
    accepted on GET requests so a stray ``?token=`` on a POST can't slip
    auth past where the browser would normally enforce same-origin.
    """
    if _TOKEN is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sidecar auth not initialised",
        )

    presented: str | None = None
    if authorization and authorization.startswith("Bearer "):
        presented = authorization.removeprefix("Bearer ").strip()
    elif token and request.method == "GET":
        presented = token

    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    # secrets.compare_digest avoids timing-leak side channels even though
    # this is a localhost-only daemon — defence in depth costs nothing.
    if not secrets.compare_digest(presented, _TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
        )


RequireToken = Depends(require_token)
