"""Cost rollup helpers shared by /agents/{name}/cost and the cost-cap rule."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from pricing import compute_cost_usd


def utc_day_start() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def utc_day_start_iso() -> str:
    return utc_day_start().isoformat()


def agent_cost_since(
    session: Session,
    workspace_id: str,
    agent_name: str,
    since: datetime,
) -> dict[str, Any]:
    """Total + per-model cost for `agent_name` in `workspace_id` since `since`."""
    rows = session.execute(
        text(
            """
            SELECT
                payload ->> 'model' AS model,
                COALESCE((payload ->> 'input_tokens')::int, 0) AS input_tokens,
                COALESCE((payload ->> 'output_tokens')::int, 0) AS output_tokens
            FROM events
            WHERE workspace_id = :wsid
              AND agent_name = :agent_name
              AND kind = 'llm_call_completed'
              AND timestamp >= :since
            """
        ),
        {"wsid": workspace_id, "agent_name": agent_name, "since": since},
    ).all()

    by_model: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    total_input = 0
    total_output = 0

    for r in rows:
        model = r.model or "unknown"
        input_tokens = r.input_tokens or 0
        output_tokens = r.output_tokens or 0
        priced_model = model if model != "unknown" else None
        cost = compute_cost_usd(priced_model, input_tokens, output_tokens)
        bucket = by_model.setdefault(
            model,
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["cost_usd"] += cost
        total_cost += cost
        total_input += input_tokens
        total_output += output_tokens

    return {
        "calls": len(rows),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost_usd": round(total_cost, 6),
        "by_model": {
            m: {**v, "cost_usd": round(v["cost_usd"], 6)}
            for m, v in by_model.items()
        },
    }


def agent_cost_today(
    session: Session, workspace_id: str, agent_name: str
) -> float:
    return agent_cost_since(session, workspace_id, agent_name, utc_day_start())[
        "cost_usd"
    ]
