import secrets
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.security import CurrentUser, create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

DEMO_EMAIL = "demo@kaagaz.demo"


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
def demo(db: Annotated[Session, Depends(get_db)]) -> SessionOut:
    """One-click demo login. The demo user has no usable password and owns the seeded sample documents."""
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(email=DEMO_EMAIL, name="Demo User", is_demo=True, password_hash=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        db.commit()
    return _session(user)


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, name=user.name, email=user.email, is_demo=user.is_demo)
