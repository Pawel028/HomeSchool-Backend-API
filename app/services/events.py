"""Audit log and transactional outbox writers (ADR-012). Both write in the caller's transaction."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, OutboxEvent


def audit(
    db: Session,
    action: str,
    *,
    actor_user_id=None,
    actor_child_id=None,
    family_id=None,
    entity: str | None = None,
    entity_id: Any = None,
    request_id: str | None = None,
    **meta: Any,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            actor_child_id=actor_child_id,
            family_id=family_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            meta=meta,
            request_id=request_id,
        )
    )


def emit(db: Session, event_type: str, payload: dict[str, Any], aggregate_id: Any = None) -> None:
    """Queue a domain event. Payloads carry identifiers only, never names or free text."""
    clean = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in payload.items()}
    db.add(
        OutboxEvent(
            event_type=event_type, aggregate_id=str(aggregate_id) if aggregate_id is not None else None, payload=clean
        )
    )
