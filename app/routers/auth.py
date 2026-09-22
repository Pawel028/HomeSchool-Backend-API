"""Sign-up, login, refresh-token rotation and logout."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from app import ratelimit
from app.deps import DbSession
from app.errors import ApiError, unauthenticated
from app.models import Family, FamilyMembership, RefreshToken, User
from app.schemas import LoginIn, RefreshIn, SignupIn, TokenOut
from app.security import hash_secret, now, token_digest, verify_secret
from app.services.auth import issue_tokens
from app.services.events import audit, emit

router = APIRouter(prefix="/v1/auth", tags=["auth"])
_DUMMY_HASH: str | None = None


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, request: Request, db: DbSession) -> TokenOut:
    ratelimit.check(f"signup:{_client_ip(request)}", 10, 3600)
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ApiError(422, "validation_error", "Unknown timezone.") from None
    email = body.email.strip()
    if db.scalar(select(User.id).where(func.lower(User.email) == email.lower())):
        raise ApiError(409, "email_taken")
    user = User(email=email, password_hash=hash_secret(body.password), full_name=body.full_name.strip())
    db.add(user)
    db.flush()
    family = Family(
        name=(body.family_name or f"{body.full_name.strip()}'s family")[:120],
        timezone=body.timezone,
        created_by=user.id,
    )
    db.add(family)
    db.flush()
    db.add(FamilyMembership(family_id=family.id, user_id=user.id, role="owner"))
    db.flush()
    audit(
        db,
        "user.signup",
        actor_user_id=user.id,
        family_id=family.id,
        entity="user",
        entity_id=user.id,
        request_id=request.state.request_id,
    )
    emit(db, "user.signed_up", {"user_id": user.id, "family_id": family.id}, aggregate_id=user.id)
    out, _ = issue_tokens(db, user)
    return out


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: DbSession) -> TokenOut:
    global _DUMMY_HASH
    email = body.email.strip().lower()
    ratelimit.check(f"login:{_client_ip(request)}:{email}", 10, 300)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        # Spend the same time as a real check so response timing does not reveal which emails exist.
        _DUMMY_HASH = _DUMMY_HASH or hash_secret("not-a-real-password")
        verify_secret(_DUMMY_HASH, body.password)
        raise ApiError(401, "invalid_credentials")
    if not verify_secret(user.password_hash, body.password) or user.status != "active":
        raise ApiError(401, "invalid_credentials")
    audit(
        db, "user.login", actor_user_id=user.id, entity="user", entity_id=user.id, request_id=request.state.request_id
    )
    out, _ = issue_tokens(db, user)
    return out


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: DbSession) -> TokenOut:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_digest(body.refresh_token)))
    if row is None:
        raise unauthenticated()
    if row.revoked_at is not None:
        # A rotated token was presented again: assume theft and revoke the whole chain. Commit before raising.
        for r in db.scalars(
            select(RefreshToken).where(RefreshToken.chain_id == row.chain_id, RefreshToken.revoked_at.is_(None))
        ):
            r.revoked_at = now()
        audit(
            db, "auth.refresh_reuse_detected", actor_user_id=row.user_id, entity="refresh_chain", entity_id=row.chain_id
        )
        db.commit()
        raise unauthenticated()
    if row.expires_at <= now():
        raise unauthenticated()
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        raise unauthenticated()
    out, new_row = issue_tokens(db, user, chain_id=row.chain_id)
    row.revoked_at = now()
    row.replaced_by = new_row.id
    return out


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: DbSession) -> Response:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_digest(body.refresh_token)))
    if row is not None:
        for r in db.scalars(
            select(RefreshToken).where(RefreshToken.chain_id == row.chain_id, RefreshToken.revoked_at.is_(None))
        ):
            r.revoked_at = now()
    return Response(status_code=204)
