from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from .tokens import decode_access_token
from .users import UserStore


@dataclass
class AuthUser:
    id: str
    username: str


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def resolve_auth_user(
    authorization: str | None,
    cookie_token: str | None,
    user_store: UserStore,
) -> AuthUser | None:
    token = _parse_bearer(authorization) or (cookie_token.strip() if cookie_token else None)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user = user_store.get_by_id(str(payload["sub"]))
    if not user:
        return None
    return AuthUser(id=user.id, username=user.username)


def get_current_user(
    authorization: str | None,
    cookie_token: str | None,
    user_store: UserStore | None,
) -> AuthUser:
    if user_store is None:
        raise HTTPException(status_code=500, detail="认证服务未初始化")
    user = resolve_auth_user(authorization, cookie_token, user_store)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user
