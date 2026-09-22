from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.security import now
from tests.helpers import complete, correct_answers

SKILL = "MAT.NUM.COUNT20"


def _mastery(parent, kid, skill=SKILL):
    return {m["skill_code"]: m for m in parent.get(f"/v1/children/{kid['id']}/mastery").json()}.get(skill)


def test_baseline_sets_a_starting_point_and_never_overwrites_history(parent, activities):
    kid = parent.add_child("K", "L1")
    r = parent.post(
        f"/v1/children/{kid['id']}/baseline",
        json={
            "ratings": [
                {"skill_code": SKILL, "rating": "with_help"},
                {"skill_code": "PHY.GROSS.BALL", "rating": "independent"},
            ]
        },
    )
    assert r.status_code == 201 and sorted(r.json()["recorded"]) == sorted([SKILL, "PHY.GROSS.BALL"])
    assert _mastery(parent, kid)["score"] == 0.6
    again = parent.post(
        f"/v1/children/{kid['id']}/baseline", json={"ratings": [{"skill_code": SKILL, "rating": "trying"}]}
    ).json()
    assert again == {"recorded": [], "skipped": [SKILL]} and _mastery(parent, kid)["score"] == 0.6
    assert (
        parent.post(
            f"/v1/children/{kid['id']}/baseline", json={"ratings": [{"skill_code": "NOPE.X.Y", "rating": "trying"}]}
        ).status_code
        == 422
    )


def test_baseline_weight_is_lower_than_activity_evidence(parent, database):
    kid = parent.add_child("K", "L1")
    parent.post(
        f"/v1/children/{kid['id']}/baseline", json={"ratings": [{"skill_code": SKILL, "rating": "independent"}]}
    )
    with database["admin"].connect() as c:
        assert tuple(c.execute(text("select source, base_weight, weight from skill_evidence")).one()) == (
            "baseline",
            0.8,
            0.8,
        )


def test_observations_use_the_rating_scale_and_keep_a_note(parent, database):
    kid = parent.add_child("K", "L1")
    url = f"/v1/children/{kid['id']}/observations"
    r = parent.post(url, json={"skill_code": SKILL, "rating": "trying", "note": "counted to 12 today"})
    assert r.status_code == 201 and r.json()["mastery"]["score"] == 0.3 and r.json()["mastery"]["status"] == "emerging"
    r = parent.post(url, json={"skill_code": SKILL, "rating": "independent"})
    # second item: alpha = max(0.2, 1/2) = 0.5 -> 0.3 + 0.5 * (1.0 - 0.3) = 0.65
    assert r.json()["mastery"]["score"] == pytest.approx(0.65) and r.json()["mastery"]["status"] == "developing"
    assert parent.post(url, json={"skill_code": "NOPE.X.Y", "rating": "trying"}).status_code == 422
    with database["admin"].connect() as c:
        assert (
            c.execute(text("select note from skill_evidence where note is not null")).scalar() == "counted to 12 today"
        )


def test_secure_needs_score_confidence_evidence_and_two_days(parent):
    kid = parent.add_child("K", "L1")
    a = {"slug": "count-the-dogs"}
    url = f"/v1/children/{kid['id']}/observations"
    day1, day2 = now() - timedelta(days=1), now()
    for stamp in (day1, day1, day1, day1, day1):
        parent.post(url, json={"skill_code": SKILL, "rating": "independent", "occurred_at": stamp.isoformat()})
    assert _mastery(parent, kid)["status"] == "developing"  # five perfect items, but all on one day
    parent.post(url, json={"skill_code": SKILL, "rating": "independent", "occurred_at": day2.isoformat()})
    m = _mastery(parent, kid)
    assert m["status"] == "secure" and m["distinct_days"] == 2 and m["confidence"] == 1.0 and a


def test_observation_time_window(parent):
    kid = parent.add_child("K", "L1")
    url = f"/v1/children/{kid['id']}/observations"
    old = (now() - timedelta(days=9)).isoformat()
    assert parent.post(url, json={"skill_code": SKILL, "rating": "trying", "occurred_at": old}).status_code == 422


def test_needs_revisit_after_30_quiet_days(parent, database):
    kid = parent.add_child("K", "L1")
    parent.post(f"/v1/children/{kid['id']}/observations", json={"skill_code": SKILL, "rating": "independent"})
    assert _mastery(parent, kid)["needs_revisit"] is False
    with database["admin"].begin() as c:
        c.execute(text("update skill_mastery set last_evidence_at = now() - interval '31 days'"))
    assert _mastery(parent, kid)["needs_revisit"] is True


def test_overview_metrics(parent, activities):
    kid = parent.add_child("K", "L1")
    a = activities["count-the-dogs"]  # planned 10 minutes
    today = now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    plan = parent.post(
        f"/v1/children/{kid['id']}/plan/items", json={"activity_id": a["id"], "scheduled_date": today.isoformat()}
    ).json()
    parent.post(
        f"/v1/children/{kid['id']}/plan/items", json={"activity_id": a["id"], "scheduled_date": today.isoformat()}
    )
    r1 = complete(
        parent.client, parent.headers, kid["id"], a, duration=80000, plan_item_id=plan["id"]
    )  # idle session: minutes are capped
    assert r1.status_code == 200, r1.text
    r2 = complete(parent.client, parent.headers, kid["id"], a, duration=600, assist=True)
    assert r2.status_code == 200, r2.text
    o = parent.get(f"/v1/children/{kid['id']}/progress/overview").json()
    assert o["activities"] == 2
    assert o["minutes"] == 30 + 10  # min(1666 min, 3 x 10) + min(10, 30)
    assert o["independent_pct"] == 50
    assert o["new_skills"] == 1
    assert (o["week_done"], o["week_planned"]) == (1, 2)
    assert o["streak"] == 1
    maths = next(s for s in o["subjects"] if s["subject_code"] == "MAT")
    assert maths["started"] == 1 and maths["progress_pct"] == 100 and maths["total"] >= 1
    english = next(s for s in o["subjects"] if s["subject_code"] == "ENG")
    assert english["progress_pct"] is None and english["started"] == 0


def test_overview_with_no_activity_shows_dashes(parent):
    kid = parent.add_child("K", "L1")
    o = parent.get(f"/v1/children/{kid['id']}/progress/overview").json()
    assert (o["activities"], o["minutes"], o["independent_pct"], o["streak"]) == (0, 0, None, 0)
    assert (
        parent.get(
            f"/v1/children/{kid['id']}/progress/overview",
            params={"range_start": "2026-02-01", "range_end": "2026-01-01"},
        ).status_code
        == 422
    )


def _tz_today():
    return now().astimezone(ZoneInfo("Asia/Kolkata")).date()


def _plan(parent, kid, activity, day):
    assert (
        parent.post(
            f"/v1/children/{kid['id']}/plan/items",
            json={"activity_id": activity["id"], "scheduled_date": day.isoformat()},
        ).status_code
        == 201
    )


def test_streak_rest_days_and_one_forgiven_miss(parent, activities):
    kid = parent.add_child("K", "L1")
    a = activities["count-the-dogs"]
    today = _tz_today()
    for n in (3, 1, 0):  # done 3 days ago, yesterday and today; two days ago was planned but missed (forgiven)
        complete(parent.client, parent.headers, kid["id"], a, occurred_at=now() - timedelta(days=n) if n else None)
    _plan(parent, kid, a, today - timedelta(days=2))
    assert parent.get(f"/v1/children/{kid['id']}/progress/overview").json()["streak"] == 3


def test_streak_resets_after_two_missed_planned_days(parent, activities):
    kid = parent.add_child("K", "L1")
    a = activities["count-the-dogs"]
    today = _tz_today()
    for n in (4, 1, 0):
        complete(parent.client, parent.headers, kid["id"], a, occurred_at=now() - timedelta(days=n) if n else None)
    _plan(parent, kid, a, today - timedelta(days=3))
    _plan(parent, kid, a, today - timedelta(days=2))
    assert parent.get(f"/v1/children/{kid['id']}/progress/overview").json()["streak"] == 2


def test_skipped_plan_items_do_not_count_as_misses(parent, activities):
    kid = parent.add_child("K", "L1")
    a = activities["count-the-dogs"]
    today = _tz_today()
    complete(parent.client, parent.headers, kid["id"], a)
    complete(parent.client, parent.headers, kid["id"], a, occurred_at=now() - timedelta(days=3))
    for n in (1, 2):
        item = parent.post(
            f"/v1/children/{kid['id']}/plan/items",
            json={"activity_id": a["id"], "scheduled_date": (today - timedelta(days=n)).isoformat()},
        ).json()
        parent.patch(f"/v1/plan-items/{item['id']}", json={"status": "skipped", "version": 1})
    assert parent.get(f"/v1/children/{kid['id']}/progress/overview").json()["streak"] == 2


def test_recommendations_are_ranked_filtered_and_explained(parent, activities):
    kid = parent.add_child("K", "L1", interests=["animals"])
    recs = parent.get(f"/v1/children/{kid['id']}/recommendations").json()
    assert recs and all(r["reason"] and 0 <= r["score"] <= 1 for r in recs)
    assert recs[0]["activity"]["slug"] == "count-the-dogs"  # interest match + biggest skill gap
    assert all(r["activity"]["level_from"] == "L1" for r in recs)  # nothing above the child's level
    assert [r["score"] for r in recs] == sorted((r["score"] for r in recs), reverse=True)
    assert len(parent.get(f"/v1/children/{kid['id']}/recommendations", params={"limit": 1}).json()) == 1
    short = parent.get(f"/v1/children/{kid['id']}/recommendations", params={"max_minutes": 10}).json()
    assert short and all(r["activity"]["duration_min"] <= 10 for r in short)
    complete(parent.client, parent.headers, kid["id"], activities["count-the-dogs"])
    after = parent.get(f"/v1/children/{kid['id']}/recommendations").json()
    assert "count-the-dogs" not in [r["activity"]["slug"] for r in after]  # done in the last 14 days


def test_goals_outrank_interests(parent):
    kid = parent.add_child("K", "L1", interests=["animals"], goals=["PHY"])
    recs = parent.get(f"/v1/children/{kid['id']}/recommendations").json()
    assert recs[0]["activity"]["slug"] == "balloon-catch" and "goal" in recs[0]["reason"]


def test_recommendations_respect_prerequisites(parent):
    kid = parent.add_child("K", "L3")
    for r in parent.get(f"/v1/children/{kid['id']}/recommendations", params={"limit": 20}).json():
        assert r["activity"]["level_from"] <= "L3" <= r["activity"]["level_to"]


def test_dashboard_bundles_overview_today_and_recommendations(parent, activities):
    kid = parent.add_child("K", "L1")
    _plan(parent, kid, activities["count-the-dogs"], _tz_today())
    d = parent.get(f"/v1/children/{kid['id']}/dashboard").json()
    assert (
        set(d) == {"overview", "today", "recommendations"} and len(d["today"]) == 1 and len(d["recommendations"]) <= 3
    )


def test_history_lists_submitted_sessions_newest_first(parent, activities):
    kid = parent.add_child("K", "L2")
    complete(
        parent.client, parent.headers, kid["id"], activities["kitchen-counting"], occurred_at=now() - timedelta(hours=2)
    )
    complete(
        parent.client,
        parent.headers,
        kid["id"],
        activities["plant-parts-puzzle"],
        correct_answers("plant-parts-puzzle"),
    )
    h = parent.get(f"/v1/children/{kid['id']}/history").json()
    assert [x["activity_title"] for x in h] == ["Plant parts puzzle", "Kitchen counting"]
    assert h[1]["needs_review"] == ["s3"] and h[0]["score"] == 1.0
    assert (
        parent.client.get(f"/v1/children/{kid['id']}/history", headers=parent.child_headers(kid["id"])).status_code
        == 200
    )


def test_progress_is_private_to_the_family(make_parent):
    a, b = make_parent(), make_parent()
    kid = a.add_child()
    for url in ("mastery", "progress/overview", "recommendations", "dashboard", "history"):
        assert b.get(f"/v1/children/{kid['id']}/{url}").status_code == 404
    assert (
        b.post(f"/v1/children/{kid['id']}/observations", json={"skill_code": SKILL, "rating": "trying"}).status_code
        == 404
    )
