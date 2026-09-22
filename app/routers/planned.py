"""Endpoints from the API catalogue (07_API_CATALOG) that are not built yet.

They exist so clients can code against the final paths and so the OpenAPI document lists the whole plan. Every one of
them answers 501 with {"error": {"code": "not_implemented"}}. When you implement one, delete its line here and add a real router.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.errors import ApiError

router = APIRouter(tags=["planned (not implemented)"])

PLANNED: list[tuple[str, str]] = [
    # auth
    ("POST", "/v1/auth/password-reset"),
    ("POST", "/v1/auth/password-reset/confirm"),
    ("POST", "/v1/auth/otp/request"),
    ("POST", "/v1/auth/otp/verify"),
    ("POST", "/v1/auth/social/google"),
    ("POST", "/v1/auth/mfa/totp"),
    ("POST", "/v1/auth/mfa/verify"),
    ("GET", "/v1/auth/sessions"),
    ("DELETE", "/v1/auth/sessions/{session_id}"),
    # identity and family
    ("PATCH", "/v1/me"),
    ("POST", "/v1/families"),
    ("GET", "/v1/families/{family_id}"),
    ("PATCH", "/v1/families/{family_id}"),
    ("POST", "/v1/families/{family_id}/invitations"),
    ("GET", "/v1/families/{family_id}/invitations"),
    ("DELETE", "/v1/families/{family_id}/invitations/{invitation_id}"),
    ("POST", "/v1/invitations/{token}/accept"),
    ("PATCH", "/v1/families/{family_id}/members/{user_id}"),
    ("DELETE", "/v1/families/{family_id}/members/{user_id}"),
    # children, progress, planning
    ("GET", "/v1/children/{child_id}/goals"),
    ("PUT", "/v1/children/{child_id}/goals"),
    ("GET", "/v1/children/{child_id}/evidence"),
    ("POST", "/v1/children/{child_id}/recurring-activities"),
    ("GET", "/v1/children/{child_id}/recurring-activities"),
    ("DELETE", "/v1/children/{child_id}/recurring-activities/{rule_id}"),
    ("POST", "/v1/children/{child_id}/reports"),
    ("POST", "/v1/recommendations/{run_id}/feedback"),
    # journal, media, assessments
    ("POST", "/v1/journal/entries"),
    ("GET", "/v1/journal/entries"),
    ("PATCH", "/v1/journal/entries/{entry_id}"),
    ("DELETE", "/v1/journal/entries/{entry_id}"),
    ("POST", "/v1/media/presign"),
    ("POST", "/v1/media/complete"),
    ("GET", "/v1/assessments"),
    ("GET", "/v1/assessments/{assessment_id}"),
    ("POST", "/v1/assessments/{assessment_id}/attempts"),
    ("POST", "/v1/assessment-attempts/{attempt_id}/submit"),
    # notifications, preferences, devices
    ("GET", "/v1/notifications"),
    ("PATCH", "/v1/notifications/{notification_id}"),
    ("POST", "/v1/notifications/read-all"),
    ("GET", "/v1/preferences"),
    ("PATCH", "/v1/preferences"),
    ("POST", "/v1/devices"),
    ("DELETE", "/v1/devices/{device_id}"),
    # privacy, jobs
    ("POST", "/v1/privacy/export"),
    ("POST", "/v1/privacy/delete"),
    ("POST", "/v1/privacy/delete/cancel"),
    ("POST", "/v1/privacy/grievances"),
    ("GET", "/v1/privacy/grievances"),
    ("GET", "/v1/jobs/{job_id}"),
    # offline sync
    ("POST", "/v1/sync/batch"),
    ("GET", "/v1/sync/changes"),
    # billing (V1)
    ("GET", "/v1/billing/subscription"),
    ("POST", "/v1/billing/play/verify"),
    ("POST", "/v1/webhooks/play-rtdn"),
    # public site content
    ("GET", "/v1/public/subjects"),
    ("GET", "/v1/public/curriculum"),
    ("GET", "/v1/public/legal/{doc}"),
    ("GET", "/v1/public/content/{slug}"),
    ("GET", "/v1/public/plans"),
    # admin
    ("GET", "/v1/admin/audit-logs"),
    ("GET", "/v1/admin/users"),
    ("PATCH", "/v1/admin/users/{user_id}/status"),
    ("GET", "/v1/admin/feature-flags"),
    ("PATCH", "/v1/admin/feature-flags/{key}"),
    ("POST", "/v1/admin/subjects"),
    ("POST", "/v1/admin/skills"),
    ("PATCH", "/v1/admin/skills/{skill_code}"),
    ("POST", "/v1/admin/activities"),
    ("POST", "/v1/admin/assessments"),
]


async def _not_implemented(request: Request) -> None:
    raise ApiError(501, "not_implemented", "This endpoint is planned but not built yet.")


for _method, _path in PLANNED:
    router.add_api_route(
        _path,
        _not_implemented,
        methods=[_method],
        status_code=501,
        summary="Planned: not implemented yet",
        response_model=None,
        name=f"planned {_method} {_path}",
    )
