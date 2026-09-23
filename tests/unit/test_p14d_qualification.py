from __future__ import annotations

import pytest
from pydantic import ValidationError

from quantos.contracts.autonomous import AutonomousLoopState
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.p14d_qualification import (
    P14D_CANONICAL_CASES,
    P14D_LIMITATIONS,
    P14D_NEGATIVE_CASES,
    P14D_RESTART_CASES,
    P14dCaseEvidence,
    P14dNamedHash,
    P14dNegativeCaseEvidence,
    P14dQualificationFile,
    P14dQualificationReport,
    P14dReplayCaseEvidence,
    P14dRestartCaseEvidence,
    P14dRootEvidence,
    p14d_principal_hash_summary,
    p14d_replay_binding_hash,
)
from quantos.contracts.status import ReasonCode

HASH = "a" * 64


def _case(case_id: str) -> P14dCaseEvidence:
    selected = case_id == "SELECTED"
    failed = case_id == "FAILED_NOT_EVALUATED"
    return P14dCaseEvidence.create(
        case_id=case_id,
        fixture_hash=HASH,
        campaign_hash=HASH,
        family_hash=HASH,
        budget_hash=HASH,
        candidate_manifest_hash=HASH,
        initial_context_pack_hash=HASH,
        agent_request_hashes=(HASH, "b" * 64),
        agent_proposal_hashes=("c" * 64, "d" * 64),
        execution_request_hashes=(HASH,),
        execution_identities=(HASH,),
        research_result_hashes=(HASH,),
        validation_report_hashes=(HASH,),
        campaign_trial_hashes=(HASH, "e" * 64),
        campaign_event_hashes=(HASH, "b" * 64),
        final_campaign_event_hash="b" * 64,
        final_ledger_snapshot_hash=HASH,
        ledger_principal_hash=HASH,
        selection_report_hash=HASH,
        selection_frozen_event_hash="f" * 64 if selected else None,
        autonomous_loop_report_hash=HASH,
        loop_state=(
            AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION
            if selected
            else AutonomousLoopState.SELECTION_COMPLETE
        ),
        trial_outcomes=(
            (TrialOutcome.PIT_REJECT, TrialOutcome.SCHEMA_INVALID)
            if failed
            else (TrialOutcome.PASS, TrialOutcome.SCHEMA_INVALID)
        ),
    )


def _replay() -> P14dReplayCaseEvidence:
    return P14dReplayCaseEvidence.create(
        request_hash=HASH,
        response_hash="b" * 64,
        proposal_hash="c" * 64,
        candidate_hash="d" * 64,
        execution_identity="e" * 64,
        execution_receipt_hash="f" * 64,
        qlib_runs_before_replay=1,
        qlib_runs_after_replay=1,
    )


def _root(root_id: str) -> P14dRootEvidence:
    return P14dRootEvidence.create(
        root_id=root_id,
        fixture_set_hash=HASH,
        qlib_binding_hash="b" * 64,
        autonomous_campaign_policy_hash="c" * 64,
        autonomous_agent_run_policy_hash="d" * 64,
        autonomous_compute_accounting_hash="e" * 64,
        autonomous_execution_bindings_hash="f" * 64,
        p14c_selection_plan_hash="1" * 64,
        cases=tuple(_case(case_id) for case_id in P14D_CANONICAL_CASES),
        negative_case_ids=P14D_NEGATIVE_CASES,
        negative_cases=tuple(
            P14dNegativeCaseEvidence(
                case_id=case_id,
                input_hash=HASH,
                outcome_hash=HASH,
                reason_code=ReasonCode.ARTIFACT_CORRUPTED,
            )
            for case_id in P14D_NEGATIVE_CASES
        ),
        restart_case_ids=P14D_RESTART_CASES,
        restart_cases=tuple(
            P14dRestartCaseEvidence(
                case_id=case_id,
                input_hash=HASH,
                pre_restart_evidence_hash=HASH,
                post_restart_evidence_hash=HASH,
            )
            for case_id in P14D_RESTART_CASES
        ),
        replay_case=_replay(),
    )


def _policy_hashes() -> tuple[P14dNamedHash, ...]:
    return (
        P14dNamedHash(name="autonomous_agent_run_policy", sha256="d" * 64),
        P14dNamedHash(name="autonomous_campaign_policy", sha256="c" * 64),
        P14dNamedHash(name="autonomous_compute_accounting", sha256="e" * 64),
        P14dNamedHash(name="autonomous_execution_bindings", sha256="f" * 64),
        P14dNamedHash(name="p14d_qualification_contract", sha256=HASH),
    )


def _report_files() -> tuple[P14dQualificationFile, ...]:
    return (
        P14dQualificationFile(logical_path="code-provenance.json", sha256=HASH, size_bytes=1),
        P14dQualificationFile(
            logical_path="frozen/p14d-qualification-contract.md", sha256=HASH, size_bytes=1
        ),
        P14dQualificationFile(logical_path="frozen/uv.lock", sha256=HASH, size_bytes=1),
        P14dQualificationFile(logical_path="runtime-fingerprint.json", sha256=HASH, size_bytes=1),
    )


def test_p14d_case_root_and_report_contracts_round_trip() -> None:
    left = _root("root-A")
    right = _root("root-B")
    assert left.cases == right.cases
    report = P14dQualificationReport.create(
        implementation_commit_hash="1" * 40,
        code_provenance_hash=HASH,
        lockfile_hash=HASH,
        runtime_fingerprint_hash=HASH,
        qualification_contract_hash=HASH,
        qlib_binding_hash="b" * 64,
        fixture_set_hash=HASH,
        policy_hashes=_policy_hashes(),
        roots=(left, right),
        principal_hash_summary=p14d_principal_hash_summary((left, right)),
        negative_case_count=len(P14D_NEGATIVE_CASES) * 2,
        restart_case_count=len(P14D_RESTART_CASES) * 2,
        limitations=P14D_LIMITATIONS,
        files=_report_files(),
    )
    assert report.qualification_hash == report.content_hash
    assert report.principal_hashes_byte_exact is True
    assert report.policy_hashes[0].name == "autonomous_agent_run_policy"


def test_p14d_case_summary_and_sequence_validators() -> None:
    case = _case("SELECTED")
    payload = case.model_dump(mode="python")
    payload["case_summary_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="summary hash"):
        P14dCaseEvidence.model_validate(payload)
    payload = case.model_dump(mode="python")
    payload["campaign_event_hashes"] = ("b" * 64, HASH)
    payload["final_campaign_event_hash"] = "b" * 64
    with pytest.raises(ValidationError, match="final campaign event"):
        P14dCaseEvidence.model_validate(payload)


def test_p14d_root_and_replay_integrity_validators() -> None:
    root = _root("root-A")
    with pytest.raises(ValidationError, match="principal hash summary"):
        P14dRootEvidence.model_validate(
            {**root.model_dump(mode="python"), "fixture_set_hash": "0" * 64}
        )
    expected = p14d_replay_binding_hash(
        request_hash=HASH,
        response_hash="b" * 64,
        proposal_hash="c" * 64,
        candidate_hash="d" * 64,
        execution_identity="e" * 64,
    )
    assert root.replay_case.prior_exchange_hash == expected
    with pytest.raises(ValidationError, match="another Qlib execution"):
        P14dReplayCaseEvidence.model_validate(
            {**root.replay_case.model_dump(mode="python"), "qlib_runs_after_replay": 2}
        )


def test_p14d_file_and_report_limits_fail_closed() -> None:
    with pytest.raises(ValidationError):
        P14dQualificationFile(logical_path="../escape", sha256=HASH, size_bytes=1)
    left = _root("root-A")
    right = _root("root-B")
    with pytest.raises(ValidationError, match="qualification files"):
        P14dQualificationReport.create(
            implementation_commit_hash="1" * 40,
            code_provenance_hash=HASH,
            lockfile_hash=HASH,
            runtime_fingerprint_hash=HASH,
            qualification_contract_hash=HASH,
            qlib_binding_hash="b" * 64,
            fixture_set_hash=HASH,
            policy_hashes=_policy_hashes(),
            roots=(left, right),
            principal_hash_summary=p14d_principal_hash_summary((left, right)),
            negative_case_count=len(P14D_NEGATIVE_CASES) * 2,
            restart_case_count=len(P14D_RESTART_CASES) * 2,
            limitations=P14D_LIMITATIONS,
            files=tuple(reversed(_report_files())),
        )
    with pytest.raises(ValidationError, match="limitations"):
        P14dQualificationReport.create(
            implementation_commit_hash="1" * 40,
            code_provenance_hash=HASH,
            lockfile_hash=HASH,
            runtime_fingerprint_hash=HASH,
            qualification_contract_hash=HASH,
            qlib_binding_hash="b" * 64,
            fixture_set_hash=HASH,
            policy_hashes=_policy_hashes(),
            roots=(left, right),
            principal_hash_summary=p14d_principal_hash_summary((left, right)),
            negative_case_count=len(P14D_NEGATIVE_CASES) * 2,
            restart_case_count=len(P14D_RESTART_CASES) * 2,
            limitations=tuple(reversed(P14D_LIMITATIONS)),
            files=_report_files(),
        )
