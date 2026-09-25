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
from quantos.research.qlib.result import (
    ResearchResultArtifactBuilder,
    ResearchResultBuildResult,
    verify_p14dq_native_label_audit,
    verify_research_result,
)
from quantos.research.qlib.signal import (
    FactorSignalArtifactBuilder,
    SignalArtifactBuildResult,
    verify_signal_artifact,
)
from quantos.research.qlib.universe import (
    QlibResearchError,
    resolve_historical_universe,
    resolve_historical_universe_spans,
)
from quantos.research.qlib.workflow import QlibWorkflowResearchResult, QlibWorkflowResearchService

__all__ = [
    "EventSignalArtifactBuildResult",
    "EventSignalArtifactBuilder",
    "FactorSignalArtifactBuilder",
    "QlibResearchError",
    "QlibWorkflowResearchResult",
    "QlibWorkflowResearchService",
    "ResearchResultArtifactBuilder",
    "ResearchResultBuildResult",
    "SignalArtifactBuildResult",
    "build_compact_pit_evidence_collection",
    "build_event_signal_evidence",
    "build_pit_evidence_bundle",
    "build_pit_evidence_collection",
    "resolve_historical_universe",
    "resolve_historical_universe_spans",
    "subset_compact_pit_evidence",
    "translate_safe_expression",
    "verify_compact_pit_evidence",
    "verify_event_signal_artifact",
    "verify_event_signal_pit",
    "verify_p14dq_native_label_audit",
    "verify_research_result",
    "verify_signal_artifact",
]
