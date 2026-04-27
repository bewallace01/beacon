"""Per-process bot identity + heartbeat.

On init() we mint a UUID, capture hostname/pid/sdk_version, and register
the instance with the backend. A daemon thread re-posts the heartbeat on
a timer so the dashboard can show "live now" status.

Graceful degradation: every backend call is best-effort. If the network
flaps, we keep heartbeating; the next successful call refreshes status.
A failure never crashes the user's bot.
"""
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("lightsei.instance")


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


class _HeartbeatPoster:
    def __init__(
        self,
        client,
        interval_s: float,
    ) -> None:
        self._client = client
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._instance_id: str = str(uuid.uuid4())
        self._hostname: str = _hostname()
        self._pid: int = os.getpid()
        self._started_at: datetime = datetime.now(timezone.utc)

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        # Fire one heartbeat synchronously on start so the dashboard sees the
        # instance immediately rather than waiting for the first tick.
        self._post_once()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="lightsei-instance", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Wait first so we don't double-post immediately after start().
            if self._stop.wait(self._interval):
                return
            try:
                self._post_once()
            except Exception as e:
                logger.warning("lightsei heartbeat error: %s", e)

    def _post_once(self) -> None:
        if self._client._http is None or not self._client.agent_name:
            return
        try:
            self._client._http.post(
                f"/agents/{self._client.agent_name}/instances/heartbeat",
                json={
                    "instance_id": self._instance_id,
                    "hostname": self._hostname,
                    "pid": self._pid,
                    "sdk_version": self._client.version,
                    "started_at": self._started_at.isoformat(),
                },
                timeout=self._client.timeout,
            )
        except Exception as e:
            logger.debug("lightsei heartbeat post failed: %s", e)
