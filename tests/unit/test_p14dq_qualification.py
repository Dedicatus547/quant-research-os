from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from quantos.artifacts.store import sha256_file
from quantos.contracts.autonomous import (
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousSelectionFinalizationProfile,
)
from quantos.contracts.base import sha256_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.campaign_selection import (
    CampaignSelectionReport,
    CampaignSelectionVerdict,
    CandidateDispositionKind,
)
from quantos.contracts.p14dq_qualification import (
    P14DQ_ADMISSIBLE_SOFT_REJECTION_GATES,
    P14DQ_CANDIDATE_HASHES,
    P14DQ_CANDIDATE_MANIFEST_HASH,
    P14DQ_FAMILY_HASH,
    P14DQ_FROZEN_VALIDATION_GATE_ORDER,
    P14DQ_FROZEN_VALIDATION_GATE_SEVERITY,
    P14DQ_REQUIRED_PASSING_GATES,
    P14DQ_TEMPLATE_HASH,
    P14dqCampaignEvidence,
    P14dqCandidateEvaluation,
    P14dqValidationGateEvidence,
)
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import (
    VALIDATION_GATE_ORDER,
    GateSeverity,
    ValidationGateId,
)
from quantos.validation import service as validation_service

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "p14dq_qualification_test_module", ROOT / "scripts/p14dq_qualification.py"
)
assert SPEC is not None and SPEC.loader is not None
sys.path.insert(0, str(ROOT / "scripts"))
try:
    runner = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = runner
    SPEC.loader.exec_module(runner)
finally:
    sys.path.remove(str(ROOT / "scripts"))


def test_frozen_family_is_reenumerated_and_profile_cannot_grant_sealed_authority() -> None:
    template, family, manifest = runner._p14dq_family_manifest()
    assert template.content_hash == P14DQ_TEMPLATE_HASH
    assert family.content_hash == P14DQ_FAMILY_HASH
    assert manifest.content_hash == P14DQ_CANDIDATE_MANIFEST_HASH
    assert tuple(item.content_hash for item in manifest.candidates) == P14DQ_CANDIDATE_HASHES

    forged = P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.model_dump(mode="python")
    forged["selected_action"] = "FREEZE_SELECTION"
    with pytest.raises(ValidationError, match="not frozen"):
        AutonomousSelectionFinalizationProfile.model_validate(forged)


def test_v3_contract_bytes_are_pinned_and_activation_binds_the_approval_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner._frozen_contract_hash(ROOT) == runner.FROZEN_CONTRACT_SHA256
    changed = tmp_path / runner.CONTRACT_PATH
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"changed contract")
    with pytest.raises(runner.QualificationError, match="v3 draft bytes"):
        runner._frozen_contract_hash(tmp_path)

    assert runner.V3_CONTRACT_APPROVED is True
    assert sha256_file(ROOT / runner.APPROVAL_RECORD_PATH) == (runner.FROZEN_APPROVAL_RECORD_SHA256)
    runner._require_v3_contract_approval()

    record = (ROOT / runner.APPROVAL_RECORD_PATH).read_bytes()
    forged = tmp_path / "p14-dq-v3-contract-approval.md"
    forged.write_bytes(record)
    monkeypatch.setattr(runner, "APPROVAL_RECORD_PATH", forged)
    runner._require_v3_contract_approval()

    forged.write_bytes(record.replace(b"563b1c44", b"00000000", 1))
    with pytest.raises(runner.QualificationError, match="does not bind"):
        runner._require_v3_contract_approval()

    forged.write_bytes(record)
    monkeypatch.setattr(runner, "FROZEN_APPROVAL_RECORD_SHA256", sha256_bytes(record))
    runner._require_v3_contract_approval()
    for old_value, new_value in (
        (runner.FROZEN_CONTRACT_SHA256, "0" * 64),
        (runner.APPROVED_IMPLEMENTATION_COMMIT, "f" * 40),
        ("review_verdict:\nAPPROVE", "review_verdict:\nREJECT"),
        ("approved_implementation_commit:", "unapproved_implementation_commit:"),
    ):
        assert old_value in record.decode("utf-8")
        forged.write_bytes(record.replace(old_value.encode("utf-8"), new_value.encode("utf-8"), 1))
        with pytest.raises(runner.QualificationError):
            runner._require_v3_contract_approval()

    monkeypatch.setattr(runner, "V3_CONTRACT_APPROVED", False)
    with pytest.raises(runner.QualificationError, match="independent contract approval"):
        runner._require_v3_contract_approval()


def _gate_evidence(
    rejections: dict[ValidationGateId, ReasonCode] | None = None,
    *,
    not_evaluated: tuple[ValidationGateId, ...] = (),
) -> tuple[P14dqValidationGateEvidence, ...]:
    rejections = rejections or {}
    gates: list[P14dqValidationGateEvidence] = []
    for gate_id in P14DQ_FROZEN_VALIDATION_GATE_ORDER:
        severity = P14DQ_FROZEN_VALIDATION_GATE_SEVERITY[gate_id]
        if gate_id in not_evaluated:
            gates.append(
                P14dqValidationGateEvidence(
                    gate_id=gate_id, severity=severity, verdict=ValidationVerdict.NOT_EVALUATED
                )
            )
        elif gate_id in rejections:
            gates.append(
                P14dqValidationGateEvidence(
                    gate_id=gate_id,
                    severity=severity,
                    verdict=ValidationVerdict.REJECT,
                    reason_code=rejections[gate_id],
                )
            )
        else:
            gates.append(
                P14dqValidationGateEvidence(
                    gate_id=gate_id, severity=severity, verdict=ValidationVerdict.PASS
                )
            )
    return tuple(gates)


def _evaluation(
    index: int,
    gates: tuple[P14dqValidationGateEvidence, ...],
    *,
    outcome: TrialOutcome = TrialOutcome.SOFT_REJECT,
    updates: dict[str, object] | None = None,
) -> P14dqCandidateEvaluation:
    payload: dict[str, object] = {
        "candidate_hash": P14DQ_CANDIDATE_HASHES[index],
        "trial_event_hash": str(index + 1) * 64,
        "trial_outcome": outcome,
        "research_result_hash": str(index + 3) * 64,
        "export_audit_hash": str(index + 5) * 64,
        "validation_report_hash": str(index + 7) * 64,
        "validation_verdict": ValidationVerdict.REJECT,
        "validation_gates": gates,
    }
    payload.update(updates or {})
    return P14dqCandidateEvaluation.model_validate(payload)


def _rejected_evaluations() -> tuple[P14dqCandidateEvaluation, ...]:
    gates = _gate_evidence({ValidationGateId.G5_OUT_OF_SAMPLE: ReasonCode.SOFT_THRESHOLD_NOT_MET})
    return tuple(_evaluation(index, gates) for index in range(2))


def _zero_eligible_report(
    evaluations: tuple[P14dqCandidateEvaluation, ...],
) -> CampaignSelectionReport:
    dispositions = tuple(
        SimpleNamespace(
            candidate_hash=item.candidate_hash,
            kind=CandidateDispositionKind.NONPASS_VALIDATION,
            trial_event_hashes=(item.trial_event_hash,),
        )
        for item in evaluations
    )
    return cast(
        CampaignSelectionReport,
        SimpleNamespace(
            candidate_dispositions=dispositions,
            run_status=RunStatus.FAILED,
            verdict=CampaignSelectionVerdict.NOT_EVALUATED,
            reason_code=ReasonCode.SOURCE_INCOMPLETE,
            selected_candidate_hash=None,
            scores=(),
        ),
    )


def _zero_eligible_payload(
    evaluations: tuple[P14dqCandidateEvaluation, ...],
) -> dict[str, object]:
    return {
        "campaign_hash": "d" * 64,
        "family_hash": P14DQ_FAMILY_HASH,
        "budget_hash": "e" * 64,
        "candidate_manifest_hash": P14DQ_CANDIDATE_MANIFEST_HASH,
        "candidate_hashes": P14DQ_CANDIDATE_HASHES,
        "context_pack_hashes": ("1" * 64, "2" * 64),
        "agent_request_hashes": ("3" * 64, "4" * 64),
        "agent_proposal_hashes": ("5" * 64, "6" * 64),
        "execution_request_hashes": ("7" * 64, "8" * 64),
        "execution_identities": ("9" * 64, "a" * 64),
        "evaluations": evaluations,
        "selection_plan_hash": "b" * 64,
        "selection_calendar_hash": "c" * 64,
        "selection_calendar_session_count": 726,
        "selection_calendar_first_date": date(2023, 1, 3),
        "selection_calendar_last_date": date(2025, 12, 30),
        "selection_report_hash": "d" * 64,
        "selection_status": RunStatus.FAILED,
        "selection_verdict": "NOT_EVALUATED",
        "selection_reason_code": ReasonCode.SOURCE_INCOMPLETE,
        "eligible_candidate_count": 0,
        "selection_performed": False,
        "selected_candidate_hash": None,
        "campaign_trial_hashes": ("1" * 64, "2" * 64),
        "campaign_event_hashes": ("3" * 64, "4" * 64),
        "final_campaign_event_hash": "4" * 64,
        "final_ledger_snapshot_hash": "5" * 64,
        "ledger_principal_hash": "6" * 64,
        "autonomous_loop_report_hash": "7" * 64,
    }


def test_frozen_gate_contract_matches_the_live_validation_service() -> None:
    assert P14DQ_FROZEN_VALIDATION_GATE_ORDER == VALIDATION_GATE_ORDER
    assert (
        dict(P14DQ_FROZEN_VALIDATION_GATE_SEVERITY)  # pyright: ignore[reportPrivateUsage]
        == validation_service._GATE_SEVERITY
    )
    admissible = set(P14DQ_ADMISSIBLE_SOFT_REJECTION_GATES)
    assert admissible == {
        gate_id
        for gate_id in VALIDATION_GATE_ORDER
        if validation_service._GATE_SEVERITY[gate_id] is GateSeverity.SOFT  # pyright: ignore[reportPrivateUsage]
        and gate_id is not ValidationGateId.G4_REFERENCE_BACKTEST
    }
    assert set(P14DQ_REQUIRED_PASSING_GATES) | admissible == set(VALIDATION_GATE_ORDER)
    assert not set(P14DQ_REQUIRED_PASSING_GATES) & admissible
    assert {
        gate_id
        for gate_id in validation_service._METRIC_GATE.values()  # pyright: ignore[reportPrivateUsage]
    } == admissible


@pytest.mark.parametrize(
    "gate_id",
    (
        ValidationGateId.G3_FACTOR_RESEARCH,
        ValidationGateId.G5_OUT_OF_SAMPLE,
        ValidationGateId.G6_COST_STRESS,
        ValidationGateId.G7_PARAMETER_STABILITY,
        ValidationGateId.G8_SUBPERIOD_STABILITY,
    ),
)
def test_genuine_soft_threshold_rejection_is_admissible(
    gate_id: ValidationGateId,
) -> None:
    gates = _gate_evidence({gate_id: ReasonCode.SOFT_THRESHOLD_NOT_MET})
    evaluations = tuple(_evaluation(index, gates) for index in range(2))
    assert all(item.admissible_research_rejection() for item in evaluations)

    report = _zero_eligible_report(evaluations)
    assert runner._verify_natural_selection_outcome(report, evaluations) == (0, False)
    evidence = P14dqCampaignEvidence.model_validate(_zero_eligible_payload(evaluations))
    assert evidence.eligible_candidate_count == 0
    assert evidence.selection_performed is False


@pytest.mark.parametrize(
    "hard_gate",
    (
        ValidationGateId.G0_SCHEMA_REFERENCE,
        ValidationGateId.G1_SNAPSHOT_DATA_QUALITY,
        ValidationGateId.G2_PIT_LINEAGE,
        ValidationGateId.G9_REPRODUCIBILITY,
        ValidationGateId.G10_ARTIFACT_INTEGRITY,
    ),
)
def test_hard_gate_rejection_fails_closed(hard_gate: ValidationGateId) -> None:
    hard = _gate_evidence(
        {
            hard_gate: ReasonCode.REPRODUCIBILITY_MISMATCH,
            ValidationGateId.G5_OUT_OF_SAMPLE: ReasonCode.SOFT_THRESHOLD_NOT_MET,
        }
    )
    evaluations = (
        _evaluation(0, hard, outcome=TrialOutcome.HARD_REJECT),
        _evaluation(1, hard, outcome=TrialOutcome.HARD_REJECT),
    )
    assert not all(item.admissible_research_rejection() for item in evaluations)
    with pytest.raises(runner.QualificationError, match="zero-eligible"):
        runner._verify_natural_selection_outcome(_zero_eligible_report(evaluations), evaluations)
    with pytest.raises(ValidationError, match="zero-eligible"):
        P14dqCampaignEvidence.model_validate(_zero_eligible_payload(evaluations))
    # A hard-gate rejection that claims the SOFT aggregate outcome is refused outright.
    with pytest.raises(ValidationError, match="not a Validation disposition"):
        _evaluation(0, hard, outcome=TrialOutcome.SOFT_REJECT)


def test_reference_backtest_gate_rejection_fails_closed() -> None:
    gates = _gate_evidence(
        {ValidationGateId.G4_REFERENCE_BACKTEST: ReasonCode.SOFT_THRESHOLD_NOT_MET}
    )
    assert not _evaluation(0, gates).admissible_research_rejection()


@pytest.mark.parametrize(
    ("gate_id", "reason_code"),
    (
        (ValidationGateId.G6_COST_STRESS, ReasonCode.ARTIFACT_CORRUPTED),
        (ValidationGateId.G3_FACTOR_RESEARCH, ReasonCode.SOURCE_INCOMPLETE),
        (ValidationGateId.G5_OUT_OF_SAMPLE, ReasonCode.SCHEMA_INVALID),
        (ValidationGateId.G6_COST_STRESS, ReasonCode.OOS_POLICY_VIOLATION),
        (ValidationGateId.G7_PARAMETER_STABILITY, ReasonCode.LOOK_AHEAD),
        (ValidationGateId.G8_SUBPERIOD_STABILITY, ReasonCode.QLIB_EXECUTION_FAILED),
        (ValidationGateId.G5_OUT_OF_SAMPLE, ReasonCode.REPRODUCIBILITY_MISMATCH),
        (ValidationGateId.G3_FACTOR_RESEARCH, ReasonCode.UNKNOWN_AVAILABILITY),
    ),
)
def test_soft_gate_non_threshold_rejection_fails_closed(
    gate_id: ValidationGateId, reason_code: ReasonCode
) -> None:
    gates = _gate_evidence({gate_id: reason_code})
    assert not _evaluation(0, gates).admissible_research_rejection()
    evaluations = tuple(_evaluation(index, gates) for index in range(2))
    with pytest.raises(runner.QualificationError, match="zero-eligible"):
        runner._verify_natural_selection_outcome(_zero_eligible_report(evaluations), evaluations)
    with pytest.raises(ValidationError, match="zero-eligible"):
        P14dqCampaignEvidence.model_validate(_zero_eligible_payload(evaluations))


def test_not_evaluated_gate_and_mixed_rejection_fail_closed() -> None:
    not_evaluated = _gate_evidence(
        {ValidationGateId.G5_OUT_OF_SAMPLE: ReasonCode.SOFT_THRESHOLD_NOT_MET},
        not_evaluated=(ValidationGateId.G6_COST_STRESS,),
    )
    assert not _evaluation(0, not_evaluated).admissible_research_rejection()

    mixed = _gate_evidence(
        {
            ValidationGateId.G5_OUT_OF_SAMPLE: ReasonCode.SOFT_THRESHOLD_NOT_MET,
            ValidationGateId.G6_COST_STRESS: ReasonCode.ARTIFACT_CORRUPTED,
        }
    )
    assert not _evaluation(0, mixed).admissible_research_rejection()


def test_incomplete_duplicate_or_unexpected_gate_set_fails_closed() -> None:
    genuine = _gate_evidence({ValidationGateId.G5_OUT_OF_SAMPLE: ReasonCode.SOFT_THRESHOLD_NOT_MET})
    for broken in (
        genuine[:-1],
        genuine[1:],
        (genuine[0], *genuine),
        tuple(reversed(genuine)),
    ):
        with pytest.raises(ValidationError, match="complete frozen Validation gate set"):
            _evaluation(0, broken)


def test_gate_severity_cannot_be_spoofed_and_aggregate_outcome_is_derived() -> None:
    with pytest.raises(ValidationError, match="severity differs from the frozen contract"):
        P14dqValidationGateEvidence(
            gate_id=ValidationGateId.G2_PIT_LINEAGE,
            severity=GateSeverity.SOFT,
            verdict=ValidationVerdict.PASS,
        )
    with pytest.raises(ValidationError, match="severity differs from the frozen contract"):
        P14dqValidationGateEvidence(
            gate_id=ValidationGateId.G5_OUT_OF_SAMPLE,
            severity=GateSeverity.HARD,
            verdict=ValidationVerdict.REJECT,
            reason_code=ReasonCode.SOFT_THRESHOLD_NOT_MET,
        )
    with pytest.raises(ValidationError, match="cannot carry a reason code"):
        P14dqValidationGateEvidence(
            gate_id=ValidationGateId.G5_OUT_OF_SAMPLE,
            severity=GateSeverity.SOFT,
            verdict=ValidationVerdict.PASS,
            reason_code=ReasonCode.SOFT_THRESHOLD_NOT_MET,
        )
    with pytest.raises(ValidationError, match="requires a reason code"):
        P14dqValidationGateEvidence(
            gate_id=ValidationGateId.G5_OUT_OF_SAMPLE,
            severity=GateSeverity.SOFT,
            verdict=ValidationVerdict.REJECT,
        )

    genuine = _gate_evidence({ValidationGateId.G5_OUT_OF_SAMPLE: ReasonCode.SOFT_THRESHOLD_NOT_MET})
    with pytest.raises(ValidationError, match="not a Validation disposition"):
        _evaluation(0, genuine, outcome=TrialOutcome.HARD_REJECT)
    with pytest.raises(ValidationError, match="not a Validation disposition"):
        _evaluation(0, genuine, outcome=TrialOutcome.EXECUTION_FAILED)
    with pytest.raises(ValidationError, match="not a Validation disposition"):
        _evaluation(0, genuine, outcome=TrialOutcome.PIT_REJECT)

    all_pass = _gate_evidence()
    with pytest.raises(ValidationError, match="Validation verdict differs"):
        _evaluation(0, all_pass, updates={"validation_verdict": ValidationVerdict.REJECT})
    with pytest.raises(ValidationError, match="not a Validation disposition"):
        _evaluation(
            0,
            all_pass,
            outcome=TrialOutcome.SOFT_REJECT,
            updates={"validation_verdict": ValidationVerdict.PASS},
        )


def test_missing_research_result_or_sidecar_hash_fails_closed() -> None:
    genuine = _gate_evidence({ValidationGateId.G5_OUT_OF_SAMPLE: ReasonCode.SOFT_THRESHOLD_NOT_MET})
    for field in ("research_result_hash", "export_audit_hash", "validation_report_hash"):
        with pytest.raises(ValidationError):
            _evaluation(0, genuine, updates={field: None})
        with pytest.raises(ValidationError):
            _evaluation(0, genuine, updates={field: "not-a-hash"})
    with pytest.raises(ValidationError):
        _evaluation(
            0,
            genuine,
            updates={"validation_verdict": ValidationVerdict.NOT_EVALUATED},
        )


def test_zero_eligible_is_a_distinct_verified_natural_outcome() -> None:
    evaluations = _rejected_evaluations()
    report = _zero_eligible_report(evaluations)
    assert runner._verify_natural_selection_outcome(report, evaluations) == (0, False)
    for changed in (
        {"verdict": CampaignSelectionVerdict.NO_SELECTION},
        {"reason_code": ReasonCode.ARTIFACT_CORRUPTED},
        {"scores": ("fabricated",)},
        {"candidate_dispositions": report.candidate_dispositions[:1]},
    ):
        with pytest.raises(runner.QualificationError):
            runner._verify_natural_selection_outcome(
                cast(CampaignSelectionReport, SimpleNamespace(**{**vars(report), **changed})),
                evaluations,
            )

    payload = _zero_eligible_payload(evaluations)
    assert P14dqCampaignEvidence.model_validate(payload).eligible_candidate_count == 0
    for changed in (
        {"selection_verdict": "NO_SELECTION"},
        {"selection_performed": True},
        {"eligible_candidate_count": 1},
        {"selection_reason_code": ReasonCode.ARTIFACT_CORRUPTED},
        {
            "evaluations": (
                evaluations[0],
                evaluations[1].model_copy(
                    update={"research_result_hash": evaluations[0].research_result_hash}
                ),
            )
        },
    ):
        with pytest.raises(ValidationError):
            P14dqCampaignEvidence.model_validate({**payload, **changed})


def test_explicit_paths_and_negative_reason_mismatches_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(runner.InputGateError) as wrong_path:
        runner._require_explicit_path(
            tmp_path / "latest", runner.ROOT / runner.SNAPSHOT_RELATIVE_PATH, "snapshot"
        )
    assert wrong_path.value.reason_code is ReasonCode.SNAPSHOT_HASH_MISMATCH

    def wrong_reason() -> None:
        raise runner.InputGateError(ReasonCode.CAPABILITY_DENIED, "injected wrong reason")

    with pytest.raises(runner.InputGateError) as mismatch:
        runner._assert_all_rejected((wrong_reason,), ReasonCode.ARTIFACT_CORRUPTED)
    assert mismatch.value.reason_code is ReasonCode.REPRODUCIBILITY_MISMATCH


def test_existing_snapshot_and_view_verifiers_reject_file_set_faults() -> None:
    for action in (runner._snapshot_file_tamper_negative, runner._view_file_set_negative):
        with pytest.raises(runner.InputGateError, match="all 3 injected variants") as rejected:
            action()
        assert rejected.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_frozen_policy_bytes_are_checked_by_bundle_verifier(tmp_path: Path) -> None:
    expected = runner._load_policies(ROOT)
    policy_root = tmp_path / "frozen" / "policies"
    policy_root.mkdir(parents=True)
    for name, relative in runner.POLICY_PATHS.items():
        (policy_root / f"{name}.yaml").write_bytes((ROOT / relative).read_bytes())
    assert runner._load_frozen_policy_bundle(tmp_path) == expected

    policy_path = policy_root / "validation_policy.yaml"
    policy_path.write_bytes(policy_path.read_bytes() + b"\n")
    with pytest.raises(runner.QualificationError, match="policy bytes differ"):
        runner._load_frozen_policy_bundle(tmp_path)


def test_failed_attempt_retains_partial_evidence_without_a_pass_report(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    partial = staging / "root-A" / "natural" / "partial.json"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b'{"trial":"rejected"}')
    (staging / "qualification-report.json").write_bytes(b'{"status":"PASS"}')
    output = tmp_path / "output"

    attempt_path = runner._preserve_failed_attempt(
        output,
        staging,
        runner.InputGateError(ReasonCode.QLIB_EXECUTION_FAILED, "injected failure"),
    )
    report = runner._verify_p14dq_attempt(attempt_path)
    assert report.status is RunStatus.FAILED
    assert report.verdict is ValidationVerdict.NOT_EVALUATED
    assert report.reason_code is ReasonCode.QLIB_EXECUTION_FAILED
    saved_partial = attempt_path / "root-A" / "natural" / "partial.json"
    assert saved_partial.read_bytes() == partial.read_bytes()
    assert not (attempt_path / "qualification-report.json").exists()
    assert (
        runner._preserve_failed_attempt(
            output,
            staging,
            runner.InputGateError(ReasonCode.QLIB_EXECUTION_FAILED, "same failure"),
        )
        == attempt_path
    )

    (attempt_path / "unexpected.json").write_bytes(b"{}")
    with pytest.raises(runner.QualificationError, match="exact-file"):
        runner._verify_p14dq_attempt(attempt_path)
