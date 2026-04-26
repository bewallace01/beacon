"""Beacon Python SDK.

Public surface:
    beacon.init(api_key, agent_name, version)
    @beacon.track
    beacon.emit(kind, payload)
    beacon.flush()
    beacon.shutdown()
    beacon.get_run_id()
"""

import logging
from typing import Any, Optional

from ._client import _client
from ._context import get_run_id
from ._track import track
from .errors import BeaconError, BeaconPolicyError

_log = logging.getLogger("beacon")

__all__ = [
    "init",
    "track",
    "emit",
    "flush",
    "shutdown",
    "check_policy",
    "get_run_id",
    "BeaconError",
    "BeaconPolicyError",
]


def init(
    api_key: Optional[str] = None,
    agent_name: Optional[str] = None,
    version: str = "0.0.0",
    *,
    base_url: Optional[str] = None,
    flush_interval: Optional[float] = None,
    batch_size: Optional[int] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> None:
    """Initialize Beacon. Idempotent: a second call is ignored."""
    _client.init(
        api_key=api_key,
        agent_name=agent_name,
        version=version,
        base_url=base_url,
        flush_interval=flush_interval,
        batch_size=batch_size,
        timeout=timeout,
        max_retries=max_retries,
    )
    _auto_patch()


def _auto_patch() -> None:
    try:
        from .integrations.openai_patch import patch_openai
        patch_openai()
    except Exception as e:
        _log.warning("beacon openai auto-patch failed: %s", e)
    try:
        from .integrations.anthropic_patch import patch_anthropic
        patch_anthropic()
    except Exception as e:
        _log.warning("beacon anthropic auto-patch failed: %s", e)


def emit(
    kind: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    run_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> None:
    _client.emit(kind, payload, run_id=run_id, agent_name=agent_name)


def check_policy(
    action: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    run_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> dict[str, Any]:
    return _client.check_policy(
        action, payload, run_id=run_id, agent_name=agent_name
    )


def flush(timeout: float = 2.0) -> None:
    _client.flush(timeout=timeout)


def shutdown() -> None:
    _client.shutdown()
