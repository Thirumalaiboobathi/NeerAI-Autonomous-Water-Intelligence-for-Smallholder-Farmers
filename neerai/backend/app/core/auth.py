"""Cognito JWT verification and the per-request Principal.

Every data access in the API is scoped to `Principal.user_id` (the verified `sub` claim). A user id supplied by the
client in a path, query or body is never trusted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import jwt
from fastapi import HTTPException, Request

from .config import Settings

log = logging.getLogger("neerai.auth")

LOCAL_USER = "local"
# The single identity behind unauthenticated demo mode. Cognito `sub` values are UUIDs, so this can never equal a real
# user id: demo data is structurally separate from real users' records (the owner is part of every storage key).
DEMO_USER = "demo-public"


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: Optional[str] = None


class KeyResolver(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class CognitoVerifier:
    """Verifies Cognito *access* tokens: signature (JWKS), issuer, expiry, token_use and app client id."""

    def __init__(self, settings: Settings, key_resolver: KeyResolver | None = None):
        self.issuer = settings.cognito_issuer
        self.client_id = settings.cognito_client_id
        self.keys: KeyResolver = key_resolver or jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)

    def verify(self, token: str) -> Principal:
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key if hasattr(key, "key") else key, algorithms=["RS256"], issuer=self.issuer,
                options={"require": ["exp", "iss", "sub", "token_use"], "verify_aud": False},
                leeway=10,
            )
        except jwt.PyJWTError as e:
            log.info("token rejected: %s", type(e).__name__)
            raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from e
        if claims.get("token_use") != "access" or claims.get("client_id") != self.client_id:
            raise HTTPException(401, "token not issued for this application", headers={"WWW-Authenticate": "Bearer"})
        sub = str(claims["sub"])
        if not sub or "#" in sub or len(sub) > 64:
            raise HTTPException(401, "invalid subject")
        return Principal(user_id=sub)


def current_principal(request: Request) -> Principal:
    st = request.app.state.neerai
    if st.settings.auth_mode == "none":
        return Principal(LOCAL_USER)
    if st.settings.auth_mode == "demo":
        return Principal(DEMO_USER)  # any Authorization header, user id header or body field is ignored
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})
    return st.verifier.verify(token.strip())
