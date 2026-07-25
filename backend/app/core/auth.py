"""Supabase JWT verification.

Tokens are verified against the project JWKS endpoint. `exp` and
`aud == "authenticated"` are enforced; `sub` becomes the user id.

Dev bypass: when ENV=dev, a request may authenticate with the `X-Dev-User-Id`
header instead of a token. The bypass is checked against live settings on every
request and is structurally impossible outside dev.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import get_settings

DEV_USER_HEADER = "X-Dev-User-Id"
SUPPORTED_ALGORITHMS = ["RS256", "ES256"]

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


@lru_cache
def get_jwks_client() -> PyJWKClient:
    """Cached JWKS client. Tests monkeypatch this to avoid network access."""
    return PyJWKClient(get_settings().jwks_url, cache_keys=True)


def verify_supabase_jwt(token: str, jwks_client: PyJWKClient | None = None) -> AuthenticatedUser:
    client = jwks_client or get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=SUPPORTED_ALGORITHMS,
        audience="authenticated",
        options={"require": ["exp", "sub", "aud"]},
    )
    return AuthenticatedUser(
        user_id=str(claims["sub"]),
        email=claims.get("email"),
        claims=claims,
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> AuthenticatedUser:
    settings = get_settings()

    if settings.is_dev:
        dev_user_id = request.headers.get(DEV_USER_HEADER)
        if dev_user_id:
            return AuthenticatedUser(
                user_id=dev_user_id,
                claims={"sub": dev_user_id, "dev_bypass": True},
            )

    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return verify_supabase_jwt(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from None
    except Exception:  # noqa: BLE001 — any verification failure must fail closed (401)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Token verification failed"
        ) from None


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
