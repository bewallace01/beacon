from tests.conftest import auth_headers


def test_list_keys_never_exposes_plaintext_or_hash(client, alice):
    r = client.get(
        "/workspaces/me/api-keys",
        headers=auth_headers(alice["session_token"]),
    )
    assert r.status_code == 200
    keys = r.json()["api_keys"]
    assert len(keys) == 1
    k = keys[0]
    assert "plaintext" not in k
    assert "hash" not in k
    assert k["prefix"]


def test_create_key_returns_plaintext_once(client, alice):
    r = client.post(
        "/workspaces/me/api-keys",
        json={"name": "ci"},
        headers=auth_headers(alice["session_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plaintext"].startswith("bk_")

    # Listing it again should not include plaintext.
    r = client.get(
        "/workspaces/me/api-keys",
        headers=auth_headers(alice["session_token"]),
    )
    found = [k for k in r.json()["api_keys"] if k["id"] == body["id"]][0]
    assert "plaintext" not in found


def test_revoke_key_makes_it_unusable(client, alice):
    # Mint a second key so revoking it doesn't lock us out.
    r = client.post(
        "/workspaces/me/api-keys",
        json={"name": "throwaway"},
        headers=auth_headers(alice["session_token"]),
    )
    new_key = r.json()
    plaintext = new_key["plaintext"]

    # Confirm it works pre-revoke.
    r = client.get("/auth/me", headers=auth_headers(plaintext))
    assert r.status_code == 200

    # Revoke (using session, not the throwaway key itself).
    r = client.delete(
        f"/workspaces/me/api-keys/{new_key['id']}",
        headers=auth_headers(alice["session_token"]),
    )
    assert r.status_code == 200

    # Now the revoked key should 401.
    r = client.get("/auth/me", headers=auth_headers(plaintext))
    assert r.status_code == 401


def test_cannot_revoke_calling_key(client, alice):
    # Authenticate via the api key, try to revoke itself.
    r = client.get(
        "/workspaces/me/api-keys",
        headers=auth_headers(alice["api_key"]["plaintext"]),
    )
    keys = r.json()["api_keys"]
    self_id = keys[0]["id"]
    r = client.delete(
        f"/workspaces/me/api-keys/{self_id}",
        headers=auth_headers(alice["api_key"]["plaintext"]),
    )
    assert r.status_code == 400


def test_cross_workspace_revoke_404(client, alice, bob):
    # Bob tries to revoke alice's api key.
    r = client.get(
        "/workspaces/me/api-keys",
        headers=auth_headers(alice["session_token"]),
    )
    alice_key_id = r.json()["api_keys"][0]["id"]
    r = client.delete(
        f"/workspaces/me/api-keys/{alice_key_id}",
        headers=auth_headers(bob["session_token"]),
    )
    assert r.status_code == 404
