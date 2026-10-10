from tests.conftest import auth, demo_auth, make_user


def test_health_and_version(client):
    assert client.get("/health").json() == {"status": "ok"}
    v = client.get("/api/v1/version").json()
    assert set(v) == {"git_sha", "built_at", "deployed_at", "llm_provider", "llm_enabled", "llm_configured"}


def test_demo_login_officer_and_owner(client):
    r = client.post("/api/v1/auth/demo", json={"role": "officer"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "officer@converza.uz"
    assert "decision:write" in body["scopes"]
    owner = client.post("/api/v1/auth/demo", json={"role": "owner"}).json()
    assert owner["user"]["role"] == "owner" and "cfo:use" in owner["scopes"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["user"]["role"] == "officer"


def test_demo_login_rejects_unknown_role(client):
    assert client.post("/api/v1/auth/demo", json={"role": "admin"}).status_code == 422


def test_login_and_refresh_token_type(client, db):
    make_user(db, "a@converza.uz", "officer")
    h = auth(client, "a@converza.uz")
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200
    tokens = client.post("/api/v1/auth/login", data={"username": "a@converza.uz", "password": "password123"}).json()
    # a refresh token is never accepted as an access token
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 200
    bad = client.post("/api/v1/auth/login", data={"username": "a@converza.uz", "password": "nope"})
    assert bad.status_code == 401 and bad.json()["code"] == "invalid_credentials"


def test_scopes_guard(client):
    owner = demo_auth(client, "owner")
    assert client.get("/api/v1/applications", headers=owner).status_code == 403
    assert client.get("/api/v1/applications").status_code == 401
    officer = demo_auth(client, "officer")
    assert client.get("/api/v1/applications", headers=officer).status_code == 200


def test_llm_switch_audited(client):
    officer = demo_auth(client, "officer")
    r = client.put("/api/v1/settings/llm", json={"enabled": False}, headers=officer)
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.get("/api/v1/version").json()["llm_enabled"] is False
    audit = client.get("/api/v1/audit?entity=setting", headers=officer).json()
    assert audit["items"][0]["after"] == {"enabled": False}
