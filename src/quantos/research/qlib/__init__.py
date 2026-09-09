"""Thin deterministic configuration adapters for Qlib research."""

from quantos.research.qlib.event_signal import (
    EventSignalArtifactBuilder,
    EventSignalArtifactBuildResult,
    build_event_signal_evidence,
    verify_event_signal_artifact,
    verify_event_signal_pit,
)
from quantos.research.qlib.expression import translate_safe_expression
from quantos.research.qlib.pit_evidence import (
    build_compact_pit_evidence_collection,
    build_pit_evidence_bundle,
    build_pit_evidence_collection,
    subset_compact_pit_evidence,
    verify_compact_pit_evidence,
)
from quantos.research.qlib.signal import (
    FactorSignalArtifactBuilder,
    SignalArtifactBuildResult,
    verify_signal_artifact,
)
from quantos.research.qlib.universe import QlibResearchError, resolve_historical_universe

__all__ = [
    "EventSignalArtifactBuildResult",
    "EventSignalArtifactBuilder",
    "FactorSignalArtifactBuilder",
    "QlibResearchError",
    "SignalArtifactBuildResult",
    "build_compact_pit_evidence_collection",
    "build_event_signal_evidence",
    "build_pit_evidence_bundle",
    "build_pit_evidence_collection",
    "resolve_historical_universe",
    "subset_compact_pit_evidence",
    "translate_safe_expression",
    "verify_compact_pit_evidence",
    "verify_event_signal_artifact",
    "verify_event_signal_pit",
    "verify_signal_artifact",
]
