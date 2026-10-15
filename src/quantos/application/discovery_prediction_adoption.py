"""Explicit immutable evidence adoption; never a persistent PIT reconstruction cache."""

from __future__ import annotations

import importlib
import json
import platform
from collections.abc import Mapping
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import cast

from quantos.application.autonomous_execution import AutonomousExecutionReceipt
from quantos.application.discovery_prediction import (
    _comparison_from_verified,  # pyright: ignore[reportPrivateUsage]
    _contract,  # pyright: ignore[reportPrivateUsage]
    _raw_json,  # pyright: ignore[reportPrivateUsage]
    _require,  # pyright: ignore[reportPrivateUsage]
    _research_policy,  # pyright: ignore[reportPrivateUsage]
    _safe_path,  # pyright: ignore[reportPrivateUsage]
    _verify_source_code,  # pyright: ignore[reportPrivateUsage]
    prediction_verifier_identity,
    verify_prediction_evidence,
)
from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import regular_tree_files, sha256_file
from quantos.contracts.autonomous import AutonomousExecutionRequest, AutonomousExecutionResult
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_prediction import (
    PREDICTION_RULE_HASH,
    PredictionEvaluationProfile,
    PredictionEvidence,
    PredictionEvidenceManifest,
    PredictionFileSource,
    PredictionImportSource,
)
from quantos.contracts.discovery_prediction_adoption import PredictionEvidenceAdoption
from quantos.contracts.pit import PITGateId
from quantos.contracts.refs import validate_logical_path
from quantos.contracts.research import ExperimentAuthoringSpec, ResolvedExperimentSpec
from quantos.contracts.research_execution import (
    PITCrossSectionEvidenceCollection,
    PITCrossSectionEvidenceCollectionV3,
)
from quantos.contracts.status import ValidationVerdict
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.research.qlib.model_split import verify_model_data_split
from quantos.research.qlib.pit_evidence import load_pit_artifact_evidence
from quantos.research.qlib.signal import verify_signal_artifact


def _original_json(reference: PredictionFileSource) -> dict[str, object]:
    """Control exits may be noncanonical historical bytes; their actual hash is authority."""
    path = _safe_path(reference.path)
    _require(path.stat().st_size <= 16 << 20, "ADOPTION_METADATA_TOO_LARGE")
    raw = path.read_bytes()
    _require(sha256_bytes(raw) == reference.sha256, "ADOPTION_ORIGINAL_HASH_MISMATCH")
    value: object = json.loads(raw)
    _require(isinstance(value, dict), "ADOPTION_ORIGINAL_NOT_OBJECT")
    return cast(dict[str, object], value)


def _prior_authority(
    adoption: PredictionEvidenceAdoption, profile: PredictionEvaluationProfile
) -> tuple[PredictionEvaluationProfile, dict[str, dict[str, object]]]:
    prior = _contract(adoption.prior_profile, PredictionEvaluationProfile)
    report = _raw_json(adoption.prior_report)
    exit_record = _original_json(adoption.prior_report_exit)
    cohort = _raw_json(adoption.prior_cohort)
    policy = _raw_json(adoption.comparison_policy)
    _require(exit_record.get("actual_exit") == 0, "PRIOR_VERIFIED_REPORT_NOT_COMPLETED")
    prelaunch = _original_json(adoption.prior_report_prelaunch)
    configuration = _raw_json(adoption.prior_configuration)
    completed_output = _safe_path(cast(str, configuration["report_output"]), directory=True)
    _require(
        _safe_path(adoption.prior_report.path).parent == completed_output
        and _safe_path(adoption.prior_profile.path) == completed_output / "profile.json"
        and all(
            _safe_path(item.evidence_root, directory=True)
            == completed_output / "evidence" / f"sha256-{item.manifest_hash}"
            for item in adoption.retained
        ),
        "ADOPTION_OUTPUT_OUTSIDE_COMPLETED_REPORT",
    )
    operator = _safe_path(adoption.prior_operator.path)
    _require(
        sha256_file(operator) == adoption.prior_operator.sha256, "ADOPTION_PRIOR_OPERATOR_CHANGED"
    )
    argv = prelaunch.get("argv")
    _require(isinstance(argv, list), "ADOPTION_PRIOR_INVOCATION_MISSING")
    command = cast(list[str], argv)
    _require(
        Path(adoption.prior_report_exit.path).parent
        == Path(adoption.prior_report_prelaunch.path).parent
        and command[command.index("--configuration") + 1] == adoption.prior_configuration.path
        and command[command.index("--configuration-sha256") + 1]
        == adoption.prior_configuration.sha256
        and command[command.index("--expected-operator-hash") + 1] == adoption.prior_operator.sha256
        and command[command.index(adoption.prior_operator.path) + 1] == "compare"
        and Path(adoption.prior_report.path).name == f"report-{adoption.prior_report.sha256}.json"
        and configuration.get("expected_report_verifier_identity_hash")
        == prior.verifier_identity_hash
        and cast(dict[str, str], configuration["comparison_policy_authority"])["sha256"]
        == adoption.comparison_policy.sha256
        and cast(dict[str, str], configuration["cohort_authority"])["sha256"]
        == adoption.prior_cohort.sha256
        and cast(dict[str, str], configuration["report_verifier_capsule"])["sha256"]
        == adoption.prior_verifier_capsule.sha256
        and cast(dict[str, str], configuration["report_verifier_inventory"])["sha256"]
        == adoption.prior_verifier_inventory.sha256,
        "ADOPTION_PRIOR_COMPLETION_ORIGIN_MISMATCH",
    )
    _require(
        prior.model_dump(exclude={"verifier_identity_hash"})
        == profile.model_dump(exclude={"verifier_identity_hash"})
        and prior.rule_hash == profile.rule_hash == PREDICTION_RULE_HASH
        and report.get("profile_hash") == prior.content_hash
        and report.get("comparison_policy_hash") == adoption.comparison_policy.sha256
        and report.get("schema_version") == "b2-common-day-report/v1",
        "ADOPTION_PROFILE_OR_POLICY_CHANGED",
    )
    requests = cohort.get("requests")
    _require(isinstance(requests, dict), "ADOPTION_COHORT_INVALID")
    request_objects = cast(dict[str, object], requests)
    request_hashes = tuple(
        sorted(
            AutonomousExecutionRequest.model_validate(value).content_hash
            for value in request_objects.values()
        )
    )
    _require(request_hashes == profile.execution_request_hashes, "ADOPTION_COHORT_CHANGED")
    _require(
        policy.get("min_defined_fraction") == profile.min_defined_fraction
        and policy.get("min_common_days") == profile.min_common_days
        and policy.get("expected_test_dates")
        == [day.isoformat() for day in profile.expected_dates],
        "ADOPTION_STATISTICAL_POLICY_CHANGED",
    )
    rows = report.get("sources")
    _require(isinstance(rows, list), "ADOPTION_PRIOR_SOURCES_MISSING")
    imported: dict[str, dict[str, object]] = {}
    for row in cast(list[object], rows):
        _require(isinstance(row, dict), "ADOPTION_PRIOR_SOURCE_INVALID")
        item = cast(dict[str, object], row)
        if item.get("status") == "IMPORTED":
            key = cast(str, item["request_hash"])
            _require(key not in imported, "ADOPTION_PRIOR_SOURCE_DUPLICATE")
            imported[key] = item
    _require(
        all(item.execution_request_hash in imported for item in adoption.retained),
        "ADOPTION_SOURCE_NOT_PREVIOUSLY_IMPORTED",
    )
    return prior, imported


def _prior_verifier(adoption: PredictionEvidenceAdoption, identity: dict[str, object]) -> None:
    capsule = _raw_json(adoption.prior_verifier_capsule)
    _raw_json(adoption.prior_verifier_inventory)  # Actual retained inventory hash, not path/stat.
    workspace = _safe_path(cast(str, capsule["workspace"]), directory=True)
    verify_code_provenance(
        workspace,
        expected_commit_hash=cast(str, capsule["actual_commit"]),
        expected_lockfile_hash=cast(str, capsule["lockfile_hash"]),
    )
    _require(
        capsule.get("source_inventory_hash") == adoption.prior_verifier_inventory.sha256
        and identity.get("rule_hash") == PREDICTION_RULE_HASH
        and identity.get("python_version") == platform.python_version(),
        "ADOPTION_PRIOR_VERIFIER_BINDING_MISMATCH",
    )
    for item in cast(list[dict[str, str]], identity["dependencies"]):
        validate_logical_path(item["logical_path"])
        path = _safe_path(workspace / "src/quantos" / item["logical_path"])
        _require(sha256_file(path) == item["sha256"], "ADOPTION_PRIOR_VERIFIER_BYTES_CHANGED")
    for item in cast(list[dict[str, str]], identity["external_dependencies"]):
        module = importlib.import_module(item["module"])
        _require(
            module.__file__ is not None and sha256_file(Path(module.__file__)) == item["sha256"],
            "ADOPTION_EXTERNAL_DEPENDENCY_CHANGED",
        )
    for name, expected in cast(dict[str, str], identity["packages"]).items():
        _require(version(name) == expected, "ADOPTION_RUNTIME_PACKAGE_CHANGED")


def _retained_originals(
    source: PredictionImportSource,
    evidence: PredictionEvidence,
    profile: PredictionEvaluationProfile,
    base_authoring: ExperimentAuthoringSpec,
) -> None:
    request = _contract(source.request, AutonomousExecutionRequest)
    outcome = _contract(source.outcome, AutonomousExecutionResult)
    receipt = _contract(source.receipt, AutonomousExecutionReceipt)
    resolved = _contract(source.resolved, ResolvedExperimentSpec)
    policy = _research_policy(source.research_policy)
    for reference in (
        source.workflow_reservation,
        source.workflow_completion,
        source.management_exit,
    ):
        _raw_json(reference)
    _verify_source_code(source, request)
    _require(
        evidence.execution_request_hash == request.content_hash
        and evidence.original_outcome_hash == outcome.content_hash
        and evidence.original_receipt_hash == receipt.content_hash
        and evidence.model_split_hash == source.model_split_sha256
        and evidence.signal_hash == source.signal_hash
        and receipt.request == request
        and evidence.profile_hash == profile.content_hash
        and evidence.verifier_identity_hash == profile.verifier_identity_hash
        and base_authoring.content_hash == request.authoring_hash,
        "ADOPTION_ORIGINAL_BINDINGS_CHANGED",
    )
    for name in (
        "snapshot_hash",
        "qlib_view_hash",
        "research_policy_hash",
        "code_commit_hash",
        "lockfile_hash",
        "qlib_version",
    ):
        _require(
            getattr(request, name) == getattr(profile, name) == getattr(resolved, name),
            "ADOPTION_SOURCE_PROFILE_BINDING_MISMATCH",
        )
    _require(
        policy.content_hash == profile.research_policy_hash
        and resolved.expression == request.candidate.expression,
        "ADOPTION_POLICY_OR_EXPRESSION_CHANGED",
    )
    signal_path = _safe_path(source.signal_path, directory=True)
    signal = verify_signal_artifact(signal_path)  # Rehash every actual signal/PIT source file.
    pit = load_pit_artifact_evidence(signal_path / "pit-evidence.json")
    if isinstance(pit, PITCrossSectionEvidenceCollectionV3):
        raise ValueError("ADOPTION_PIT_EXECUTION_PROFILE_MISMATCH")
    _require(
        signal.artifact_hash == evidence.signal_hash
        and signal.resolved_experiment_hash == resolved.content_hash
        and signal.snapshot_hash == request.snapshot_hash
        and signal.qlib_view_hash == request.qlib_view_hash
        and signal.source_expression_or_model_hash == request.candidate.expression.content_hash
        and pit.content_hash == evidence.pit_evidence_hash == resolved.pit_audit_evidence_hash
        and pit.snapshot_hash == request.snapshot_hash
        and pit.expression_spec_hash == request.candidate.expression.content_hash
        and pit.universe_index == resolved.strategy.universe_index,
        "ADOPTION_PIT_OR_SIGNAL_CHANGED",
    )
    # Same hard gates as independent import. Their source reproduction is adopted
    # from the completed prior report only after the full actual dependency closure hashes match.
    gate_sets = (
        [bundle.gates for bundle in pit.bundles]
        if isinstance(pit, PITCrossSectionEvidenceCollection)
        else [item.report.gates for bundle in pit.bundles for item in bundle.items]
    )
    _require(
        all(
            tuple(g.gate_id for g in gates) == tuple(PITGateId)
            and all(g.verdict is ValidationVerdict.PASS for g in gates)
            for gates in gate_sets
        ),
        "ADOPTION_PIT_HARD_REJECTION",
    )
    native = _safe_path(source.native_root, directory=True)
    _require(
        native.name == f"sha256-{request.execution_identity}", "ADOPTION_NATIVE_IDENTITY_CHANGED"
    )
    _require(
        {Path(item.path).relative_to(native).as_posix() for item in evidence.native_sources}
        == {"pred.pkl", "label.pkl", "metrics.json", "sig_analysis/ic.pkl", "sig_analysis/ric.pkl"},
        "ADOPTION_NATIVE_SOURCE_SET_CHANGED",
    )
    for reference in evidence.native_sources:
        _require(
            sha256_file(_safe_path(reference.path)) == reference.sha256,
            "ADOPTION_NATIVE_ORIGINAL_CHANGED",
        )
    split = native / "model-data-splits.json"
    _require(sha256_file(split) == source.model_split_sha256, "ADOPTION_MODEL_SPLIT_CHANGED")
    calendar = tuple(
        date.fromisoformat(day)
        for day in (Path(source.qlib_view_path) / "calendars/day.txt").read_text().splitlines()
        if day
    )
    verify_model_data_split(split, resolved=resolved, research_policy=policy, calendar=calendar)


def adopt_prediction_evidence(
    adoption: PredictionEvidenceAdoption,
    profile: PredictionEvaluationProfile,
    *,
    base_authoring: ExperimentAuthoringSpec,
) -> dict[str, tuple[PredictionEvidence, str]]:
    """Verify the unchanged actual closure and adopt prior successful evidence.

    Snapshot/view files are hashed once per unique identity, never read through a
    numerical data engine. No PIT fact is injected into any reconstruction scope.
    """
    prior, imported = _prior_authority(adoption, profile)
    _require(
        profile.verifier_identity_hash
        == sha256_bytes(canonical_json_bytes(prediction_verifier_identity())),
        "VERIFIER_IDENTITY_MISMATCH",
    )
    data_roots: set[tuple[str, str]] = set()
    verified: dict[str, tuple[PredictionEvidence, str]] = {}
    verifier_checked = False
    for retained in adoption.retained:
        path = _safe_path(retained.evidence_root, directory=True)
        _require(
            path.name == f"sha256-{retained.manifest_hash}", "ADOPTION_EVIDENCE_DIRECTORY_CHANGED"
        )
        _require(
            {p.relative_to(path).as_posix() for p in regular_tree_files(path)}
            == {
                "manifest.json",
                "evidence.json",
                "source.json",
                "profile.json",
                "verifier-identity.json",
            },
            "ADOPTION_EVIDENCE_FILE_SET_CHANGED",
        )
        manifest = PredictionEvidenceManifest.model_validate_json(
            (path / "manifest.json").read_bytes()
        )
        evidence = PredictionEvidence.model_validate_json((path / "evidence.json").read_bytes())
        source = PredictionImportSource.model_validate_json((path / "source.json").read_bytes())
        identity = cast(
            dict[str, object], json.loads((path / "verifier-identity.json").read_bytes())
        )
        for name, contract in (
            ("manifest.json", manifest),
            ("evidence.json", evidence),
            ("source.json", source),
        ):
            _require(
                (path / name).read_bytes() == contract.canonical_bytes(),
                "ADOPTION_EVIDENCE_NOT_CANONICAL",
            )
        _require(
            (path / "profile.json").read_bytes() == prior.canonical_bytes()
            and (path / "verifier-identity.json").read_bytes() == canonical_json_bytes(identity),
            "ADOPTION_PROFILE_OR_IDENTITY_BYTES_CHANGED",
        )
        _require(
            manifest.content_hash
            == retained.manifest_hash
            == imported[retained.execution_request_hash].get("evidence_hash")
            and manifest.execution_request_hash
            == retained.execution_request_hash
            == evidence.execution_request_hash
            == source.request.sha256
            and manifest.evidence_hash == evidence.content_hash
            and manifest.source_hash
            == source.content_hash
            == imported[retained.execution_request_hash].get("source_hash")
            and manifest.profile_hash == prior.content_hash
            and manifest.verifier_identity_hash
            == prior.verifier_identity_hash
            == sha256_bytes(canonical_json_bytes(identity)),
            "ADOPTION_EVIDENCE_PRIOR_REPORT_MISMATCH",
        )
        if not verifier_checked:
            _prior_verifier(adoption, identity)
            verifier_checked = True
        roots = (source.snapshot_path, source.qlib_view_path)
        if roots not in data_roots:
            snapshot, view = (
                verify_snapshot(_safe_path(roots[0], directory=True)),
                verify_qlib_view(_safe_path(roots[1], directory=True)),
            )
            _require(
                snapshot.snapshot_hash == prior.snapshot_hash
                and view.view_hash == prior.qlib_view_hash
                and view.source_snapshot_hash == snapshot.snapshot_hash,
                "ADOPTION_ACTUAL_DATA_IDENTITY_CHANGED",
            )
            data_roots.add(roots)
        _retained_originals(source, evidence, prior, base_authoring)
        verified[retained.execution_request_hash] = (evidence, retained.manifest_hash)
    return verified


def compare_with_adopted_prediction_evidence(
    adoption: PredictionEvidenceAdoption,
    profile: PredictionEvaluationProfile,
    new_sources: Mapping[str, PredictionImportSource],
    new_references: Mapping[str, tuple[Path, str]],
    *,
    base_authoring: ExperimentAuthoringSpec,
) -> dict[str, object]:
    """Same comparison rules; retained facts adopted, newly added evidence fully verified."""
    verified = adopt_prediction_evidence(adoption, profile, base_authoring=base_authoring)
    _require(not set(verified) & set(new_sources), "ADOPTION_AND_NEW_SOURCE_OVERLAP")
    _require(
        set(new_sources) <= set(profile.execution_request_hashes)
        and set(new_references) <= set(new_sources),
        "UNDECLARED_COMPARISON_REQUEST",
    )
    rows: list[dict[str, object]] = []
    for key in profile.execution_request_hashes:
        row: dict[str, object] = {
            "execution_request_hash": key,
            "status": "SOURCE_MISSING",
            "reason": "SOURCE_MISSING",
            "primary_common_rank_ic_mean": None,
            "own_dates_rank_ic_mean_sensitivity": None,
        }
        rows.append(row)
        if key in verified:
            continue
        if key not in new_sources:
            continue
        if key not in new_references:
            row.update(status="EVIDENCE_MISSING", reason="EVIDENCE_MISSING")
            continue
        if new_sources[key].request.sha256 != key:
            row.update(
                status="SOURCE_VERIFICATION_REJECTED", reason="COMPARISON_SOURCE_REQUEST_MISMATCH"
            )
            continue
        path, digest = new_references[key]
        try:
            evidence = verify_prediction_evidence(
                path,
                expected_hash=digest,
                source=new_sources[key],
                profile=profile,
                base_authoring=base_authoring,
            )
            verified[key] = (evidence, digest)
        except (OSError, ValueError, RuntimeError) as error:
            row.update(status="SOURCE_VERIFICATION_REJECTED", reason=type(error).__name__)
    report = _comparison_from_verified(profile, rows, verified)
    report["retained_evidence_adoption_hash"] = adoption.content_hash
    report["retained_evidence_semantics"] = (
        "PRIOR_FULL_VERIFICATION_ADOPTED_ACTUAL_CLOSURE_REHASHED"
    )
    return report
