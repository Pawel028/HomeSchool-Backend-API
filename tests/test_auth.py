from sqlalchemy import text

PW = "correct-horse-battery"


def _signup(client, email="a@example.com", **kw):
    return client.post("/v1/auth/signup", json={"email": email, "password": PW, "full_name": "Asha Rao", **kw})


def test_signup_creates_user_family_and_tokens(client):
    r = _signup(client)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "a@example.com" and "password" not in r.text and "password_hash" not in r.text
    assert len(body["memberships"]) == 1 and body["memberships"][0]["role"] == "owner"
    assert body["memberships"][0]["guardian_verified"] is False
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
    assert me["pin_set"] is False and me["user"]["platform_role"] is None


def test_signup_rejects_duplicates_case_insensitively_and_bad_input(client):
    assert _signup(client, "Dup@Example.com").status_code == 201
    r = _signup(client, "dup@example.com")
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    assert (
        client.post(
            "/v1/auth/signup", json={"email": "b@example.com", "password": "short", "full_name": "B"}
        ).status_code
        == 422
    )
    assert _signup(client, "c@example.com", timezone="Mars/Olympus").status_code == 422


def test_passwords_are_stored_as_argon2id(client, database):
    _signup(client)
    with database["admin"].connect() as c:
        h = c.execute(text("select password_hash from users")).scalar()
    assert h.startswith("$argon2id$") and PW not in h


def test_login_success_and_uniform_failure(client):
    _signup(client)
    ok = client.post("/v1/auth/login", json={"email": "A@example.com", "password": PW})
    assert ok.status_code == 200 and ok.json()["access_token"]
    wrong = client.post("/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
    missing = client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["error"]["code"] == missing.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json()["error"]["message"] == missing.json()["error"]["message"]


def test_login_is_rate_limited(client):
    _signup(client)
    codes = [
        client.post("/v1/auth/login", json={"email": "a@example.com", "password": "nope-nope-nope"}).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_refresh_rotates_and_reuse_revokes_the_chain(client):
    first = _signup(client).json()
    r1 = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r1.status_code == 200
    second = r1.json()
    assert second["refresh_token"] != first["refresh_token"]
    # presenting the OLD token again is treated as theft: the whole chain is revoked
    assert client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(client):
    t = _signup(client).json()
    assert client.post("/v1/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_bad_and_wrong_type_tokens_are_rejected(client, parent):
    assert client.get("/v1/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/v1/me").status_code == 401
    elev = parent.post("/v1/me/pin/verify", json={"pin": "2468"}).json()["elevation_token"]
    assert (
        client.get("/v1/me", headers={"Authorization": f"Bearer {elev}"}).status_code == 401
    )  # elevation token is not an access token


def test_disabled_user_is_locked_out(client, database):
    t = _signup(client).json()
    with database["admin"].begin() as c:
        c.execute(text("update users set status = 'disabled'"))
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 401
    assert client.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 401
