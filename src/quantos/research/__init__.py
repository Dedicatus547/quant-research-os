"""Offline research adapters that delegate execution to Qlib."""

from quantos.research.qlib import (
    FactorSignalArtifactBuilder,
    QlibResearchError,
    SignalArtifactBuildResult,
    build_pit_evidence_bundle,
    build_pit_evidence_collection,
    resolve_historical_universe,
    translate_safe_expression,
    verify_signal_artifact,
)

__all__ = [
    "FactorSignalArtifactBuilder",
    "QlibResearchError",
    "SignalArtifactBuildResult",
    "build_pit_evidence_bundle",
    "build_pit_evidence_collection",
    "resolve_historical_universe",
    "translate_safe_expression",
    "verify_signal_artifact",
]
