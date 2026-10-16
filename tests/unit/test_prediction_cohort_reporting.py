"""Synthetic cross-origin contracts and read-only reports; no scientific engine calls."""

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged

from quantos.application import discovery_prediction_cohort as reporting
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_evaluation import (
    ScientificEvaluationBudget,
    ScientificEvaluationDeclaration,
)
from quantos.contracts.discovery_prediction import PredictionFileSource


def write_reference(path, value):
    raw = (
        value.canonical_bytes()
        if hasattr(value, "canonical_bytes")
        else canonical_json_bytes(value)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return PredictionFileSource(path=str(path), sha256=sha256_bytes(raw))


@pytest.fixture
def cohort_probe(staged, tmp_path):
    f = staged
    original, successor = (
        f.request.model_copy(update={"code_commit_hash": code * 40}) for code in ("2", "3")
    )
    dates = tuple(date(2023, 1, 2) + timedelta(days=i) for i in range(3))
    wrapper_hash = "b" * 64
    policy_source = write_reference(
        tmp_path / "policy.json",
        {
            "schema_version": "post-hm-scientific-comparison-design/v1",
            "new_llm_calls_authorized": False,
            "tests_authorized": False,
            "sealed_confirmation_authorized": False,
            "original_sequential_batch_hash": wrapper_hash,
            "minimum_defined_fraction": 2 / 3,
            "minimum_common_days": 2,
            "required_meaningful_llm_increment": 0.05,
            "acceptable_five_entry_llm_wall_seconds": 10,
            "acceptable_new_scientific_management_wall_seconds": 10,
            "adopted_historical_origins": 1,
            "new_candidate_executions": 1,
            "max_compute_units": 36,
            "expected_complete_growth_bytes": 1024,
        },
    )
    policy = reporting.policy_from_design(policy_source)
    declaration = ScientificEvaluationDeclaration(
        original_sequential_batch_hash=wrapper_hash,
        original_generation_policy_hash="a" * 64,
        original_batch_hash=f.batch.content_hash,
        original_design_hash=f.batch.design.content_hash,
        original_generation_source_commit="1" * 40,
        original_generation_source_declaration_hash="a" * 64,
        evaluation_source_declaration_hash="b" * 64,
        snapshot_hash=f.request.snapshot_hash,
        qlib_view_hash=f.request.qlib_view_hash,
        authorization_hash="c" * 64,
        scientific_scheduling_cutoff_hash="d" * 64,
        budget=ScientificEvaluationBudget(
            full_batch_compute_units=36,
            new_execution_compute_units=18,
            max_compute_units=36,
            max_distinct_candidates=2,
            max_new_candidate_executions=1,
        ),
        bindings=f.batch.design.bindings.model_copy(
            update={"code_commit_hash": successor.code_commit_hash}
        ),
        scientific_adoption_plan_hash="e" * 64,
        exposure_history_append=("SYNTHETIC UNIT TEST ONLY; NO EXECUTION AUTHORITY",),
    )
    keys = ("a" * 64, "b" * 64)
    failed = AutonomousExecutionResult(
        request_hash=original.content_hash,
        outcome="EXECUTION_FAILED",
        execution_requested=True,
        compute_seconds=18,
    )
    old_ref = write_reference(tmp_path / "old-outcome.json", failed)
    origin = SimpleNamespace(
        target_subtask_hash=keys[0], source_subtask_hash="c" * 64, source_outcome=old_ref
    )
    adoption = SimpleNamespace(
        origins=(origin,), source_requests=(original,), new_subtask_hashes=(keys[1],)
    )
    requests = tuple(
        SimpleNamespace(content_hash=r.content_hash, method=r.method, max_attempts=5)
        for r in f.batch.requests
    )
    mappings = tuple(
        SimpleNamespace(
            request_hash=r.content_hash,
            reservation_hash=str(i) * 64,
            response_hash=None,
            status="ADMITTED",
            reason="STATIC_CAPABILITY_ADMITTED",
            subtask_hash=keys[1] if r.method == "RANDOM" else keys[0],
        )
        for i, r in enumerate(requests, 1)
    )
    mappings += (
        SimpleNamespace(
            request_hash=requests[0].content_hash,
            reservation_hash="4" * 64,
            response_hash=None,
            status="FAILED",
            reason="CAPTURE_FAILED",
            subtask_hash=None,
        ),
    )
    tasks = tuple(
        SimpleNamespace(content_hash=k, manifest=SimpleNamespace(candidates=(f.request.candidate,)))
        for k in keys
    )
    batch = SimpleNamespace(
        design=f.batch.design, subtasks=tasks, requests=requests, mappings=mappings
    )
    wrapper = SimpleNamespace(content_hash=wrapper_hash, batch=batch)
    service = SimpleNamespace(
        batch=batch,
        sequential_batch=wrapper,
        evaluation_declaration=declaration,
        scientific_verified_adoption=lambda: adoption,
        scientific_dependency_adoption=SimpleNamespace(
            content_hash="f" * 64, original_source_commit=original.code_commit_hash
        ),
        task_request=lambda key: successor if key == keys[1] else original,
        output_root=tmp_path / "report-only",
    )
    cohort = reporting.pure_cohort_prepare(service, policy=policy, expected_dates=dates)
    return SimpleNamespace(
        service=service,
        cohort=cohort,
        keys=keys,
        adoption=adoption,
        old_ref=old_ref,
        failed=failed,
        policy_source=policy_source,
        dates=dates,
    )


def test_pure_prepare_preserves_actual_origin_identities_without_execution(cohort_probe):
    p = cohort_probe
    reporting.verify_scientific_prediction_cohort(p.service, p.cohort)
    assert len(p.cohort.profiles) == 2
    assert [item.mode for item in p.cohort.origins] == [
        "REUSED_HISTORICAL_ORIGIN",
        "NEW_SCIENTIFIC_EXECUTION",
    ]
    assert {item.actual_request.code_commit_hash for item in p.cohort.origins} == {
        "2" * 40,
        "3" * 40,
    }
    assert not p.service.output_root.exists()
    assert p.old_ref.sha256 == sha256_bytes(Path(p.old_ref.path).read_bytes())


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("authority", "VERIFIED_SCIENTIFIC_ADOPTION_REQUIRED"),
        ("opportunities", "FROZEN_FIFTEEN_OPPORTUNITIES_REQUIRED"),
        ("partition", "COHORT_PARTITION_INCOMPLETE"),
        ("code", "ACTUAL_ORIGIN_SCIENTIFIC_TUPLE_DIFFERS"),
        ("pair", "ADOPTION_REQUEST_PAIRING_INVALID"),
        ("policy", "FROZEN_SCIENTIFIC_COHORT_COUNTS_OR_AUTHORITY_DIFFERS"),
    ],
)
def test_pure_prepare_rejects_authority_partition_or_identity_drift(cohort_probe, damage, reason):
    p = cohort_probe
    if damage == "authority":
        p.service.evaluation_declaration = None
    elif damage == "opportunities":
        p.service.batch.requests[0].max_attempts = 4
    elif damage == "partition":
        p.adoption.new_subtask_hashes = ("f" * 64,)
    elif damage == "code":
        p.service.scientific_dependency_adoption.original_source_commit = "9" * 40
    elif damage == "pair":
        p.adoption.source_requests = ()
    else:
        p.service.sequential_batch.content_hash = "0" * 64
    with pytest.raises(ValueError, match=reason):
        reporting.pure_cohort_prepare(p.service, policy=p.cohort.policy, expected_dates=p.dates)


@pytest.mark.parametrize(
    "damage", ["date", "requests", "threshold", "counts", "targets", "profile"]
)
def test_cohort_contract_rejects_rebinding_a_frozen_denominator(cohort_probe, damage):
    p = cohort_probe
    values = p.cohort.model_dump()
    if damage == "date":
        values["expected_dates"] = p.dates[:-1]
    elif damage == "requests":
        values["profiles"][0]["execution_request_hashes"] = ("f" * 64,)
    elif damage == "threshold":
        values["policy"]["min_defined_fraction"] = 1
    elif damage == "counts":
        values["policy"]["new_execution_count"] = 2
    elif damage == "targets":
        values["origins"] = list(reversed(values["origins"]))
    else:
        values["origins"][0]["prediction_profile_hash"] = "f" * 64
    with pytest.raises(ValueError):
        type(p.cohort).model_validate(values)


def test_verifier_repair_is_separate_and_cannot_change_scientific_scope(
    cohort_probe, tmp_path, monkeypatch
):
    p = cohort_probe
    predecessor = write_reference(tmp_path / "cohort.json", p.cohort)
    successor = p.cohort.model_copy(update={"cohort_verifier_identity_hash": "0" * 64})
    monkeypatch.setattr(reporting, "pure_cohort_prepare", lambda *_a, **_kw: successor)
    rebuilt, repair = reporting.prepare_scientific_prediction_cohort_repair(p.service, predecessor)
    assert rebuilt == successor and repair.scientific_reexecution_required is False
    reporting.verify_scientific_prediction_cohort_repair(p.service, successor, repair)
    assert reporting._repair_predecessor(predecessor) == p.cohort
    changed = successor.model_copy(update={"expected_dates": p.dates[:-1]})
    monkeypatch.setattr(reporting, "pure_cohort_prepare", lambda *_a, **_kw: changed)
    with pytest.raises(ValueError, match="COHORT_REPAIR_SCOPE_CHANGED"):
        reporting.prepare_scientific_prediction_cohort_repair(p.service, predecessor)
    Path(predecessor.path).write_bytes(b"{}")
    with pytest.raises(ValueError, match="PREDECESSOR_COHORT_HASH_MISMATCH"):
        reporting._repair_predecessor(predecessor)


def synthetic_evidence(request, dates, values, label="label"):
    return SimpleNamespace(
        daily=tuple(
            SimpleNamespace(trade_date=d, rank_ic=SimpleNamespace(value=v))
            for d, v in zip(dates, values, strict=True)
        ),
        native_sources=(SimpleNamespace(path="/synthetic/label.pkl", sha256=label),),
        original_execution_outcome="EXECUTION_FAILED",
        original_failure_reason="QLIB_EXECUTION_FAILED",
        original_validation_report_hash=None,
        original_receipt_hash=request.content_hash,
    )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("available", "AVAILABLE"),
        ("label", "UNAVAILABLE"),
        ("common", "UNAVAILABLE"),
        ("coverage", "AVAILABLE"),
        ("rejected", "AVAILABLE"),
        ("missing", "AVAILABLE"),
        ("request", "AVAILABLE"),
        ("evidence", "AVAILABLE"),
        ("none", "UNAVAILABLE"),
    ],
)
def test_global_report_keeps_failures_nulls_and_all_opportunities(
    cohort_probe, monkeypatch, case, expected
):
    p = cohort_probe
    originals = {o.target_subtask_hash: o.actual_request for o in p.cohort.origins}
    sources = {
        k: SimpleNamespace(request=SimpleNamespace(sha256=r.content_hash))
        for k, r in originals.items()
    }
    refs = {k: (Path("/not-read"), k) for k in p.keys}
    evidence = {
        p.keys[0]: synthetic_evidence(originals[p.keys[0]], p.dates, (0.2, 0.4, None)),
        p.keys[1]: synthetic_evidence(originals[p.keys[1]], p.dates, (0.0, 0.2, None)),
    }
    if case == "label":
        evidence[p.keys[1]].native_sources[0].sha256 = "other"
    elif case == "common":
        evidence[p.keys[1]] = synthetic_evidence(originals[p.keys[1]], p.dates, (None, 0.2, 0.4))
    elif case == "coverage":
        evidence[p.keys[1]] = synthetic_evidence(originals[p.keys[1]], p.dates, (None, None, None))
    elif case == "missing":
        del sources[p.keys[1]]
    elif case == "request":
        sources[p.keys[1]].request.sha256 = "wrong"
    elif case == "evidence":
        del refs[p.keys[1]]
    elif case == "none":
        sources = {}
    calls = []

    def verify(_path, *, expected_hash, source, profile, base_authoring):
        calls.append(expected_hash)
        assert source.request.sha256 in profile.execution_request_hashes
        if case == "rejected" and expected_hash == p.keys[1]:
            raise ValueError("PIT_HARD_REJECTION")
        return evidence[expected_hash]

    monkeypatch.setattr(reporting, "verify_prediction_evidence", verify)
    monkeypatch.setattr(
        reporting,
        "generation_counts_from_verified_batch",
        lambda _: {"scope": "synthetic counts only"},
    )
    report = reporting.compare_scientific_prediction_cohort(p.service, p.cohort, sources, refs)
    assert report["primary_comparison_status"] == expected
    assert report["candidate_denominator"] == 2 and report["opportunity_denominator"] == 15
    assert len(report["opportunity_rows"]) == 4
    assert report["opportunity_rows"][-1]["primary_common_rank_ic_mean"] is None
    assert report["original_validation_and_p14c"] == "UNCHANGED"
    old = report["candidate_rows"][0]
    assert old["original_execution_outcome"] == "EXECUTION_FAILED"
    assert old["original_validation_report_hash"] is None
    assert report["science_count_scope"]["new"]["unknown_terminal_outcomes"] == 1
    assert report["science_count_scope"]["new"]["distinct_execution_requested"] is None
    assert report["science_count_scope"]["historical"]["observed_budget_units"] == 18
    if case == "available":
        assert report["common_days"] == 2
        assert report["llm_minus_best_baseline"] == 0
        assert old["primary_common_rank_ic_mean"] == pytest.approx(0.3)
    elif case in ("label", "common", "none"):
        assert report["llm_minus_best_baseline"] is None
    if case in ("request", "evidence", "missing", "none"):
        assert p.keys[1] not in calls
    assert not p.service.output_root.exists()


def test_actual_terminal_observation_rejects_changed_request_and_hash(cohort_probe):
    p = cohort_probe
    request = p.cohort.origins[1].actual_request
    path = p.service.output_root / "tasks" / p.keys[1] / "outcome.json"
    outcome = AutonomousExecutionResult(
        request_hash=request.content_hash,
        outcome="PIT_REJECT",
        execution_requested=False,
        compute_seconds=0,
    )
    write_reference(path, outcome)
    observed = reporting._execution_observations(p.service, p.cohort)
    counts = reporting._science_counts(p.cohort, observed)
    assert counts["new"]["distinct_execution_requested"] == 0
    assert counts["historical_budget_recharged"] is False
    write_reference(path, p.failed)
    with pytest.raises(ValueError, match="ACTUAL_OUTCOME_ORIGIN_MISMATCH"):
        reporting._execution_observations(p.service, p.cohort)
    assert (
        reporting.bounded_prediction_rejection(ValueError("PIT_HARD_REJECTION"))
        == "PIT_HARD_REJECTION"
    )
    assert reporting.bounded_prediction_rejection(RuntimeError("private path /x")) == "RuntimeError"
