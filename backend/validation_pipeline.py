"""Validation pipeline (Phase 7.3).

Wires the pure validators in `backend/validators/` into the event
ingestion path. Called from POST /events after the event is inserted:
looks up every (workspace_id, event.kind, validator_name) registered
in `validator_configs`, runs the matching validator function, and
writes one row to `event_validations` per validator.

Phase 7A is advisory: failures here never block ingestion. The
function catches every exception per-validator and records a row
with status='error' rather than raising, so a buggy validator can't
take down /events for a workspace. The 200ms cumulative cap is a
defensive backstop — validators are pure functions with no I/O, so
hitting it usually means a pathological regex or schema; remaining
validators get skipped with status='timeout'.

Phase 7B will move this pre-emit and make the pipeline blocking.
"""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

import validators
from models import Event, EventValidation, ValidatorConfig

logger = logging.getLogger("lightsei.validation")

# Total budget across all validators on one event. Validators are pure
# functions; if cumulative time exceeds this, something is pathological
# and we'd rather drop the rest than make every /events call slow.
TIME_BUDGET_S = 0.2


def _status_from_result(result: dict) -> str:
    """Map ValidationResult to the event_validations.status string.

    - ok=True, no violations -> 'pass'
    - ok=True, all violations are warn -> 'warn'
    - ok=False -> 'fail'
    """
    if not result["violations"]:
        return "pass"
    if result["ok"]:
        return "warn"
    return "fail"


def run_validators(session: Session, workspace_id: str, event: Event) -> None:
    """Run every validator registered for this workspace + event kind.

    Inserts one row per validator into event_validations. Errors per
    validator are recorded as rows with status='error'; the function
    itself never raises.
    """
    rows = session.execute(
        select(ValidatorConfig)
        .where(
            ValidatorConfig.workspace_id == workspace_id,
            ValidatorConfig.event_kind == event.kind,
        )
    ).scalars().all()

    if not rows:
        return

    started = time.monotonic()
    now = datetime.now(timezone.utc)

    for cfg in rows:
        elapsed = time.monotonic() - started
        if elapsed >= TIME_BUDGET_S:
            _insert_validation(
                session, event.id, cfg.validator_name,
                status="timeout",
                violations=[{
                    "rule": "timeout",
                    "message": (
                        f"validator skipped: cumulative budget "
                        f"{TIME_BUDGET_S}s exceeded"
                    ),
                }],
                created_at=now,
            )
            continue

        try:
            validator_fn = validators.REGISTRY.get(cfg.validator_name)
            if validator_fn is None:
                # Config references a validator that's no longer in the
                # registry (e.g. renamed in code without migrating the
                # config rows). Record an error so it's visible, don't
                # crash ingestion.
                _insert_validation(
                    session, event.id, cfg.validator_name,
                    status="error",
                    violations=[{
                        "rule": "unknown_validator",
                        "message": (
                            f"validator {cfg.validator_name!r} is not in "
                            "the registry; check validator_configs for "
                            "stale entries"
                        ),
                    }],
                    created_at=now,
                )
                continue

            result = validator_fn(event.payload, cfg.config)
            _insert_validation(
                session, event.id, cfg.validator_name,
                status=_status_from_result(result),
                violations=result["violations"],
                created_at=now,
            )
        except Exception as exc:
            # Defensive: a validator function should never raise (the
            # contract is "report errors as violations"), but if one
            # does, we record it without losing the event.
            logger.exception(
                "validator %s crashed on event %s",
                cfg.validator_name, event.id,
            )
            _insert_validation(
                session, event.id, cfg.validator_name,
                status="error",
                violations=[{
                    "rule": "validator_exception",
                    "message": f"{type(exc).__name__}: {exc}",
                }],
                created_at=now,
            )


def _insert_validation(
    session: Session,
    event_id: int,
    validator_name: str,
    *,
    status: str,
    violations: list,
    created_at: datetime,
) -> None:
    """ON CONFLICT DO NOTHING upsert.

    The unique constraint is (event_id, validator_name). A duplicate
    (e.g. retry path) is harmless and we'd rather keep the original
    result than overwrite — so DO NOTHING, not DO UPDATE.
    """
    stmt = pg_insert(EventValidation).values(
        event_id=event_id,
        validator_name=validator_name,
        status=status,
        violations=violations,
        created_at=created_at,
    ).on_conflict_do_nothing(
        index_elements=["event_id", "validator_name"],
    )
    session.execute(stmt)
