"""Daily cost cap. Scoped per (workspace_id, agent_name)."""
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from cost import agent_cost_today

_GUARDED_ACTIONS = {
    "openai.chat.completions.create",
    "anthropic.messages.create",
}


def check(
    session: Session,
    *,
    workspace_id: str,
    agent_name: str,
    action: str,
    payload: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if action not in _GUARDED_ACTIONS:
        return None

    row = session.execute(
        text(
            """
            SELECT daily_cost_cap_usd FROM agents
            WHERE workspace_id = :wsid AND name = :name
            """
        ),
        {"wsid": workspace_id, "name": agent_name},
    ).first()
    if row is None:
        return None
    cap = row.daily_cost_cap_usd
    if cap is None:
        return None

    cost_so_far = agent_cost_today(session, workspace_id, agent_name)
    if cost_so_far >= cap:
        return {
            "allow": False,
            "reason": "daily cost cap exceeded",
            "policy": "cost_cap",
            "cost_so_far_usd": round(cost_so_far, 6),
            "cap_usd": cap,
        }
    return None
