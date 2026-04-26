"""Agent control plane: receive commands from the Lightsei dashboard.

Usage:
    @lightsei.on_command("ping")
    def handle_ping(payload):
        return {"pong": True}

    lightsei.init(api_key="...", agent_name="my-bot")

Register handlers BEFORE init(). When init runs, if any handlers are
registered, a daemon poller thread starts and asks the backend for pending
commands every `command_poll_interval` seconds (default 5). For each command
the poller looks up the matching handler, calls it with the payload, and
posts the return value (or any raised exception) back as the result.

A built-in "ping" handler is registered by default so users can verify
connectivity from the dashboard without writing any code.
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("lightsei.commands")

# kind -> callable(payload: dict) -> dict | None
_handlers: Dict[str, Callable[[dict[str, Any]], Optional[dict[str, Any]]]] = {}


def on_command(kind: str):
    """Decorator: register a handler for a command kind.

    The handler receives the command's payload dict. Its return value (must
    be a dict or None) becomes the command's result. If the handler raises,
    the command is marked failed with the exception's repr.
    """
    def decorator(fn: Callable[[dict[str, Any]], Optional[dict[str, Any]]]):
        _handlers[kind] = fn
        return fn
    return decorator


# Built-in: a simple ping/pong so the dashboard's "send command" form is
# useful out of the box, even before the user writes any handlers.
@on_command("ping")
def _handle_ping(payload: dict[str, Any]) -> dict[str, Any]:
    return {"pong": True, "echo": payload}


class _Poller:
    def __init__(self, client, interval: float) -> None:
        self._client = client
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="lightsei-commands", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_once()
            except Exception as e:
                logger.warning("lightsei command poller error: %s", e)
            self._stop.wait(self._interval)

    def _tick_once(self) -> None:
        if self._client._http is None or not self._client.agent_name:
            return
        try:
            r = self._client._http.post(
                f"/agents/{self._client.agent_name}/commands/claim",
                timeout=self._client.timeout,
            )
            if r.status_code != 200:
                return
            cmd = r.json().get("command")
        except Exception:
            return
        if cmd is None:
            return
        self._dispatch(cmd)

    def _dispatch(self, cmd: dict[str, Any]) -> None:
        kind = cmd.get("kind") or ""
        cmd_id = cmd.get("id")
        handler = _handlers.get(kind)
        if handler is None:
            self._complete(cmd_id, error=f"no handler for command kind={kind!r}")
            return
        try:
            result = handler(cmd.get("payload") or {})
        except BaseException as e:
            self._complete(cmd_id, error=repr(e))
            return
        if result is not None and not isinstance(result, dict):
            result = {"value": result}
        self._complete(cmd_id, result=result)

    def _complete(
        self,
        cmd_id: Optional[str],
        *,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        if cmd_id is None or self._client._http is None:
            return
        body: dict[str, Any] = {}
        if error is not None:
            body["error"] = error
        elif result is not None:
            body["result"] = result
        try:
            self._client._http.post(
                f"/commands/{cmd_id}/complete",
                json=body,
                timeout=self._client.timeout,
            )
        except Exception as e:
            logger.warning("lightsei failed to post command result: %s", e)


def has_handlers() -> bool:
    """True if the user (or our built-in ping) registered at least one
    handler. Used by `init()` to decide whether to start a poller.

    Always True today because of the built-in ping handler — but kept as a
    hook in case we want to make ping opt-in later.
    """
    return bool(_handlers)
