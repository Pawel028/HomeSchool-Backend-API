"""Read-only curriculum and activity catalogue (published content only; answer keys are never returned)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.deps import CurrentActor, DbSession
from app.errors import not_found
from app.models import Activity, ActivitySkill, Interest, Level, Skill, SkillPrerequisite, Subject
from app.schemas import ActivityDetail, ActivitySummary, LevelOut, SkillOut, SubjectOut
from app.services.content import public_definition

router = APIRouter(prefix="/v1", tags=["curriculum"])


@router.get("/curriculum/levels", response_model=list[LevelOut])
def levels(actor: CurrentActor, db: DbSession) -> list[Level]:
    return list(db.scalars(select(Level).order_by(Level.sort_order)))


@router.get("/curriculum/subjects", response_model=list[SubjectOut])
def subjects(actor: CurrentActor, db: DbSession) -> list[Subject]:
    return list(db.scalars(select(Subject).order_by(Subject.display_order)))


@router.get("/curriculum/interests")
def interests(actor: CurrentActor, db: DbSession) -> list[dict]:
    return [{"code": i.code, "name": i.name} for i in db.scalars(select(Interest).order_by(Interest.name))]


@router.get("/curriculum/skills", response_model=list[SkillOut])
def skills(actor: CurrentActor, db: DbSession, subject: str | None = None, level: str | None = None) -> list[SkillOut]:
    q = select(Skill).order_by(Skill.subject_code, Skill.level_code, Skill.code)
    if subject:
        q = q.where(Skill.subject_code == subject)
    if level:
        q = q.where(Skill.level_code == level)
    rows = list(db.scalars(q))
    pre: dict[str, list[str]] = {}
    for p in db.scalars(select(SkillPrerequisite)):
        pre.setdefault(p.skill_code, []).append(p.prerequisite_code)
    return [
        SkillOut(
            code=s.code,
            subject_code=s.subject_code,
            level_code=s.level_code,
            name=s.name,
            prerequisites=sorted(pre.get(s.code, [])),
        )
        for s in rows
    ]


@router.get("/activities", response_model=list[ActivitySummary])
def list_activities(
    actor: CurrentActor,
    db: DbSession,
    subject: str | None = None,
    level: str | None = None,
    interest: str | None = None,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Activity]:
    stmt = select(Activity).where(Activity.status == "published")
    if subject:
        stmt = stmt.where(Activity.subject_code == subject)
    if level:
        lv = {c: o for c, o in db.execute(select(Level.code, Level.sort_order)).all()}
        if level not in lv:
            return []
        stmt = stmt.where(
            select(Level.sort_order).where(Level.code == Activity.level_from).scalar_subquery() <= lv[level],
            select(Level.sort_order).where(Level.code == Activity.level_to).scalar_subquery() >= lv[level],
        )
    if interest:
        stmt = stmt.where(Activity.interest_tags.any(interest))
    if q:
        stmt = stmt.where(
            func.to_tsvector("simple", Activity.title + " " + func.coalesce(Activity.summary, "")).op("@@")(
                func.plainto_tsquery("simple", q)
            )
        )
    return list(db.scalars(stmt.order_by(Activity.subject_code, Activity.title).limit(limit).offset(offset)))


@router.get("/activities/{activity_id}", response_model=ActivityDetail)
def get_activity(activity_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> ActivityDetail:
    a = db.scalar(select(Activity).where(Activity.id == activity_id, Activity.status == "published"))
    if a is None:
        raise not_found()
    codes = sorted(db.scalars(select(ActivitySkill.skill_code).where(ActivitySkill.activity_id == a.id)))
    return ActivityDetail(
        **ActivitySummary.model_validate(a).model_dump(), skills=codes, definition=public_definition(a.definition)
    )
