"""Offline deterministic validation pipeline with lazy Qlib runtime loading."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from quantos.validation.locators import (
    CostStressLocator,
    ParameterStabilityLocator,
    SubperiodLocator,
    ValidationRunLocators,
    VariantArtifactLocator,
)

if TYPE_CHECKING:
    from quantos.validation.service import (
        ValidationBuildResult,
        ValidationError,
        ValidationService,
        compare_backtest_artifacts,
        verify_validation_report,
    )

_SERVICE_EXPORTS = {
    "ValidationBuildResult",
    "ValidationError",
    "ValidationService",
    "compare_backtest_artifacts",
    "verify_validation_report",
}


def __getattr__(name: str) -> Any:
    if name not in _SERVICE_EXPORTS:
        raise AttributeError(name)
    return getattr(import_module("quantos.validation.service"), name)


__all__ = [
    "CostStressLocator",
    "ParameterStabilityLocator",
    "SubperiodLocator",
    "ValidationBuildResult",
    "ValidationError",
    "ValidationRunLocators",
    "ValidationService",
    "VariantArtifactLocator",
    "compare_backtest_artifacts",
    "verify_validation_report",
]
