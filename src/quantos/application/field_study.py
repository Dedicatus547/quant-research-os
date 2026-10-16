"""Offline preparation and explicit execution of the fixed V/P study."""

from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast

from quantos.application.autonomous_execution import (
    QuantosResearchExecutionAdapter,
    VerifiedExecutionInputs,
    build_autonomous_execution_bindings,
    quote_autonomous_workload,
    require_durable_execution_root,
)
from quantos.application.enumeration import enumerate_research_family
from quantos.application.field_study_recovery import (
    activate_supersession,
    check_opportunity,
    make_source_adoption,
    predecessor,
    verify_source_adoption,
)
from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import (
    ArtifactConflictError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
)
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import AutonomousExecutionRequest, autonomous_execution_identity
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import ParameterDimension, ResearchFamilySpec
from quantos.contracts.discovery_prediction import (
    PredictionEvaluationProfile,
    PredictionImportSource,
)
from quantos.contracts.enumeration import (
    ResearchFactorTemplateNode,
    ResearchFactorTemplateSpec,
    ResearchTemplateParameterSlot,
)
from quantos.contracts.field_study import (
    FIELD_STUDY_QUESTION,
    FieldStudyBudget,
    FieldStudyExecutionScope,
    FieldStudyPreparation,
    FieldStudyRecoveryOrigin,
    FieldStudyRecoveryPreparation,
    FieldStudyRetainedReaderBinding,
    FieldStudyTask,
    FrozenFieldStudyConfiguration,
    PreparedFieldStudy,
)
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.research import ResolvedExperimentSpec
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.infrastructure.hosted_storage import LEASE_ENV, configured_guard
from quantos.research.qlib.model_split import effective_model_segments


def read_pinned(path: Path, expected_hash: str) -> bytes:
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("pinned input must not contain symlinks")
    with opened_directory(path.parent) as parent:
        raw = read_regular_bytes_at(parent, path.name, max_bytes=16 << 20)
    if sha256_bytes(raw) != expected_hash:
        raise ValueError("pinned file hash mismatch")
    return raw


def load_configuration(path: Path, expected_hash: str) -> FrozenFieldStudyConfiguration:
    raw = read_pinned(path, expected_hash)
    config = FrozenFieldStudyConfiguration.model_validate_json(raw)
    if raw != config.canonical_bytes():
        raise ValueError("configuration must have canonical bytes")
    return config


def load_recovery_origin(path: Path, expected_hash: str) -> FieldStudyRecoveryOrigin:
    raw = read_pinned(path, expected_hash)
    origin = FieldStudyRecoveryOrigin.model_validate_json(raw)
    if raw != origin.canonical_bytes():
        raise ValueError("recovery origin must have canonical bytes")
    return origin


def supersede(preparation: PreparedFieldStudy) -> None:
    """Explicit management operation, separate from prepare/status and science."""
    _validate(preparation)
    activate_supersession(preparation)


def _write_once(path: Path, raw: bytes) -> None:
    if path.exists():
        if read_pinned(path, sha256_bytes(raw)) != raw:
            raise ArtifactConflictError("frozen field-study output conflict")
    else:
        atomic_write_bytes(path, raw)


def build_task(
    config: FrozenFieldStudyConfiguration,
    label: Literal["V", "P"],
    snapshot: DataSnapshotManifest,
    view: QlibViewManifest,
    *,
    origin: FieldStudyRecoveryOrigin | None = None,
) -> FieldStudyTask:
    authoring = config.volume if label == "V" else config.price
    expression = cast(SafeQlibExpressionSpec, authoring.expression)
    window = next(n for n in expression.nodes if n.window is not None)
    template = ResearchFactorTemplateSpec(
        template_id=f"{config.study_id}-{label.lower()}",
        expression_schema_version=expression.schema_version,
        nodes=tuple(
            ResearchFactorTemplateNode(
                node_id=n.node_id,
                operator=n.operator,
                inputs=n.inputs,
                field_name=n.field_name,
                window=None if n == window else n.window,
            )
            for n in expression.nodes
        ),
        output_node_id=expression.output_node_id,
        input_lag_trading_days=0,
        parameter_slots=(
            ResearchTemplateParameterSlot(name="window", node_id=window.node_id, field="window"),
        ),
    )
    family = ResearchFamilySpec(
        family_id=f"{config.study_id}-{label.lower()}",
        research_question=FIELD_STUDY_QUESTION,
        hypothesis_hash=config.content_hash,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted({n.operator for n in expression.nodes}, key=str)),
        parameter_space=(ParameterDimension(name="window", values=(5,)),),
        declared_candidate_count=1,
    )
    manifest = enumerate_research_family(family, template)
    charge = quote_autonomous_workload(
        authoring, config.validation_policy, window_node_id=window.node_id
    )
    budget = FieldStudyBudget(max_compute_units=charge)
    scope = FieldStudyExecutionScope(
        campaign_id=f"{config.study_id}-{label.lower()}",
        configuration_hash=config.content_hash,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        snapshot_hash=config.snapshot_hash,
        qlib_view_hash=config.qlib_view_hash,
        development=config.research_policy.validation,
        validation=config.research_policy.test,
    )
    bindings = build_autonomous_execution_bindings(
        snapshot=snapshot,
        qlib_view=view,
        authoring=authoring,
        research_policy=config.research_policy,
        validation_policy=config.validation_policy,
        cost_policy=config.cost_policy,
        backtest_policy=config.backtest_policy,
        code_commit_hash=config.code_commit_hash,
        lockfile_hash=config.lockfile_hash,
        field_study=config,
        field_study_origin=origin,
    )
    candidate = manifest.candidates[0]
    identity = autonomous_execution_identity(
        campaign_hash=scope.content_hash,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        candidate_manifest_hash=manifest.content_hash,
        candidate=candidate,
        snapshot_hash=config.snapshot_hash,
        qlib_view_hash=config.qlib_view_hash,
        segment=CampaignSegment.VALIDATION,
        segment_start=config.research_policy.test.start,
        segment_end=config.research_policy.test.end,
        trial_ordinal=1,
        bindings=bindings,
    )
    request = AutonomousExecutionRequest(
        **bindings.model_dump(exclude={"schema_version"}),
        idempotency_key=identity,
        execution_identity=identity,
        trial_ordinal=1,
        campaign_hash=scope.content_hash,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        candidate_manifest_hash=manifest.content_hash,
        candidate=candidate,
        candidate_exact_expression_hash=candidate.exact_expression_hash,
        candidate_structural_expression_hash=candidate.structural_expression_hash,
        snapshot_hash=config.snapshot_hash,
        qlib_view_hash=config.qlib_view_hash,
        segment=CampaignSegment.VALIDATION,
        segment_start=config.research_policy.test.start,
        segment_end=config.research_policy.test.end,
        # The legacy port requires this hash field. It explicitly binds fixed-design
        # input, not an AgentRun; no Agent manifest or generation response is created.
        agent_run_hash=config.input_reference(label),
        remaining_executions=1,
        remaining_validation_rounds=1,
        remaining_compute_seconds=charge,
    )
    return FieldStudyTask(
        label=label,
        family=family,
        template=template,
        manifest=manifest,
        budget=budget,
        campaign=scope,
        bindings=bindings,
        request=request,
        compute_units=charge,
    )


@dataclass(frozen=True)
class _EvaluationDates:
    evaluation_start: date
    evaluation_end: date


def _segments(config: FrozenFieldStudyConfiguration, calendar: tuple[date, ...]):
    # This reused pure resolver reads evaluation dates only. No fake resolved artifact
    # or provisional PIT evidence is published.
    context = _EvaluationDates(config.research_policy.test.start, config.research_policy.test.end)
    return effective_model_segments(
        config.research_policy, cast(ResolvedExperimentSpec, context), calendar
    )


def _distinct_roots(paths: list[Path]) -> None:
    for path in paths:
        if (
            not path.is_absolute()
            or path != path.resolve()
            or any(p.is_symlink() for p in (path, *path.parents))
        ):
            raise ValueError("authority roots must be explicit canonical paths")
    for i, left in enumerate(paths):
        for right in paths[i + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError("preparation, execution, source and data roots must be disjoint")


def _validate(preparation: PreparedFieldStudy) -> None:
    config = preparation.configuration
    _distinct_roots(
        [
            Path(preparation.preparation_root),
            Path(preparation.execution_root),
            Path(config.workspace),
            Path(config.snapshot_path),
            Path(config.qlib_view_path),
        ]
    )
    adoption = (
        preparation.source_adoption
        if isinstance(preparation, FieldStudyRecoveryPreparation)
        else None
    )
    if preparation.tasks != tuple(
        build_task(
            config,
            label,
            preparation.snapshot,
            preparation.view,
            origin=adoption.origin if adoption else None,
        )
        for label in ("V", "P")
    ):
        raise ValueError("prepared task identity or budget mismatch")
    dates = tuple(
        d
        for d in preparation.full_calendar
        if config.research_policy.test.start <= d <= config.research_policy.test.end
    )
    profile = preparation.prediction_profile
    if (
        profile.execution_request_hashes
        != tuple(sorted(t.request.content_hash for t in preparation.tasks))
        or profile.expected_dates != dates
        or profile.min_defined_fraction != 0.9
        or profile.min_common_days != math.ceil(0.9 * len(dates))
        or preparation.effective_segments != _segments(config, preparation.full_calendar)
        or any(
            getattr(profile, key) != getattr(config, key)
            for key in ("snapshot_hash", "qlib_view_hash", "code_commit_hash", "lockfile_hash")
        )
        or profile.research_policy_hash != config.research_policy.content_hash
        or profile.qlib_version != preparation.view.qlib_version
    ):
        raise ValueError("prepared comparison policy mismatch")
    horizon = config.research_policy.label_horizon_trading_sessions
    usable = [
        d
        for i, d in enumerate(preparation.full_calendar)
        if d in dates and i + horizon < len(preparation.full_calendar)
    ]
    if not usable or preparation.last_computable_label_date != usable[-1]:
        raise ValueError("prepared label cutoff mismatch")
    if adoption is not None and (
        adoption.successor_preparation_root != preparation.preparation_root
        or adoption.successor_execution_root != preparation.execution_root
        or adoption.evaluation_capsule_hash != preparation.source_capsule_hash
        or adoption.evaluation_inventory_hash != preparation.source_inventory_hash
    ):
        raise ValueError("prepared origin declaration differs from its successor inventory")


def load_preparation(path: Path, expected_hash: str) -> PreparedFieldStudy:
    raw = read_pinned(path, expected_hash)
    schema = json.loads(raw).get("schema_version")
    model = (
        FieldStudyRecoveryPreparation
        if schema == "frozen-field-study-preparation/v2"
        else FieldStudyPreparation
    )
    preparation = model.model_validate_json(raw)
    if raw != preparation.canonical_bytes():
        raise ValueError("preparation is not canonical")
    _validate(preparation)
    return preparation


def prepare(
    config: FrozenFieldStudyConfiguration,
    output_root: Path,
    execution_root: Path,
    *,
    origin: FieldStudyRecoveryOrigin | None = None,
) -> PreparedFieldStudy:
    from quantos.application.discovery_prediction import prediction_verifier_identity

    require_durable_execution_root(output_root)
    require_durable_execution_root(execution_root)
    paths = [
        output_root.absolute(),
        execution_root.absolute(),
        Path(config.workspace).absolute(),
        Path(config.snapshot_path).absolute(),
        Path(config.qlib_view_path).absolute(),
    ]
    _distinct_roots(paths)
    verify_code_provenance(
        Path(config.workspace),
        expected_commit_hash=config.code_commit_hash,
        expected_lockfile_hash=config.lockfile_hash,
    )
    inputs = VerifiedExecutionInputs(Path(config.snapshot_path), Path(config.qlib_view_path))
    if (
        inputs.snapshot.snapshot_hash != config.snapshot_hash
        or inputs.view.view_hash != config.qlib_view_hash
        or inputs.view.source_snapshot_hash != config.snapshot_hash
    ):
        raise ValueError("configured data identity differs")
    calendar = tuple(
        date.fromisoformat(s.strip())
        for s in (Path(config.qlib_view_path) / "calendars/day.txt").read_text().splitlines()
        if s.strip()
    )
    segments = _segments(config, calendar)
    dates = tuple(
        d
        for d in calendar
        if config.research_policy.test.start <= d <= config.research_policy.test.end
    )
    tasks = (
        build_task(config, "V", inputs.snapshot, inputs.view, origin=origin),
        build_task(config, "P", inputs.snapshot, inputs.view, origin=origin),
    )
    profile = PredictionEvaluationProfile(
        verifier_identity_hash=sha256_bytes(canonical_json_bytes(prediction_verifier_identity())),
        execution_request_hashes=tuple(sorted(t.request.content_hash for t in tasks)),
        expected_dates=dates,
        snapshot_hash=config.snapshot_hash,
        qlib_view_hash=config.qlib_view_hash,
        research_policy_hash=config.research_policy.content_hash,
        code_commit_hash=config.code_commit_hash,
        lockfile_hash=config.lockfile_hash,
        qlib_version=inputs.view.qlib_version,
        min_defined_fraction=0.9,
        min_common_days=math.ceil(0.9 * len(dates)),
    )
    names = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=config.workspace)
        .decode()
        .split("\0")
    )
    inventory = {
        "schema_version": "frozen-field-study-source-inventory/v1",
        "files": [
            {
                "path": n,
                "bytes_hash": sha256_file(Path(config.workspace) / n),
                "size_bytes": (Path(config.workspace) / n).stat().st_size,
            }
            for n in sorted(names)
            if n
        ],
    }
    inventory_raw = canonical_json_bytes(inventory)
    capsule_raw = canonical_json_bytes(
        {
            "schema_version": "frozen-field-study-source-capsule/v1",
            "workspace": config.workspace,
            "actual_commit": config.code_commit_hash,
            "lockfile_hash": config.lockfile_hash,
            "source_inventory_hash": sha256_bytes(inventory_raw),
            "configuration_hash": config.content_hash,
            "execution_profile": config.execution_profile,
        }
    )
    usable = [
        d
        for i, d in enumerate(calendar)
        if d in dates and i + config.research_policy.label_horizon_trading_sessions < len(calendar)
    ]
    if not usable:
        raise ValueError("calendar has no computable test labels")
    extra: dict[str, object] = {}
    if origin is not None:
        adoption = make_source_adoption(
            origin,
            predecessor(origin),
            config,
            tasks,
            preparation_root=output_root.absolute(),
            execution_root=execution_root.absolute(),
            inventory_hash=sha256_bytes(inventory_raw),
            capsule_hash=sha256_bytes(capsule_raw),
        )
        verify_source_adoption(adoption, config, tasks, successor_inventory=inventory)
        extra["source_adoption"] = adoption
    preparation_type = (
        FieldStudyRecoveryPreparation if origin is not None else FieldStudyPreparation
    )
    preparation = preparation_type.model_validate(
        dict(
            schema_version="frozen-field-study-preparation/v2"
            if origin
            else "frozen-field-study-preparation/v1",
            configuration=config,
            snapshot=inputs.snapshot,
            view=inputs.view,
            tasks=tasks,
            prediction_profile=profile,
            execution_root=str(execution_root.absolute()),
            preparation_root=str(output_root.absolute()),
            full_calendar=calendar,
            effective_segments=segments,
            last_computable_label_date=usable[-1],
            source_inventory_hash=sha256_bytes(inventory_raw),
            source_capsule_hash=sha256_bytes(capsule_raw),
            **extra,
        )
    )
    _validate(preparation)
    verify_code_provenance(
        Path(config.workspace),
        expected_commit_hash=config.code_commit_hash,
        expected_lockfile_hash=config.lockfile_hash,
    )
    with exclusive_directory_lock(output_root):
        for name, raw in (
            ("configuration.json", config.canonical_bytes()),
            ("source-inventory.json", inventory_raw),
            ("source-capsule.json", capsule_raw),
            ("preparation.json", preparation.canonical_bytes()),
        ):
            _write_once(output_root / name, raw)
        for task in tasks:
            _write_once(output_root / task.label / "request.json", task.request.canonical_bytes())
        if isinstance(preparation, FieldStudyRecoveryPreparation):
            _write_once(
                output_root / "source-adoption.json", preparation.source_adoption.canonical_bytes()
            )
    return preparation


def status(preparation: PreparedFieldStudy) -> dict[str, object]:
    _validate(preparation)
    rows: list[dict[str, object]] = []
    for task in preparation.tasks:
        root = Path(preparation.execution_root) / task.label
        receipt = root / "execution-records/identities" / f"{task.request.execution_identity}.json"
        rows.append(
            {
                "label": task.label,
                "request_hash": task.request.content_hash,
                "receipt_present": receipt.is_file(),
                "compute_units": task.compute_units,
                "state": "RECEIPT_PRESENT_UNVERIFIED" if receipt.is_file() else "NOT_COMPLETED",
            }
        )
    return {
        "preparation_hash": preparation.content_hash,
        "tasks": rows,
        "scientific_verification": "NOT_PERFORMED_BY_STATUS",
    }


def run(
    preparation: PreparedFieldStudy,
    label: Literal["V", "P"],
    *,
    request_hash: str,
    max_compute_units: int,
    expected_new_bytes: int,
    resume: bool = False,
):
    _validate(preparation)
    task = next(t for t in preparation.tasks if t.label == label)
    if request_hash != task.request.content_hash or max_compute_units < task.compute_units:
        raise ValueError("explicit request or compute allowance differs")
    if expected_new_bytes <= 0:
        raise ValueError("complete job growth must be explicit and positive")
    config = preparation.configuration
    root = Path(preparation.execution_root) / label
    adoption = (
        preparation.source_adoption
        if isinstance(preparation, FieldStudyRecoveryPreparation)
        else None
    )
    if adoption is not None:
        verify_source_adoption(adoption, config, preparation.tasks)
    check_opportunity(config, task.request, root, adoption)
    read_pinned(
        Path(preparation.preparation_root) / "source-capsule.json", preparation.source_capsule_hash
    )
    read_pinned(
        Path(preparation.preparation_root) / "source-inventory.json",
        preparation.source_inventory_hash,
    )
    require_durable_execution_root(root)
    guard = configured_guard()
    guard.require_root(root)
    guard.require_lease()
    with opened_directory(Path(os.environ[LEASE_ENV])) as parent:
        lease_raw = read_regular_bytes_at(parent, "prelaunch.json", max_bytes=16384)
    if json.loads(lease_raw).get("expected_new_bytes", -1) < expected_new_bytes:
        raise ValueError("growth reservation exceeds storage lease")
    guard.check(expected_new_bytes)
    adapter = QuantosResearchExecutionAdapter(
        campaign=task.campaign,
        budget=task.budget,
        family=task.family,
        template=task.template,
        manifest=task.manifest,
        bindings=task.bindings,
        snapshot_path=Path(config.snapshot_path),
        qlib_view_path=Path(config.qlib_view_path),
        base_authoring=config.volume if label == "V" else config.price,
        research_policy=config.research_policy,
        validation_policy=config.validation_policy,
        cost_policy=config.cost_policy,
        backtest_policy=config.backtest_policy,
        output_root=root,
        workspace=Path(config.workspace),
        field_study=config,
        field_study_source_adoption=adoption,
        discovery_stage_recovery=True,
    )
    with exclusive_directory_lock(root / "management"):
        prior = adapter.verified_completed_execution(task.request)
        if prior is not None:
            _write_once(root / "outcome.json", prior.canonical_bytes())
            return prior
        attempts = root / "management/attempts"
        existing = sorted(attempts.glob("*/intent.json"))
        if existing and not resume:
            raise ValueError("retained unfinished attempt requires explicit --resume")
        attempt = attempts / f"{len(existing) + 1:08d}"
        _write_once(
            attempt / "intent.json",
            canonical_json_bytes(
                {
                    "request_hash": request_hash,
                    "storage_policy_hash": guard.policy_hash,
                    "lease_prelaunch_hash": sha256_bytes(lease_raw),
                    "expected_new_bytes": expected_new_bytes,
                    "max_compute_units": max_compute_units,
                }
            ),
        )
        try:
            result = adapter.execute(task.request)
            _write_once(root / "outcome.json", result.canonical_bytes())
        except BaseException:
            _write_once(
                attempt / "returned.json",
                canonical_json_bytes(
                    {"status": "EXCEPTION", "request_hash": request_hash, "process_exit": None}
                ),
            )
            raise
        _write_once(
            attempt / "returned.json",
            canonical_json_bytes(
                {
                    "status": "RETURNED",
                    "outcome_hash": result.content_hash,
                    "request_hash": request_hash,
                    "process_exit": None,
                }
            ),
        )
        return result


def compare(
    preparation: PreparedFieldStudy,
    sources: dict[str, PredictionImportSource],
    output_root: Path,
) -> dict[str, object]:
    return _compare(preparation, sources, output_root, preparation.prediction_profile)


def _compare(
    preparation: PreparedFieldStudy,
    sources: dict[str, PredictionImportSource],
    output_root: Path,
    profile: PredictionEvaluationProfile,
    *,
    bindings: dict[str, object] | None = None,
) -> dict[str, object]:
    from quantos.application.discovery_prediction import publish_prediction_cohort

    _validate(preparation)
    if set(sources) - {"V", "P"}:
        raise ValueError("undeclared comparison candidate")
    _distinct_roots(
        [
            output_root.absolute(),
            Path(preparation.preparation_root),
            Path(preparation.execution_root),
            Path(preparation.configuration.workspace),
            Path(preparation.configuration.snapshot_path),
            Path(preparation.configuration.qlib_view_path),
        ]
    )
    by_request = {
        t.request.content_hash: sources[t.label] for t in preparation.tasks if t.label in sources
    }
    authorings = {
        t.request.content_hash: (
            preparation.configuration.volume if t.label == "V" else preparation.configuration.price
        )
        for t in preparation.tasks
    }
    report = publish_prediction_cohort(
        profile,
        by_request,
        base_authorings=authorings,
        output_root=output_root / "evidence",
    )
    report_rows = cast(list[dict[str, object]], report["rows"])
    rows = {str(row["execution_request_hash"]): row for row in report_rows}
    values = [
        rows[t.request.content_hash].get("primary_common_rank_ic_mean") for t in preparation.tasks
    ]
    available = report["missing_or_rejected_requests"] == 0 and all(v is not None for v in values)
    report.update(
        study_hash=preparation.content_hash,
        candidate_labels={t.label: t.request.content_hash for t in preparation.tasks},
        volume_minus_price=cast(float, values[0]) - cast(float, values[1]) if available else None,
        paired_comparison_status="AVAILABLE" if available else "UNAVAILABLE",
        paired_common_days=report["common_days"] if available else None,
    )
    if bindings is not None:
        report.update(bindings)
    raw = canonical_json_bytes(report)
    _write_once(output_root / f"comparison-{sha256_bytes(raw)}.json", raw)
    return report


def compare_retained(binding_path: Path, binding_hash: str) -> dict[str, object]:
    """Adopt a pinned reader identity and verify originals once, without execution."""
    from quantos.application.discovery_prediction import (
        prediction_verifier_identity,
        validate_prediction_output_root,
    )

    raw = read_pinned(binding_path, binding_hash)
    binding = FieldStudyRetainedReaderBinding.model_validate_json(raw)
    if raw != binding.canonical_bytes():
        raise ValueError("reader binding must be canonical")
    prep = load_preparation(Path(binding.preparation.path), binding.preparation.sha256)
    config = prep.configuration
    if binding.producer.model_dump(exclude={"schema_version"}) != {
        "workspace": config.workspace,
        "commit_hash": config.code_commit_hash,
        "lockfile_hash": config.lockfile_hash,
    }:
        raise ValueError("producer identity differs from preparation")
    for identity in (binding.producer, binding.reader):
        workspace = Path(identity.workspace)
        if not workspace.is_absolute() or workspace != workspace.resolve():
            raise ValueError("code workspace must be canonical and absolute")
        verify_code_provenance(
            workspace,
            expected_commit_hash=identity.commit_hash,
            expected_lockfile_hash=identity.lockfile_hash,
        )
    if Path(__file__).resolve() != (
        Path(binding.reader.workspace) / "src/quantos/application/field_study.py"
    ):
        raise ValueError("loaded reader does not match bound workspace")
    profile_raw = read_pinned(Path(binding.reader_profile.path), binding.reader_profile.sha256)
    profile = PredictionEvaluationProfile.model_validate_json(profile_raw)
    if profile_raw != profile.canonical_bytes():
        raise ValueError("reader profile must be canonical")
    if profile.model_dump(exclude={"verifier_identity_hash"}) != prep.prediction_profile.model_dump(
        exclude={"verifier_identity_hash"}
    ):
        raise ValueError("reader profile escaped producer policy")
    if profile.verifier_identity_hash != sha256_bytes(
        canonical_json_bytes(prediction_verifier_identity())
    ):
        raise ValueError("reader verifier identity mismatch")
    payload = json.loads(read_pinned(Path(binding.sources.path), binding.sources.sha256))
    if not isinstance(payload, dict):
        raise ValueError("retained sources require explicit V/P descriptors or nulls")
    payload = cast(dict[str, object], payload)
    if set(payload) != {"V", "P"}:
        raise ValueError("retained sources require explicit V/P descriptors or nulls")
    sources = {
        label: PredictionImportSource.model_validate(value)
        for label, value in payload.items()
        if value is not None
    }
    output = Path(binding.output_root)
    _distinct_roots(
        [
            output,
            Path(prep.preparation_root),
            Path(prep.execution_root),
            Path(config.workspace),
            Path(config.snapshot_path),
            Path(config.qlib_view_path),
        ]
    )
    reader_root = Path(binding.reader.workspace)
    if output == reader_root or output in reader_root.parents or reader_root in output.parents:
        raise ValueError("output overlaps reader workspace")
    for path in (
        binding_path.absolute(),
        Path(binding.preparation.path).absolute(),
        Path(binding.reader_profile.path).absolute(),
        Path(binding.sources.path).absolute(),
    ):
        if output == path or output in path.parents:
            raise ValueError("output overlaps pinned reader input")
    validate_prediction_output_root(output, tuple(sources.values()))
    guard = configured_guard()
    guard.require_root(output)
    guard.require_lease()
    with opened_directory(Path(os.environ[LEASE_ENV])) as parent:
        lease_raw = read_regular_bytes_at(parent, "prelaunch.json", max_bytes=16384)
    if json.loads(lease_raw).get("expected_new_bytes", -1) < binding.expected_new_bytes:
        raise ValueError("growth reservation exceeds storage lease")
    capacity = guard.check(binding.expected_new_bytes)
    bindings: dict[str, object] = {
        "reader_binding_hash": binding_hash,
        "reader_binding": binding.model_dump(mode="json"),
        "producer_profile_hash": prep.prediction_profile.content_hash,
        "reader_profile_hash": profile.content_hash,
        "sources_hash": binding.sources.sha256,
    }
    with exclusive_directory_lock(output):
        if any(output.iterdir()):
            raise ValueError("retained comparison output must be empty")
        _write_once(
            output / "prelaunch.json",
            canonical_json_bytes(
                {
                    **bindings,
                    "capacity": capacity,
                    "scope": "SUCCESSOR_READER_ONLY_NO_TRAINING",
                }
            ),
        )
        try:
            report = _compare(prep, sources, output, profile, bindings=bindings)
        except BaseException as error:
            _write_once(
                output / "failure.json",
                canonical_json_bytes(
                    {
                        "error_class": type(error).__name__,
                        "reader_binding_hash": binding_hash,
                    }
                ),
            )
            raise
        _write_once(
            output / "completion.json",
            canonical_json_bytes(
                {
                    "entrypoint_status": "RETURNED",
                    "reader_binding_hash": binding_hash,
                    "process_exit": None,
                    "outer_exit_and_cleanup": "REQUIRE_REAL_OBSERVATION",
                }
            ),
        )
        return report


def configuration_from_workspace(
    *,
    study_id: str,
    workspace: Path,
    snapshot_path: Path,
    qlib_view_path: Path,
    code_commit_hash: str,
    lockfile_hash: str,
) -> FrozenFieldStudyConfiguration:
    """Materialize only the committed B0 inputs and existing shared policies."""
    from quantos.config import load_yaml_contract
    from quantos.contracts.cost import BacktestPolicy, CostPolicy
    from quantos.contracts.research import ExperimentAuthoringSpec, ResearchPolicy, ValidationPolicy

    return FrozenFieldStudyConfiguration(
        study_id=study_id,
        workspace=str(workspace.absolute()),
        snapshot_path=str(snapshot_path.absolute()),
        qlib_view_path=str(qlib_view_path.absolute()),
        snapshot_hash="6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9",
        qlib_view_hash="fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b",
        code_commit_hash=code_commit_hash,
        lockfile_hash=lockfile_hash,
        volume=load_yaml_contract(
            workspace / "configs/research/adjusted_volume_relative5_v1/volume_candidate.yaml",
            ExperimentAuthoringSpec,
        ),
        price=load_yaml_contract(
            workspace / "configs/research/adjusted_volume_relative5_v1/price_control.yaml",
            ExperimentAuthoringSpec,
        ),
        research_policy=load_yaml_contract(
            workspace / "configs/research/policy_v1.yaml", ResearchPolicy
        ),
        validation_policy=load_yaml_contract(
            workspace / "configs/validation/research_candidate_v1.yaml", ValidationPolicy
        ),
        cost_policy=load_yaml_contract(workspace / "configs/backtest/cost_v1.yaml", CostPolicy),
        backtest_policy=load_yaml_contract(
            workspace / "configs/backtest/policy_v1.yaml", BacktestPolicy
        ),
    )
