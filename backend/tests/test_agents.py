from tests.conftest import auth_headers


def test_patch_cap_only_does_not_clear_prompt(client, alice):
    """Regression: the partial-update path must respect model_fields_set so that
    PATCH-ing only one field never wipes the other."""
    h = auth_headers(alice["session_token"])

    # Set a system prompt first.
    r = client.patch(
        "/agents/demo",
        json={"system_prompt": "you are a helpful agent"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "you are a helpful agent"

    # Now set a cap without sending system_prompt at all.
    r = client.patch(
        "/agents/demo",
        json={"daily_cost_cap_usd": 0.50},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["daily_cost_cap_usd"] == 0.50
    assert body["system_prompt"] == "you are a helpful agent"  # preserved


def test_patch_cap_null_clears(client, alice):
    h = auth_headers(alice["session_token"])
    client.patch("/agents/demo", json={"daily_cost_cap_usd": 1.00}, headers=h)
    r = client.patch("/agents/demo", json={"daily_cost_cap_usd": None}, headers=h)
    assert r.status_code == 200
    assert r.json()["daily_cost_cap_usd"] is None


def test_patch_system_prompt_whitespace_clears(client, alice):
    h = auth_headers(alice["session_token"])
    client.patch("/agents/demo", json={"system_prompt": "be nice"}, headers=h)
    r = client.patch("/agents/demo", json={"system_prompt": "   "}, headers=h)
    assert r.status_code == 200
    assert r.json()["system_prompt"] is None


def test_get_agent_404_when_unknown(client, alice):
    h = auth_headers(alice["session_token"])
    r = client.get("/agents/never-seen", headers=h)
    assert r.status_code == 404
