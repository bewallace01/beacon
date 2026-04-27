"""Phase 5.1: deployment upload + list + delete.

Worker-facing endpoints land in 5.2; this file only covers the user-facing
upload surface.
"""
import io

from tests.conftest import auth_headers


def _upload(client, headers, agent_name="my-bot", payload=b"PK\x03\x04fake-zip"):
    return client.post(
        "/workspaces/me/deployments",
        headers=headers,
        data={"agent_name": agent_name},
        files={"bundle": ("bundle.zip", io.BytesIO(payload), "application/zip")},
    )


def test_upload_creates_queued_deployment(client, alice):
    h = auth_headers(alice["session_token"])
    r = _upload(client, h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_name"] == "my-bot"
    assert body["status"] == "queued"
    assert body["desired_state"] == "running"
    assert body["source_blob_id"]
    assert body["claimed_by"] is None
    assert body["started_at"] is None


def test_list_returns_uploaded_deployment(client, alice):
    h = auth_headers(alice["session_token"])
    _upload(client, h, "alpha")
    _upload(client, h, "beta")

    r = client.get("/workspaces/me/deployments", headers=h)
    assert r.status_code == 200
    deps = r.json()["deployments"]
    assert {d["agent_name"] for d in deps} == {"alpha", "beta"}


def test_list_filter_by_agent_name(client, alice):
    h = auth_headers(alice["session_token"])
    _upload(client, h, "alpha")
    _upload(client, h, "beta")

    r = client.get(
        "/workspaces/me/deployments?agent_name=alpha", headers=h,
    )
    deps = r.json()["deployments"]
    assert {d["agent_name"] for d in deps} == {"alpha"}


def test_get_one_returns_metadata(client, alice):
    h = auth_headers(alice["session_token"])
    created = _upload(client, h).json()
    r = client.get(
        f"/workspaces/me/deployments/{created['id']}", headers=h,
    )
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_cross_workspace_isolation(client, alice, bob):
    h_a = auth_headers(alice["session_token"])
    h_b = auth_headers(bob["session_token"])
    created = _upload(client, h_a).json()

    # Bob's list does not include alice's deployment.
    r = client.get("/workspaces/me/deployments", headers=h_b)
    assert r.json()["deployments"] == []

    # Bob's GET-by-id returns 404 (no leak).
    r = client.get(
        f"/workspaces/me/deployments/{created['id']}", headers=h_b,
    )
    assert r.status_code == 404

    # Bob's DELETE returns 404 too.
    r = client.delete(
        f"/workspaces/me/deployments/{created['id']}", headers=h_b,
    )
    assert r.status_code == 404


def test_delete_removes_deployment_and_blob(client, alice):
    """The blob should be GC'd when the last deployment referencing it goes."""
    h = auth_headers(alice["session_token"])
    created = _upload(client, h).json()
    blob_id = created["source_blob_id"]

    r = client.delete(
        f"/workspaces/me/deployments/{created['id']}", headers=h,
    )
    assert r.status_code == 200

    # Deployment is gone.
    r = client.get(
        f"/workspaces/me/deployments/{created['id']}", headers=h,
    )
    assert r.status_code == 404

    # Blob is gone too — query the table directly.
    from sqlalchemy import text
    from db import engine
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id FROM deployment_blobs WHERE id = :id"),
            {"id": blob_id},
        ).all()
    assert len(rows) == 0


def test_empty_bundle_400(client, alice):
    h = auth_headers(alice["session_token"])
    r = _upload(client, h, payload=b"")
    assert r.status_code == 400


def test_oversized_bundle_413(client, alice):
    """Body cap middleware rejects a >10 MB upload before it hits the route."""
    h = auth_headers(alice["session_token"])
    big = b"x" * (10 * 1024 * 1024 + 1024)
    r = _upload(client, h, payload=big)
    assert r.status_code == 413


def test_bundle_storage_is_lossless(client, alice):
    """The exact bytes we uploaded come back out of deployment_blobs."""
    h = auth_headers(alice["session_token"])
    payload = bytes(range(256)) * 4  # 1024 bytes of varied content
    r = _upload(client, h, payload=payload)
    assert r.status_code == 200
    blob_id = r.json()["source_blob_id"]

    from sqlalchemy import text
    from db import engine
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT data, size_bytes, sha256 FROM deployment_blobs WHERE id = :id"
            ),
            {"id": blob_id},
        ).all()
    assert len(rows) == 1
    data, size, sha = rows[0]
    assert bytes(data) == payload
    assert size == len(payload)
    import hashlib
    assert sha == hashlib.sha256(payload).hexdigest()


def test_deployment_creates_agent_row_if_new(client, alice):
    """Uploading for an unseen agent_name should ensure the agent row, so the
    deployment shows up correctly on the agents list."""
    h = auth_headers(alice["session_token"])
    _upload(client, h, agent_name="brand-new-bot")

    r = client.get("/agents", headers=h)
    names = [a["name"] for a in r.json()["agents"]]
    assert "brand-new-bot" in names


def test_logs_fetch_returns_recent_lines(client, alice):
    """Worker writes via /worker/* (tested in test_worker_api). User reads
    via /workspaces/me/deployments/{id}/logs."""
    h = auth_headers(alice["session_token"])
    dep = _upload(client, h).json()

    # Seed via the worker endpoint.
    worker_h = {"Authorization": "Bearer test-worker-token"}
    client.post(
        f"/worker/deployments/{dep['id']}/logs",
        headers=worker_h,
        json={"lines": [
            {"stream": "stdout", "line": f"line {i}"} for i in range(5)
        ]},
    )

    r = client.get(
        f"/workspaces/me/deployments/{dep['id']}/logs", headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert [x["line"] for x in body["lines"]] == [f"line {i}" for i in range(5)]
    assert body["max_id"] > 0


def test_logs_fetch_after_id_returns_incremental(client, alice):
    h = auth_headers(alice["session_token"])
    dep = _upload(client, h).json()
    worker_h = {"Authorization": "Bearer test-worker-token"}

    client.post(
        f"/worker/deployments/{dep['id']}/logs",
        headers=worker_h,
        json={"lines": [
            {"stream": "stdout", "line": f"a{i}"} for i in range(3)
        ]},
    )
    r = client.get(
        f"/workspaces/me/deployments/{dep['id']}/logs", headers=h,
    )
    first_max = r.json()["max_id"]

    client.post(
        f"/worker/deployments/{dep['id']}/logs",
        headers=worker_h,
        json={"lines": [
            {"stream": "stdout", "line": f"b{i}"} for i in range(2)
        ]},
    )
    r = client.get(
        f"/workspaces/me/deployments/{dep['id']}/logs"
        f"?after_id={first_max}",
        headers=h,
    )
    body = r.json()
    assert [x["line"] for x in body["lines"]] == ["b0", "b1"]


def test_logs_cross_workspace_404(client, alice, bob):
    h_a = auth_headers(alice["session_token"])
    h_b = auth_headers(bob["session_token"])
    dep = _upload(client, h_a).json()
    r = client.get(
        f"/workspaces/me/deployments/{dep['id']}/logs", headers=h_b,
    )
    assert r.status_code == 404


def test_stop_flips_desired_state(client, alice):
    h = auth_headers(alice["session_token"])
    dep = _upload(client, h).json()
    assert dep["desired_state"] == "running"

    r = client.post(
        f"/workspaces/me/deployments/{dep['id']}/stop", headers=h,
    )
    assert r.status_code == 200
    assert r.json()["desired_state"] == "stopped"


def test_redeploy_creates_new_pointing_at_same_blob(client, alice):
    h = auth_headers(alice["session_token"])
    old = _upload(client, h, agent_name="x").json()
    blob_id = old["source_blob_id"]

    r = client.post(
        f"/workspaces/me/deployments/{old['id']}/redeploy", headers=h,
    )
    assert r.status_code == 200
    new = r.json()
    assert new["id"] != old["id"]
    assert new["source_blob_id"] == blob_id
    assert new["status"] == "queued"
    assert new["agent_name"] == "x"

    # Old deployment is now flagged stopped.
    refetch = client.get(
        f"/workspaces/me/deployments/{old['id']}", headers=h,
    ).json()
    assert refetch["desired_state"] == "stopped"


def test_unauthenticated_blocked(client):
    r = client.get("/workspaces/me/deployments")
    assert r.status_code == 401
    r = client.post(
        "/workspaces/me/deployments",
        data={"agent_name": "x"},
        files={"bundle": ("b.zip", io.BytesIO(b"abc"), "application/zip")},
    )
    assert r.status_code == 401
