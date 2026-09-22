"""Content admin API (platform_role content_admin or super_admin). Admins never see family or child data (RLS)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.deps import AdminActor, DbSession
from app.errors import ApiError, not_found
from app.models import Activity, ActivitySkill, Family, Skill, User
from app.schemas import (
    AdminActivityDetail,
    AdminActivitySummary,
    AdminDefinitionIn,
    AdminStats,
    AdminStatusIn,
    BundleIn,
    BundleReport,
)
from app.security import now
from app.services import catalog
from app.services.events import audit

router = APIRouter(prefix="/v1/admin", tags=["admin"])
TRANSITIONS = {
    "draft": {"in_review", "archived"},
    "in_review": {"draft", "published", "archived"},
    "published": {"archived"},
    "archived": {"draft"},
}


def _detail(db, a: Activity) -> AdminActivityDetail:
    codes = sorted(db.scalars(select(ActivitySkill.skill_code).where(ActivitySkill.activity_id == a.id)))
    base = AdminActivitySummary.model_validate(a).model_dump()
    return AdminActivityDetail(**base, skills=codes, definition=a.definition)


def _get(db, activity_id: uuid.UUID) -> Activity:
    a = db.get(Activity, activity_id)
    if a is None:
        raise not_found()
    return a


@router.get("/stats", response_model=AdminStats)
def stats(actor: AdminActor, db: DbSession) -> AdminStats:
    by_status = dict(db.execute(select(Activity.status, func.count()).group_by(Activity.status)).all())
    return AdminStats(
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        families=db.scalar(select(func.count()).select_from(Family)) or 0,
        activities_by_status=by_status,
        skills=db.scalar(select(func.count()).select_from(Skill)) or 0,
    )


@router.get("/activities", response_model=list[AdminActivitySummary])
def list_activities(
    actor: AdminActor,
    db: DbSession,
    status: str | None = None,
    subject: str | None = None,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Activity]:
    stmt = select(Activity)
    if status:
        stmt = stmt.where(Activity.status == status)
    if subject:
        stmt = stmt.where(Activity.subject_code == subject)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Activity.title).like(like), func.lower(Activity.slug).like(like)))
    return list(db.scalars(stmt.order_by(Activity.updated_at.desc()).limit(limit).offset(offset)))


@router.get("/activities/{activity_id}", response_model=AdminActivityDetail)
def get_activity(activity_id: uuid.UUID, actor: AdminActor, db: DbSession) -> AdminActivityDetail:
    return _detail(db, _get(db, activity_id))


@router.put("/activities/{activity_id}/definition", response_model=AdminActivityDetail)
def put_definition(
    activity_id: uuid.UUID, body: AdminDefinitionIn, actor: AdminActor, db: DbSession
) -> AdminActivityDetail:
    a = _get(db, activity_id)
    catalog.update_definition(db, a, body.definition)
    audit(
        db,
        "content.definition_updated",
        actor_user_id=actor.user_id,
        entity="activity",
        entity_id=a.id,
        version=a.version,
        request_id=actor.request_id,
    )
    return _detail(db, a)


@router.post("/activities/{activity_id}/status", response_model=AdminActivityDetail)
def set_status(activity_id: uuid.UUID, body: AdminStatusIn, actor: AdminActor, db: DbSession) -> AdminActivityDetail:
    a = _get(db, activity_id)
    if body.status == a.status:
        return _detail(db, a)
    if body.status not in TRANSITIONS[a.status]:
        raise ApiError(409, "conflict", f"Cannot move from {a.status} to {body.status}.")
    if body.status == "published":
        catalog.publish(db, a)
    else:
        a.status = body.status
    a.updated_at = now()
    audit(
        db,
        "content.status_changed",
        actor_user_id=actor.user_id,
        entity="activity",
        entity_id=a.id,
        status=a.status,
        request_id=actor.request_id,
    )
    return _detail(db, a)


@router.post("/content/bundle", response_model=BundleReport)
def import_bundle(body: BundleIn, actor: AdminActor, db: DbSession) -> BundleReport:
    report = catalog.import_bundle(db, body)
    if not body.dry_run and report.ok:
        audit(
            db,
            "content.bundle_imported",
            actor_user_id=actor.user_id,
            entity="bundle",
            entity_id=body.version,
            created=report.created,
            updated=report.updated,
            request_id=actor.request_id,
        )
    return report
