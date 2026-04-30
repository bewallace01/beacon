"""Trigger pipeline (Phase 9.4) — wires event ingestion to notification dispatch.

Three pieces:

  detect_triggers(event, outcomes) -> list[str]
      Inspect the just-ingested event + its validation outcomes and
      return the symbolic triggers that fired. An event can fire
      multiple triggers (a polaris.plan event with a fail-status
      validation fires both `polaris.plan` AND `validation.fail`).

  build_dispatch_plans(session, ...) -> list[DispatchPlan]
      For each fired trigger, find every active workspace channel
      whose `triggers` list includes it. Build a Signal per
      (channel, trigger) pair. Pure read against the DB; no writes.

  dispatch_and_persist(plan)
      Run one dispatch and record the NotificationDelivery row. Has
      its own DB session — designed to be called from FastAPI
      BackgroundTasks after the request response is sent. Never
      raises.

The split lets POST /events do the cheap detection + plan-building
synchronously inside the request transaction (so a single read of
the channel list serves all triggers) but defer the slow HTTP-out
to background tasks.

Phase 7 + 8's blocking validators run BEFORE the event is inserted,
so a 422-rejected event never reaches this pipeline — that's the
intended behavior. A blocking-validator rejection is invisible to
notifications by design (the user wanted it suppressed). Phase 10+
can add a `validation.blocked` trigger if we want to surface those
explicitly.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Event, NotificationChannel, NotificationDelivery
from notifications import dispatch as run_dispatch
from notifications._types import Signal
from validation_pipeline import ValidationOutcome

logger = logging.getLogger("lightsei.notifications.triggers")


# Symbolic trigger names. Kept stable across underlying event-kind
# renames so a channel registered today keeps working when we tweak
# event kinds later. The dashboard surfaces these too in 9.5's
# trigger checkboxes.
TRIGGER_POLARIS_PLAN = "polaris.plan"
TRIGGER_VALIDATION_FAIL = "validation.fail"
TRIGGER_RUN_FAILED = "run_failed"


@dataclass
class DispatchPlan:
    """One queued dispatch. The fields are exactly what
    dispatch_and_persist needs — no DB session reference, no live
    ORM rows, so the plan can outlive the request that built it."""
    channel_id: str
    channel_type: str
    target_url: str
    secret_token: str | None
    trigger: str
    event_id: int
    signal: Signal


def detect_triggers(
    event: Event, outcomes: Iterable[ValidationOutcome]
) -> list[str]:
    """Which symbolic triggers does this just-ingested event fire?

    Order is stable so a channel subscribed to multiple triggers
    receives them in a predictable sequence.
    """
    fired: list[str] = []
    if event.kind == TRIGGER_POLARIS_PLAN:
        fired.append(TRIGGER_POLARIS_PLAN)
    # validation.fail fires when ANY of this event's validation outcomes
    # has fail status. Only one trigger emission per event (not per
    # failing validator) — receivers get one notification per event,
    # not one per rule violated.
    if any(o.status == "fail" for o in outcomes):
        if TRIGGER_VALIDATION_FAIL not in fired:
            fired.append(TRIGGER_VALIDATION_FAIL)
    if event.kind == "run_failed":
        fired.append(TRIGGER_RUN_FAILED)
    return fired


def build_dispatch_plans(
    session: Session,
    *,
    event: Event,
    workspace_id: str,
    fired_triggers: list[str],
    dashboard_url_for,
    payload_for_signal: dict | None = None,
) -> list[DispatchPlan]:
    """Read the workspace's active channels, cross-product with
    fired_triggers, build one plan per matching (channel, trigger).

    `dashboard_url_for(trigger, agent_name, run_id)` is injected by
    the caller so the dashboard URL builder lives in main.py (where
    DASHBOARD_BASE_URL is configured) rather than depending on it
    here. Keeps this module testable without importing main.

    `payload_for_signal` defaults to `event.payload` but lets the
    caller supplement (e.g., attach validation outcomes to a
    validation.fail signal so the formatter has them — the event's
    own payload doesn't carry the post-emit validation results).
    """
    if not fired_triggers:
        return []

    channels = session.execute(
        select(NotificationChannel).where(
            NotificationChannel.workspace_id == workspace_id,
            NotificationChannel.is_active == True,  # noqa: E712 — explicit for SQL clarity
        )
    ).scalars().all()
    if not channels:
        return []

    plans: list[DispatchPlan] = []
    base_payload = payload_for_signal if payload_for_signal is not None else (event.payload or {})

    for ch in channels:
        ch_triggers = list(ch.triggers or [])
        for trigger in fired_triggers:
            if trigger not in ch_triggers:
                continue
            signal = Signal(
                trigger=trigger,
                agent_name=event.agent_name,
                dashboard_url=dashboard_url_for(trigger, event.agent_name, event.run_id),
                timestamp=event.timestamp,
                payload=base_payload,
                workspace_id=workspace_id,
            )
            plans.append(DispatchPlan(
                channel_id=ch.id,
                channel_type=ch.type,
                target_url=ch.target_url,
                secret_token=ch.secret_token,
                trigger=trigger,
                event_id=event.id,
                signal=signal,
            ))
    return plans


def dispatch_and_persist(plan: DispatchPlan) -> None:
    """Run one dispatch in the background and record the audit row.

    Called from FastAPI BackgroundTasks after the /events response
    is sent. Has its own DB session because the request session is
    closed by the time this runs. Never raises — every failure path
    produces a Delivery and a corresponding row.
    """
    # Local imports keep this function importable from contexts that
    # don't have the full backend wired up (e.g., per-task retry
    # tooling we might add later).
    from db import engine
    from sqlalchemy.orm import Session as ORMSession

    try:
        delivery = run_dispatch(
            channel_type=plan.channel_type,
            target_url=plan.target_url,
            signal=plan.signal,
            secret_token=plan.secret_token,
        )
    except Exception as exc:  # belt and suspenders — dispatch shouldn't raise
        logger.exception("notification dispatch crashed for channel %s", plan.channel_id)
        from notifications._types import Delivery
        delivery = Delivery(
            status="failed",
            response_summary={
                "error": "dispatch_exception",
                "message": f"{type(exc).__name__}: {exc}",
            },
        )

    try:
        with ORMSession(engine) as session:
            row = NotificationDelivery(
                channel_id=plan.channel_id,
                event_id=plan.event_id,
                trigger=plan.trigger,
                status=delivery.status,
                response_summary=delivery.response_summary,
                attempt_count=delivery.attempt_count,
                sent_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
    except Exception:  # pragma: no cover — last-ditch
        # Audit-row write failure shouldn't crash the background task.
        # The Delivery is gone but the dispatched message either landed
        # or didn't on the wire — we log and move on.
        logger.exception(
            "failed to persist notification_delivery for channel %s event %s",
            plan.channel_id, plan.event_id,
        )
