"""Origin-preserving baseline adoption and two-opportunity recovery continuity."""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import (
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
)
from quantos.backtest import verify_backtest_artifact
from quantos.contracts.autonomous import AutonomousExecutionRequest
from quantos.contracts.backtest import BacktestArtifactManifest
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_prediction import PredictionFileSource, PredictionImportSource
from quantos.contracts.field_study import (
    FieldStudyBaselineOrigin,
    FieldStudyOpportunityState,
    FieldStudyOpportunityTransfer,
    FieldStudyPreparation,
    FieldStudyRecoveryOrigin,
    FieldStudyRecoveryPreparation,
    FieldStudySourceAdoption,
    FieldStudyTask,
    FrozenFieldStudyConfiguration,
    PreparedFieldStudy,
)
from quantos.contracts.native_adoption import verify_adoption_bindings
from quantos.contracts.refs import validate_logical_path
from quantos.contracts.research import ResolvedExperimentSpec
from quantos.research.qlib.signal import verify_signal_artifact

# Only the reviewed recorder change and this explicit recovery connection may
# differ in executable code. Data/PIT/expression/signal/backtest/gates/configs stay exact.
_WIRING_CHANGES = frozenset(
    {
        "src/quantos/research/qlib/workflow.py",
        "src/quantos/contracts/field_study.py",
        "src/quantos/application/field_study.py",
        "src/quantos/application/field_study_recovery.py",
        "src/quantos/application/autonomous_execution.py",
        "src/quantos/application/discovery_prediction.py",
        "scripts/frozen_field_study.py",
    }
)


def plain_path(value: str | Path) -> Path:
    path = Path(value)
    if (
        not path.is_absolute()
        or path != path.resolve()
        or any(p.is_symlink() for p in (path, *path.parents))
    ):
        raise ValueError("field-study origin requires canonical absolute paths")
    return path


def read_origin(reference: PredictionFileSource, *, limit: int = 16 << 20) -> bytes:
    path = plain_path(reference.path)
    with opened_directory(path.parent) as parent:
        raw = read_regular_bytes_at(parent, path.name, max_bytes=limit)
    if sha256_bytes(raw) != reference.sha256:
        raise ValueError("field-study original hash mismatch")
    return raw


def _json(path: Path, digest: str | None = None) -> dict[str, Any]:
    path = plain_path(path)
    with opened_directory(path.parent) as parent:
        raw = read_regular_bytes_at(parent, path.name, max_bytes=16 << 20)
    if digest is not None and sha256_bytes(raw) != digest:
        raise ValueError("field-study original hash mismatch")
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(cast(dict[str, Any], value)) != raw:
        raise ValueError("field-study original is not canonical metadata")
    return cast(dict[str, Any], value)


def predecessor(origin: FieldStudyRecoveryOrigin) -> FieldStudyPreparation:
    from quantos.application.field_study import load_preparation

    path = plain_path(origin.predecessor_preparation.path)
    old = load_preparation(path, origin.predecessor_preparation.sha256)
    if (
        not isinstance(old, FieldStudyPreparation)
        or path != Path(old.preparation_root) / "preparation.json"
    ):
        raise ValueError("field-study recovery requires its original v1 preparation")
    return old


def _inventory(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if value.get("schema_version") != "frozen-field-study-source-inventory/v1" or not isinstance(
        value.get("files"), list
    ):
        raise ValueError("field-study source inventory schema differs")
    files: dict[str, dict[str, Any]] = {}
    for entry in value["files"]:
        if not isinstance(entry, dict):
            raise ValueError("field-study source inventory entry differs")
        item = cast(dict[str, Any], entry)
        if set(item) != {"path", "bytes_hash", "size_bytes"} or (
            not isinstance(item.get("path"), str)
            or not isinstance(item.get("bytes_hash"), str)
            or re.fullmatch(r"[0-9a-f]{64}", item["bytes_hash"]) is None
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] < 0
        ):
            raise ValueError("field-study source inventory entry differs")
        name = validate_logical_path(item["path"])
        if name in files:
            raise ValueError("field-study source inventory duplicate")
        files[name] = item
    if not files:
        raise ValueError("field-study source inventory empty")
    return files


def verify_origin_sources(
    origin: FieldStudyRecoveryOrigin,
    config: FrozenFieldStudyConfiguration,
    successor_inventory: dict[str, Any],
) -> FieldStudyPreparation:
    old = predecessor(origin)
    if origin.successor_configuration_hash != config.content_hash or (
        old.configuration.model_dump(exclude={"study_id", "workspace", "code_commit_hash"})
        != config.model_dump(exclude={"study_id", "workspace", "code_commit_hash"})
        or old.configuration.code_commit_hash == config.code_commit_hash
    ):
        raise ValueError("field-study recovery changes scientific inputs or successor identity")
    source = plain_path(origin.reconstructed_workspace)
    verify_code_provenance(
        source,
        expected_commit_hash=old.configuration.code_commit_hash,
        expected_lockfile_hash=old.configuration.lockfile_hash,
    )
    verify_code_provenance(
        plain_path(config.workspace),
        expected_commit_hash=config.code_commit_hash,
        expected_lockfile_hash=config.lockfile_hash,
    )
    old_root = Path(old.preparation_root)
    capsule = _json(old_root / "source-capsule.json", old.source_capsule_hash)
    if (
        capsule.get("workspace") != old.configuration.workspace
        or capsule.get("actual_commit") != old.configuration.code_commit_hash
        or capsule.get("configuration_hash") != old.configuration.content_hash
        or capsule.get("lockfile_hash") != old.configuration.lockfile_hash
        or capsule.get("source_inventory_hash") != old.source_inventory_hash
    ):
        raise ValueError("field-study historical capsule or checkout mapping differs")
    original = _inventory(_json(old_root / "source-inventory.json", old.source_inventory_hash))
    successor = _inventory(successor_inventory)
    for workspace, inventory in ((source, original), (Path(config.workspace), successor)):
        tracked = (
            subprocess.check_output(["git", "ls-files", "-z"], cwd=workspace).decode().split("\0")
        )
        if set(inventory) != {name for name in tracked if name}:
            raise ValueError("field-study source inventory is not the complete checkout")
        for name, item in inventory.items():
            path = plain_path(workspace / name)
            if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["bytes_hash"]:
                raise ValueError("field-study reconstructed source inventory differs")
    changes = {
        name: (original.get(name, {}).get("bytes_hash"), successor.get(name, {}).get("bytes_hash"))
        for name in original.keys() | successor.keys()
        if original.get(name, {}).get("bytes_hash") != successor.get(name, {}).get("bytes_hash")
    }
    declared = {
        item.path: (item.original_hash, item.successor_hash) for item in origin.source_changes
    }
    if changes != declared:
        raise ValueError("field-study source difference declaration is incomplete")
    for name in changes:
        documentary = name == "README.md" or name.startswith(("docs/", "tests/"))
        if not documentary and (name not in _WIRING_CHANGES or changes[name][1] is None):
            raise ValueError("field-study adoption changes a scientific implementation dependency")
    return old


def make_source_adoption(
    origin: FieldStudyRecoveryOrigin,
    old: FieldStudyPreparation,
    config: FrozenFieldStudyConfiguration,
    tasks: tuple[FieldStudyTask, FieldStudyTask],
    *,
    preparation_root: Path,
    execution_root: Path,
    inventory_hash: str,
    capsule_hash: str,
) -> FieldStudySourceAdoption:
    return FieldStudySourceAdoption(
        origin=origin,
        original_source_commit=old.configuration.code_commit_hash,
        evaluation_source_commit=config.code_commit_hash,
        lockfile_hash=config.lockfile_hash,
        evaluation_capsule_hash=capsule_hash,
        evaluation_inventory_hash=inventory_hash,
        successor_preparation_root=str(preparation_root),
        successor_execution_root=str(execution_root),
        transfers=cast(
            tuple[FieldStudyOpportunityTransfer, FieldStudyOpportunityTransfer],
            tuple(
                FieldStudyOpportunityTransfer(
                    label=prior.label,
                    opportunity_identity=prior.request.execution_identity,
                    original_request_hash=prior.request.content_hash,
                    successor_request_hash=new.request.content_hash,
                )
                for prior, new in zip(old.tasks, tasks, strict=True)
            ),
        ),
    )


def verify_source_adoption(
    adoption: FieldStudySourceAdoption,
    config: FrozenFieldStudyConfiguration,
    tasks: tuple[FieldStudyTask, FieldStudyTask],
    *,
    successor_inventory: dict[str, Any] | None = None,
) -> FieldStudyPreparation:
    inventory = successor_inventory or _json(
        Path(adoption.successor_preparation_root) / "source-inventory.json",
        adoption.evaluation_inventory_hash,
    )
    if sha256_bytes(canonical_json_bytes(inventory)) != adoption.evaluation_inventory_hash:
        raise ValueError("field-study successor inventory hash differs")
    capsule = {
        "schema_version": "frozen-field-study-source-capsule/v1",
        "workspace": config.workspace,
        "actual_commit": config.code_commit_hash,
        "lockfile_hash": config.lockfile_hash,
        "source_inventory_hash": adoption.evaluation_inventory_hash,
        "configuration_hash": config.content_hash,
        "execution_profile": config.execution_profile,
    }
    if sha256_bytes(canonical_json_bytes(capsule)) != adoption.evaluation_capsule_hash:
        raise ValueError("field-study successor capsule differs")
    old = verify_origin_sources(adoption.origin, config, inventory)
    expected = make_source_adoption(
        adoption.origin,
        old,
        config,
        tasks,
        preparation_root=Path(adoption.successor_preparation_root),
        execution_root=Path(adoption.successor_execution_root),
        inventory_hash=adoption.evaluation_inventory_hash,
        capsule_hash=adoption.evaluation_capsule_hash,
    )
    if adoption != expected or any(t.compute_units != 18 for t in (*old.tasks, *tasks)):
        raise ValueError("field-study adoption request or budget continuity differs")
    roots = [
        plain_path(adoption.successor_preparation_root),
        plain_path(adoption.successor_execution_root),
    ]
    from quantos.application.field_study import (
        _distinct_roots,  # pyright: ignore[reportPrivateUsage]
    )

    _distinct_roots(
        [*roots, Path(config.workspace), Path(config.snapshot_path), Path(config.qlib_view_path)]
    )
    for root in roots:
        for previous in [Path(old.preparation_root), Path(old.execution_root)]:
            if root == previous or root in previous.parents or previous in root.parents:
                raise ValueError("field-study successor output overlaps predecessor")
    labels = {item.label for item in adoption.origin.baselines}
    for task in old.tasks:
        root = Path(old.execution_root) / task.label
        if (root / "outcome.json").exists() or list(
            (root / "execution-records/identities").glob("*.json")
        ):
            raise ValueError("field-study recovery cannot replace a terminal opportunity")
        if root.exists() and task.label not in labels:
            raise ValueError("field-study recovery omits an occupied original opportunity")
    for item in adoption.origin.baselines:
        verify_baseline_origin(old, item)
    return old


def _checkpoint(
    reference: PredictionFileSource,
    request: AutonomousExecutionRequest,
    stage: str,
    outputs: dict[str, str],
    root: Path,
) -> dict[str, Any]:
    from quantos.application.autonomous_execution import DiscoveryExecutionStageCheckpoint

    raw = read_origin(reference)
    record = DiscoveryExecutionStageCheckpoint.model_validate_json(raw)
    expected_root = root / "execution-checkpoints" / request.execution_identity / stage
    if (
        raw != record.canonical_bytes()
        or Path(reference.path) != expected_root / f"sha256-{record.inputs_hash}.json"
        or record.request_hash != request.content_hash
        or record.stage != stage
        or record.outputs != outputs
    ):
        raise ValueError("field-study checkpoint differs from the original request/stage")
    attempt = expected_root / record.inputs_hash / "attempts" / f"{record.attempt_ordinal:08d}"
    reservation = _json(attempt / "reservation.json", record.reservation_hash)
    completion = _json(attempt / "completion.json")
    if (
        reservation.get("request_hash") != request.content_hash
        or reservation.get("stage") != stage
        or reservation.get("inputs_hash") != record.inputs_hash
        or completion.get("status") != "SUCCEEDED"
        or completion.get("checkpoint_hash") != record.content_hash
        or completion.get("inputs_hash") != record.inputs_hash
        or sha256_bytes(
            canonical_json_bytes(
                {
                    "request_hash": request.content_hash,
                    "runtime_fingerprint_hash": reservation.get("runtime_fingerprint_hash"),
                    "stage": stage,
                    "inputs": reservation.get("inputs"),
                    "recovery_policy": "discovery-stage-original-verification/v1",
                }
            )
        )
        != record.inputs_hash
    ):
        raise ValueError("field-study checkpoint has no successful original completion")
    return reservation


def verify_baseline_origin(old: FieldStudyPreparation, origin: FieldStudyBaselineOrigin) -> None:
    from quantos.application.autonomous_execution import (
        AutonomousExecutionTrialIndex,
        QuantosResearchExecutionAdapter,
    )

    task = next(t for t in old.tasks if t.label == origin.label)
    root = Path(old.execution_root) / origin.label
    index = AutonomousExecutionTrialIndex.model_validate(
        _json(
            root
            / "trial-identities"
            / f"{task.request.campaign_hash}-{task.request.trial_ordinal:08d}.json"
        )
    )
    if index != AutonomousExecutionTrialIndex(
        campaign_hash=task.request.campaign_hash,
        trial_ordinal=task.request.trial_ordinal,
        execution_identity=task.request.execution_identity,
        request_hash=task.request.content_hash,
    ):
        raise ValueError("field-study original opportunity index differs")
    expected_request = root / "execution-requests" / f"{task.request.execution_identity}.json"
    if (
        plain_path(origin.request.path) != expected_request
        or read_origin(origin.request) != task.request.canonical_bytes()
    ):
        raise ValueError("field-study original request was substituted")
    pit = _checkpoint(
        origin.pit_checkpoint,
        task.request,
        "baseline-pit",
        {"pit_evidence_hash": origin.pit.sha256},
        root,
    )
    signal = _checkpoint(
        origin.signal_checkpoint,
        task.request,
        "baseline-signal",
        {"signal_hash": origin.signal_hash},
        root,
    )
    baseline = _checkpoint(
        origin.backtest_checkpoint,
        task.request,
        "baseline",
        {"backtest_hash": origin.backtest_hash},
        root,
    )
    if pit["inputs"] != signal["inputs"]:
        raise ValueError("field-study PIT/signal producer inputs differ")
    signal_root = (
        root
        / "executions"
        / task.request.execution_identity
        / "baseline/signals"
        / f"sha256-{origin.signal_hash}"
    )
    backtest_root = (
        root
        / "executions"
        / task.request.execution_identity
        / "baseline/backtests"
        / f"sha256-{origin.backtest_hash}"
    )
    if (
        plain_path(origin.signal_path) != signal_root
        or plain_path(origin.backtest_path) != backtest_root
    ):
        raise ValueError("field-study originals escaped their original execution")
    manifest = verify_signal_artifact(signal_root)
    backtest = verify_backtest_artifact(backtest_root)
    resolved = ResolvedExperimentSpec.model_validate_json(
        (signal_root / "resolved-experiment.json").read_bytes()
    )
    pit_raw = read_origin(origin.pit, limit=512 << 20)
    if (
        manifest.artifact_hash != origin.signal_hash
        or backtest.result_hash != origin.backtest_hash
        or manifest.resolved_experiment_hash != resolved.content_hash
        or backtest.resolved_experiment_hash != resolved.content_hash
        or backtest.signal_artifact_hash != manifest.artifact_hash
        or resolved.code_commit_hash != old.configuration.code_commit_hash
        or resolved.lockfile_hash != old.configuration.lockfile_hash
        or plain_path(origin.pit.path) != signal_root / "pit-evidence.json"
        or manifest.pit_evidence_hash != origin.pit.sha256
        or resolved.pit_audit_evidence_hash != origin.pit.sha256
        or baseline["inputs"].get("resolved_hash") != resolved.content_hash
        or baseline["inputs"].get("signal_hash") != manifest.artifact_hash
    ):
        raise ValueError("field-study original artifact bindings differ")
    authoring = QuantosResearchExecutionAdapter._authoring(  # pyright: ignore[reportPrivateUsage]
        cast(
            Any,
            SimpleNamespace(
                base_authoring=old.configuration.volume
                if origin.label == "V"
                else old.configuration.price
            ),
        ),
        task.request,
    )
    if authoring.content_hash != resolved.authoring_spec_hash:
        raise ValueError("field-study original authoring differs")
    for name in (
        "snapshot_hash",
        "qlib_view_hash",
        "research_policy_hash",
        "validation_policy_hash",
        "cost_policy_hash",
        "backtest_policy_hash",
        "lockfile_hash",
        "qlib_version",
    ):
        if getattr(resolved, name) != getattr(task.request, name):
            raise ValueError("field-study original scientific binding differs")
    from quantos.application.data_qualified_release import (
        _operator_delays as research_operator_delays,  # pyright: ignore[reportPrivateUsage]
    )
    from quantos.application.data_qualified_release import (
        _schedule_hash as research_schedule_hash,  # pyright: ignore[reportPrivateUsage]
    )
    from quantos.contracts.research_execution import PITCrossSectionEvidenceCollectionV3

    evidence = PITCrossSectionEvidenceCollectionV3.model_validate_json(pit_raw)
    if (
        evidence.content_hash != origin.pit.sha256
        or evidence.expression != task.request.candidate.expression
        or evidence.snapshot_hash != task.request.snapshot_hash
        or evidence.qlib_view_hash != task.request.qlib_view_hash
        or evidence.operator_delays != research_operator_delays(authoring)
        or evidence.universe_index != resolved.strategy.universe_index
        or pit["inputs"].get("schedule_hash")
        != research_schedule_hash(tuple(b.schedule for b in evidence.bundles))
        or pit["inputs"].get("provisional_resolved_hash")
        != resolved.model_copy(update={"pit_audit_evidence_hash": "0" * 64}).content_hash
    ):
        raise ValueError("field-study PIT producer proof differs from its scientific inputs")
    workflow_root = root / "execution-checkpoints" / task.request.execution_identity / "workflow"
    failed = plain_path(origin.workflow_failure.path)
    if (
        not failed.is_relative_to(workflow_root)
        or failed.name != "completion.json"
        or list(workflow_root.glob("sha256-*.json"))
    ):
        raise ValueError("field-study Workflow is not an unfinished original stage")
    failure = _json(failed, origin.workflow_failure.sha256)
    reservation = _json(failed.with_name("reservation.json"))
    if (
        failure.get("status") != "FAILED"
        or reservation.get("request_hash") != task.request.content_hash
        or reservation.get("stage") != "workflow"
        or failure.get("inputs_hash") != reservation.get("inputs_hash")
    ):
        raise ValueError("field-study Workflow failure is not request-bound")
    exit_path = plain_path(origin.guard_exit.path)
    control = Path(old.execution_root).parent / "storage-control"
    exit_record = _json(exit_path, origin.guard_exit.sha256)
    owner = _json(control / "lease.lock")
    prelaunch = _json(exit_path.with_name("prelaunch.json"))
    policy_path = exit_path.with_name("policy.json")
    matched_intents = [
        item
        for path in (root / "management/attempts").glob("*/intent.json")
        if (item := _json(path)).get("request_hash") == task.request.content_hash
        and item.get("lease_prelaunch_hash") == sha256_file(exit_path.with_name("prelaunch.json"))
    ]
    if (
        exit_path.parent.parent != control
        or exit_path.name != "exit.json"
        or owner.get("run") != str(exit_path.parent)
        or exit_record.get("cleanup_verified") is not True
        or exit_record.get("waitpid_observed") is not True
        or exit_record.get("namespace_exit_observed") is not True
        or exit_record.get("return_code") in (None, 0)
        or owner.get("policy_hash") != exit_record.get("policy_hash")
        or prelaunch.get("policy_hash") != exit_record.get("policy_hash")
        or sha256_file(policy_path) != exit_record.get("policy_hash")
        or prelaunch.get("stage") != "deployment"
        or len(matched_intents) != 1
        or matched_intents[0].get("max_compute_units") != task.compute_units
        or matched_intents[0].get("expected_new_bytes") != 8589934592
        or matched_intents[0].get("storage_policy_hash") != exit_record.get("policy_hash")
        or prelaunch.get("expected_new_bytes") != 8589934592
    ):
        raise ValueError("field-study failed parent's actual wait/cleanup is unavailable")


def continuity_root(config: FrozenFieldStudyConfiguration) -> Path:
    # Fixed canonical data locator, shared by predecessor/successor and independent
    # of configurable output directories. No writes in predecessor evidence roots.
    return plain_path(Path(config.snapshot_path).parents[2] / "field-study-continuity")


@contextmanager
def opportunity_lease(
    config: FrozenFieldStudyConfiguration,
    request: AutonomousExecutionRequest,
    adoption: FieldStudySourceAdoption | None,
) -> Generator[None, None, None]:
    identity = request.execution_identity
    if adoption is not None:
        transfer = next(
            (t for t in adoption.transfers if t.successor_request_hash == request.content_hash),
            None,
        )
        if transfer is None:
            raise ValueError("field-study request has no opportunity transfer")
        identity = transfer.opportunity_identity
    with exclusive_directory_lock(continuity_root(config) / "leases" / identity):
        yield


def _state(
    config: FrozenFieldStudyConfiguration,
    request: AutonomousExecutionRequest,
    output_root: Path,
    adoption: FieldStudySourceAdoption | None,
) -> FieldStudyOpportunityState:
    identity, original_hash = request.execution_identity, request.content_hash
    if adoption is not None:
        transfer = next(
            (t for t in adoption.transfers if t.successor_request_hash == request.content_hash),
            None,
        )
        if transfer is None:
            raise ValueError("field-study request has no opportunity transfer")
        identity, original_hash = transfer.opportunity_identity, transfer.original_request_hash
    return FieldStudyOpportunityState(
        opportunity_identity=identity,
        original_request_hash=original_hash,
        active_request_hash=request.content_hash,
        active_configuration_hash=config.content_hash,
        active_execution_root=str(plain_path(output_root)),
        source_adoption_record_hash=adoption.content_hash if adoption else None,
    )


def check_opportunity(
    config: FrozenFieldStudyConfiguration,
    request: AutonomousExecutionRequest,
    output_root: Path,
    adoption: FieldStudySourceAdoption | None,
    *,
    claim: bool = False,
) -> None:
    expected = _state(config, request, output_root, adoption)
    root = continuity_root(config)

    def check() -> None:
        path = root / f"{expected.opportunity_identity}.supersession.json"
        if adoption is not None:
            # A partial registration cannot launch either successor opportunity.
            for transfer in adoption.transfers:
                state = FieldStudyOpportunityState(
                    opportunity_identity=transfer.opportunity_identity,
                    original_request_hash=transfer.original_request_hash,
                    active_request_hash=transfer.successor_request_hash,
                    active_configuration_hash=config.content_hash,
                    active_execution_root=str(
                        Path(adoption.successor_execution_root) / transfer.label
                    ),
                    source_adoption_record_hash=adoption.content_hash,
                )
                saved = root / f"{state.opportunity_identity}.supersession.json"
                if (
                    not saved.exists()
                    or FieldStudyOpportunityState.model_validate(_json(saved)) != state
                ):
                    raise ValueError(
                        "field-study successor requires complete supersession activation"
                    )
        if not path.exists():
            path = root / f"{expected.opportunity_identity}.json"
        if path.exists():
            raw = _json(path)
            if FieldStudyOpportunityState.model_validate(raw) != expected:
                raise ValueError(
                    "field-study opportunity is superseded or already claimed elsewhere"
                )
        elif claim:
            atomic_write_bytes(path, expected.canonical_bytes())

    if claim:
        with exclusive_directory_lock(root):
            check()
    else:
        check()


def activate_supersession(preparation: PreparedFieldStudy) -> None:
    if not isinstance(preparation, FieldStudyRecoveryPreparation):
        raise ValueError("only explicit field-study recovery may supersede opportunities")
    adoption = preparation.source_adoption
    root = continuity_root(preparation.configuration)
    states = tuple(
        _state(
            preparation.configuration,
            task.request,
            Path(preparation.execution_root) / task.label,
            adoption,
        )
        for task in preparation.tasks
    )
    global_path = root.parent / "hosted-evidence/storage-control/lease.lock"
    with plain_path(global_path).open("rb") as global_lock, ExitStack() as locks:
        fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for task in preparation.tasks:
            locks.enter_context(
                opportunity_lease(preparation.configuration, task.request, adoption)
            )
        locks.enter_context(exclusive_directory_lock(root))
        old = verify_source_adoption(adoption, preparation.configuration, preparation.tasks)
        # Preflight both before any write; partial crash is idempotently resumable.
        for state in states:
            supersession = root / f"{state.opportunity_identity}.supersession.json"
            if (
                supersession.exists()
                and FieldStudyOpportunityState.model_validate(_json(supersession)) != state
            ):
                raise ValueError("field-study opportunity has a different successor")
            path = root / f"{state.opportunity_identity}.json"
            task = next(
                t for t in old.tasks if t.request.execution_identity == state.opportunity_identity
            )
            initial = _state(
                old.configuration, task.request, Path(old.execution_root) / task.label, None
            )
            if path.exists() and FieldStudyOpportunityState.model_validate(_json(path)) != initial:
                raise ValueError("field-study opportunity has a different successor")
        for state in states:
            # Append-only supersession, never overwrite the original claim.
            path = root / f"{state.opportunity_identity}.supersession.json"
            atomic_write_bytes(path, state.canonical_bytes())


def verify_native_receipts(
    adoption: FieldStudySourceAdoption,
    request: AutonomousExecutionRequest,
    output_root: Path,
    *,
    require_complete: bool = False,
) -> tuple[str, ...]:
    """Same native receipt/binding predicates for adapter recovery and prediction reader."""
    from quantos.contracts.native_adoption import NativeArtifactAdoptionReceipt

    label = output_root.name
    transfer = next((t for t in adoption.transfers if t.label == label), None)
    if (
        transfer is None
        or transfer.successor_request_hash != request.content_hash
        or (
            plain_path(output_root) != Path(adoption.successor_execution_root) / label
            or request.code_commit_hash != adoption.evaluation_source_commit
            or request.lockfile_hash != adoption.lockfile_hash
        )
    ):
        raise ValueError("field-study native receipt is outside its successor request")
    origins = tuple(item for item in adoption.origin.baselines if item.label == label)
    paths = tuple(sorted((output_root / "native-adoptions").glob("sha256-*.json")))
    if not origins:
        if paths:
            raise ValueError("field-study unadopted opportunity has native receipts")
        return ()
    origin = origins[0]
    old_resolved = ResolvedExperimentSpec.model_validate_json(
        (plain_path(origin.signal_path) / "resolved-experiment.json").read_bytes()
    )
    baseline = output_root / "executions" / request.execution_identity / "baseline"
    signals = tuple((baseline / "signals").glob("sha256-*/resolved-experiment.json"))
    if len(signals) > 1:
        raise ValueError("field-study adopted signal is ambiguous")
    new_resolved = (
        ResolvedExperimentSpec.model_validate_json(signals[0].read_bytes()) if signals else None
    )
    if new_resolved is not None:
        verify_adoption_bindings(old_resolved, new_resolved)
        if (
            old_resolved.code_commit_hash != adoption.original_source_commit
            or any(
                getattr(new_resolved, name) != getattr(request, name)
                for name in (
                    "code_commit_hash",
                    "lockfile_hash",
                    "snapshot_hash",
                    "qlib_view_hash",
                    "research_policy_hash",
                    "validation_policy_hash",
                    "cost_policy_hash",
                    "backtest_policy_hash",
                    "qlib_version",
                )
            )
            or new_resolved.expression != request.candidate.expression
        ):
            raise ValueError("field-study adopted resolution escaped its successor request")
    verified: dict[str, str] = {}
    for path in paths:
        raw = _json(path)
        receipt = NativeArtifactAdoptionReceipt.model_validate(raw)
        if path.name != f"sha256-{receipt.content_hash}.json" or (
            receipt.source_adoption_record_hash != adoption.content_hash
            or receipt.scientific_origin_commit != adoption.original_source_commit
            or receipt.adoption_commit != request.code_commit_hash
            or receipt.lockfile_hash != request.lockfile_hash
            or new_resolved is None
            or receipt.original_resolved_hash != old_resolved.content_hash
            or receipt.adopted_resolved_hash != new_resolved.content_hash
            or receipt.artifact_kind in verified
        ):
            raise ValueError("field-study native receipt origin or identity differs")
        signal = receipt.artifact_kind == "FACTOR_SIGNAL"
        old_root = Path(origin.signal_path if signal else origin.backtest_path)
        new_root = (
            baseline
            / ("signals" if signal else "backtests")
            / f"sha256-{receipt.adopted_artifact_hash}"
        )
        old_manifest = (
            verify_signal_artifact(old_root) if signal else verify_backtest_artifact(old_root)
        )
        new_manifest = (
            verify_signal_artifact(new_root) if signal else verify_backtest_artifact(new_root)
        )
        expected_old_hash = origin.signal_hash if signal else origin.backtest_hash
        actual_old_hash = getattr(old_manifest, "artifact_hash" if signal else "result_hash")
        actual_new_hash = getattr(new_manifest, "artifact_hash" if signal else "result_hash")
        if (
            receipt.original_artifact_hash != expected_old_hash
            or actual_old_hash != expected_old_hash
            or old_manifest.resolved_experiment_hash != old_resolved.content_hash
            or new_manifest.resolved_experiment_hash != new_resolved.content_hash
            or actual_new_hash != receipt.adopted_artifact_hash
        ):
            raise ValueError("field-study native receipt artifact differs")
        if not signal:
            if len(signals) != 1 or not (
                isinstance(old_manifest, BacktestArtifactManifest)
                and isinstance(new_manifest, BacktestArtifactManifest)
            ):
                raise ValueError("field-study adopted backtest lacks its signal or manifest")
            signal_path = next(iter(signals))
            adopted_signal = verify_signal_artifact(signal_path.parent)
            if (
                new_manifest.signal_artifact_hash != adopted_signal.artifact_hash
                or old_manifest.signal_artifact_hash != origin.signal_hash
                or new_manifest.cost_policy_hash != new_resolved.cost_policy_hash
                or new_manifest.backtest_policy_hash != new_resolved.backtest_policy_hash
            ):
                raise ValueError("field-study adopted backtest changes its signal or policies")
        native_files = {
            item.logical_path: (item.sha256, item.size_bytes)
            for item in old_manifest.files
            if (
                item.logical_path == "signals.parquet"
                if signal
                else item.logical_path.endswith(".parquet")
            )
        }
        actual_files = {
            item.logical_path: (item.bytes_hash, item.size_bytes) for item in receipt.native_files
        }
        if actual_files != native_files or len(actual_files) != len(receipt.native_files):
            raise ValueError("field-study receipt native file set differs")
        for name, (digest, size) in native_files.items():
            for root in (old_root, new_root):
                native = plain_path(root / name)
                if native.stat().st_size != size or sha256_file(native) != digest:
                    raise ValueError("field-study adopted native bytes changed")
        verified[receipt.artifact_kind] = receipt.content_hash
    for kind, directory in (("FACTOR_SIGNAL", "signals"), ("QLIB_BACKTEST", "backtests")):
        artifacts = tuple((baseline / directory).glob("sha256-*/manifest.json"))
        if len(artifacts) > 1 or ((require_complete or artifacts) and kind not in verified):
            raise ValueError("field-study adopted stage lacks its unique native receipt")
    return tuple(sorted(verified.values()))


def prediction_source_adoption(
    source: PredictionImportSource,
    config: FrozenFieldStudyConfiguration,
    request: AutonomousExecutionRequest,
    evidence_hashes: tuple[str, ...],
) -> FieldStudySourceAdoption | None:
    """Independently bind successor prediction sources to their actual adoption chain."""
    from quantos.application.field_study import load_preparation

    root = plain_path(source.research_policy.path).parent
    path = root / "source-adoption.json"
    if not path.exists():
        return None
    adoption = FieldStudySourceAdoption.model_validate(_json(path))
    prepared_path = root / "preparation.json"
    prepared = load_preparation(prepared_path, sha256_file(prepared_path))
    if (
        not isinstance(prepared, FieldStudyRecoveryPreparation)
        or prepared.configuration != config
        or prepared.source_adoption != adoption
        or Path(prepared.preparation_root) != root
        or prepared.source_capsule_hash != source.source_capsule.sha256
        or prepared.source_inventory_hash != source.source_inventory.sha256
        or plain_path(source.source_capsule.path) != root / "source-capsule.json"
        or plain_path(source.source_inventory.path) != root / "source-inventory.json"
        or plain_path(source.research_policy.path) != root / "configuration.json"
    ):
        raise ValueError("field-study prediction origin inventory differs")
    verify_source_adoption(adoption, config, prepared.tasks)
    task = next((t for t in prepared.tasks if t.request == request), None)
    if task is None:
        raise ValueError("field-study prediction has no successor request")
    output_root = Path(prepared.execution_root) / task.label
    check_opportunity(config, request, output_root, adoption)
    hashes = verify_native_receipts(adoption, request, output_root, require_complete=True)
    if not set(hashes) <= set(evidence_hashes):
        raise ValueError("field-study outcome lost its adoption receipts")
    return adoption
