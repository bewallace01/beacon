from typing import Any, Optional


class BeaconError(Exception):
    """Base class for Beacon-raised errors."""


class BeaconPolicyError(BeaconError):
    """Raised when a policy check denies an action."""

    def __init__(self, reason: str, decision: Optional[dict[str, Any]] = None):
        self.reason = reason
        self.decision = decision or {}
        super().__init__(reason)
