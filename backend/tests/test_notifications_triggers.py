"""Phase 9.4: end-to-end trigger pipeline.

Tests POST /events firing notifications via BackgroundTasks. The
FastAPI TestClient runs background tasks in-process during the
request lifecycle (synchronously), so we can post an event, then
inspect the deliveries table immediately to verify the right
channels were notified with the right triggers.

Pure trigger-detection logic gets covered separately in
test_notifications_dispatch.py via the helpers; this file is
about the integration: event ingestion -> channels enqueued ->
audit rows written.

httpx is mocked at the notifications._http layer so the dispatcher
can run end-to-end without making real HTTP calls.
"""
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import httpx
from sqlalchemy import select

from models import NotificationDelivery
from notifications import _http as notifications_http
from notifications.triggers import (
    TRIGGER_POLARIS_PLAN,
    TRIGGER_RUN_FAILED,
    TRIGGER_VALIDATION_FAIL,
    detect_triggers,
)
from tests.conftest import auth_headers
from validation_pipeline import ValidationOutcome


# ---------- httpx mock helper (shared across notifications tests) ---------- #


@contextmanager
def mock_httpx_post(handler):
    """Same pattern as test_notifications_dispatch.mock_httpx_post.
    Re-implemented here rather than imported because tests in the
    same suite share state if one mocks at import time."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    with patch.object(notifications_http.httpx, "Client", side_effect=factory):
        yield


# ---------- detect_triggers (pure logic) ---------- #


def _outcome(status: str, name: str = "schema_strict") -> ValidationOutcome:
    return ValidationOutcome(
        validator_name=name, mode="advisory", status=status, violations=[],
    )


class _FakeEvent:
    """Stand-in for a sqlalchemy Event row in unit tests of
    detect_triggers — only the fields detect_triggers reads."""
    def __init__(self, kind: str):
        self.kind = kind


def test_detect_polaris_plan_fires_on_kind_match():
    fired = detect_triggers(_FakeEvent("polaris.plan"), [_outcome("pass")])
    assert fired == ["polaris.plan"]


def test_detect_run_failed_fires_on_kind_match():
    fired = detect_triggers(_FakeEvent("run_failed"), [])
    assert fired == ["run_failed"]


def test_detect_validation_fail_fires_when_any_outcome_failed():
    fired = detect_triggers(
        _FakeEvent("custom"),
        [_outcome("pass"), _outcome("fail", name="content_rules")],
    )
    assert fired == ["validation.fail"]


def test_detect_polaris_plan_with_fail_fires_both():
    """A polaris.plan event whose validations failed should fire both
    triggers — a channel subscribed to either gets one notification,
    a channel subscribed to both gets two."""
    fired = detect_triggers(
        _FakeEvent("polaris.plan"),
        [_outcome("fail")],
    )
    assert TRIGGER_POLARIS_PLAN in fired
    assert TRIGGER_VALIDATION_FAIL in fired


def test_detect_no_triggers_for_run_started_with_pass_validations():
    """The most common event type fires nothing — keeps the trigger
    pipeline a no-op for the bulk of /events traffic."""
    fired = detect_triggers(_FakeEvent("run_started"), [_outcome("pass")])
    assert fired == []


def test_detect_validation_fail_only_fires_once_per_event():
    """Two failing validators on one event = one validation.fail
    trigger, not two. Receivers get one notification per event."""
    fired = detect_triggers(
        _FakeEvent("custom"),
        [_outcome("fail", "schema_strict"), _outcome("fail", "content_rules")],
    )
    assert fired.count("validation.fail") == 1


def test_detect_warn_outcomes_dont_fire_validation_fail():
    """warn-status validations are advisory — they shouldn't ping
    notifications. Only 'fail' fires."""
    fired = detect_triggers(_FakeEvent("custom"), [_outcome("warn")])
    assert "validation.fail" not in fired


# ---------- end-to-end: POST /events triggers BG dispatch ---------- #


def _create_channel(client, headers, *, name="primary", type_="slack",
                    triggers=None, target_url="https://hooks.slack.com/services/T/B/X"):
    body = {
        "name": name,
        "type": type_,
        "target_url": target_url,
        "triggers": triggers or [TRIGGER_POLARIS_PLAN, TRIGGER_VALIDATION_FAIL, TRIGGER_RUN_FAILED],
    }
    r = client.post("/workspaces/me/notifications", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _post_event(client, headers, kind, payload, run_id=None):
    return client.post(
        "/events",
        json={
            "run_id": run_id or str(uuid.uuid4()),
            "agent_name": "polaris",
            "kind": kind,
            "payload": payload,
        },
        headers=headers,
    )


def _deliveries_for(channel_id):
    """Read all deliveries for a channel via the ORM — bypasses the
    audit endpoint to verify rows even if endpoint logic has bugs."""
    from db import engine
    from sqlalchemy.orm import Session as ORMSession

    with ORMSession(engine) as s:
        rows = s.execute(
            select(NotificationDelivery)
            .where(NotificationDelivery.channel_id == channel_id)
            .order_by(NotificationDelivery.id)
        ).scalars().all()
        # Materialize while session is open
        return [(r.trigger, r.status, r.event_id) for r in rows]


def test_polaris_plan_event_fires_subscribed_channel(client, alice):
    """The happy path: register a Slack channel subscribed to
    polaris.plan, POST a polaris.plan event, expect one
    notification_deliveries row."""
    h = auth_headers(alice["api_key"]["plaintext"])
    ch = _create_channel(client, h, name="slack-test",
                         triggers=[TRIGGER_POLARIS_PLAN])

    captured: list[str] = []

    def handler(req):
        captured.append(str(req.url))
        return httpx.Response(200, text="ok")

    with mock_httpx_post(handler):
        r = _post_event(client, h, "polaris.plan", {
            "summary": "test plan",
            "next_actions": [],
            "doc_hashes": {"memory_md": "x", "tasks_md": "y"},
            "model": "claude-opus-4-7",
            "tokens_in": 1, "tokens_out": 1,
        })
    assert r.status_code == 200

    deliveries = _deliveries_for(ch["id"])
    assert len(deliveries) == 1
    trigger, status, event_id = deliveries[0]
    assert trigger == TRIGGER_POLARIS_PLAN
    assert status == "sent"
    assert event_id == r.json()["id"]
    assert captured == ["https://hooks.slack.com/services/T/B/X"]


def test_event_with_no_matching_subscriptions_creates_no_deliveries(client, alice):
    """Channel subscribed only to polaris.plan; we post a run_started
    event. No notifications fire."""
    h = auth_headers(alice["api_key"]["plaintext"])
    ch = _create_channel(client, h, name="plan-only",
                         triggers=[TRIGGER_POLARIS_PLAN])

    with mock_httpx_post(lambda req: httpx.Response(200, text="ok")):
        r = _post_event(client, h, "run_started", {})
    assert r.status_code == 200
    assert _deliveries_for(ch["id"]) == []


def test_inactive_channel_skipped(client, alice):
    """An is_active=False channel doesn't fire even on matching
    triggers. Useful for users who want to mute a channel without
    deleting it."""
    h = auth_headers(alice["api_key"]["plaintext"])
    ch = _create_channel(client, h, name="muted",
                         triggers=[TRIGGER_POLARIS_PLAN])
    # Mute the channel
    client.patch(
        f"/workspaces/me/notifications/{ch['id']}",
        json={"is_active": False},
        headers=h,
    )

    with mock_httpx_post(lambda req: httpx.Response(200, text="ok")):
        _post_event(client, h, "polaris.plan", {})
    assert _deliveries_for(ch["id"]) == []


def test_channel_with_multiple_matching_triggers_gets_one_per_trigger(client, alice):
    """A polaris.plan event with a fail validation outcome + a channel
    subscribed to both polaris.plan AND validation.fail = 2 deliveries.
    No deduplication: each subscribed trigger is its own message."""
    h = auth_headers(alice["api_key"]["plaintext"])
    # Register a blocking-... wait, advisory schema_strict so validation
    # outcome lands a fail row but the event still ingests.
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary", "next_actions"],
        "additionalProperties": True,
    }
    client.put(
        "/workspaces/me/validators/polaris.plan/schema_strict",
        json={"config": {"schema": schema}, "mode": "advisory"},
        headers=h,
    )

    ch = _create_channel(client, h, name="both-subs",
                         triggers=[TRIGGER_POLARIS_PLAN, TRIGGER_VALIDATION_FAIL])

    with mock_httpx_post(lambda req: httpx.Response(200, text="ok")):
        # Missing required `next_actions` -> validation fails (but
        # advisory, so event still lands).
        r = _post_event(client, h, "polaris.plan", {"summary": "x"})
    assert r.status_code == 200

    deliveries = _deliveries_for(ch["id"])
    triggers_fired = sorted(d[0] for d in deliveries)
    assert triggers_fired == [TRIGGER_POLARIS_PLAN, TRIGGER_VALIDATION_FAIL]
    assert all(d[1] == "sent" for d in deliveries)


def test_multiple_channels_subscribed_each_get_their_own_delivery(client, alice):
    """Two channels, both subscribed to polaris.plan = 2 deliveries
    (one per channel) for one event."""
    h = auth_headers(alice["api_key"]["plaintext"])
    ch1 = _create_channel(client, h, name="channel-one",
                          triggers=[TRIGGER_POLARIS_PLAN])
    ch2 = _create_channel(client, h, name="channel-two",
                          triggers=[TRIGGER_POLARIS_PLAN],
                          type_="discord",
                          target_url="https://discord.com/api/webhooks/X/Y")

    captured: list[str] = []

    def handler(req):
        captured.append(str(req.url))
        return httpx.Response(200, text="ok")

    with mock_httpx_post(handler):
        _post_event(client, h, "polaris.plan", {})

    assert len(_deliveries_for(ch1["id"])) == 1
    assert len(_deliveries_for(ch2["id"])) == 1
    # Both URLs got hit
    assert "https://hooks.slack.com/services/T/B/X" in captured
    assert "https://discord.com/api/webhooks/X/Y" in captured


def test_cross_workspace_isolation(client, alice, bob):
    """Alice's channel doesn't fire on bob's events even if both
    workspaces have channels with the same name + same trigger
    subscriptions."""
    ha = auth_headers(alice["api_key"]["plaintext"])
    hb = auth_headers(bob["api_key"]["plaintext"])
    ch_alice = _create_channel(client, ha, name="alice-ch",
                                triggers=[TRIGGER_POLARIS_PLAN])

    captured = []
    with mock_httpx_post(lambda req: (captured.append(str(req.url)),
                                       httpx.Response(200, text="ok"))[1]):
        # Bob posts a polaris.plan event under his workspace
        _post_event(client, hb, "polaris.plan", {})

    # Alice's channel should not have any deliveries.
    assert _deliveries_for(ch_alice["id"]) == []
    # And no http call landed on alice's URL.
    assert captured == []


def test_failed_dispatch_still_records_delivery_row(client, alice):
    """Receiver returns 4xx -> delivery row lands with status=failed,
    event ingestion still returns 200. The audit trail captures the
    failure for the user to debug."""
    h = auth_headers(alice["api_key"]["plaintext"])
    ch = _create_channel(client, h, name="bad-url",
                         triggers=[TRIGGER_POLARIS_PLAN])

    with mock_httpx_post(lambda req: httpx.Response(401, text="unauthorized")):
        r = _post_event(client, h, "polaris.plan", {})
    assert r.status_code == 200

    deliveries = _deliveries_for(ch["id"])
    assert len(deliveries) == 1
    assert deliveries[0][1] == "failed"


def test_run_failed_event_fires_run_failed_trigger(client, alice):
    h = auth_headers(alice["api_key"]["plaintext"])
    ch = _create_channel(client, h, name="crash-watch",
                         triggers=[TRIGGER_RUN_FAILED])

    with mock_httpx_post(lambda req: httpx.Response(200, text="ok")):
        _post_event(client, h, "run_failed", {"error": "RuntimeError: kaboom"})

    deliveries = _deliveries_for(ch["id"])
    assert len(deliveries) == 1
    assert deliveries[0][0] == TRIGGER_RUN_FAILED
    assert deliveries[0][1] == "sent"


def test_trigger_pipeline_does_not_block_ingestion_on_dispatcher_crash(client, alice, monkeypatch):
    """If the dispatcher itself crashes (registry corruption,
    unexpected exception), the event still ingests cleanly. The
    background task records a failed delivery; nothing surfaces to
    the /events caller.

    Patches the bound name `run_dispatch` inside notifications.triggers
    (where dispatch_and_persist actually calls it), not
    notifications.dispatch — `from notifications import dispatch as
    run_dispatch` was bound at module-load time, so monkeypatching the
    notifications package wouldn't reach the call site."""
    h = auth_headers(alice["api_key"]["plaintext"])
    ch = _create_channel(client, h, name="canary",
                         triggers=[TRIGGER_POLARIS_PLAN])

    from notifications import triggers as triggers_mod

    def boom(*args, **kwargs):
        raise RuntimeError("simulated dispatcher crash")
    monkeypatch.setattr(triggers_mod, "run_dispatch", boom)

    r = _post_event(client, h, "polaris.plan", {})
    assert r.status_code == 200

    deliveries = _deliveries_for(ch["id"])
    assert len(deliveries) == 1
    assert deliveries[0][1] == "failed"
    # The dispatcher-exception path tagged the delivery's
    # response_summary with the right error type.
    from db import engine
    from sqlalchemy.orm import Session as ORMSession
    with ORMSession(engine) as s:
        row = s.execute(
            select(NotificationDelivery)
            .where(NotificationDelivery.channel_id == ch["id"])
        ).scalar_one()
        assert row.response_summary["error"] == "dispatch_exception"
        assert "simulated dispatcher crash" in row.response_summary["message"]
