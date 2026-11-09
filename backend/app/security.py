"""Password hashing (bcrypt) and JWT bearer tokens."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import unauthorized
from app.models import User

_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    # bcrypt only reads the first 72 bytes and the library raises on longer input. A Hindi password of
    # 30 characters is already ~90 bytes in UTF-8, so truncate the bytes explicitly (same on verify).
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
    except ValueError:
        return False


def create_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=s.jwt_expires_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm=_ALGORITHM)


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise unauthorized("Your session has expired. Please log in again.") from e
    except jwt.InvalidTokenError as e:
        raise unauthorized("Invalid token") from e
    return str(payload["sub"])


def current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized()
    user = db.get(User, decode_token(authorization[7:].strip()))
    if user is None:
        raise unauthorized("This account no longer exists")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
