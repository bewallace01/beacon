from typing import Any, Optional


class LightseiError(Exception):
    """Base class for Lightsei-raised errors."""


class LightseiPolicyError(LightseiError):
    """Raised when a policy check denies an action."""

    def __init__(self, reason: str, decision: Optional[dict[str, Any]] = None):
        self.reason = reason
        self.decision = decision or {}
        super().__init__(reason)
