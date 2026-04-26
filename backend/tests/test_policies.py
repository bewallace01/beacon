"""Cost-cap policy. This is the only layer-2 rule in the spine, and it's the
demo criterion for Phase 2, so it has to keep working forever."""
import uuid

from tests.conftest import auth_headers


def _seed_completed_call(client, headers, agent_name, model,
                         input_tokens, output_tokens):
    run_id = str(uuid.uuid4())
    client.post(
        "/events",
        json={
            "run_id": run_id, "agent_name": agent_name,
            "kind": "run_started", "payload": {},
        },
        headers=headers,
    )
    client.post(
        "/events",
        json={
            "run_id": run_id, "agent_name": agent_name,
            "kind": "llm_call_completed",
            "payload": {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        },
        headers=headers,
    )


def test_no_cap_means_allow(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = client.post(
        "/policy/check",
        json={
            "agent_name": "demo",
            "action": "openai.chat.completions.create",
            "payload": {},
        },
        headers=h,
    )
    assert r.status_code == 200
    assert r.json() == {"allow": True}


def test_under_cap_allow(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    client.patch("/agents/demo", json={"daily_cost_cap_usd": 1.00}, headers=h)

    # gpt-4o-mini is cheap, this won't approach $1
    _seed_completed_call(client, h, "demo", "gpt-4o-mini", 1000, 500)

    r = client.post(
        "/policy/check",
        json={"agent_name": "demo", "action": "openai.chat.completions.create"},
        headers=h,
    )
    assert r.json() == {"allow": True}


def test_over_cap_deny_openai(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    # Tiny cap so a single recorded call breaches it.
    client.patch(
        "/agents/demo", json={"daily_cost_cap_usd": 1e-9}, headers=h,
    )
    _seed_completed_call(client, h, "demo", "gpt-4o-mini", 1000, 500)

    r = client.post(
        "/policy/check",
        json={"agent_name": "demo", "action": "openai.chat.completions.create"},
        headers=h,
    )
    body = r.json()
    assert body["allow"] is False
    assert body["policy"] == "cost_cap"
    assert body["reason"] == "daily cost cap exceeded"
    assert body["cap_usd"] == 1e-9
    assert body["cost_so_far_usd"] > 1e-9


def test_over_cap_deny_anthropic(client, alice):
    """Cap should cover anthropic action too — same rollup, both providers."""
    h = auth_headers(alice["api_key"]["plaintext"])
    client.patch("/agents/demo", json={"daily_cost_cap_usd": 1e-9}, headers=h)
    _seed_completed_call(client, h, "demo", "claude-haiku-4-5", 100, 50)

    r = client.post(
        "/policy/check",
        json={"agent_name": "demo", "action": "anthropic.messages.create"},
        headers=h,
    )
    assert r.json()["allow"] is False


def test_non_guarded_action_allowed_even_when_over_cap(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    client.patch("/agents/demo", json={"daily_cost_cap_usd": 1e-9}, headers=h)
    _seed_completed_call(client, h, "demo", "gpt-4o-mini", 1000, 500)

    r = client.post(
        "/policy/check",
        json={"agent_name": "demo", "action": "demo.unrelated.action"},
        headers=h,
    )
    assert r.json() == {"allow": True}


def test_caps_are_workspace_scoped(client, alice, bob):
    """Alice's cap must not affect bob's policy decisions for an agent that
    happens to share the same name."""
    h_a = auth_headers(alice["api_key"]["plaintext"])
    h_b = auth_headers(bob["api_key"]["plaintext"])

    client.patch("/agents/shared", json={"daily_cost_cap_usd": 1e-9}, headers=h_a)
    _seed_completed_call(client, h_a, "shared", "gpt-4o-mini", 1000, 500)

    # Alice over cap.
    r = client.post(
        "/policy/check",
        json={"agent_name": "shared", "action": "openai.chat.completions.create"},
        headers=h_a,
    )
    assert r.json()["allow"] is False

    # Bob has no cap on his "shared" agent — must be allowed.
    r = client.post(
        "/policy/check",
        json={"agent_name": "shared", "action": "openai.chat.completions.create"},
        headers=h_b,
    )
    assert r.json() == {"allow": True}
