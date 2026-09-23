"""Application services exposed through deterministic entry points."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quantos.application.research_mcp import (
        DatasetBinding,
        LedgerSearchBinding,
        ProposalChainBinding,
        ResearchMcpError,
        ResearchMcpService,
        p14_research_mcp_policy,
        research_mcp_policy,
    )
    from quantos.application.stdio_rpc import (
        StdioJsonRpcAdapter,
        build_json_rpc_tool_schema,
        serve_stdio,
    )

from quantos.application.admission import (
    EventFeatureAdmissionError,
    EventFeatureAdmissionPolicy,
    build_event_feature_artifact,
)
from quantos.application.autonomous import (
    AutonomousAgentDriver,
    AutonomousAgentExchangeStore,
    AutonomousCampaignOrchestrator,
    AutonomousLoopReportStore,
    AutonomousOrchestrationError,
    CampaignEventStore,
    DeterministicResearchExecutionPort,
    ReplayAgentDriver,
    ScriptedAgentDriver,
)
from quantos.application.campaign_selection import (
    CampaignSelectionError,
    CampaignSelectionService,
    publish_selection_plan,
    verify_selection_plan_artifact,
    verify_selection_report_artifact,
)
from quantos.application.campaigns import CampaignGovernanceError, ResearchCampaignGovernor
from quantos.application.capabilities import publish_capability_report
from quantos.application.doctor import DoctorReport, build_doctor_report
from quantos.application.enumeration import (
    CandidateEnumerationError,
    build_candidate_duplicate_evidence,
    enumerate_research_family,
    exact_expression_hash,
    structural_expression_hash,
    verify_candidate_enumeration_manifest,
)
from quantos.application.event_features import (
    EventFeatureBuildResult,
    EventFeatureError,
    FrozenEventFeatureAdmissionPolicy,
    publish_event_feature_artifact,
    resolve_trading_sessions,
    verify_event_feature_artifact,
)
from quantos.application.evidence_mcp import (
    EvidenceBinding,
    EvidenceMcpError,
    EvidenceMcpService,
    evidence_mcp_policy,
)
from quantos.application.harness_spike import (
    build_codex_spike_report,
    evaluate_codex_capture,
)
from quantos.application.ledger import (
    ResearchLedgerError,
    ResearchLedgerService,
    bind_context_pack,
    build_context_bound_agent_run_spec,
    verify_context_bound_agent_manifest,
    verify_context_bound_agent_run_spec,
)
from quantos.application.pit import (
    PITAuditService,
    expression_field_names,
    load_canonical_pit_request_json,
    load_pit_spec_json,
    propagate_availability,
    temporal_from_canonical_row,
)
from quantos.application.proposal_mcp import (
    ProposalMcpError,
    ProposalMcpService,
    proposal_mcp_policy,
)
from quantos.application.proposals import ProposalCompilationError, compile_experiment_proposal
from quantos.application.provenance import (
    ProvenanceError,
    capture_code_provenance,
    capture_runtime_fingerprint,
    verify_code_provenance,
)
from quantos.application.security import (
    AgentRequestBoundary,
    AuthorityRootResolver,
    BoundaryAuditDecision,
    ResourceBudget,
    SecurityBoundaryError,
    load_bounded_json_object,
    restricted_agent_environment,
)
from quantos.application.specs import resolve_experiment

_LAZY_EXPORTS = {
    "DatasetBinding": ("quantos.application.research_mcp", "DatasetBinding"),
    "LedgerSearchBinding": ("quantos.application.research_mcp", "LedgerSearchBinding"),
    "ProposalChainBinding": ("quantos.application.research_mcp", "ProposalChainBinding"),
    "ResearchMcpError": ("quantos.application.research_mcp", "ResearchMcpError"),
    "ResearchMcpService": ("quantos.application.research_mcp", "ResearchMcpService"),
    "p14_research_mcp_policy": (
        "quantos.application.research_mcp",
        "p14_research_mcp_policy",
    ),
    "research_mcp_policy": ("quantos.application.research_mcp", "research_mcp_policy"),
    "StdioJsonRpcAdapter": ("quantos.application.stdio_rpc", "StdioJsonRpcAdapter"),
    "build_json_rpc_tool_schema": (
        "quantos.application.stdio_rpc",
        "build_json_rpc_tool_schema",
    ),
    "serve_stdio": ("quantos.application.stdio_rpc", "serve_stdio"),
}


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "AgentRequestBoundary",
    "AuthorityRootResolver",
    "AutonomousAgentDriver",
    "AutonomousAgentExchangeStore",
    "AutonomousCampaignOrchestrator",
    "AutonomousLoopReportStore",
    "AutonomousOrchestrationError",
    "BoundaryAuditDecision",
    "CampaignEventStore",
    "CampaignGovernanceError",
    "CampaignSelectionError",
    "CampaignSelectionService",
    "CandidateEnumerationError",
    "DatasetBinding",
    "DeterministicResearchExecutionPort",
    "DoctorReport",
    "EventFeatureAdmissionError",
    "EventFeatureAdmissionPolicy",
    "EventFeatureBuildResult",
    "EventFeatureError",
    "EvidenceBinding",
    "EvidenceMcpError",
    "EvidenceMcpService",
    "FrozenEventFeatureAdmissionPolicy",
    "LedgerSearchBinding",
    "PITAuditService",
    "ProposalChainBinding",
    "ProposalCompilationError",
    "ProposalMcpError",
    "ProposalMcpService",
    "ProvenanceError",
    "ReplayAgentDriver",
    "ResearchCampaignGovernor",
    "ResearchLedgerError",
    "ResearchLedgerService",
    "ResearchMcpError",
    "ResearchMcpService",
    "ResourceBudget",
    "ScriptedAgentDriver",
    "SecurityBoundaryError",
    "StdioJsonRpcAdapter",
    "bind_context_pack",
    "build_candidate_duplicate_evidence",
    "build_codex_spike_report",
    "build_context_bound_agent_run_spec",
    "build_doctor_report",
    "build_event_feature_artifact",
    "build_json_rpc_tool_schema",
    "capture_code_provenance",
    "capture_runtime_fingerprint",
    "compile_experiment_proposal",
    "enumerate_research_family",
    "evaluate_codex_capture",
    "evidence_mcp_policy",
    "exact_expression_hash",
    "expression_field_names",
    "load_bounded_json_object",
    "load_canonical_pit_request_json",
    "load_pit_spec_json",
    "p14_research_mcp_policy",
    "propagate_availability",
    "proposal_mcp_policy",
    "publish_capability_report",
    "publish_event_feature_artifact",
    "publish_selection_plan",
    "research_mcp_policy",
    "resolve_experiment",
    "resolve_trading_sessions",
    "restricted_agent_environment",
    "serve_stdio",
    "structural_expression_hash",
    "temporal_from_canonical_row",
    "verify_candidate_enumeration_manifest",
    "verify_code_provenance",
    "verify_context_bound_agent_manifest",
    "verify_context_bound_agent_run_spec",
    "verify_event_feature_artifact",
    "verify_selection_plan_artifact",
    "verify_selection_report_artifact",
]
