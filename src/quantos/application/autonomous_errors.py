"""Errors shared by autonomous control and execution adapter services."""

from __future__ import annotations

from quantos.contracts.status import ReasonCode


class AutonomousOrchestrationError(RuntimeError):
    """Integrity or authority failure that stops the autonomous loop."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
