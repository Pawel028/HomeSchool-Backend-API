from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    """Liveness: the process is up (no dependencies touched)."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    """Readiness: the database answers."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
    except Exception:  # noqa: BLE001
        raise ApiError(503, "internal_error", "Database is not reachable.") from None
    return {"status": "ready"}


@router.get("/v1/config")
def client_config() -> dict:
    """Public, non-secret client configuration (minimum app version, notice version, feature flags)."""
    s = get_settings()
    return {
        "env": s.app_env,
        "min_app_version": s.min_app_version,
        "declaration_notice_version": s.declaration_notice_version,
        "guardian_verification": "otp_declaration",
        "features": {"recommendations": s.enable_recommendations},
    }
