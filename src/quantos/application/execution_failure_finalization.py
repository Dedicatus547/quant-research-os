"""Explicit offline closure of a retained MLflow recorder-start failure.

This management successor does not execute or adopt scientific output. It binds
the original STARTED reservation and controller exit, then uses the unchanged
adapter's native failure/receipt publishers and verifier. Frozen source and
failed parent controller records remain untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import Field, NonNegativeInt

from quantos.application.autonomous_execution import (
    AutonomousExecutionTrialIndex,
    QuantosResearchExecutionAdapter,
    require_durable_execution_root,
)
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.autonomous import AutonomousExecutionRequest, AutonomousExecutionResult
from quantos.contracts.base import CanonicalContract, sha256_bytes
from quantos.contracts.hosted import HostedResearchBudgetFact, HostedResearchStepIntent
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.sdk_producer import parse_agent_request


class RetainedFailureOriginal(CanonicalContract):
    schema_version: Literal["retained-failure-original/v1"] = "retained-failure-original/v1"
    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)


class RetainedMlflowFailureFinalization(CanonicalContract):
    """Management-origin proof; never a replacement scientific source identity."""

    schema_version: Literal["retained-mlflow-failure-finalization/v1"] = (
        "retained-mlflow-failure-finalization/v1"
    )
    request_hash: str = Field(pattern=SHA256_PATTERN)
    execution_identity: str = Field(pattern=SHA256_PATTERN)
    originating_code_commit: str
    management_source_hash: str = Field(pattern=SHA256_PATTERN)
    originals: dict[str, RetainedFailureOriginal]
    actual_controller_exit: Literal[1] = 1
    actual_exception_class: Literal["MlflowException"] = "MlflowException"
    failure_stage: Literal["MLFLOW_RECORDER_START"] = "MLFLOW_RECORDER_START"
    classification: Literal["FAILED_NOT_EVALUATED"] = "FAILED_NOT_EVALUATED"
    compute_units: NonNegativeInt
    scientific_reexecutions: Literal[0] = 0
    sdk_calls: Literal[0] = 0


def _read(path: Path, expected_hash: str | None = None) -> tuple[bytes, RetainedFailureOriginal]:
    require_durable_execution_root(path)
    with opened_directory(path.parent) as parent:
        encoded = read_regular_bytes_at(parent, path.name, max_bytes=1 << 20)
    digest = sha256_bytes(encoded)
    if expected_hash is not None and digest != expected_hash:
        raise ArtifactIntegrityError("retained failure original hash differs")
    return encoded, RetainedFailureOriginal(path=str(path.absolute()), sha256=digest)


_Contract = TypeVar("_Contract", bound=CanonicalContract)


def _contract(
    path: Path, expected_hash: str, cls: type[_Contract]
) -> tuple[_Contract, RetainedFailureOriginal]:
    encoded, original = _read(path, expected_hash)
    value = cls.model_validate_json(encoded)
    if value.canonical_bytes() != encoded or value.content_hash != expected_hash:
        raise ArtifactIntegrityError("retained failure contract is not its canonical original")
    return value, original


def finalize_retained_mlflow_failure(
    adapter: QuantosResearchExecutionAdapter,
    *,
    started_intent_path: Path,
    started_intent_hash: str,
    reservation_path: Path,
    reservation_hash: str,
    baseline_path: Path,
    baseline_hash: str,
    controller_directory: Path,
    expected_exit_hash: str,
    expected_loaded_hash: str,
    expected_controller_request_hash: str,
    expected_management_source_hash: str,
) -> AutonomousExecutionResult:
    """Verify retained proof and close through the adapter-owned publication boundary."""
    return adapter.finalize_retained_mlflow_failure(
        started_intent_path=started_intent_path,
        started_intent_hash=started_intent_hash,
        reservation_path=reservation_path,
        reservation_hash=reservation_hash,
        baseline_path=baseline_path,
        baseline_hash=baseline_hash,
        controller_directory=controller_directory,
        expected_exit_hash=expected_exit_hash,
        expected_loaded_hash=expected_loaded_hash,
        expected_controller_request_hash=expected_controller_request_hash,
        expected_management_source_hash=expected_management_source_hash,
    )


def verify_retained_mlflow_failure(
    adapter: QuantosResearchExecutionAdapter,
    *,
    started_intent_path: Path,
    started_intent_hash: str,
    reservation_path: Path,
    reservation_hash: str,
    baseline_path: Path,
    baseline_hash: str,
    controller_directory: Path,
    expected_exit_hash: str,
    expected_loaded_hash: str,
    expected_controller_request_hash: str,
    expected_management_source_hash: str,
) -> tuple[AutonomousExecutionRequest, RetainedMlflowFailureFinalization]:
    """Verify original proofs and return the exact request/witness without publishing.

    The caller must hold campaign/controller authority and ensure the original
    process has terminated. The adapter owns locked, immutable publication and
    preserves the reserved execution and frozen charge. Hosted accounting
    continuation remains a separate existing operation.
    """
    require_durable_execution_root(adapter.output_root)
    management_bytes, management_original = _read(Path(__file__), expected_management_source_hash)
    if sha256_bytes(management_bytes) != expected_management_source_hash:
        raise ArtifactIntegrityError("management source differs")
    intent, intent_original = _contract(
        started_intent_path, started_intent_hash, HostedResearchStepIntent
    )
    reservation, reservation_original = _contract(
        reservation_path, reservation_hash, HostedResearchBudgetFact
    )
    baseline, baseline_original = _contract(baseline_path, baseline_hash, HostedResearchBudgetFact)
    request = intent.execution_request
    if (
        intent.phase != "STARTED"
        or request is None
        or intent.execution_result_hash is not None
        or intent.trial_hash is not None
        or intent.budget_reservation_hash != reservation_hash
        or reservation.phase != "RESERVED"
        or reservation.previous_hash != baseline_hash
        or reservation.campaign_hash != request.campaign_hash
        or baseline.campaign_hash != request.campaign_hash
        or reservation.hosted_spec_hash != baseline.hosted_spec_hash
        or reservation.request_hash != intent.request_hash
        or reservation.used_executions - baseline.used_executions != 1
        or reservation.used_trials - baseline.used_trials != 1
    ):
        raise ArtifactIntegrityError("retained failure has no exact STARTED execution reservation")

    exit_bytes, exit_original = _read(controller_directory / "exit.json", expected_exit_hash)
    loaded_bytes, loaded_original = _read(
        controller_directory / "loaded.json", expected_loaded_hash
    )
    controller_request_bytes, controller_request_original = _read(
        controller_directory / "request-1.json", expected_controller_request_hash
    )
    before_bytes, before_original = _read(controller_directory / "before-step-1.json")
    actual_exit, loaded, before = (
        json.loads(exit_bytes),
        json.loads(loaded_bytes),
        json.loads(before_bytes),
    )
    controller_request = parse_agent_request(controller_request_bytes, max_bytes=1 << 20)
    frames = actual_exit.get("failure_frames", ())
    observed = tuple((frame.get("filename"), frame.get("function")) for frame in frames)
    required = (
        ("autonomous_execution.py", "_execute_pipeline"),
        ("workflow.py", "run"),
        ("file_store.py", "create_run"),
        ("file_store.py", "set_tag"),
        ("file_store.py", "_get_run_info"),
    )
    positions = [observed.index(pair) if pair in observed else -1 for pair in required]
    if (
        actual_exit.get("exit_code") != 1
        or actual_exit.get("error_class") != "MlflowException"
        or not actual_exit.get("finished_utc")
        or -1 in positions
        or positions != sorted(positions)
        or observed[-1:] != (("file_store.py", "_get_run_info"),)
        or loaded.get("campaign_hash") != request.campaign_hash
        or loaded.get("spec_hash") != reservation.hosted_spec_hash
        or controller_request.content_hash != intent.request_hash
        or before.get("request_hash") != intent.request_hash
    ):
        raise ArtifactIntegrityError(
            "retained controller exit does not prove this recorder failure"
        )

    charge = adapter.execution_compute_charge(request)
    if reservation.used_compute_units - baseline.used_compute_units != charge:
        raise ArtifactIntegrityError("retained failure charge differs from original reservation")
    index_path = (
        adapter.output_root
        / "trial-identities"
        / f"{request.campaign_hash}-{request.trial_ordinal:08d}.json"
    )
    index_bytes, index_original = _read(index_path)
    index = AutonomousExecutionTrialIndex.model_validate_json(index_bytes)
    if index_bytes != index.canonical_bytes() or index != AutonomousExecutionTrialIndex(
        campaign_hash=request.campaign_hash,
        trial_ordinal=request.trial_ordinal,
        execution_identity=request.execution_identity,
        request_hash=request.content_hash,
    ):
        raise ArtifactIntegrityError("retained failure original trial identity differs")
    indexed_bytes, indexed_original = _read(
        adapter.output_root / "trial-identity-artifacts" / f"sha256-{index.content_hash}.json",
        index.content_hash,
    )
    if indexed_bytes != index_bytes:
        raise ArtifactIntegrityError("retained trial identity content index differs")
    witness = RetainedMlflowFailureFinalization(
        request_hash=request.content_hash,
        execution_identity=request.execution_identity,
        originating_code_commit=request.code_commit_hash,
        management_source_hash=expected_management_source_hash,
        compute_units=charge,
        originals={
            "management_source": management_original,
            "started_intent": intent_original,
            "reservation": reservation_original,
            "reservation_baseline": baseline_original,
            "controller_exit": exit_original,
            "controller_loaded": loaded_original,
            "controller_request": controller_request_original,
            "controller_before_step": before_original,
            "trial_identity": index_original,
            "trial_identity_index": indexed_original,
        },
    )
    return request, witness
