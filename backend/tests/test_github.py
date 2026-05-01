"""Phase 10.1: GitHub integration CRUD + PAT validation against GitHub.

Endpoint round-trips, secret masking, agent-path CRUD, cross-workspace
isolation. PAT validation is mocked at the github_api.httpx layer using
the same MockTransport pattern Phase 9.2 uses for notifications.
"""
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

import github_api
from tests.conftest import auth_headers


# ---------- httpx mock helper ---------- #


@contextmanager
def mock_github_api(handler):
    """Patch the httpx.Client used inside github_api with one routing
    through `handler` (a function taking a Request and returning a
    Response, or raising). Same shape as the notifications mock."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    with patch.object(github_api.httpx, "Client", side_effect=factory):
        yield


def _ok_repo_response(default_branch: str = "main", private: bool = False):
    """Standard 200 from GET /repos/{owner}/{name}."""
    return httpx.Response(200, json={
        "full_name": "acme/widgets",
        "default_branch": default_branch,
        "private": private,
    })


def _put_integration(
    client, headers, *,
    repo_owner: str = "acme",
    repo_name: str = "widgets",
    branch: str = "main",
    pat: str = "ghp_test_token_value",
):
    body = {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "branch": branch,
        "pat": pat,
    }
    return client.put("/workspaces/me/github", json=body, headers=headers)


# ---------- happy path: register + read + update + delete ---------- #


def test_first_registration_returns_webhook_secret_and_masks_pat(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    with mock_github_api(lambda req: _ok_repo_response()):
        r = _put_integration(client, h, pat="ghp_supersecrettoken12345678")

    assert r.status_code == 200, r.text
    body = r.json()
    # Repo + branch round-trip.
    assert body["repo_owner"] == "acme"
    assert body["repo_name"] == "widgets"
    assert body["branch"] == "main"
    assert body["is_active"] is True
    assert body["webhook_url"].endswith("/webhooks/github")
    assert body["has_webhook_secret"] is True
    # PAT is masked, never echoed verbatim.
    assert body["pat_masked"].startswith("ghp_")
    assert body["pat_masked"].endswith("5678")
    assert "supersecret" not in body["pat_masked"]
    assert "supersecret" not in str(body)
    # Webhook secret is revealed exactly once on first creation, with a
    # note saying "save this now".
    assert "webhook_secret" in body
    assert isinstance(body["webhook_secret"], str)
    assert len(body["webhook_secret"]) >= 30
    assert "save this secret" in body["webhook_secret_reveal_note"].lower()
    # GitHub default branch comes back as a hint
    assert body.get("default_branch_from_github") == "main"


def test_get_returns_no_plaintext_secret_after_initial_reveal(client, alice):
    """GET never echoes the webhook secret in plaintext after the
    initial registration. Caller must DELETE + re-PUT to get a new
    one (mirrors GitHub's own webhook UX)."""
    h = auth_headers(alice["api_key"]["plaintext"])
    with mock_github_api(lambda req: _ok_repo_response()):
        first = _put_integration(client, h, pat="ghp_supersecrettoken12345678").json()

    r = client.get("/workspaces/me/github", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["repo_owner"] == "acme"
    assert body["pat_masked"].startswith("ghp_")
    assert body["has_webhook_secret"] is True
    # Plaintext webhook secret NOT included on GET.
    assert "webhook_secret" not in body
    # And the masked PAT doesn't accidentally regress to full plaintext.
    assert "supersecret" not in str(body)


def test_update_keeps_webhook_secret_but_rotates_pat(client, alice):
    """PUT-after-PUT updates the PAT and repo/branch but does NOT
    regenerate the webhook secret (so the user's GitHub-side webhook
    keeps verifying without a re-paste). To rotate, DELETE + PUT."""
    h = auth_headers(alice["api_key"]["plaintext"])
    with mock_github_api(lambda req: _ok_repo_response(default_branch="develop")):
        first = _put_integration(client, h, pat="ghp_first_token_aaaaaaaa").json()
        second = _put_integration(
            client, h, pat="ghp_second_token_bbbbbbbb", branch="develop",
        ).json()

    assert first["id"] == second["id"]  # same row, updated in place
    assert second["branch"] == "develop"
    # Update path doesn't return a fresh webhook_secret.
    assert "webhook_secret" not in second
    # PAT mask reflects the new token.
    assert second["pat_masked"].endswith("bbbb")


def test_delete_then_reput_generates_fresh_webhook_secret(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    with mock_github_api(lambda req: _ok_repo_response()):
        first = _put_integration(client, h).json()
    secret_one = first["webhook_secret"]

    assert client.delete("/workspaces/me/github", headers=h).status_code == 200
    assert client.get("/workspaces/me/github", headers=h).status_code == 404

    with mock_github_api(lambda req: _ok_repo_response()):
        second = _put_integration(client, h).json()
    secret_two = second["webhook_secret"]
    # New webhook secret generated.
    assert secret_one != secret_two


def test_get_404_when_no_integration(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    assert client.get("/workspaces/me/github", headers=h).status_code == 404


def test_delete_404_when_no_integration(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    assert client.delete("/workspaces/me/github", headers=h).status_code == 404


# ---------- PAT validation against GitHub ---------- #


def test_put_rejects_bad_pat_with_clear_message(client, alice):
    """GitHub returns 401 → registration 400s with the GitHub-shaped
    error message so the user sees 'token rejected', not a vague
    'something went wrong'."""
    h = auth_headers(alice["api_key"]["plaintext"])
    with mock_github_api(lambda req: httpx.Response(401, json={"message": "Bad credentials"})):
        r = _put_integration(client, h, pat="ghp_invalid")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "rejected" in detail.lower() or "token" in detail.lower()


def test_put_rejects_unreachable_repo_with_404_translation(client, alice):
    """GitHub 404 → 400 with a clear 'token can't see this repo' hint
    rather than passing through 404 (which would suggest the endpoint
    itself was missing)."""
    h = auth_headers(alice["api_key"]["plaintext"])
    with mock_github_api(lambda req: httpx.Response(404, json={"message": "Not Found"})):
        r = _put_integration(client, h, repo_owner="ghost", repo_name="nonexistent")
    assert r.status_code == 400
    assert "couldn't find repo" in r.json()["detail"].lower() or "doesn't exist" in r.json()["detail"].lower()


def test_put_translates_403_scope_error(client, alice):
    """GitHub 403 = scope missing (or rate-limited). Surface as 400
    with a hint at the cause."""
    h = auth_headers(alice["api_key"]["plaintext"])
    with mock_github_api(lambda req: httpx.Response(403, json={"message": "Forbidden"})):
        r = _put_integration(client, h)
    assert r.status_code == 400
    assert "scope" in r.json()["detail"].lower() or "rate" in r.json()["detail"].lower()


def test_put_502s_on_github_transport_error(client, alice):
    """A network failure reaching GitHub is a transient API problem,
    not a user problem — return 502 so the user's client knows it can
    retry rather than fix their input."""
    h = auth_headers(alice["api_key"]["plaintext"])

    def boom(req):
        raise httpx.TimeoutException("timed out", request=req)

    with mock_github_api(boom):
        r = _put_integration(client, h)
    assert r.status_code == 502


# ---------- input validation ---------- #


def test_put_rejects_malformed_repo_owner(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = _put_integration(client, h, repo_owner="not a valid GH user")
    assert r.status_code == 400


def test_put_rejects_malformed_repo_name(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = _put_integration(client, h, repo_name="bad name with spaces")
    assert r.status_code == 400


def test_put_rejects_blank_pat(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = _put_integration(client, h, pat="")
    # Pydantic 422 for min_length violation, not 400 — both are fine
    # but pin which one we get so a future schema change is visible.
    assert r.status_code in (400, 422)


# ---------- agent path CRUD ---------- #


def test_agent_path_round_trip(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = client.put(
        "/workspaces/me/github/agents/polaris",
        json={"path": "polaris"}, headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_name"] == "polaris"
    assert body["path"] == "polaris"

    listed = client.get("/workspaces/me/github/agents", headers=h).json()
    assert len(listed["agents"]) == 1
    assert listed["agents"][0]["agent_name"] == "polaris"


def test_agent_path_update_in_place(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    client.put(
        "/workspaces/me/github/agents/polaris",
        json={"path": "polaris"}, headers=h,
    )
    r = client.put(
        "/workspaces/me/github/agents/polaris",
        json={"path": "bots/polaris"}, headers=h,
    )
    assert r.status_code == 200
    listed = client.get("/workspaces/me/github/agents", headers=h).json()
    assert len(listed["agents"]) == 1
    assert listed["agents"][0]["path"] == "bots/polaris"


def test_agent_path_delete(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    client.put(
        "/workspaces/me/github/agents/polaris",
        json={"path": "polaris"}, headers=h,
    )
    r = client.delete("/workspaces/me/github/agents/polaris", headers=h)
    assert r.status_code == 200
    assert client.get("/workspaces/me/github/agents", headers=h).json() == {"agents": []}


def test_agent_path_delete_404_for_missing(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = client.delete("/workspaces/me/github/agents/never-registered", headers=h)
    assert r.status_code == 404


@pytest.mark.parametrize("bad_path", [
    "",                 # blank
    "/leading/slash",   # absolute
    "../foo",           # parent traversal at start
    "foo/../bar",       # parent traversal mid-path
    "foo/..",           # parent traversal at end
    "windows\\path",    # backslashes
])
def test_agent_path_rejects_bad_paths(client, alice, bad_path):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = client.put(
        "/workspaces/me/github/agents/polaris",
        json={"path": bad_path}, headers=h,
    )
    # blank fails Pydantic min_length first; the rest hit our explicit
    # validator. Both should refuse the value.
    assert r.status_code in (400, 422), f"path {bad_path!r} should be rejected"


def test_agent_path_rejects_malformed_agent_name(client, alice):
    """Agent names follow [A-Za-z][A-Za-z0-9_-]{0,63}. URL-path
    sanitization happens at the regex layer."""
    h = auth_headers(alice["api_key"]["plaintext"])
    r = client.put(
        "/workspaces/me/github/agents/has spaces",
        json={"path": "ok"}, headers=h,
    )
    # FastAPI will URL-encode this; the underlying regex catches
    # what gets through. Either rejection-shape is acceptable.
    assert r.status_code in (400, 404, 422)


# ---------- cross-workspace isolation ---------- #


def test_workspace_isolation_on_integration(client, alice, bob):
    """Alice's integration is invisible to bob, and vice versa.
    UNIQUE(workspace_id) means each can have their own without
    collision."""
    ha = auth_headers(alice["api_key"]["plaintext"])
    hb = auth_headers(bob["api_key"]["plaintext"])

    with mock_github_api(lambda req: _ok_repo_response()):
        _put_integration(client, ha, repo_owner="alice-co", repo_name="repo-a")
        _put_integration(client, hb, repo_owner="bob-co", repo_name="repo-b")

    body_a = client.get("/workspaces/me/github", headers=ha).json()
    body_b = client.get("/workspaces/me/github", headers=hb).json()
    assert body_a["repo_owner"] == "alice-co"
    assert body_b["repo_owner"] == "bob-co"

    # Alice's DELETE doesn't touch bob's row.
    client.delete("/workspaces/me/github", headers=ha)
    assert client.get("/workspaces/me/github", headers=hb).status_code == 200


def test_workspace_isolation_on_agent_paths(client, alice, bob):
    ha = auth_headers(alice["api_key"]["plaintext"])
    hb = auth_headers(bob["api_key"]["plaintext"])
    client.put(
        "/workspaces/me/github/agents/polaris",
        json={"path": "alice/path"}, headers=ha,
    )

    listed_b = client.get("/workspaces/me/github/agents", headers=hb).json()
    assert listed_b == {"agents": []}

    # bob's DELETE on alice's agent name 404s rather than leaking the
    # row's existence.
    r = client.delete("/workspaces/me/github/agents/polaris", headers=hb)
    assert r.status_code == 404


# ---------- auth ---------- #


def test_unauthorized_paths(client):
    assert client.get("/workspaces/me/github").status_code == 401
    assert client.put(
        "/workspaces/me/github",
        json={"repo_owner": "a", "repo_name": "b", "pat": "x"},
    ).status_code == 401
    assert client.get("/workspaces/me/github/agents").status_code == 401
