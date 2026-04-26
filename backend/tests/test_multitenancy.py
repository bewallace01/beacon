"""Cross-workspace isolation. The whole multi-tenancy story rests on these."""
import uuid

from tests.conftest import auth_headers


def test_alice_cannot_read_bob_runs(client, alice, bob):
    h_a = auth_headers(alice["api_key"]["plaintext"])
    h_b = auth_headers(bob["api_key"]["plaintext"])

    bob_run = str(uuid.uuid4())
    client.post(
        "/events",
        json={
            "run_id": bob_run, "agent_name": "demo",
            "kind": "run_started", "payload": {},
        },
        headers=h_b,
    )

    # Alice's /runs list does not include bob's run.
    r = client.get("/runs", headers=h_a)
    assert r.status_code == 200
    assert all(r_["id"] != bob_run for r_ in r.json()["runs"])

    # Direct read returns 404 (not 403, no leakage of existence).
    r = client.get(f"/runs/{bob_run}/events", headers=h_a)
    assert r.status_code == 404


def test_same_agent_name_independent_caps(client, alice, bob):
    """Two workspaces can both have an agent named 'shared' with independent
    settings. The composite PK on agents is the load-bearing piece."""
    h_a = auth_headers(alice["session_token"])
    h_b = auth_headers(bob["session_token"])

    client.patch("/agents/shared", json={"daily_cost_cap_usd": 0.10}, headers=h_a)
    client.patch("/agents/shared", json={"daily_cost_cap_usd": 5.00}, headers=h_b)

    a = client.get("/agents/shared", headers=h_a).json()
    b = client.get("/agents/shared", headers=h_b).json()
    assert a["daily_cost_cap_usd"] == 0.10
    assert b["daily_cost_cap_usd"] == 5.00


def test_alice_cannot_see_bob_api_keys(client, alice, bob):
    h_a = auth_headers(alice["session_token"])
    r = client.get("/workspaces/me/api-keys", headers=h_a)
    assert r.status_code == 200
    keys = r.json()["api_keys"]
    # Only one key — alice's own. Bob's must not appear.
    assert len(keys) == 1
