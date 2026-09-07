from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from quantos.application import AgentRequestBoundary
from quantos.contracts import (
    AgentCapability,
    AgentCapabilityPolicy,
    AgentRole,
    AgentRunManifest,
    AgentRunSpec,
    AgentUsage,
    EvidenceAvailabilityKind,
    EvidenceCitation,
    EvidenceExtractionProposal,
    EvidenceRecord,
    EvidenceRevisionKind,
    EvidenceSourceKind,
    EvidenceUsePermission,
    ExpectedDirection,
    ExtractedTextArtifact,
    FactorProposalSpec,
    FalsificationCriterion,
    HypothesisProposal,
    InterpretationProposal,
    LedgerAssertionAuthority,
    ObservationProposal,
    ProposedAttribute,
    RegisteredFeatureRef,
    ResearchLedgerEvent,
    ResearchLedgerNodeKind,
    ResearchLedgerSnapshot,
    RunStatus,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    ToolInteractionDigest,
)

NOW = datetime(2026, 1, 5, 9, tzinfo=UTC)
H = "a" * 64


def _evidence(
    *, availability: EvidenceAvailabilityKind = EvidenceAvailabilityKind.PROVEN
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="ev-001",
        source_kind=EvidenceSourceKind.STRUCTURED_FIXTURE,
        source_locator="fixture://announcements/001",
        publisher="synthetic-fixture",
        retrieval_request_hash="1" * 64,
        retrieval_response_metadata_hash="2" * 64,
        raw_bytes_hash="3" * 64,
        raw_size_bytes=100,
        media_type="application/pdf",
        encoding=None,
        published_at=NOW,
        fetched_at=NOW,
        observed_at=NOW,
        available_at=None if availability is EvidenceAvailabilityKind.UNKNOWN else NOW,
        availability_kind=availability,
        availability_policy_hash="4" * 64,
        revision_kind=EvidenceRevisionKind.ORIGINAL,
        collector_version="fixture-collector/1",
        license_id="fixture-license/1",
        use_permission=EvidenceUsePermission.RESEARCH_ALLOWED,
        entity_refs=("600000.SH",),
        limitations=(),
    )


def _text(evidence: EvidenceRecord) -> ExtractedTextArtifact:
    return ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        text_hash="5" * 64,
        character_count=20,
        page_count=1,
        parser_name="fixture-parser",
        parser_version="1",
        parser_config_hash="6" * 64,
        code_commit_hash="7" * 40,
        runtime_fingerprint_hash="8" * 64,
    )


def _citation(evidence: EvidenceRecord, text: ExtractedTextArtifact) -> EvidenceCitation:
    return EvidenceCitation(
        evidence_hash=evidence.content_hash,
        extracted_text_hash=text.content_hash,
        page=1,
        char_start=0,
        char_end=10,
        cited_text_hash="9" * 64,
    )


def test_evidence_temporal_revision_and_citation_contracts_fail_closed() -> None:
    evidence = _evidence()
    text = _text(evidence)
    citation = _citation(evidence, text)

    assert citation.char_end == 10
    assert EvidenceRecord.model_validate_json(evidence.model_dump_json()) == evidence

    with pytest.raises(ValidationError, match="unknown availability"):
        EvidenceRecord.model_validate(
            {
                **_evidence().model_dump(mode="python"),
                "availability_kind": "UNKNOWN",
                "available_at": NOW,
            }
        )
    with pytest.raises(ValidationError, match="revision lineage"):
        EvidenceRecord.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "revision_kind": "REVISION",
                "predecessor_evidence_hash": None,
            }
        )
    with pytest.raises(ValidationError, match="character range"):
        EvidenceCitation.model_validate(
            {**citation.model_dump(mode="python"), "char_start": 10, "char_end": 10}
        )


def test_observation_hypothesis_factor_and_interpretation_remain_proposals() -> None:
    evidence = _evidence()
    text = _text(evidence)
    citation = _citation(evidence, text)
    observation = ObservationProposal(
        proposal_id="obs-001",
        agent_run_hash="a" * 64,
        statement="The fixture contains a disclosed event.",
        citations=(citation,),
    )
    hypothesis = HypothesisProposal(
        proposal_id="hyp-001",
        agent_run_hash="b" * 64,
        observation_hashes=(observation.content_hash,),
        claim="The event may be followed by a positive response.",
        mechanism="The disclosure may change investor expectations.",
        evidence_citations=(citation,),
        expected_direction=ExpectedDirection.POSITIVE,
        confounders=("recent_return",),
        falsification=(
            FalsificationCriterion(
                metric="annualized_return",
                comparison="min",
                threshold=0,
                segment="SEALED_CONFIRMATION",
            ),
        ),
    )
    expression = SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="absolute_delta",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
            SafeExpressionNode(node_id="delta", operator="delta", inputs=("price",), window=2),
            SafeExpressionNode(node_id="output", operator="abs", inputs=("delta",)),
        ),
        output_node_id="output",
    )
    factor = FactorProposalSpec(
        proposal_id="factor-001",
        agent_run_hash="c" * 64,
        hypothesis_hash=hypothesis.content_hash,
        family_hash="0" * 64,
        factor_template_hash="1" * 64,
        parameters=(ProposedAttribute(name="window", value=2),),
        expression=expression,
        registered_features=(
            RegisteredFeatureRef(
                field_name="adjusted_close",
                source_artifact_hash="d" * 64,
                availability_policy_hash="e" * 64,
            ),
        ),
        rationale="Use only an admitted safe expression DAG.",
    )
    interpretation = InterpretationProposal(
        proposal_id="interpretation-001",
        agent_run_hash="f" * 64,
        campaign_hash="1" * 64,
        validation_report_hash="2" * 64,
        summary="This text does not alter the deterministic verdict.",
        findings=("The configured gate result remains authoritative.",),
    )

    assert factor.expression.schema_version == "safe-qlib-expression/v2"
    assert interpretation.validation_report_hash == "2" * 64
    with pytest.raises(ValidationError):
        HypothesisProposal.model_validate(
            {**hypothesis.model_dump(mode="python"), "status": "VALIDATED"}
        )
    with pytest.raises(ValidationError, match="every expression field"):
        FactorProposalSpec.model_validate(
            {**factor.model_dump(mode="python"), "registered_features": []}
        )
    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate(
            {**interpretation.model_dump(mode="python"), "verdict": "PASS"}
        )


def test_extraction_proposal_citations_must_bind_exact_frozen_text() -> None:
    evidence = _evidence()
    text = _text(evidence)
    citation = _citation(evidence, text)
    proposal = EvidenceExtractionProposal(
        proposal_id="extract-001",
        agent_run_hash="a" * 64,
        evidence_hash=evidence.content_hash,
        extracted_text_hash=text.content_hash,
        event_label="share_repurchase",
        entity_refs=("600000.SH",),
        proposed_event_time=NOW,
        citations=(citation,),
    )

    assert proposal.citations == (citation,)
    with pytest.raises(ValidationError, match="must bind"):
        EvidenceExtractionProposal.model_validate(
            {
                **proposal.model_dump(mode="python"),
                "extracted_text_hash": "f" * 64,
            }
        )


def test_capability_policy_drives_the_p8_boundary_without_authority_access() -> None:
    capabilities = tuple(
        sorted(
            (
                AgentCapability.DATASET_DESCRIBE,
                AgentCapability.PROPOSAL_SUBMIT_HYPOTHESIS,
            ),
            key=str,
        )
    )
    policy = AgentCapabilityPolicy(
        policy_id="researcher-v1",
        capabilities=capabilities,
        max_payload_bytes=1000,
        max_payload_depth=8,
        max_payload_nodes=100,
        max_string_bytes=500,
        max_requests=10,
        environment_allowlist=("LANG", "TZ"),
    )
    boundary = AgentRequestBoundary.from_policy(policy)

    assert boundary.accept("dataset.describe", b'{"snapshot_hash":"' + b"a" * 64 + b'"}')
    with pytest.raises(ValueError):
        AgentCapabilityPolicy.model_validate(
            {**policy.model_dump(mode="python"), "network_allowed": True}
        )


def test_agent_run_manifest_binds_provenance_but_never_claims_reproducible_text() -> None:
    run_spec = AgentRunSpec(
        run_id="agent-run-001",
        role=AgentRole.RESEARCHER,
        capability_policy_hash="1" * 64,
        campaign_hash="2" * 64,
        requested_model_configuration_hash="3" * 64,
        tool_schema_hash="4" * 64,
        instruction_hashes=("5" * 64,),
        skill_hash="6" * 64,
        evidence_hashes=("7" * 64,),
    )
    interaction = ToolInteractionDigest(
        sequence=1,
        capability=AgentCapability.DATASET_DESCRIBE,
        request_hash="8" * 64,
        response_hash="9" * 64,
        succeeded=True,
    )
    manifest = AgentRunManifest(
        run_spec_hash=run_spec.content_hash,
        provider_thread_id="thread-synthetic-001",
        provider_model_identifier="provider/model-version",
        model_snapshot_immutable=False,
        model_configuration_hash=run_spec.requested_model_configuration_hash,
        harness_identifier="codex/test",
        sandbox_policy_hash="a" * 64,
        permission_policy_hash="b" * 64,
        runtime_policy_hash="c" * 64,
        instruction_hashes=run_spec.instruction_hashes,
        skill_hash=run_spec.skill_hash,
        tool_schema_hash=run_spec.tool_schema_hash,
        interactions=(interaction,),
        input_hashes=("d" * 64,),
        output_proposal_hashes=("e" * 64,),
        transcript_hash="f" * 64,
        usage=AgentUsage(
            input_tokens=100,
            output_tokens=20,
            tool_calls=1,
            retry_count=0,
        ),
        run_status=RunStatus.SUCCEEDED,
        limitations=("MODEL_IDENTIFIER_NOT_IMMUTABLE",),
        started_at=NOW,
        completed_at=NOW,
    )

    assert manifest.run_spec_hash == run_spec.content_hash
    with pytest.raises(ValidationError, match="limitation"):
        AgentRunManifest.model_validate({**manifest.model_dump(mode="python"), "limitations": []})
    with pytest.raises(ValidationError, match="failed Agent run"):
        AgentRunManifest.model_validate(
            {
                **manifest.model_dump(mode="python"),
                "run_status": "FAILED",
                "failure_reason_code": "HARNESS_FAILED",
            }
        )


def test_ledger_explicitly_separates_source_agent_human_and_verdict_authority() -> None:
    source = ResearchLedgerEvent(
        event_id=UUID("11111111-1111-1111-1111-111111111111"),
        ledger_id="ledger-001",
        sequence=1,
        node_id="evidence-001",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_hash="1" * 64,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW,
    )
    agent = ResearchLedgerEvent(
        event_id=UUID("22222222-2222-2222-2222-222222222222"),
        ledger_id="ledger-001",
        sequence=2,
        node_id="hypothesis-001",
        node_kind=ResearchLedgerNodeKind.HYPOTHESIS_PROPOSAL,
        object_hash="2" * 64,
        authority=LedgerAssertionAuthority.AGENT_PROPOSAL,
        parent_object_hashes=(source.object_hash,),
        agent_run_hash="3" * 64,
        occurred_at=NOW,
        previous_event_hash=source.content_hash,
    )
    human = ResearchLedgerEvent(
        event_id=UUID("22222222-2222-2222-2222-222222222223"),
        ledger_id="ledger-001",
        sequence=3,
        node_id="review-001",
        node_kind=ResearchLedgerNodeKind.HUMAN_REVIEW_STATEMENT,
        object_hash="3" * 64,
        authority=LedgerAssertionAuthority.HUMAN_REVIEWED,
        parent_object_hashes=(agent.object_hash,),
        human_review_evidence_hash="4" * 64,
        occurred_at=NOW,
        previous_event_hash=agent.content_hash,
    )
    verdict = ResearchLedgerEvent(
        event_id=UUID("33333333-3333-3333-3333-333333333333"),
        ledger_id="ledger-001",
        sequence=4,
        node_id="validation-001",
        node_kind=ResearchLedgerNodeKind.VALIDATION_REPORT,
        object_hash="5" * 64,
        authority=LedgerAssertionAuthority.DETERMINISTIC_VERDICT,
        parent_object_hashes=(human.object_hash,),
        validation_report_hash="5" * 64,
        occurred_at=NOW,
        previous_event_hash=human.content_hash,
    )
    snapshot = ResearchLedgerSnapshot(
        ledger_id="ledger-001",
        source_event_hashes=(
            source.content_hash,
            agent.content_hash,
            human.content_hash,
            verdict.content_hash,
        ),
        head_event_hash=verdict.content_hash,
        node_object_hashes=tuple(
            sorted((source.object_hash, agent.object_hash, human.object_hash, verdict.object_hash))
        ),
        created_at=NOW,
    )

    assert snapshot.head_event_hash == verdict.content_hash
    with pytest.raises(ValidationError, match="proposal nodes"):
        ResearchLedgerEvent.model_validate(
            {
                **agent.model_dump(mode="python"),
                "node_kind": "VALIDATION_REPORT",
            }
        )
