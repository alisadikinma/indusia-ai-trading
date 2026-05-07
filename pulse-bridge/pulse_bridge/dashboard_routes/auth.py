"""JWT verification — matches dashboard-ui/src/lib/auth.ts conventions exactly.

- HS256
- Issuer:  "bot-cockpit"
- Audience: "bot-cockpit-operator"
- Token source priority: Authorization: Bearer <token> header,
  then HTTP-only cookie named SESSION_COOKIE_NAME ("bot_cockpit_session").
- Hard-fail (no silent default) on missing DASHBOARD_JWT_SECRET — Iron Law 3.
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt

# Must match dashboard-ui/src/lib/auth.ts
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "bot-cockpit"
JWT_AUDIENCE = "bot-cockpit-operator"
SESSION_COOKIE_NAME = "bot_cockpit_session"


def _get_secret() -> str:
    secret = os.environ.get("DASHBOARD_JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "Missing DASHBOARD_JWT_SECRET — pulse-bridge dashboard refuses to verify "
            "JWTs without an explicit shared secret. Set the same value used by dashboard-ui."
        )
    if len(secret) < 32:
        raise RuntimeError(
            "DASHBOARD_JWT_SECRET must be at least 32 characters long."
        )
    return secret


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip() or None
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        return cookie
    return None


def _decode(token: str) -> dict:
    secret = _get_secret()
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired session: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def verify_jwt(request: Request) -> dict:
    """FastAPI dependency: returns the decoded JWT payload or raises 401."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode(token)
    if payload.get("role") != "operator" or not isinstance(payload.get("sub"), str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def verify_jwt_token(token: str) -> dict:
    """Plain-token verifier for the WebSocket handshake (where Depends is unwieldy)."""
    payload = _decode(token)
    if payload.get("role") != "operator" or not isinstance(payload.get("sub"), str):
        raise HTTPException(status_code=401, detail="Invalid session payload.")
    return payload


# Re-usable Depends() instance for routers that want it as a dependency.
JwtDep = Annotated[dict, Depends(verify_jwt)]
jwt_dep = Depends(verify_jwt)
