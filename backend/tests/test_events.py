import uuid

from tests.conftest import auth_headers


def _post_event(client, headers, run_id, agent_name, kind, payload=None):
    r = client.post(
        "/events",
        json={
            "run_id": run_id,
            "agent_name": agent_name,
            "kind": kind,
            "payload": payload or {},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_post_event_creates_run_and_event(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    run_id = str(uuid.uuid4())

    _post_event(client, h, run_id, "demo", "run_started")
    _post_event(client, h, run_id, "demo", "custom", {"x": 1})

    r = client.get("/runs", headers=h)
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert any(r_["id"] == run_id and r_["agent_name"] == "demo" for r_ in runs)

    r = client.get(f"/runs/{run_id}/events", headers=h)
    assert r.status_code == 200
    body = r.json()
    kinds = [e["kind"] for e in body["events"]]
    assert kinds == ["run_started", "custom"]
    assert body["events"][1]["payload"] == {"x": 1}


def test_run_ended_sets_ended_at(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    run_id = str(uuid.uuid4())
    _post_event(client, h, run_id, "demo", "run_started")
    _post_event(client, h, run_id, "demo", "run_ended")

    r = client.get(f"/runs/{run_id}/events", headers=h)
    assert r.json()["run"]["ended_at"] is not None


def test_get_run_events_404_for_unknown(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    r = client.get(f"/runs/{uuid.uuid4()}/events", headers=h)
    assert r.status_code == 404


def test_run_id_collision_across_workspaces_409(client, alice, bob):
    """Two workspaces submitting the same run_id must not silently merge."""
    h_a = auth_headers(alice["api_key"]["plaintext"])
    h_b = auth_headers(bob["api_key"]["plaintext"])
    shared_id = str(uuid.uuid4())

    _post_event(client, h_a, shared_id, "demo", "run_started")

    r = client.post(
        "/events",
        json={
            "run_id": shared_id,
            "agent_name": "demo",
            "kind": "run_started",
            "payload": {},
        },
        headers=h_b,
    )
    assert r.status_code == 409
