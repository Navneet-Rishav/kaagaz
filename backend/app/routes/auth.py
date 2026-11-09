from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.ratelimit import limiter
from app.security import CurrentUser, create_token, hash_password, verify_password
from app.services.demo_data import create_demo_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    is_demo: bool


class SessionOut(BaseModel):
    token: str
    user: UserOut


def _session(user: User) -> SessionOut:
    return SessionOut(
        token=create_token(user.id), user=UserOut(id=user.id, name=user.name, email=user.email, is_demo=user.is_demo)
    )


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Annotated[Session, Depends(get_db)]) -> SessionOut:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ApiError(409, "email_taken", "An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return _session(user)


@router.post("/login")
def login(body: LoginIn, db: Annotated[Session, Depends(get_db)]) -> SessionOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # Same message for unknown email and wrong password, so the endpoint does not reveal which emails exist.
    if not user or user.is_demo or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect")
    return _session(user)


@router.post("/demo")
def demo(request: Request, db: Annotated[Session, Depends(get_db)]) -> SessionOut:
    """One-click demo login. Each click gets a fresh, isolated demo account (no usable password) seeded with
    the three sample documents, so visitors never see each other's uploads. Expires after 24 hours."""
    ip = request.client.host if request.client else "unknown"
    limiter.hit("demo", ip, limit=20)  # per IP per hour: each demo account runs the pipeline 3 times
    return _session(create_demo_user(db))


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, name=user.name, email=user.email, is_demo=user.is_demo)
