"""Offline research adapters that delegate execution to Qlib."""

from quantos.research.event_study import (
    EventStudyBuildResult,
    EventStudyError,
    build_event_study,
    verify_event_study,
)
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
    "EventStudyBuildResult",
    "EventStudyError",
    "FactorSignalArtifactBuilder",
    "QlibResearchError",
    "SignalArtifactBuildResult",
    "build_event_study",
    "build_pit_evidence_bundle",
    "build_pit_evidence_collection",
    "resolve_historical_universe",
    "translate_safe_expression",
    "verify_event_study",
    "verify_signal_artifact",
]
