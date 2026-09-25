from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from quantos.contracts.autonomous import (
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousSelectionFinalizationProfile,
)
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.campaign_selection import (
    CampaignSelectionReport,
    CampaignSelectionVerdict,
    CandidateDispositionKind,
)
from quantos.contracts.p14dq_qualification import (
    P14DQ_CANDIDATE_HASHES,
    P14DQ_CANDIDATE_MANIFEST_HASH,
    P14DQ_FAMILY_HASH,
    P14DQ_TEMPLATE_HASH,
    P14dqCampaignEvidence,
    P14dqCandidateEvaluation,
)
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict

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


def test_v3_draft_bytes_are_pinned_but_qualification_is_unapproved(tmp_path: Path) -> None:
    assert runner._frozen_contract_hash(ROOT) == runner.FROZEN_CONTRACT_SHA256
    changed = tmp_path / runner.CONTRACT_PATH
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"changed contract")
    with pytest.raises(runner.QualificationError, match="v3 draft bytes"):
        runner._frozen_contract_hash(tmp_path)
    with pytest.raises(runner.QualificationError, match="independent contract approval"):
        runner._require_v3_contract_approval()


def _rejected_evaluations() -> tuple[P14dqCandidateEvaluation, ...]:
    return tuple(
        P14dqCandidateEvaluation(
            candidate_hash=candidate_hash,
            trial_event_hash=str(index + 1) * 64,
            trial_outcome=TrialOutcome.SOFT_REJECT,
            research_result_hash=str(index + 3) * 64,
            export_audit_hash=str(index + 5) * 64,
            validation_report_hash=str(index + 7) * 64,
            validation_verdict=ValidationVerdict.REJECT,
        )
        for index, candidate_hash in enumerate(P14DQ_CANDIDATE_HASHES)
    )


def test_zero_eligible_is_a_distinct_verified_natural_outcome() -> None:
    evaluations = _rejected_evaluations()
    dispositions = tuple(
        SimpleNamespace(
            candidate_hash=item.candidate_hash,
            kind=CandidateDispositionKind.NONPASS_VALIDATION,
            trial_event_hashes=(item.trial_event_hash,),
        )
        for item in evaluations
    )
    report = cast(
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
    assert runner._verify_natural_selection_outcome(report, evaluations) == (0, False)
    for changed in (
        {"verdict": CampaignSelectionVerdict.NO_SELECTION},
        {"reason_code": ReasonCode.ARTIFACT_CORRUPTED},
        {"scores": ("fabricated",)},
        {"candidate_dispositions": dispositions[:1]},
    ):
        with pytest.raises(runner.QualificationError):
            runner._verify_natural_selection_outcome(
                cast(CampaignSelectionReport, SimpleNamespace(**{**vars(report), **changed})),
                evaluations,
            )

    payload = {
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
