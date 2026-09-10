from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.config import load_yaml_contract
from quantos.contracts import (
    EventFeatureAdmissionPolicySpec,
    EventFeatureArtifactFile,
    EventFeatureArtifactManifest,
    EventFeatureBenchmarkCase,
    EventStudyArtifactFile,
    EventStudyArtifactManifest,
    EventStudyMetric,
    EventStudyRow,
    EventStudySpec,
    JsonRpcToolDescriptor,
    JsonRpcToolSchemaManifest,
    JsonRpcTranscript,
    JsonRpcTranscriptEntry,
    P13BenchmarkBinding,
    P13QualificationBundle,
    P13QualificationReport,
    ProposedAttribute,
    ReasonCode,
    RunStatus,
    TradingSessionResolution,
    ValidationVerdict,
    canonical_json_bytes,
    sha256_bytes,
)

ROOT = Path(__file__).parents[2]


def _policy() -> EventFeatureAdmissionPolicySpec:
    return load_yaml_contract(
        ROOT / "configs/research/p13_share_repurchase_benchmark_v1.yaml",
        EventFeatureAdmissionPolicySpec,
    )


def test_human_frozen_real_sse_benchmark_is_exact() -> None:
    policy = load_yaml_contract(
        ROOT / "configs/research/p13_real_sse_share_repurchase_benchmark_v1.yaml",
        EventFeatureAdmissionPolicySpec,
    )

    assert policy.content_hash == "dcae0005fe5a0ea8323629b1336cb2c94d5e915c7191d94139c3811ad2ee78a6"
    assert len(policy.cases) == 1
    case = policy.cases[0]
    assert case.content_hash == "4f6fc3171da7ceb18ddca0d0efdb6312b3e9f2dded35d558a53cacf04102cb39"
    assert case.entity_refs == ("600010.SH",)
    assert case.attributes == ()

    binding = load_yaml_contract(
        ROOT / "configs/research/p13_real_sse_benchmark_binding_v1.yaml",
        P13BenchmarkBinding,
    )
    assert binding.evidence_store_hash == (
        "be484479b61c7096ffd58e99fa31168dc06a7fc7ae4597a2d455cda2c41250b1"
    )
    assert binding.evidence_hash == (
        "a9bded470d48a604ba33d137e17a06be1b0d0a104c7ccf4ae267e9bb4a716aee"
    )
    assert binding.extracted_text_hash == (
        "36850b3940cf85db08d08843008bfe711d0f6f26b23ca55f1a48ec37732d8d46"
    )


def test_p13_qualification_bundle_is_hash_only_and_canonical() -> None:
    bundle = P13QualificationBundle(
        benchmark_binding_hash="1" * 64,
        qualification_report_hash="2" * 64,
        native_bridge_report_hash="3" * 64,
        independent_root_count=2,
        limitations=("NO_DATA_QUALIFIED_EVENT_RESULT", "SINGLE_SOURCE_NON_VINTAGE"),
    )
    assert bundle.model_dump(mode="json")["schema_version"] == "p13-qualification-bundle/v1"
    _invalid(
        P13QualificationBundle,
        {**bundle.model_dump(), "limitations": ("SINGLE_SOURCE_NON_VINTAGE", "A")},
    )
    _invalid(P13QualificationBundle, {**bundle.model_dump(), "feature_artifact_hash": "bad"})


def test_approved_v2_preserves_expected_semantics_and_binds_new_source() -> None:
    policy = load_yaml_contract(
        ROOT / "configs/research/p13_real_sse_share_repurchase_benchmark_v2.yaml",
        EventFeatureAdmissionPolicySpec,
    )
    binding = load_yaml_contract(
        ROOT / "configs/research/p13_real_sse_benchmark_binding_v2.yaml", P13BenchmarkBinding
    )
    old = load_yaml_contract(
        ROOT / "configs/research/p13_real_sse_share_repurchase_benchmark_v1.yaml",
        EventFeatureAdmissionPolicySpec,
    ).cases[0]
    assert policy.content_hash == "a1eecec872b784c1dea5f90cbf6197a47e494a0be79eb65fa411879fa2c0b8f3"
    assert binding.benchmark_policy_hash == policy.content_hash
    case = policy.cases[0]
    assert (case.evidence_hash, case.extracted_text_hash) == (
        binding.evidence_hash,
        binding.extracted_text_hash,
    )
    assert (case.event_label, case.entity_refs, case.event_time, case.attributes) == (
        old.event_label,
        old.entity_refs,
        old.event_time,
        old.attributes,
    )
    assert [(c.page, c.char_start, c.char_end, c.cited_text_hash) for c in case.citations] == [
        (c.page, c.char_start, c.char_end, c.cited_text_hash) for c in old.citations
    ]


def _invalid(contract_type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        contract_type.model_validate(payload)


def test_benchmark_contracts_reject_ambiguous_or_noncanonical_expectations() -> None:
    case = _policy().cases[0]
    base = case.model_dump(mode="python")

    _invalid(EventFeatureBenchmarkCase, {**base, "event_time": datetime(2024, 1, 2)})
    _invalid(EventFeatureBenchmarkCase, {**base, "entity_refs": ()})
    _invalid(EventFeatureBenchmarkCase, {**base, "entity_refs": ("600000.SH", "600000.SH")})
    page_only = case.citations[0].model_copy(update={"char_start": None, "char_end": None})
    _invalid(EventFeatureBenchmarkCase, {**base, "citations": (page_only,)})
    _invalid(
        EventFeatureBenchmarkCase,
        {**base, "citations": (case.citations[0], case.citations[0])},
    )
    duplicate_attributes = (
        ProposedAttribute(name="amount", value=1),
        ProposedAttribute(name="amount", value=2),
    )
    _invalid(EventFeatureBenchmarkCase, {**base, "attributes": duplicate_attributes})
    wrong_source = case.citations[0].model_copy(update={"evidence_hash": "0" * 64})
    _invalid(EventFeatureBenchmarkCase, {**base, "citations": (wrong_source,)})

    _invalid(EventFeatureAdmissionPolicySpec, {**_policy().model_dump(), "cases": ()})
    duplicate = case.model_copy(update={"case_id": "share-repurchase-002"})
    _invalid(
        EventFeatureAdmissionPolicySpec,
        {**_policy().model_dump(), "cases": (case, duplicate)},
    )


def test_resolution_and_event_study_contracts_fail_closed() -> None:
    resolution = TradingSessionResolution(
        snapshot_hash="1" * 64,
        resolver_policy_hash="2" * 64,
        calendar_file_hash="3" * 64,
        instrument_file_hash="4" * 64,
        evidence_hash="5" * 64,
        evidence_available_at=datetime(2024, 1, 2, tzinfo=UTC),
        entity_ref="600000.SH",
        exchange="SSE",
        effective_trade_date=date(2024, 1, 3),
    )
    _invalid(
        TradingSessionResolution,
        {**resolution.model_dump(), "evidence_available_at": datetime(2024, 1, 2)},
    )
    with pytest.raises(ValueError):
        EventFeatureArtifactFile(logical_path="../escape", sha256="1" * 64, size_bytes=1)

    valid_spec = EventStudySpec(
        study_id="event-study",
        event_feature_artifact_hash="1" * 64,
        snapshot_hash="2" * 64,
        benchmark_id="000300.SH",
        code_commit_hash="1" * 40,
        runtime_fingerprint_hash="2" * 64,
        window_start=0,
        window_end=1,
        metrics=(EventStudyMetric.EVENT_COUNT, EventStudyMetric.MEAN_CAR),
    )
    _invalid(
        EventStudySpec,
        {
            **valid_spec.model_dump(),
            "metrics": (EventStudyMetric.MEAN_CAR, EventStudyMetric.EVENT_COUNT),
        },
    )
    _invalid(EventStudySpec, {**valid_spec.model_dump(), "window_start": 2})
    _invalid(
        EventStudyRow,
        {
            "entity_ref": "600000.SH",
            "event_trade_date": date(2024, 1, 3),
            "window_start_date": date(2024, 1, 2),
            "window_end_date": date(2024, 1, 4),
            "stock_return": 0.1,
            "benchmark_return": 0.05,
            "abnormal_return": 0.05,
            "cumulative_abnormal_return": 0.05,
        },
    )
    _invalid(
        EventStudyRow,
        {
            "entity_ref": "600000.SH",
            "event_trade_date": date(2024, 1, 3),
            "window_start_date": date(2024, 1, 3),
            "window_end_date": date(2024, 1, 4),
            "stock_return": 0.1,
            "benchmark_return": 0.05,
            "abnormal_return": 0.01,
            "cumulative_abnormal_return": 0.01,
        },
    )


def test_artifact_manifest_and_qualification_report_invariants() -> None:
    feature_names = (
        "admission-policy.json",
        "admission-record.json",
        "evidence.json",
        "extracted-text.json",
        "extraction-proposal.json",
        "feature.json",
        "resolver-policy.json",
        "trading-session-resolutions.json",
    )
    feature_files = tuple(
        EventFeatureArtifactFile(logical_path=name, sha256=f"{index:x}" * 64, size_bytes=1)
        for index, name in enumerate(feature_names, 1)
    )
    feature = EventFeatureArtifactManifest.create(
        feature_hash="1" * 64,
        evidence_hash="2" * 64,
        extracted_text_hash="3" * 64,
        extraction_proposal_hash="4" * 64,
        admission_record_hash="5" * 64,
        admission_policy_hash="6" * 64,
        resolver_policy_hash="7" * 64,
        resolution_hashes=("8" * 64,),
        snapshot_hash="9" * 64,
        files=feature_files,
    )
    _invalid(
        EventFeatureArtifactManifest,
        {**feature.model_dump(), "resolution_hashes": ()},
    )
    _invalid(EventFeatureArtifactManifest, {**feature.model_dump(), "files": feature_files[:-1]})
    _invalid(EventFeatureArtifactManifest, {**feature.model_dump(), "artifact_hash": "0" * 64})

    study_names = (
        "event-feature-manifest.json",
        "event-study-rows.json",
        "event-study-spec.json",
        "event-study-summary.json",
    )
    study_files = tuple(
        EventStudyArtifactFile(logical_path=name, sha256=f"{index:x}" * 64, size_bytes=1)
        for index, name in enumerate(study_names, 1)
    )
    study = EventStudyArtifactManifest.create(
        spec_hash="1" * 64,
        event_feature_artifact_hash="2" * 64,
        event_feature_hash="3" * 64,
        snapshot_hash="4" * 64,
        row_count=1,
        rows_hash="5" * 64,
        summary_hash="6" * 64,
        files=study_files,
    )
    _invalid(EventStudyArtifactManifest, {**study.model_dump(), "files": study_files[:-1]})
    _invalid(EventStudyArtifactManifest, {**study.model_dump(), "artifact_hash": "0" * 64})

    report = {
        "benchmark_policy_hash": "1" * 64,
        "benchmark_case_count": 1,
        "proposal_count": 1,
        "schema_valid_count": 1,
        "citation_accurate_count": 1,
        "admitted_count": 1,
        "pit_valid_count": 1,
        "duplicate_count": 0,
        "schema_valid_rate": 1.0,
        "citation_accuracy": 1.0,
        "admission_rate": 1.0,
        "pit_valid_rate": 1.0,
        "duplicate_rate": 0.0,
        "total_agent_tokens": 0,
        "offline_engineering_status": RunStatus.SUCCEEDED,
        "offline_engineering_verdict": ValidationVerdict.PASS,
        "data_qualified_status": RunStatus.FAILED,
        "data_qualified_verdict": ValidationVerdict.NOT_EVALUATED,
        "data_qualified_reason": ReasonCode.ADMISSION_REJECTED,
        "limitations": ("SYNTHETIC_FIXTURE",),
    }
    _invalid(P13QualificationReport, {**report, "admitted_count": 2})
    _invalid(P13QualificationReport, {**report, "admission_rate": 0.0})
    _invalid(
        P13QualificationReport,
        {
            **report,
            "offline_engineering_status": RunStatus.FAILED,
            "offline_engineering_verdict": ValidationVerdict.REJECT,
        },
    )
    _invalid(
        P13QualificationReport,
        {**report, "offline_engineering_verdict": ValidationVerdict.NOT_EVALUATED},
    )
    _invalid(P13QualificationReport, {**report, "data_qualified_reason": None})
    P13QualificationReport.model_validate(
        {
            **report,
            "data_qualified_status": RunStatus.SUCCEEDED,
            "data_qualified_verdict": ValidationVerdict.REJECT,
            "data_qualified_reason": None,
        }
    )


def test_json_rpc_schema_and_transcript_contract_invariants() -> None:
    schema = {"type": "object"}
    descriptor = JsonRpcToolDescriptor(
        method="registry.search",
        input_schema=schema,
        input_schema_hash=sha256_bytes(canonical_json_bytes(schema)),
    )
    _invalid(JsonRpcToolDescriptor, {**descriptor.model_dump(), "input_schema_hash": "1" * 64})
    with pytest.raises(ValidationError):
        JsonRpcToolSchemaManifest(tools=())
    with pytest.raises(ValidationError):
        JsonRpcToolSchemaManifest(tools=(descriptor, descriptor))
    entry = JsonRpcTranscriptEntry(
        sequence=1,
        method="registry.search",
        request_hash="2" * 64,
        response_hash="3" * 64,
        succeeded=True,
    )
    _invalid(
        JsonRpcTranscriptEntry, {**entry.model_dump(), "reason_code": ReasonCode.SCHEMA_INVALID}
    )
    transcript = JsonRpcTranscript.create(tool_schema_hash="4" * 64, entries=(entry,))
    _invalid(JsonRpcTranscript, {**transcript.model_dump(), "transcript_hash": "0" * 64})
    second = entry.model_copy(update={"sequence": 3})
    _invalid(JsonRpcTranscript, {**transcript.model_dump(), "entries": (entry, second)})
