"""Validation pipeline (Phase 7.3, blocking added in Phase 8.2).

Wires the pure validators in `backend/validators/` into the event
ingestion path. Two phases:

  evaluate_validators(workspace_id, event_kind, payload) → outcomes
      Looks up every (workspace_id, event_kind, validator_name)
      registered in `validator_configs`, runs the matching validator,
      returns a list of ValidationOutcome objects (one per config).
      Pure — no event row required, no DB writes.

  find_blocking_failures(outcomes) → list[ValidationOutcome]
      Returns the outcomes that should reject the event at ingestion
      (mode='blocking', status='fail'). Errors and timeouts on
      blocking validators do NOT block — only an explicit fail. A
      buggy or slow validator can't take the API down.

  write_validation_rows(event_id, outcomes) → None
      Persists the outcomes to event_validations once the event has
      a row id.

POST /events calls these in order: evaluate → check blocking → if
clear, insert event → write rows. Phase 7A behavior (every config in
advisory mode, no rejection) is preserved by find_blocking_failures
returning [] when no configs are blocking.

Time budget: cumulative 200ms across all validators on one event.
Validators are pure functions; if cumulative time exceeds this,
something is pathological. Remaining configs get status='timeout'
outcomes and are not blocking.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

import validators
from models import EventValidation, ValidatorConfig

logger = logging.getLogger("lightsei.validation")

# Total budget across all validators on one event. See module docstring.
TIME_BUDGET_S = 0.2


@dataclass
class ValidationOutcome:
    validator_name: str
    mode: str          # "advisory" | "blocking"
    status: str        # "pass" | "fail" | "warn" | "error" | "timeout"
    violations: list[dict[str, Any]]


def _status_from_result(result: dict) -> str:
    """Map a validator's ValidationResult to a status string.

    - ok=True, no violations -> 'pass'
    - ok=True, violations present -> 'warn' (only warn-severity entries)
    - ok=False -> 'fail'
    """
    if not result["violations"]:
        return "pass"
    if result["ok"]:
        return "warn"
    return "fail"


def evaluate_validators(
    session: Session,
    workspace_id: str,
    event_kind: str,
    payload: Any,
) -> list[ValidationOutcome]:
    """Run every validator registered for this workspace + event kind.

    Pure compute pass — no DB writes, no event_id required. Caller
    decides whether to act on the outcomes (block, write audit rows,
    both).
    """
    rows = session.execute(
        select(ValidatorConfig)
        .where(
            ValidatorConfig.workspace_id == workspace_id,
            ValidatorConfig.event_kind == event_kind,
        )
    ).scalars().all()

    if not rows:
        return []

    outcomes: list[ValidationOutcome] = []
    started = time.monotonic()

    for cfg in rows:
        elapsed = time.monotonic() - started
        if elapsed >= TIME_BUDGET_S:
            outcomes.append(ValidationOutcome(
                validator_name=cfg.validator_name,
                mode=cfg.mode,
                status="timeout",
                violations=[{
                    "rule": "timeout",
                    "message": (
                        f"validator skipped: cumulative budget "
                        f"{TIME_BUDGET_S}s exceeded"
                    ),
                }],
            ))
            continue

        validator_fn = validators.REGISTRY.get(cfg.validator_name)
        if validator_fn is None:
            outcomes.append(ValidationOutcome(
                validator_name=cfg.validator_name,
                mode=cfg.mode,
                status="error",
                violations=[{
                    "rule": "unknown_validator",
                    "message": (
                        f"validator {cfg.validator_name!r} is not in the "
                        "registry; check validator_configs for stale entries"
                    ),
                }],
            ))
            continue

        try:
            result = validator_fn(payload, cfg.config)
            outcomes.append(ValidationOutcome(
                validator_name=cfg.validator_name,
                mode=cfg.mode,
                status=_status_from_result(result),
                violations=result["violations"],
            ))
        except Exception as exc:
            # Validator functions should never raise (the contract is
            # "report errors as violations") but if one does, we record
            # it as a status='error' outcome rather than crashing the
            # request. error != fail, so this never blocks.
            logger.exception(
                "validator %s crashed evaluating event_kind=%s",
                cfg.validator_name, event_kind,
            )
            outcomes.append(ValidationOutcome(
                validator_name=cfg.validator_name,
                mode=cfg.mode,
                status="error",
                violations=[{
                    "rule": "validator_exception",
                    "message": f"{type(exc).__name__}: {exc}",
                }],
            ))

    return outcomes


def find_blocking_failures(
    outcomes: list[ValidationOutcome],
) -> list[ValidationOutcome]:
    """Outcomes that should reject the event at ingestion.

    Only `mode='blocking' AND status='fail'` blocks. Errors and
    timeouts on blocking validators do NOT block — a buggy or slow
    validator must not take the API down for a workspace.
    """
    return [o for o in outcomes if o.mode == "blocking" and o.status == "fail"]


def write_validation_rows(
    session: Session,
    event_id: int,
    outcomes: list[ValidationOutcome],
) -> None:
    """Persist outcomes to event_validations.

    Called after the event row exists. ON CONFLICT DO NOTHING so a
    retry path (if it ever exists) doesn't duplicate rows.
    """
    if not outcomes:
        return
    now = datetime.now(timezone.utc)
    for o in outcomes:
        stmt = pg_insert(EventValidation).values(
            event_id=event_id,
            validator_name=o.validator_name,
            status=o.status,
            violations=o.violations,
            created_at=now,
        ).on_conflict_do_nothing(
            index_elements=["event_id", "validator_name"],
        )
        session.execute(stmt)
