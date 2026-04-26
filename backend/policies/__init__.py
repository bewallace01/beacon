"""Lightsei policy engine (custom Python — see MEMORY.md "Policy engine decision").

Each rule is a pure function that returns either:
- None: rule is silent / not applicable
- dict with at least {"allow": bool, "reason": str}: rule has a verdict

`evaluate` runs the rules in order and returns the first deny it sees, or an
allow if every rule was silent or allowed.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session

from . import cost_cap

_RULES = [cost_cap.check]


def evaluate(
    session: Session,
    *,
    workspace_id: str,
    agent_name: Optional[str],
    action: Optional[str],
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not agent_name or not action:
        return {"allow": True}
    payload = payload or {}
    for rule in _RULES:
        verdict = rule(
            session,
            workspace_id=workspace_id,
            agent_name=agent_name,
            action=action,
            payload=payload,
        )
        if verdict is None:
            continue
        if not verdict.get("allow", True):
            return verdict
    return {"allow": True}
