"""Frozen Q11 predicate unit cases; synthetic contracts grant no live qualification."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from quantos.contracts.campaign_selection import CampaignSelectionReport
from quantos.contracts.hosted import HostedCampaignReport
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import (
    VALIDATION_GATE_ORDER,
    GateResult,
    GateSeverity,
    ValidationArtifactFile,
    ValidationGateId,
    ValidationReport,
)
from quantos.infrastructure.hosted_business_verification import (
    HostedVerifiedBusiness,
    verify_q11_research_predicate,
)
from quantos.infrastructure.hosted_verification import HostedQualificationError


def _validation(
    *, reject: ValidationGateId | None = None, failed: bool = False
) -> ValidationReport:
    hard = {
        ValidationGateId.G0_SCHEMA_REFERENCE,
        ValidationGateId.G1_SNAPSHOT_DATA_QUALITY,
        ValidationGateId.G2_PIT_LINEAGE,
        ValidationGateId.G9_REPRODUCIBILITY,
        ValidationGateId.G10_ARTIFACT_INTEGRITY,
    }
    evidence = ArtifactRef(
        kind="qualification-fixture",
        sha256="a" * 64,
        size_bytes=1,
        media_type="application/json",
        logical_path="fixture.json",
    )
    gates = tuple(
        GateResult(
            gate_id=gate,
            severity=GateSeverity.HARD if gate in hard else GateSeverity.SOFT,
            verdict=ValidationVerdict.REJECT if gate is reject else ValidationVerdict.PASS,
            reason_code=ReasonCode.SOFT_THRESHOLD_NOT_MET if gate is reject else None,
            reason="synthetic unit predicate fixture",
            evidence=(evidence,),
        )
        for gate in VALIDATION_GATE_ORDER
    )
    return ValidationReport.create(
        experiment_id="hosted-predicate-fixture",
        authoring_spec_hash="a" * 64,
        validation_policy_hash="b" * 64,
        research_policy_hash="c" * 64,
        runtime_fingerprint_hash="d" * 64,
        run_status=RunStatus.FAILED if failed else RunStatus.SUCCEEDED,
        verdict=ValidationVerdict.NOT_EVALUATED
        if failed
        else (ValidationVerdict.REJECT if reject is not None else ValidationVerdict.PASS),
        canonical=True,
        gates=gates,
        files=tuple(
            ValidationArtifactFile(logical_path=path, sha256="f" * 64, size_bytes=1)
            for path in (
                "authoring-spec.json",
                "research-policy.json",
                "runtime-fingerprint.json",
                "validation-policy.json",
            )
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _facts(*reports: ValidationReport) -> HostedVerifiedBusiness:
    # The predicate consumes only these report fields; full business authority is
    # independently verified before this helper is used in production.
    zero = all(report.verdict is ValidationVerdict.REJECT for report in reports)
    from quantos.contracts.campaign_selection import (
        CampaignSelectionVerdict,
        CandidateDispositionKind,
    )

    campaign = cast(
        HostedCampaignReport,
        SimpleNamespace(remaining_candidate_hashes=(), candidate_hashes=("1" * 64, "2" * 64)),
    )
    selection = cast(
        CampaignSelectionReport,
        SimpleNamespace(
            run_status=RunStatus.FAILED if zero else RunStatus.SUCCEEDED,
            verdict=CampaignSelectionVerdict.NOT_EVALUATED
            if zero
            else CampaignSelectionVerdict.SELECTED,
            reason_code=ReasonCode.SOURCE_INCOMPLETE if zero else None,
            selected_candidate_hash=None if zero else "1" * 64,
            candidate_dispositions=tuple(
                SimpleNamespace(kind=CandidateDispositionKind.NONPASS_VALIDATION) for _ in range(2)
            ),
        ),
    )
    return HostedVerifiedBusiness(campaign, selection, reports, ("3" * 64, "4" * 64), ())


def test_q11_all_soft_reject_and_mixed_pass_results_follow_frozen_p14c() -> None:
    rejected = _validation(reject=ValidationGateId.G5_OUT_OF_SAMPLE)
    passed = _validation()
    assert (
        verify_q11_research_predicate(_facts(rejected, rejected))
        == "COMPLETE_ADMISSIBLE_SOFT_REJECT"
    )
    assert (
        verify_q11_research_predicate(_facts(passed, rejected))
        == "COMPLETE_MIXED_VALIDATION_RESULTS"
    )
    assert verify_q11_research_predicate(_facts(passed, passed)) == "COMPLETE_VALIDATION_PASS"


@pytest.mark.parametrize(
    "gate",
    [gate for gate in VALIDATION_GATE_ORDER if gate is not ValidationGateId.G5_OUT_OF_SAMPLE],
)
def test_q11_other_gate_rejects_never_borrow_g5_exception(gate: ValidationGateId) -> None:
    with pytest.raises(HostedQualificationError, match="outside frozen G5"):
        verify_q11_research_predicate(_facts(_validation(reject=gate), _validation()))


def test_q11_execution_failure_and_wrong_gate_severity_remain_rejected() -> None:
    with pytest.raises(HostedQualificationError, match="execution"):
        verify_q11_research_predicate(_facts(_validation(failed=True), _validation()))
    passed = _validation()
    gates = list(passed.gates)
    gates[0] = gates[0].model_copy(update={"severity": GateSeverity.SOFT})
    changed = passed.model_copy(update={"gates": tuple(gates)})
    with pytest.raises(HostedQualificationError, match="severity"):
        verify_q11_research_predicate(_facts(changed, passed))
