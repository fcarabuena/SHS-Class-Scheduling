from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import Role, School, User
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

SUSPENDED = "This school's account is suspended. Please contact the service administrator."

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    # Role and school are re-read from the database on every request, so a
    # deactivated or demoted user loses access immediately.
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    if db.get(School, user.school_id).status == "suspended" and not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, SUSPENDED)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not allow this action")
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles(Role.admin))]
EditorUser = Annotated[User, Depends(require_roles(Role.admin, Role.scheduler))]


def require_platform_admin(user: CurrentUser) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only platform administrators can do this")
    return user


PlatformAdmin = Annotated[User, Depends(require_platform_admin)]
