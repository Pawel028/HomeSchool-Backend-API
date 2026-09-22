"""Child profiles, child sessions (child tokens) and the isolation guarantees, including at the database level."""

import uuid

import pytest
from sqlalchemy import create_engine, text


def test_child_crud_and_optimistic_locking(parent):
    child = parent.add_child("Aarav", "L2", interests=["animals"], goals=["MAT"])
    assert child["version"] == 1 and child["interests"] == ["animals"]
    listed = parent.get(f"/v1/families/{parent.family_id}/children").json()
    assert [c["id"] for c in listed] == [child["id"]]
    r = parent.patch(f"/v1/children/{child['id']}", json={"display_name": "Aarav R", "version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["display_name"] == "Aarav R"
    stale = parent.patch(f"/v1/children/{child['id']}", json={"display_name": "X", "version": 1})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "conflict"


def test_child_validation(parent):
    url = f"/v1/families/{parent.family_id}/children"
    assert parent.post(url, json={"display_name": "A", "level_code": "L9"}).status_code == 422
    assert parent.post(url, json={"display_name": "A", "interests": ["not-an-interest"]}).status_code == 422
    assert parent.post(url, json={"display_name": ""}).status_code == 422


def test_delete_needs_the_pin_and_revokes_child_tokens(parent):
    child = parent.add_child()
    ch = parent.child_headers(child["id"])
    assert parent.delete(f"/v1/children/{child['id']}").json()["error"]["code"] == "elevation_required"
    assert parent.delete(f"/v1/children/{child['id']}", headers={"X-Elevation-Token": "garbage"}).status_code == 403
    assert parent.delete(f"/v1/children/{child['id']}", headers=parent.elevation()).status_code == 204
    assert parent.get(f"/v1/children/{child['id']}").status_code == 404
    assert parent.client.get(f"/v1/children/{child['id']}", headers=ch).status_code == 401  # session revoked
    assert parent.get(f"/v1/families/{parent.family_id}/children").json() == []


def test_elevation_token_is_bound_to_the_user(make_parent):
    a, b = make_parent(), make_parent()
    child = a.add_child()
    stolen = b.elevation()
    assert a.delete(f"/v1/children/{child['id']}", headers=stolen).status_code == 403


def test_families_are_isolated_from_each_other(make_parent):
    a, b = make_parent(), make_parent()
    child = a.add_child()
    assert b.get(f"/v1/children/{child['id']}").status_code == 404
    assert b.patch(f"/v1/children/{child['id']}", json={"display_name": "hack", "version": 1}).status_code == 404
    assert b.post(f"/v1/children/{child['id']}/sessions", json={"device_id": "device-0001"}).status_code == 404
    assert b.get(f"/v1/children/{child['id']}/plan").status_code == 404
    assert b.get(f"/v1/families/{a.family_id}/children").status_code == 404
    assert b.post(f"/v1/families/{a.family_id}/children", json={"display_name": "intruder"}).status_code == 404


def test_child_token_is_scoped_to_one_child(parent):
    kid, sibling = parent.add_child("Kid"), parent.add_child("Sibling")
    ch = parent.child_headers(kid["id"])
    c = parent.client
    assert c.get(f"/v1/children/{kid['id']}", headers=ch).status_code == 200
    assert c.get(f"/v1/children/{sibling['id']}", headers=ch).status_code == 404
    assert c.get(f"/v1/children/{sibling['id']}/plan", headers=ch).status_code == 404
    # everything that is for parents only is closed to a child token
    for method, url in [
        ("GET", "/v1/me"),
        ("GET", f"/v1/families/{parent.family_id}/children"),
        ("GET", f"/v1/families/{parent.family_id}/consents"),
        ("GET", f"/v1/children/{kid['id']}/mastery"),
        ("GET", f"/v1/children/{kid['id']}/progress/overview"),
        ("GET", "/v1/admin/stats"),
        ("POST", f"/v1/children/{kid['id']}/sessions"),
        ("POST", f"/v1/children/{kid['id']}/plan/items"),
    ]:
        r = c.request(method, url, headers=ch, json={} if method == "POST" else None)
        assert r.status_code in (403, 404, 422), (method, url, r.status_code)
        assert r.status_code != 200
    assert c.put("/v1/me/pin", headers=ch, json={"pin": "1111"}).status_code == 403


def test_leaving_child_mode_needs_the_pin(parent):
    kid = parent.add_child()
    ch = parent.child_headers(kid["id"])
    assert parent.delete(f"/v1/children/{kid['id']}/sessions").status_code == 403
    assert parent.delete(f"/v1/children/{kid['id']}/sessions", headers=parent.elevation()).status_code == 204
    assert parent.client.get(f"/v1/children/{kid['id']}", headers=ch).status_code == 401


def test_opening_a_new_session_on_the_same_device_revokes_the_old_token(parent):
    kid = parent.add_child()
    old = parent.child_headers(kid["id"], "device-aaaa")
    new = parent.child_headers(kid["id"], "device-aaaa")
    other = parent.child_headers(kid["id"], "device-bbbb")
    c = parent.client
    assert c.get(f"/v1/children/{kid['id']}", headers=old).status_code == 401
    assert c.get(f"/v1/children/{kid['id']}", headers=new).status_code == 200
    assert c.get(f"/v1/children/{kid['id']}", headers=other).status_code == 200


def test_educator_can_teach_but_not_manage(make_parent, database):
    owner, edu = make_parent(), make_parent(verified=False, pin=False)
    kid = owner.add_child()
    with database["admin"].begin() as c:
        c.execute(
            text("insert into family_memberships (family_id, user_id, role) values (:f, :u, 'educator')"),
            {"f": owner.family_id, "u": edu.user_id},
        )
    assert edu.get(f"/v1/children/{kid['id']}").status_code == 200
    assert edu.post(f"/v1/families/{owner.family_id}/children", json={"display_name": "Nope"}).status_code == 403
    assert edu.patch(f"/v1/children/{kid['id']}", json={"display_name": "Nope", "version": 1}).status_code == 403
    assert (
        edu.put(
            f"/v1/families/{owner.family_id}/consents",
            json={"purpose": "media_capture", "granted": True, "notice_version": "2026-09-draft"},
        ).status_code
        == 403
    )
    assert edu.post(
        f"/v1/children/{kid['id']}/observations", json={"skill_code": "MAT.COUNT.TO20", "rating": "independent"}
    ).status_code in (201, 422)


# ------------------------------------------------------------------------------------------------ database-level RLS
def _rls_conn(database):
    """A raw connection as the production application role (not a superuser, cannot bypass RLS)."""
    return create_engine(database["app_url"]).connect()


def test_application_role_cannot_bypass_rls(database):
    with _rls_conn(database) as c:
        row = c.execute(
            text("select rolsuper, rolbypassrls, rolcreaterole from pg_roles where rolname = current_user")
        ).one()
    assert (row.rolsuper, row.rolbypassrls, row.rolcreaterole) == (False, False, False)


def test_rls_hides_other_families_even_for_unfiltered_sql(make_parent, database):
    a, b = make_parent(), make_parent()
    a.add_child("A-child")
    b.add_child("B-child")
    with _rls_conn(database) as c:
        with c.begin():
            assert c.execute(text("select count(*) from children")).scalar() == 0  # no identity: nothing is visible
        with c.begin():
            c.execute(text("select set_config('app.user_id', :u, true)"), {"u": a.user_id})
            names = [r[0] for r in c.execute(text("select display_name from children"))]
        assert names == ["A-child"]
        with c.begin():
            c.execute(text("select set_config('app.family_id', :f, true)"), {"f": b.family_id})
            assert [r[0] for r in c.execute(text("select display_name from children"))] == [
                "B-child"
            ]  # a child token's view


def test_rls_blocks_writes_into_other_families(make_parent, database):
    a, b = make_parent(), make_parent()
    with _rls_conn(database) as c:
        tx = c.begin()
        c.execute(text("select set_config('app.user_id', :u, true)"), {"u": a.user_id})
        with pytest.raises(Exception, match="row-level security"):
            c.execute(text("insert into children (family_id, display_name) values (:f, 'sneaky')"), {"f": b.family_id})
        tx.rollback()


def test_rls_covers_every_family_table(database):
    with database["admin"].connect() as c:
        rows = c.execute(
            text("""select relname, relrowsecurity, relforcerowsecurity from pg_class
                                 where relname in ('children','consents','plans','plan_items','activity_sessions','skill_evidence','skill_mastery')""")
        ).all()
    assert len(rows) == 7 and all(r.relrowsecurity and r.relforcerowsecurity for r in rows)


def test_audit_log_is_append_only_for_the_application_role(parent, database):
    parent.add_child()
    with _rls_conn(database) as c:
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text("delete from audit_log"))
    with _rls_conn(database) as c:
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text("update audit_log set action = 'x'"))
    with database["admin"].connect() as c:
        assert c.execute(text("select count(*) from audit_log where action = 'child.created'")).scalar() == 1


def test_audit_and_outbox_hold_ids_not_names(parent, database):
    parent.add_child("Secret Name")
    with database["admin"].connect() as c:
        blob = " ".join(str(r) for r in c.execute(text("select meta::text, entity_id from audit_log"))) + " ".join(
            str(r) for r in c.execute(text("select payload::text from outbox_events"))
        )
    assert "Secret Name" not in blob and parent.email not in blob


def test_application_role_cannot_change_the_schema(database):
    with _rls_conn(database) as c:
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text(f"create table t_{uuid.uuid4().hex[:6]} (x int)"))
