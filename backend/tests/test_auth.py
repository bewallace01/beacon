from tests.conftest import auth_headers, signup


def test_signup_returns_api_key_and_session(client):
    r = client.post(
        "/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "hunter22hunter22",
            "workspace_name": "alice-co",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["workspace"]["name"] == "alice-co"
    assert body["api_key"]["plaintext"].startswith("bk_")
    assert body["session_token"].startswith("bks_")


def test_signup_duplicate_email_409(client, alice):
    r = client.post(
        "/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "hunter22hunter22",
            "workspace_name": "another",
        },
    )
    assert r.status_code == 409


def test_login_success_and_wrong_password(client, alice):
    r = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "hunter22hunter22"},
    )
    assert r.status_code == 200
    assert r.json()["session_token"].startswith("bks_")

    r = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "wrong-pw-here"},
    )
    assert r.status_code == 401


def test_auth_me_credential_kind(client, alice):
    r = client.get("/auth/me", headers=auth_headers(alice["session_token"]))
    assert r.status_code == 200
    assert r.json()["credential"] == "session"
    assert r.json()["user"]["email"] == "alice@example.com"

    r = client.get(
        "/auth/me", headers=auth_headers(alice["api_key"]["plaintext"]),
    )
    assert r.status_code == 200
    assert r.json()["credential"] == "api_key"
    assert r.json()["user"] is None


def test_logout_revokes_only_calling_session(client, alice):
    # Create a second session by logging in again.
    r = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "hunter22hunter22"},
    )
    second_session = r.json()["session_token"]

    # Logout the second session.
    r = client.post("/auth/logout", headers=auth_headers(second_session))
    assert r.status_code == 200

    # Original signup session must still authenticate.
    r = client.get("/auth/me", headers=auth_headers(alice["session_token"]))
    assert r.status_code == 200

    # Revoked session must not.
    r = client.get("/auth/me", headers=auth_headers(second_session))
    assert r.status_code == 401


def test_logout_with_api_key_400(client, alice):
    r = client.post(
        "/auth/logout", headers=auth_headers(alice["api_key"]["plaintext"]),
    )
    assert r.status_code == 400


def test_unauthenticated_requests_401(client):
    assert client.get("/runs").status_code == 401
    r = client.get("/runs", headers={"Authorization": "Bearer bk_does-not-exist"})
    assert r.status_code == 401
