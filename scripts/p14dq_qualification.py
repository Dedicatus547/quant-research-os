#!/usr/bin/env python3
"""Run or verify the bounded P14-DQ Data-qualified campaign qualification."""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch
from uuid import UUID

from pydantic import ValidationError

from quantos.application.autonomous import (
    AutonomousAgentExchangeStore,
    AutonomousCampaignOrchestrator,
    ReplayAgentDriver,
    ScriptedAgentDriver,
)
from quantos.application.autonomous_execution import (
    QuantosResearchExecutionAdapter,
    autonomous_compute_accounting_policy_hash,
    build_autonomous_execution_bindings,
)
from quantos.application.campaign_selection import (
    CampaignSelectionService,
    verify_selection_report_artifact,
)
from quantos.application.campaigns import ResearchCampaignGovernor
from quantos.application.enumeration import (
    enumerate_research_family,
    verify_candidate_enumeration_manifest,
)
from quantos.application.ledger import ResearchLedgerService
from quantos.application.provenance import (
    capture_code_provenance,
    capture_runtime_fingerprint,
    verify_code_provenance,
)
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    publish_directory,
    regular_tree_files,
    sha256_file,
)
from quantos.config import load_yaml_contract
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import (
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousAgentRunPolicy,
    AutonomousCampaignPolicy,
    AutonomousCandidateProposal,
    AutonomousLoopReport,
    AutonomousLoopState,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    CampaignEventType,
    CampaignStoppingRule,
    MultipleTestingPolicy,
    ParameterDimension,
    ResearchBudgetSpec,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    ResearchSegment,
    TrialOutcome,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    CampaignSelectionEventType,
    CampaignSelectionVerdict,
    MultipleTestingPolicySpec,
    SelectionPolicySpec,
)
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.enumeration import (
    CandidateEnumerationManifest,
    ResearchFactorTemplateNode,
    ResearchFactorTemplateSpec,
    ResearchTemplateParameterSlot,
)
from quantos.contracts.ledger import (
    LedgerAssertionAuthority,
    LedgerObjectAccess,
    ResearchContextBudgetPolicy,
    ResearchLedgerNodeKind,
    ResearchLedgerObjectRef,
    ResearchLedgerSearchPolicy,
)
from quantos.contracts.p14d_qualification import (
    P14D_NEGATIVE_CASES,
    p14d_replay_binding_hash,
)
from quantos.contracts.p14dq_qualification import (
    P14DQ_CANDIDATE_HASHES,
    P14DQ_CANDIDATE_MANIFEST_HASH,
    P14DQ_FAMILY_HASH,
    P14DQ_LIMITATIONS,
    P14DQ_NEGATIVE_CASES,
    P14DQ_RESTART_CASES,
    P14DQ_SNAPSHOT_HASH,
    P14DQ_TEMPLATE_HASH,
    P14DQ_UPSTREAM_RELEASE_REPORT_HASH,
    P14DQ_VIEW_HASH,
    P14DQ_VIEW_SPEC_HASH,
    P14dqCampaignEvidence,
    P14dqCandidateEvaluation,
    P14dqExternalBindings,
    P14dqNamedHash,
    P14dqNegativeCaseEvidence,
    P14dqQualificationAttempt,
    P14dqQualificationFile,
    P14dqQualificationReport,
    P14dqReplayCaseEvidence,
    P14dqRestartCaseEvidence,
    P14dqRootEvidence,
    p14dq_principal_hash_summary,
)
from quantos.contracts.pit import SafeQlibOperator
from quantos.contracts.provenance import CodeProvenance, RuntimeFingerprint
from quantos.contracts.qlib_view import QlibViewManifest, QlibViewSpec
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ValidationPolicy,
)
from quantos.contracts.snapshot import (
    DataQualityReport,
    DataSnapshotManifest,
    SnapshotSourceKind,
)
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.data import QlibViewBuildError, SnapshotBuildError, verify_qlib_view, verify_snapshot
from quantos.research.qlib import (
    QlibWorkflowResearchService,
    verify_research_result,
)
from quantos.validation import verify_validation_report

ROOT = Path(__file__).resolve().parents[1]
p14d = importlib.import_module(
    "scripts.p14d_qualification" if __package__ else "p14d_qualification"
)

CONTRACT_PATH = Path("docs/p14-dq-qualification-contract.md")
FROZEN_CONTRACT_SHA256 = "2e8dab7816f49c45e8728892288673d8565947a76d7202d14681f830f2957069"
SNAPSHOT_RELATIVE_PATH = Path(
    "artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
)
VIEW_RELATIVE_PATH = Path(
    "artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
)
UPSTREAM_RELEASE_RELATIVE_PATH = Path("artifacts/releases/data-qualified-v0.1-f3fc768/report.json")
QUALITY_REPORT_HASH = "e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8"
QLIB_SOURCE_COMMIT = "da920b7f954f48ab1bb64117c976710de198373e"
QLIB_VERSION = "0.9.7"
DATASET_ID = "cn-a-share-hs300-eval-2015-2025-v1"
EXPECTED_RELEASE_REPORT = {
    "schema_version": "data-qualified-release-report/v1",
    "status": "PASS",
    "release_track": "DATA_QUALIFIED",
    "data_qualified": True,
    "source_kind": "TUSHARE",
    "snapshot_hash": P14DQ_SNAPSHOT_HASH,
    "qlib_view_hash": P14DQ_VIEW_HASH,
    "qlib_version": QLIB_VERSION,
    "qlib_source_commit": QLIB_SOURCE_COMMIT,
    "validation_verdict": "REJECT",
    "strategy_status": "REJECTED",
    "limitations": ["SINGLE_SOURCE_NON_VINTAGE"],
}
POLICY_PATHS = {
    "research_policy": Path("configs/research/policy_v1.yaml"),
    "validation_policy": Path("configs/validation/research_candidate_v1.yaml"),
    "cost_policy": Path("configs/backtest/cost_v1.yaml"),
    "backtest_policy": Path("configs/backtest/policy_v1.yaml"),
    "execution_authoring": Path("configs/research/hs300_momentum_v1.yaml"),
}
FROZEN_POLICY_FILE_HASHES = {
    "research_policy": "b9fc6224c3764b7a07109bfd5b7dc84e370039515151dbc6fad4da978b2e306e",
    "validation_policy": "fc21b697071399a719e47782ecbc7380b802f4f142c3cd0149f33c3682e0114e",
    "cost_policy": "0eb3288018095a026d6dea45b1a98b8963849a67639df14bf22ee8b940ab8bec",
    "backtest_policy": "07deceaaa75137e20b40c3f2072cc97aef44a5348f2d4721eb8da8bc8a0a21cb",
    "execution_authoring": "18854871e2b3f54a472d6366b8214130396b267aad68c7d4868ed2296c8bc679",
}
POLICY_FILES = {
    "research_policy": ResearchPolicy,
    "validation_policy": ValidationPolicy,
    "cost_policy": CostPolicy,
    "backtest_policy": BacktestPolicy,
    "execution_authoring": ExperimentAuthoringSpec,
}


class QualificationError(RuntimeError):
    """A frozen P14-DQ engineering gate failed."""


class QualificationAttemptError(QualificationError):
    """A failed qualification whose immutable attempt evidence was retained."""

    def __init__(self, cause: BaseException, attempt_path: Path) -> None:
        super().__init__(str(cause))
        self.attempt_path = str(attempt_path)
        reason = getattr(cause, "reason_code", None)
        if isinstance(reason, ReasonCode):
            self.reason_code = reason


class InputGateError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _ExternalInputs:
    snapshot_path: Path
    view_path: Path
    release_path: Path
    snapshot: DataSnapshotManifest
    quality_report: DataQualityReport
    view: QlibViewManifest
    view_spec: QlibViewSpec
    release_payload: dict[str, object]
    release_bytes: bytes
    snapshot_manifest_bytes: bytes
    quality_report_bytes: bytes
    view_manifest_bytes: bytes
    view_spec_bytes: bytes
    bindings: P14dqExternalBindings


@dataclass(frozen=True)
class _Policies:
    research: ResearchPolicy
    validation: ValidationPolicy
    cost: CostPolicy
    backtest: BacktestPolicy
    authoring: ExperimentAuthoringSpec
    file_hashes: tuple[P14dqNamedHash, ...]
    contract_hashes: tuple[P14dqNamedHash, ...]


def _canonical_model_file(model: object) -> bytes:
    return canonical_json_bytes(cast(object, model).model_dump(mode="python"))  # type: ignore[attr-defined]


def _manifest_inventory_hash(files: Sequence[object]) -> str:
    return sha256_bytes(
        canonical_json_bytes(tuple(cast(object, item).model_dump(mode="python") for item in files))  # type: ignore[attr-defined]
    )


def _view_manifest_bindings_hash(view: QlibViewManifest) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "converter_inputs": view.converter_inputs,
                "dump_bin_sha256": view.dump_bin_sha256,
                "files": view.files,
                "health_check_passed": view.health_check_passed,
                "health_check_sha256": view.health_check_sha256,
                "qlib_source_commit": view.qlib_source_commit,
                "qlib_version": view.qlib_version,
                "semantic_samples": view.semantic_samples,
                "source_snapshot_hash": view.source_snapshot_hash,
                "view_spec_hash": view.view_spec_hash,
            }
        )
    )


def _frozen_contract_hash(workspace: Path) -> str:
    actual = sha256_file(workspace / CONTRACT_PATH)
    if actual != FROZEN_CONTRACT_SHA256:
        raise QualificationError("P14-DQ contract bytes differ from approved baseline 37880e8")
    return actual


def _path_has_symlink_component(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def _require_explicit_path(path: Path, expected: Path, label: str) -> None:
    supplied = path if path.is_absolute() else ROOT / path
    if (
        supplied != expected
        or supplied.resolve(strict=True) != expected.resolve(strict=True)
        or _path_has_symlink_component(supplied)
    ):
        raise InputGateError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            f"explicit {label} path does not match the frozen content-addressed path",
        )


def _verify_snapshot_metadata(snapshot: DataSnapshotManifest) -> None:
    if (
        snapshot.snapshot_hash != P14DQ_SNAPSHOT_HASH
        or snapshot.content_hash != P14DQ_SNAPSHOT_HASH
        or snapshot.dataset_id != DATASET_ID
        or snapshot.source_kind is not SnapshotSourceKind.TUSHARE
        or snapshot.provider != "tushare-pro"
        or snapshot.start_date != date(2014, 11, 1)
        or snapshot.end_date != date(2025, 12, 31)
        or snapshot.quality_report_hash != QUALITY_REPORT_HASH
        or snapshot.limitations != ("SINGLE_SOURCE_NON_VINTAGE",)
    ):
        raise InputGateError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "snapshot metadata differs from the frozen Data-qualified input",
        )


def _verify_quality_report(
    snapshot: DataSnapshotManifest,
    report: DataQualityReport | None,
    encoded: bytes | None,
) -> None:
    if report is None or encoded is None:
        raise InputGateError(ReasonCode.ARTIFACT_CORRUPTED, "snapshot quality report is missing")
    if (
        encoded != report.canonical_bytes()
        or report.content_hash != snapshot.quality_report_hash
        or report.content_hash != QUALITY_REPORT_HASH
        or not report.passed
        or "SINGLE_SOURCE_NON_VINTAGE" not in snapshot.limitations
    ):
        raise InputGateError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "snapshot quality report or non-vintage limitation differs from the frozen input",
        )


def _verify_view_metadata(
    view: QlibViewManifest,
    snapshot: DataSnapshotManifest,
    view_spec: QlibViewSpec | None = None,
) -> None:
    if (
        view.view_hash != P14DQ_VIEW_HASH
        or view.content_hash != P14DQ_VIEW_HASH
        or view.source_snapshot_hash != snapshot.snapshot_hash
        or view.view_spec_hash != P14DQ_VIEW_SPEC_HASH
        or view.qlib_version != QLIB_VERSION
        or view.qlib_source_commit != QLIB_SOURCE_COMMIT
        or not view.health_check_passed
        or view_spec is None
        or view_spec.content_hash != P14DQ_VIEW_SPEC_HASH
        or view_spec.source_snapshot_hash != snapshot.snapshot_hash
        or view_spec.qlib_version != view.qlib_version
        or view_spec.qlib_source_commit != view.qlib_source_commit
        or view_spec.dump_bin_sha256 != view.dump_bin_sha256
        or view_spec.health_check_sha256 != view.health_check_sha256
        or not all(item.passed for item in view.semantic_samples)
    ):
        raise InputGateError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "Qlib view identity, lineage, converter or health evidence differs "
            "from the frozen input",
        )


def _verify_release_qualification(payload: Mapping[str, object]) -> None:
    if any(payload.get(key) != value for key, value in EXPECTED_RELEASE_REPORT.items()):
        raise InputGateError(
            ReasonCode.CAPABILITY_DENIED,
            "upstream P2-P7 release is not the frozen qualified release",
        )


def _assert_root_lineage(*, snapshot_hash: str, view_hash: str, release_hash: str) -> None:
    if (
        snapshot_hash != P14DQ_SNAPSHOT_HASH
        or view_hash != P14DQ_VIEW_HASH
        or release_hash != P14DQ_UPSTREAM_RELEASE_REPORT_HASH
    ):
        raise InputGateError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "qualification root attempted to substitute a frozen upstream input",
        )


def _verify_release_bytes(encoded: bytes) -> dict[str, object]:
    try:
        payload_raw = json.loads(encoded)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InputGateError(
            ReasonCode.ARTIFACT_CORRUPTED, "upstream release report is not valid JSON"
        ) from error
    if not isinstance(payload_raw, dict):
        raise InputGateError(
            ReasonCode.ARTIFACT_CORRUPTED, "upstream release report is not an object"
        )
    payload = cast(dict[str, object], payload_raw)
    if (
        encoded != canonical_json_bytes(payload)
        or sha256_bytes(encoded) != P14DQ_UPSTREAM_RELEASE_REPORT_HASH
    ):
        raise InputGateError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "upstream release report bytes are noncanonical or hash-mismatched",
        )
    _verify_release_qualification(payload)
    return payload


def verify_external_inputs(
    *, workspace: Path, snapshot_path: Path, view_path: Path, release_report_path: Path
) -> _ExternalInputs:
    """Verify the exact frozen external inputs without acquiring or rebuilding data."""

    workspace = workspace.resolve(strict=True)
    expected_snapshot = workspace / SNAPSHOT_RELATIVE_PATH
    expected_view = workspace / VIEW_RELATIVE_PATH
    expected_release = workspace / UPSTREAM_RELEASE_RELATIVE_PATH
    _require_explicit_path(snapshot_path, expected_snapshot, "snapshot")
    _require_explicit_path(view_path, expected_view, "Qlib view")
    _require_explicit_path(release_report_path, expected_release, "upstream release report")
    try:
        snapshot = verify_snapshot(expected_snapshot)
        snapshot_manifest_bytes = (expected_snapshot / "manifest.json").read_bytes()
        if snapshot_manifest_bytes != _canonical_model_file(snapshot):
            raise InputGateError(ReasonCode.ARTIFACT_CORRUPTED, "snapshot manifest is noncanonical")
        _verify_snapshot_metadata(snapshot)
        quality_report_bytes = (expected_snapshot / "quality-report.json").read_bytes()
        quality_report = DataQualityReport.model_validate_json(quality_report_bytes)
        _verify_quality_report(snapshot, quality_report, quality_report_bytes)
        view = verify_qlib_view(expected_view)
        view_manifest_bytes = (expected_view / "manifest.json").read_bytes()
        if view_manifest_bytes != _canonical_model_file(view):
            raise InputGateError(
                ReasonCode.ARTIFACT_CORRUPTED, "Qlib view manifest is noncanonical"
            )
        view_spec_bytes = (expected_view / "view-spec.json").read_bytes()
        view_spec = QlibViewSpec.model_validate_json(view_spec_bytes)
        if view_spec_bytes != view_spec.canonical_bytes():
            raise InputGateError(ReasonCode.ARTIFACT_CORRUPTED, "Qlib view spec is noncanonical")
        _verify_view_metadata(view, snapshot, view_spec)
        release_bytes = expected_release.read_bytes()
        release_payload = _verify_release_bytes(release_bytes)
    except InputGateError:
        raise
    except (SnapshotBuildError, QlibViewBuildError) as error:
        raise InputGateError(error.reason_code, str(error)) from error
    except (OSError, ValidationError, ValueError, TypeError, KeyError) as error:
        reason = getattr(error, "reason_code", ReasonCode.ARTIFACT_CORRUPTED)
        if not isinstance(reason, ReasonCode):
            reason = ReasonCode.ARTIFACT_CORRUPTED
        raise InputGateError(reason, "frozen external input verification failed") from error

    release_input_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "data_qualified": release_payload.get("data_qualified"),
                "release_track": release_payload.get("release_track"),
                "snapshot_hash": release_payload.get("snapshot_hash"),
                "status": release_payload.get("status"),
                "view_hash": release_payload.get("qlib_view_hash"),
            }
        )
    )
    bindings = P14dqExternalBindings(
        snapshot_path=SNAPSHOT_RELATIVE_PATH.as_posix(),
        snapshot_hash=snapshot.snapshot_hash,
        snapshot_manifest_file_hash=sha256_bytes(snapshot_manifest_bytes),
        snapshot_files_inventory_hash=_manifest_inventory_hash(snapshot.files),
        source_kind=snapshot.source_kind.value,
        provider=snapshot.provider,
        dataset_id=snapshot.dataset_id,
        snapshot_start_date=snapshot.start_date,
        snapshot_end_date=snapshot.end_date,
        quality_report_hash=quality_report.content_hash,
        quality_report_file_hash=sha256_bytes(quality_report_bytes),
        non_vintage_limitation="SINGLE_SOURCE_NON_VINTAGE",
        qlib_view_path=VIEW_RELATIVE_PATH.as_posix(),
        qlib_view_hash=view.view_hash,
        qlib_view_manifest_file_hash=sha256_bytes(view_manifest_bytes),
        qlib_view_files_inventory_hash=_manifest_inventory_hash(view.files),
        view_spec_hash=view.view_spec_hash,
        view_spec_file_hash=sha256_bytes(view_spec_bytes),
        qlib_version=view.qlib_version,
        qlib_source_commit=view.qlib_source_commit,
        dump_bin_sha256=view.dump_bin_sha256,
        health_check_sha256=view.health_check_sha256,
        qlib_view_manifest_bindings_hash=_view_manifest_bindings_hash(view),
        upstream_release_report_path=UPSTREAM_RELEASE_RELATIVE_PATH.as_posix(),
        upstream_release_report_hash=sha256_bytes(release_bytes),
        upstream_release_input_hash=release_input_hash,
        upstream_release_status=cast(str, release_payload["status"]),
        upstream_release_track=cast(str, release_payload["release_track"]),
        upstream_data_qualified=cast(bool, release_payload["data_qualified"]),
        historical_validation_verdict=cast(str, release_payload["validation_verdict"]),
        historical_strategy_status=cast(str, release_payload["strategy_status"]),
    )
    _assert_root_lineage(
        snapshot_hash=snapshot.snapshot_hash,
        view_hash=view.view_hash,
        release_hash=bindings.upstream_release_report_hash,
    )
    return _ExternalInputs(
        snapshot_path=expected_snapshot,
        view_path=expected_view,
        release_path=expected_release,
        snapshot=snapshot,
        quality_report=quality_report,
        view=view,
        view_spec=view_spec,
        release_payload=release_payload,
        release_bytes=release_bytes,
        snapshot_manifest_bytes=snapshot_manifest_bytes,
        quality_report_bytes=quality_report_bytes,
        view_manifest_bytes=view_manifest_bytes,
        view_spec_bytes=view_spec_bytes,
        bindings=bindings,
    )


def _assert_frozen_policy_periods(
    research: ResearchPolicy,
    authoring: ExperimentAuthoringSpec,
) -> None:
    expected = (
        (research.train.start, research.train.end, date(2015, 1, 1), date(2019, 12, 31)),
        (research.validation.start, research.validation.end, date(2020, 1, 1), date(2022, 12, 31)),
        (research.test.start, research.test.end, date(2023, 1, 1), date(2025, 12, 31)),
    )
    if any(
        (start, end) != (required_start, required_end)
        for start, end, required_start, required_end in expected
    ):
        raise QualificationError("frozen research policy dates differ from P14-DQ")
    if authoring.strategy.universe_index != "000300.SH" or authoring.strategy.top_k != 50:
        raise QualificationError("frozen execution authoring policy differs from P14-DQ")


def _load_policies(workspace: Path) -> _Policies:
    loaded: dict[str, object] = {}
    file_hashes: list[P14dqNamedHash] = []
    contract_hashes: list[P14dqNamedHash] = []
    for name, relative in POLICY_PATHS.items():
        path = workspace / relative
        file_hash = sha256_file(path)
        if file_hash != FROZEN_POLICY_FILE_HASHES[name]:
            raise QualificationError(f"frozen P14-DQ {name} policy bytes differ from baseline")
        contract_type = cast(type[object], POLICY_FILES[name])
        contract = load_yaml_contract(path, contract_type)
        loaded[name] = contract
        file_hashes.append(P14dqNamedHash(name=f"{name}_file", sha256=file_hash))
        contract_hashes.append(
            P14dqNamedHash(name=name, sha256=cast(object, contract).content_hash)  # type: ignore[attr-defined]
        )
    research = cast(ResearchPolicy, loaded["research_policy"])
    validation = cast(ValidationPolicy, loaded["validation_policy"])
    cost = cast(CostPolicy, loaded["cost_policy"])
    backtest = cast(BacktestPolicy, loaded["backtest_policy"])
    base_authoring = cast(ExperimentAuthoringSpec, loaded["execution_authoring"])
    _assert_frozen_policy_periods(research, base_authoring)
    return _Policies(
        research=research,
        validation=validation,
        cost=cost,
        backtest=backtest,
        authoring=base_authoring,
        file_hashes=tuple(sorted(file_hashes, key=lambda item: item.name)),
        contract_hashes=tuple(sorted(contract_hashes, key=lambda item: item.name)),
    )


def _template() -> ResearchFactorTemplateSpec:
    return ResearchFactorTemplateSpec(
        template_id="p14-dq-adjusted-close-delta-template-v1",
        expression_schema_version="safe-qlib-expression/v2",
        nodes=(
            ResearchFactorTemplateNode(
                node_id="price",
                operator=SafeQlibOperator.FIELD,
                field_name="adjusted_close",
            ),
            ResearchFactorTemplateNode(
                node_id="factor", operator=SafeQlibOperator.DELTA, inputs=("price",)
            ),
        ),
        output_node_id="factor",
        input_lag_trading_days=0,
        parameter_slots=(
            ResearchTemplateParameterSlot(name="window", node_id="factor", field="window"),
        ),
    )


def _family(template: ResearchFactorTemplateSpec) -> ResearchFamilySpec:
    return ResearchFamilySpec(
        family_id="p14-dq-live-data-engineering-v1",
        research_question=(
            "Can the bounded deterministic P14-DQ scripted/replay campaign reproduce identical "
            "principal engineering evidence in independent roots on the exact Data-qualified "
            "snapshot and derived Qlib view using the predeclared two-candidate adjusted-close "
            "DELTA family?"
        ),
        hypothesis_hash="147495c5a1f583aa8cd58c11d3de84ee1612d7149495ffed8c5257f43d4231a3",
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted((SafeQlibOperator.DELTA, SafeQlibOperator.FIELD), key=str)),
        parameter_space=(ParameterDimension(name="window", values=(2, 3)),),
        declared_candidate_count=2,
    )


def _p14dq_family_manifest() -> tuple[
    ResearchFactorTemplateSpec, ResearchFamilySpec, CandidateEnumerationManifest
]:
    template = _template()
    family = _family(template)
    manifest = enumerate_research_family(family, template)
    if (
        template.content_hash != P14DQ_TEMPLATE_HASH
        or family.content_hash != P14DQ_FAMILY_HASH
        or manifest.content_hash != P14DQ_CANDIDATE_MANIFEST_HASH
        or tuple(item.content_hash for item in manifest.candidates) != P14DQ_CANDIDATE_HASHES
    ):
        raise QualificationError("P14-DQ P14b enumerator output differs from the frozen family")
    verify_candidate_enumeration_manifest(family, template, manifest)
    return template, family, manifest


def _proposal(
    campaign: ResearchCampaignSpec,
    candidate: object,
    ordinal: int,
) -> AutonomousCandidateProposal:
    spec = cast(object, candidate)
    return AutonomousCandidateProposal(
        campaign_hash=campaign.content_hash,
        candidate_hash=spec.content_hash,  # type: ignore[attr-defined]
        parameters=spec.parameters,  # type: ignore[attr-defined]
        expression=spec.expression,  # type: ignore[attr-defined]
        exact_expression_hash=spec.exact_expression_hash,  # type: ignore[attr-defined]
        structural_expression_hash=spec.structural_expression_hash,  # type: ignore[attr-defined]
        rationale=f"frozen P14-DQ enumerated candidate {ordinal}",
    )


def _build_case_context(
    case_root: Path,
    inputs: _ExternalInputs,
    policies: _Policies,
    code: CodeProvenance,
    *,
    workspace: Path,
) -> p14d._CaseContext:
    """Build the existing P14d context around P14-DQ's frozen live inputs and family."""

    case_root.mkdir(parents=True, exist_ok=True)
    template, family, manifest = _p14dq_family_manifest()
    fixture = p14d._Fixture(
        fixture_id="p14-dq-live-data-lineage",
        snapshot_path=inputs.snapshot_path,
        view_path=inputs.view_path,
        snapshot_manifest=inputs.snapshot,
        view_manifest=inputs.view,
        fixture_hash=inputs.bindings.content_hash,
    )
    policy_hashes = tuple(
        sorted(
            {
                *(item.sha256 for item in policies.file_hashes),
                *(item.sha256 for item in policies.contract_hashes),
                inputs.bindings.content_hash,
                _frozen_contract_hash(workspace),
            }
        )
    )
    ledger_id = "p14-dq-natural-ledger-v1"
    ledger = ResearchLedgerService(case_root / "ledger")
    evidence_bytes = canonical_json_bytes(
        {
            "external_bindings_hash": inputs.bindings.content_hash,
            "policy_hashes": policy_hashes,
            "purpose": "P14-DQ frozen Data-qualified campaign inputs",
        }
    )
    evidence_ref = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(evidence_bytes),
        media_type="application/json",
        source_domain="p14-dq-qualified-lineage",
        access=LedgerObjectAccess.PUBLIC_HISTORY,
    )
    ledger.append(
        ledger_id=ledger_id,
        node_id="p14-dq-frozen-campaign-inputs",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=evidence_ref,
        object_bytes=evidence_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=p14d.LEDGER_SEEDED_AT,
    )
    initial_ledger = ledger.verify(
        ledger_id, created_at=p14d.LEDGER_SEEDED_AT + timedelta(seconds=1)
    )
    budget = ResearchBudgetSpec(
        budget_id="p14-dq-two-candidate-budget-v1",
        max_trials=2,
        max_distinct_candidates=2,
        max_agent_runs=2,
        max_executions=2,
        max_validation_rounds=2,
        max_compute_seconds=100_000,
    )
    campaign = ResearchCampaignSpec(
        campaign_id="p14-dq-live-data-campaign-v1",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=(evidence_ref.object_hash,),
        ledger_snapshot_hash=initial_ledger.content_hash,
        snapshot_hash=inputs.snapshot.snapshot_hash,
        qlib_view_hash=inputs.view.view_hash,
        development=ResearchSegment(start=date(2020, 1, 1), end=date(2022, 12, 31)),
        validation=ResearchSegment(start=date(2023, 1, 1), end=date(2025, 12, 31)),
        sealed_confirmation=ResearchSegment(start=date(2026, 1, 1), end=date(2026, 1, 30)),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    first_candidate = manifest.candidates[0]
    authoring_payload = policies.authoring.model_dump(mode="python")
    authoring_payload.update(
        {
            "experiment_id": "p14-dq-live-candidate-base-v1",
            "evaluation_start": policies.research.test.start,
            "evaluation_end": policies.research.test.end,
            "expression": first_candidate.expression.model_dump(mode="python"),
        }
    )
    authoring = ExperimentAuthoringSpec.model_validate(authoring_payload)
    bindings = build_autonomous_execution_bindings(
        snapshot=inputs.snapshot,
        qlib_view=inputs.view,
        research_policy=policies.research,
        validation_policy=policies.validation,
        authoring=authoring,
        cost_policy=policies.cost,
        backtest_policy=policies.backtest,
        code_commit_hash=code.commit_hash,
        lockfile_hash=code.lockfile_hash,
    )
    execution_root = case_root / "execution"
    adapter_args: dict[str, object] = {
        "campaign": campaign,
        "family": family,
        "budget": budget,
        "template": template,
        "manifest": manifest,
        "snapshot_path": inputs.snapshot_path,
        "qlib_view_path": inputs.view_path,
        "base_authoring": authoring,
        "research_policy": policies.research,
        "validation_policy": policies.validation,
        "cost_policy": policies.cost,
        "backtest_policy": policies.backtest,
        "bindings": bindings,
        "output_root": execution_root,
        "workspace": workspace,
        "canonical_validation": True,
    }
    multiple_testing = MultipleTestingPolicySpec(seed="9" * 64)
    selection_policy = SelectionPolicySpec(
        multiple_testing_policy_hash=multiple_testing.content_hash,
        direction="POSITIVE",
    )
    selection = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple_testing,
        selection_policy,
        inputs.view_path,
        (execution_root / "research-results",),
    )
    governor = ResearchCampaignGovernor(family, template, manifest)
    activation = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID(int=int(sha256_bytes(b"p14-dq-activation-v1")[:32], 16)),
        occurred_at=p14d.CASE_STARTED_AT - timedelta(seconds=3),
    )
    plan_event, _plan = selection.freeze_plan(
        governor,
        (activation,),
        event_id=UUID(int=int(sha256_bytes(b"p14-dq-plan-v1")[:32], 16)),
        occurred_at=p14d.CASE_STARTED_AT - timedelta(seconds=2),
        artifact_root=case_root / "selection-plans",
    )
    search_policy = ResearchLedgerSearchPolicy(
        policy_id="p14-dq-live-search-policy-v1",
        allowed_node_kinds=tuple(sorted(ResearchLedgerNodeKind, key=str)),
        allowed_authorities=tuple(sorted(LedgerAssertionAuthority, key=str)),
        allow_cross_campaign_history=True,
        max_query_bytes=4096,
        max_query_terms=32,
        max_hit_bytes=262144,
        max_results=50,
        max_serialized_bytes=1_000_000,
        max_index_entries=1000,
        max_terms_per_object=4096,
        max_index_serialized_bytes=16_777_216,
    )
    context_budget = ResearchContextBudgetPolicy(
        policy_id="p14-dq-live-context-budget-v1",
        max_items=50,
        max_item_bytes=262144,
        max_serialized_bytes=1_000_000,
    )
    campaign_policy = AutonomousCampaignPolicy(
        policy_id="p14-dq-live-campaign-policy-v1",
        context_query="outcome research_policy_hash",
        readable_campaign_hashes=(campaign.content_hash,),
        trial_segment=CampaignSegment.VALIDATION,
    )
    agent_policy = AutonomousAgentRunPolicy(
        capability_policy_hash="a" * 64,
        requested_model_configuration_hash="b" * 64,
        tool_schema_hash="c" * 64,
        instruction_hashes=("d" * 64,),
        skill_hash="e" * 64,
        sandbox_policy_hash="f" * 64,
        permission_policy_hash="1" * 64,
        runtime_policy_hash="2" * 64,
        harness_identifier="scripted-agent-driver/v1",
        provider_model_identifier="p14-dq-scripted-replay/v1",
        model_snapshot_immutable=True,
    )
    proposal = _proposal(campaign, first_candidate, 1)
    malformed_proposal = canonical_json_bytes(
        {"candidate_hash": manifest.candidates[1].content_hash}
    )
    return p14d._CaseContext(
        case_id="P14DQ_NATURAL",
        case_root=case_root,
        fixture=fixture,
        ledger=ledger,
        ledger_id=ledger_id,
        initial_ledger=initial_ledger,
        initial_events=(activation, plan_event),
        campaign=campaign,
        family=family,
        budget=budget,
        template=template,
        manifest=manifest,
        search_policy=search_policy,
        context_budget=context_budget,
        campaign_policy=campaign_policy,
        agent_policy=agent_policy,
        selection=selection,
        adapter_args=adapter_args,
        execution_bindings=bindings,
        proposal=proposal,
        malformed_proposal=malformed_proposal,
    )


def _script(context: p14d._CaseContext) -> tuple[AutonomousCandidateProposal, ...]:
    return tuple(
        _proposal(context.campaign, candidate, index + 1)
        for index, candidate in enumerate(context.manifest.candidates)
    )


def _adapter(context: p14d._CaseContext) -> QuantosResearchExecutionAdapter:
    return QuantosResearchExecutionAdapter(**context.adapter_args)  # type: ignore[arg-type]


def _build_orchestrator(
    context: p14d._CaseContext,
    adapter: QuantosResearchExecutionAdapter,
    script: Sequence[AutonomousCandidateProposal | bytes],
) -> AutonomousCampaignOrchestrator:
    return AutonomousCampaignOrchestrator(
        campaign=context.campaign,
        family=context.family,
        budget=context.budget,
        template=context.template,
        manifest=context.manifest,
        initial_ledger_snapshot=context.initial_ledger,
        ledger_service=context.ledger,
        ledger_id=context.ledger_id,
        search_policy=context.search_policy,
        context_budget=context.context_budget,
        campaign_policy=context.campaign_policy,
        agent_run_policy=context.agent_policy,
        agent_driver=ScriptedAgentDriver(tuple(script), context.agent_policy),
        execution_port=adapter,
        exchange_root=context.case_root / "agent-exchanges",
        event_root=context.case_root / "campaign-events",
        selection_service=context.selection,
        selection_artifact_root=context.case_root / "selection-reports",
        autonomous_report_root=context.case_root / "loop-reports",
        execution_bindings=context.execution_bindings,
        selection_finalization_profile=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    )


def _restart_state(context: p14d._CaseContext, workflow_runs: int) -> dict[str, object]:
    from quantos.application.autonomous import CampaignEventStore

    governor = ResearchCampaignGovernor(context.family, context.template, context.manifest)
    events = CampaignEventStore(context.case_root / "campaign-events").load(
        governor, context.campaign, context.budget
    )
    receipts = p14d._load_receipts(context)
    exchanges = p14d._load_exchanges(context.case_root / "agent-exchanges", context.agent_policy)
    reports = tuple(sorted((context.case_root / "selection-reports").glob("sha256-*")))
    result_paths = tuple(
        sorted(
            item for item in (context.case_root / "execution" / "research-results").glob("sha256-*")
        )
    )
    trial_events = tuple(
        event
        for event in events
        if getattr(event, "trial", None) is not None
        and getattr(event.trial, "proposal_hash", None) is not None
    )
    selection_events = tuple(
        event
        for event in events
        if isinstance(event, CampaignSelectionEvent)
        and event.event_type is CampaignSelectionEventType.SELECTION_FROZEN
    )
    close_events = tuple(
        event
        for event in events
        if getattr(getattr(event, "event_type", None), "value", None)
        == CampaignEventType.CLOSED.value
    )
    final_ledger = context.ledger.verify(
        context.ledger_id, created_at=p14d.CASE_STARTED_AT + timedelta(days=1)
    )
    selection_report_hashes = {item.name.removeprefix("sha256-") for item in reports}
    ledger_events = context.ledger._load_and_verify().get(context.ledger_id, ())
    selection_verdict_node_hashes = tuple(
        sorted(
            event.content_hash
            for event in ledger_events
            if event.node_kind is ResearchLedgerNodeKind.CAMPAIGN_SELECTION_REPORT
            and event.authority is LedgerAssertionAuthority.DETERMINISTIC_VERDICT
            and event.verdict_report_hash in selection_report_hashes
        )
    )
    return {
        "event_hashes": tuple(event.content_hash for event in events),
        "execution_receipt_hashes": tuple(sorted(item.content_hash for item in receipts)),
        "exchange_hashes": tuple(sorted(item.content_hash for item in exchanges)),
        "report_directory_names": tuple(item.name for item in reports),
        "research_result_directory_names": tuple(item.name for item in result_paths),
        "selection_event_hashes": tuple(item.content_hash for item in selection_events),
        "selection_verdict_node_hashes": selection_verdict_node_hashes,
        "close_event_hashes": tuple(item.content_hash for item in close_events),
        "trial_event_hashes": tuple(event.content_hash for event in trial_events),
        "ledger_snapshot_hash": final_ledger.content_hash,
        "workflow_runs": workflow_runs,
    }


def _assert_restart_state(
    state: Mapping[str, object],
    *,
    trials: int,
    receipts: int,
    exchanges: int,
    reports: int,
    verdict_nodes: int,
    closes: int,
    workflow_runs: int,
) -> None:
    if (
        len(cast(tuple[str, ...], state["trial_event_hashes"])) != trials
        or len(cast(tuple[str, ...], state["execution_receipt_hashes"])) != receipts
        or len(cast(tuple[str, ...], state["exchange_hashes"])) != exchanges
        or len(cast(tuple[str, ...], state["report_directory_names"])) != reports
        or len(cast(tuple[str, ...], state["selection_verdict_node_hashes"])) != verdict_nodes
        or len(cast(tuple[str, ...], state["close_event_hashes"])) != closes
        or cast(tuple[str, ...], state["selection_event_hashes"])
        or state["workflow_runs"] != workflow_runs
    ):
        raise QualificationError("P14-DQ restart state duplicated or lost campaign authority")


def _restart_evidence(
    case_id: str,
    context: p14d._CaseContext,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> P14dqRestartCaseEvidence:
    return P14dqRestartCaseEvidence(
        case_id=case_id,
        input_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    "campaign_hash": context.campaign.content_hash,
                    "case_id": case_id,
                    "external_input_hash": context.fixture.fixture_hash,
                }
            )
        ),
        pre_restart_evidence_hash=sha256_bytes(canonical_json_bytes(before)),
        post_restart_evidence_hash=sha256_bytes(canonical_json_bytes(after)),
        qlib_runs_before_restart=cast(int, before["workflow_runs"]),
        qlib_runs_after_restart=cast(int, after["workflow_runs"]),
        pre_campaign_close_count=len(cast(tuple[str, ...], before["close_event_hashes"])),
        post_campaign_close_count=len(cast(tuple[str, ...], after["close_event_hashes"])),
    )


def _run_natural_with_restarts(
    context: p14d._CaseContext,
) -> tuple[p14d._CaseRun, tuple[P14dqRestartCaseEvidence, ...]]:
    """Execute both candidates once while resuming through all three frozen boundaries."""

    script = _script(context)
    calls = {"count": 0}
    original_workflow = QlibWorkflowResearchService.run

    def count_workflow(self: object, *args: object, **kwargs: object):
        calls["count"] += 1
        return original_workflow(cast(QlibWorkflowResearchService, self), *args, **kwargs)

    with patch.object(QlibWorkflowResearchService, "run", count_workflow):
        adapter_a = _adapter(context)
        orchestrator_a = _build_orchestrator(context, adapter_a, script)
        orchestrator_a.event_store.seed(
            context.initial_events, orchestrator_a.governor, context.campaign, context.budget
        )
        real_append = orchestrator_a.event_store.append
        append_calls = {"count": 0}

        def crash_before_first_trial(*args: object, **kwargs: object):
            append_calls["count"] += 1
            if append_calls["count"] == 1:
                raise p14d._InjectedRestartCrash("crash after exchange and receipt, before trial")
            return real_append(*args, **kwargs)

        with patch.object(orchestrator_a.event_store, "append", crash_before_first_trial):
            try:
                orchestrator_a.run(context.initial_events, started_at=p14d.CASE_STARTED_AT)
            except p14d._InjectedRestartCrash:
                pass
            else:
                raise QualificationError("P14-DQ exchange/receipt restart boundary did not fire")
        state_before_trial = _restart_state(context, calls["count"])
        _assert_restart_state(
            state_before_trial,
            trials=0,
            receipts=1,
            exchanges=1,
            reports=0,
            verdict_nodes=0,
            closes=0,
            workflow_runs=1,
        )

        adapter_b = _adapter(context)
        orchestrator_b = _build_orchestrator(context, adapter_b, script)
        real_reconcile = orchestrator_b._reconcile_ledger  # pyright: ignore[reportPrivateUsage]
        reconcile_calls = {"count": 0}

        def crash_after_first_trial(*args: object, **kwargs: object):
            reconcile_calls["count"] += 1
            if reconcile_calls["count"] == 2:
                raise p14d._InjectedRestartCrash("crash after trial, before Ledger reconciliation")
            return real_reconcile(*args, **kwargs)

        orchestrator_b._reconcile_ledger = crash_after_first_trial  # type: ignore[method-assign]
        try:
            orchestrator_b.run(context.initial_events, started_at=p14d.RESTART_STARTED_AT)
        except p14d._InjectedRestartCrash:
            pass
        else:
            raise QualificationError("P14-DQ trial/Ledger restart boundary did not fire")
        state_after_first_trial = _restart_state(context, calls["count"])
        _assert_restart_state(
            state_after_first_trial,
            trials=1,
            receipts=1,
            exchanges=1,
            reports=0,
            verdict_nodes=0,
            closes=0,
            workflow_runs=1,
        )

        adapter_c = _adapter(context)
        orchestrator_c = _build_orchestrator(context, adapter_c, script)
        real_close = orchestrator_c.governor.close
        close_calls = {"count": 0}

        def crash_before_close(*args: object, **kwargs: object):
            close_calls["count"] += 1
            if close_calls["count"] == 1:
                raise p14d._InjectedRestartCrash("crash after report publication, before close")
            return real_close(*args, **kwargs)

        orchestrator_c.governor.close = crash_before_close  # type: ignore[method-assign]
        try:
            orchestrator_c.run(
                context.initial_events, started_at=p14d.RESTART_STARTED_AT + timedelta(minutes=5)
            )
        except p14d._InjectedRestartCrash:
            orchestrator_c.governor.close = real_close  # type: ignore[method-assign]
        else:
            raise QualificationError("P14-DQ report/close restart boundary did not fire")
        state_after_report = _restart_state(context, calls["count"])
        _assert_restart_state(
            state_after_report,
            trials=2,
            receipts=2,
            exchanges=2,
            reports=1,
            verdict_nodes=1,
            closes=0,
            workflow_runs=2,
        )

        adapter_d = _adapter(context)
        orchestrator_d = _build_orchestrator(context, adapter_d, script)
        report, events = orchestrator_d.run(
            context.initial_events, started_at=p14d.RESTART_STARTED_AT + timedelta(minutes=10)
        )
        final_state = _restart_state(context, calls["count"])
        _assert_restart_state(
            final_state,
            trials=2,
            receipts=2,
            exchanges=2,
            reports=1,
            verdict_nodes=1,
            closes=1,
            workflow_runs=2,
        )

    restart_cases = (
        _restart_evidence(
            P14DQ_RESTART_CASES[0], context, state_before_trial, state_after_first_trial
        ),
        _restart_evidence(
            P14DQ_RESTART_CASES[1], context, state_after_first_trial, state_after_report
        ),
        _restart_evidence(P14DQ_RESTART_CASES[2], context, state_after_report, final_state),
    )
    return (
        p14d._CaseRun(
            context=context,
            orchestrator=orchestrator_d,
            adapter=adapter_d,
            report=report,
            events=events,
        ),
        restart_cases,
    )


def _assert_report_only_completion(report: AutonomousLoopReport, events: Sequence[object]) -> None:
    forbidden_event_names = {
        CampaignSelectionEventType.SELECTION_FROZEN.value,
        CampaignEventType.OOS_ACCESSED.value,
    }
    if (
        report.state is not AutonomousLoopState.SELECTION_COMPLETE
        or report.selection_event_hash is not None
        or report.sealed_confirmation_authority
        or report.limitations != P14DQ_LIMITATIONS
        or any(
            getattr(getattr(item, "event_type", None), "value", None) in forbidden_event_names
            for item in events
        )
        or any(
            getattr(getattr(item, "trial", None), "segment", None)
            is CampaignSegment.SEALED_CONFIRMATION
            for item in events
        )
        or not events
        or getattr(getattr(events[-1], "event_type", None), "value", None)
        != CampaignEventType.CLOSED.value
    ):
        raise InputGateError(
            ReasonCode.OOS_POLICY_VIOLATION,
            "P14-DQ report-only completion contains a sealed handoff or missing close",
        )


def _campaign_evidence(run: p14d._CaseRun) -> P14dqCampaignEvidence:
    context = run.context
    loop_report = cast(AutonomousLoopReport, run.report)
    _assert_report_only_completion(loop_report, run.events)
    selection_hash = loop_report.selection_report_hash
    if selection_hash is None:
        raise QualificationError("P14-DQ natural campaign did not publish a P14c report")
    selection_path = context.case_root / "selection-reports" / f"sha256-{selection_hash}"
    selection_report = verify_selection_report_artifact(selection_path)
    if selection_report.run_status is not RunStatus.SUCCEEDED or selection_report.verdict not in {
        CampaignSelectionVerdict.SELECTED,
        CampaignSelectionVerdict.NO_SELECTION,
    }:
        raise InputGateError(
            selection_report.reason_code or ReasonCode.SOURCE_INCOMPLETE,
            "P14-DQ natural campaign failed P14c or has zero eligible candidates",
        )
    if selection_report.report_hash != loop_report.selection_report_hash:
        raise QualificationError("P14-DQ loop report and P14c report hashes disagree")
    if loop_report.selection_event_hash is not None:
        raise QualificationError("P14-DQ selected report was handed off to sealed authority")

    calendar = context.selection.calendar
    plan = context.selection.plan
    if calendar is None or plan is None:
        raise QualificationError("P14-DQ P14c plan lacks its Qlib-view calendar")
    view_dates = tuple(
        date.fromisoformat(line.strip())
        for line in (context.fixture.view_path / "calendars" / "day.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )
    derived_dates = tuple(
        item for item in view_dates if date(2023, 1, 1) <= item <= date(2025, 12, 31)
    )
    if (
        calendar.qlib_view_hash != context.fixture.view_manifest.view_hash
        or calendar.start != date(2023, 1, 1)
        or calendar.end != date(2025, 12, 31)
        or calendar.trading_dates != derived_dates
        or plan.validation_calendar_hash != calendar.content_hash
    ):
        raise QualificationError("P14-DQ P14c calendar differs from the verified Qlib view")

    exchanges = p14d._load_exchanges(context.case_root / "agent-exchanges", context.agent_policy)
    receipts = p14d._load_receipts(context)
    if len(exchanges) != 2 or len(receipts) != 2:
        raise QualificationError("P14-DQ natural campaign did not execute exactly two proposals")
    if any(
        P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.content_hash
        not in item.request.relevant_policy_hashes
        for item in exchanges
    ):
        raise QualificationError("P14-DQ Agent requests omitted the report-only profile hash")
    trial_events = tuple(
        event
        for event in run.events
        if getattr(event, "trial", None) is not None
        and getattr(event, "event_type", None) is CampaignEventType.TRIAL_RECORDED
    )
    if len(trial_events) != 2 or any(
        event.trial.segment is not CampaignSegment.VALIDATION for event in trial_events
    ):
        raise QualificationError("P14-DQ natural campaign escaped its validation segment")
    receipts_by_candidate = {item.request.candidate.content_hash: item for item in receipts}
    trial_by_candidate = {event.trial.candidate_hash: event for event in trial_events}
    if set(receipts_by_candidate) != set(P14DQ_CANDIDATE_HASHES) or set(trial_by_candidate) != set(
        P14DQ_CANDIDATE_HASHES
    ):
        raise QualificationError(
            "P14-DQ natural trial accounting differs from the full denominator"
        )

    evaluations: list[P14dqCandidateEvaluation] = []
    for candidate_hash in P14DQ_CANDIDATE_HASHES:
        receipt = receipts_by_candidate[candidate_hash]
        event = trial_by_candidate[candidate_hash]
        if (
            receipt.request.campaign_hash != context.campaign.content_hash
            or receipt.request.candidate.content_hash != candidate_hash
            or receipt.outcome.outcome is not event.trial.outcome
        ):
            raise QualificationError("P14-DQ execution receipt differs from its campaign trial")
        result_hash = receipt.outcome.research_result_hash
        validation_hash = receipt.outcome.validation_report_hash
        if result_hash is None or validation_hash is None:
            raise QualificationError("P14-DQ natural candidate lacks verified result evidence")
        result_path = context.case_root / "execution" / "research-results" / f"sha256-{result_hash}"
        validation_path = (
            context.case_root / "execution" / "validation" / f"sha256-{validation_hash}"
        )
        result = verify_research_result(result_path)
        validation_report = verify_validation_report(validation_path)
        if result.content_hash != result_hash or validation_report.content_hash != validation_hash:
            raise QualificationError("P14-DQ ResearchResult or ValidationReport hash changed")
        evaluations.append(
            P14dqCandidateEvaluation(
                candidate_hash=candidate_hash,
                trial_event_hash=event.content_hash,
                trial_outcome=event.trial.outcome,
                research_result_hash=result_hash,
                validation_report_hash=validation_hash,
                validation_status=validation_report.status,
                validation_verdict=validation_report.verdict,
            )
        )
    if not any(item.trial_outcome is TrialOutcome.PASS for item in evaluations):
        raise QualificationError(
            "both P14-DQ candidates failed Validation; zero eligible candidates "
            "cannot be NO_SELECTION"
        )

    final_ledger = context.ledger.verify(
        context.ledger_id, created_at=p14d.CASE_STARTED_AT + timedelta(days=1)
    )
    if final_ledger.content_hash != loop_report.final_ledger_snapshot_hash:
        raise QualificationError("P14-DQ final Ledger snapshot differs from the loop report")
    if any(
        event.event_type is CampaignEventType.OOS_ACCESSED
        for event in run.events
        if hasattr(event, "event_type")
    ):
        raise QualificationError("P14-DQ campaign emitted OOSAccessed")

    exchanges = tuple(sorted(exchanges, key=lambda item: item.request.run_ordinal))
    ordered_receipts = tuple(receipts_by_candidate[item] for item in P14DQ_CANDIDATE_HASHES)
    return P14dqCampaignEvidence(
        campaign_hash=context.campaign.content_hash,
        family_hash=context.family.content_hash,
        budget_hash=context.budget.content_hash,
        candidate_manifest_hash=context.manifest.content_hash,
        candidate_hashes=P14DQ_CANDIDATE_HASHES,
        context_pack_hashes=tuple(item.request.context_pack.content_hash for item in exchanges),
        agent_request_hashes=tuple(item.request.content_hash for item in exchanges),
        agent_proposal_hashes=tuple(item.response.proposal_hash for item in exchanges),
        execution_request_hashes=tuple(item.request.content_hash for item in ordered_receipts),
        execution_identities=tuple(item.request.execution_identity for item in ordered_receipts),
        evaluations=tuple(evaluations),
        selection_plan_hash=plan.content_hash,
        selection_calendar_hash=calendar.content_hash,
        selection_calendar_session_count=len(calendar.trading_dates),
        selection_calendar_first_date=calendar.trading_dates[0],
        selection_calendar_last_date=calendar.trading_dates[-1],
        selection_report_hash=selection_report.report_hash,
        selection_verdict=selection_report.verdict.value,
        selected_candidate_hash=selection_report.selected_candidate_hash,
        campaign_trial_hashes=tuple(
            trial_by_candidate[item].content_hash for item in P14DQ_CANDIDATE_HASHES
        ),
        campaign_event_hashes=tuple(event.content_hash for event in run.events),
        final_campaign_event_hash=run.events[-1].content_hash,
        final_ledger_snapshot_hash=final_ledger.content_hash,
        ledger_principal_hash=p14d._ledger_principal_hash(final_ledger),
        autonomous_loop_report_hash=loop_report.content_hash,
        loop_state=loop_report.state,
        selection_event_hash=loop_report.selection_event_hash,
        sealed_confirmation_authority=loop_report.sealed_confirmation_authority,
    )


def _replay_case(run: p14d._CaseRun) -> P14dqReplayCaseEvidence:
    context = run.context
    exchanges = p14d._load_exchanges(context.case_root / "agent-exchanges", context.agent_policy)
    first = min(exchanges, key=lambda item: item.request.run_ordinal)
    candidate_hash = run.orchestrator._extract_candidate_hash(  # pyright: ignore[reportPrivateUsage]
        first.response.proposal_bytes
    )
    receipts = p14d._load_receipts(context)
    matches = tuple(
        item for item in receipts if item.request.candidate.content_hash == candidate_hash
    )
    if len(matches) != 1:
        raise QualificationError("P14-DQ replay cannot uniquely link the exchange to its receipt")
    receipt = matches[0]
    store = AutonomousAgentExchangeStore(
        context.case_root / "agent-exchanges", context.agent_policy
    )
    workflow_calls = {"count": 0}
    original = QlibWorkflowResearchService.run

    def count_workflow(self: object, *args: object, **kwargs: object):
        workflow_calls["count"] += 1
        return original(cast(QlibWorkflowResearchService, self), *args, **kwargs)

    with patch.object(QlibWorkflowResearchService, "run", count_workflow):
        response = ReplayAgentDriver(store).run(first.request)
        replayed_outcome = run.adapter.execute(receipt.request)
    if (
        response != first.response
        or response.proposal_hash != first.response.proposal_hash
        or workflow_calls["count"] != 0
        or replayed_outcome.execution_artifact_hash != receipt.content_hash
        or candidate_hash not in run.orchestrator._candidate_by_hash  # pyright: ignore[reportPrivateUsage]
    ):
        raise QualificationError("P14-DQ replay changed proposal or repeated Qlib execution")
    prior_hash = p14d_replay_binding_hash(
        request_hash=first.request.content_hash,
        response_hash=response.content_hash,
        proposal_hash=response.proposal_hash,
        candidate_hash=candidate_hash,
        execution_identity=receipt.request.execution_identity,
    )
    return P14dqReplayCaseEvidence(
        prior_exchange_hash=prior_hash,
        request_hash=first.request.content_hash,
        response_hash=response.content_hash,
        proposal_hash=response.proposal_hash,
        candidate_hash=candidate_hash,
        execution_identity=receipt.request.execution_identity,
        execution_receipt_hash=receipt.content_hash,
        qlib_runs_before_replay=0,
        qlib_runs_after_replay=workflow_calls["count"],
    )


def _reason_code(error: BaseException) -> ReasonCode:
    reason = getattr(error, "reason_code", None)
    if isinstance(reason, ReasonCode):
        return reason
    if isinstance(
        error, (QualificationError, ValidationError, ValueError, OSError, TypeError, KeyError)
    ):
        return ReasonCode.ARTIFACT_CORRUPTED
    raise QualificationError(f"unclassified P14-DQ negative-case exception: {type(error).__name__}")


def _record_dq_negative(
    case_id: str,
    action: Callable[[], object],
    *,
    inputs: _ExternalInputs,
    expected_reason: ReasonCode,
) -> P14dqNegativeCaseEvidence:
    input_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "case_id": case_id,
                "external_bindings_hash": inputs.bindings.content_hash,
                "runner": "p14dq-negative/v1",
            }
        )
    )
    try:
        action()
    except Exception as error:
        observed = _reason_code(error)
        if observed is not expected_reason:
            raise QualificationError(
                f"P14-DQ negative case {case_id} returned {observed}, expected {expected_reason}"
            ) from error
        outcome_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "case_id": case_id,
                    "error_type": type(error).__name__,
                    "reason_code": observed.value,
                }
            )
        )
        return P14dqNegativeCaseEvidence(
            case_id=case_id,
            input_hash=input_hash,
            outcome_hash=outcome_hash,
            reason_code=observed,
        )
    raise QualificationError(f"P14-DQ negative case {case_id} was not rejected")


def _assert_all_rejected(
    actions: Sequence[Callable[[], object]], expected_reason: ReasonCode
) -> None:
    observed: list[tuple[str, str]] = []
    for index, action in enumerate(actions):
        try:
            action()
        except Exception as error:
            try:
                reason = _reason_code(error)
            except QualificationError as unclassified:
                raise InputGateError(
                    ReasonCode.REPRODUCIBILITY_MISMATCH,
                    f"P14-DQ injected variant {index} raised an unclassified failure",
                ) from unclassified
            if reason is not expected_reason:
                raise InputGateError(
                    ReasonCode.REPRODUCIBILITY_MISMATCH,
                    "P14-DQ injected variant "
                    f"{index} returned {reason}, expected {expected_reason}",
                ) from error
            observed.append((type(error).__name__, reason.value))
        else:
            raise InputGateError(
                ReasonCode.REPRODUCIBILITY_MISMATCH,
                f"P14-DQ injected variant {index} was accepted",
            )
    if not observed:
        raise QualificationError("P14-DQ negative case did not execute an injected variant")
    raise InputGateError(expected_reason, f"all {len(observed)} injected variants were rejected")


def _snapshot_file_tamper_negative() -> None:
    source = p14d._single_sha_directory(p14d.FIXTURE_ROOT / "no_selection" / "snapshot")
    actions: list[Callable[[], object]] = []
    with tempfile.TemporaryDirectory(prefix="p14dq-snapshot-mutation-") as temporary_name:
        temporary = Path(temporary_name)
        for kind in ("extra", "missing", "tampered"):
            target = temporary / kind / source.name
            shutil.copytree(source, target)
            manifest = DataSnapshotManifest.model_validate_json(
                (target / "manifest.json").read_bytes()
            )
            if kind == "extra":
                (target / "unexpected-file.txt").write_bytes(b"unexpected")
            elif kind == "missing":
                (target / manifest.files[0].logical_path).unlink()
            else:
                changed = target / manifest.files[0].logical_path
                changed.write_bytes(changed.read_bytes() + b"x")
            actions.append(lambda destination=target: verify_snapshot(destination))
        _assert_all_rejected(actions, ReasonCode.ARTIFACT_CORRUPTED)


def _view_file_set_negative() -> None:
    source = p14d._single_sha_directory(p14d.FIXTURE_ROOT / "no_selection" / "view")
    actions: list[Callable[[], object]] = []
    with tempfile.TemporaryDirectory(prefix="p14dq-view-mutation-") as temporary_name:
        temporary = Path(temporary_name)
        for kind in ("extra", "missing", "tampered"):
            target = temporary / kind / source.name
            shutil.copytree(source, target)
            manifest = QlibViewManifest.model_validate_json((target / "manifest.json").read_bytes())
            if kind == "extra":
                (target / "unexpected-file.txt").write_bytes(b"unexpected")
            elif kind == "missing":
                (target / manifest.files[0].logical_path).unlink()
            else:
                changed = target / manifest.files[0].logical_path
                changed.write_bytes(changed.read_bytes() + b"x")
            actions.append(lambda destination=target: verify_qlib_view(destination))
        _assert_all_rejected(actions, ReasonCode.ARTIFACT_CORRUPTED)


def _check_bundle_external_metadata_mutation(inputs: _ExternalInputs) -> None:
    with tempfile.TemporaryDirectory(prefix="p14dq-bundle-metadata-") as temporary_name:
        root = Path(temporary_name)
        external = root / "external"
        external.mkdir()
        metadata = {
            "snapshot-manifest.json": inputs.snapshot_manifest_bytes,
            "snapshot-quality-report.json": inputs.quality_report_bytes,
            "qlib-view-manifest.json": inputs.view_manifest_bytes,
            "qlib-view-spec.json": inputs.view_spec_bytes,
            "upstream-release-report.json": inputs.release_bytes,
        }
        for name, encoded in metadata.items():
            (external / name).write_bytes(encoded)
        manifest_path = external / "snapshot-manifest.json"
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        _load_bundle_external_metadata(root, inputs.bindings)


def _check_bundle_inventory_mutation(kind: str) -> None:
    with tempfile.TemporaryDirectory(prefix="p14dq-bundle-inventory-") as temporary_name:
        root = Path(temporary_name)
        (root / "qualification-report.json").write_bytes(b"{}")
        body = root / "body.json"
        body.write_bytes(b'{"ok":true}')
        expected_file = P14dqQualificationFile(
            logical_path="body.json",
            sha256=sha256_file(body),
            size_bytes=body.stat().st_size,
        )
        if kind == "extra":
            (root / "extra.json").write_bytes(b"{}")
        elif kind == "missing":
            body.unlink()
        elif kind == "hash-mismatch":
            body.write_bytes(b'{"ok":false}')
        else:
            raise QualificationError("unknown P14-DQ bundle inventory mutation")
        _verify_report_file_set(root, SimpleNamespace(files=(expected_file,)))


def _dq_negative_cases(
    inputs: _ExternalInputs,
    run: p14d._CaseRun,
) -> tuple[P14dqNegativeCaseEvidence, ...]:
    fixture_snapshot = p14d._single_sha_directory(p14d.FIXTURE_ROOT / "no_selection" / "snapshot")
    snapshot_manifest = inputs.snapshot
    view_manifest = inputs.view
    quality = inputs.quality_report
    spec = inputs.view_spec
    release_payload = inputs.release_payload
    report = cast(AutonomousLoopReport, run.report)

    def mutated_release_bytes() -> object:
        wrong_lineage = dict(release_payload)
        wrong_lineage["snapshot_hash"] = "0" * 64
        return _assert_all_rejected(
            (
                lambda: _verify_release_bytes(inputs.release_bytes + b" "),
                lambda: _verify_release_bytes(canonical_json_bytes(wrong_lineage)),
            ),
            ReasonCode.ARTIFACT_CORRUPTED,
        )

    def negative_report_only_handoff() -> object:
        invalid = report.model_copy(
            update={
                "state": AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION,
                "selection_event_hash": "0" * 64,
            }
        )
        _assert_report_only_completion(invalid, run.events)
        return None

    def negative_oos_event() -> object:
        _assert_report_only_completion(
            report,
            (*run.events, SimpleNamespace(event_type=CampaignEventType.OOS_ACCESSED)),
        )
        return None

    def negative_sealed_trial() -> object:
        _assert_report_only_completion(
            report,
            (
                *run.events,
                SimpleNamespace(
                    event_type=CampaignEventType.TRIAL_RECORDED,
                    trial=SimpleNamespace(segment=CampaignSegment.SEALED_CONFIRMATION),
                ),
            ),
        )
        return None

    def negative_sealed_authority() -> object:
        invalid = report.model_copy(update={"sealed_confirmation_authority": True})
        _assert_report_only_completion(invalid, run.events)
        return None

    def negative_selection_frozen_event() -> object:
        _assert_report_only_completion(
            report,
            (
                *run.events,
                SimpleNamespace(
                    event_type=CampaignSelectionEventType.SELECTION_FROZEN,
                ),
            ),
        )
        return None

    def forbidden_handoff_mutations() -> object:
        _assert_all_rejected(
            (
                negative_report_only_handoff,
                negative_oos_event,
                negative_sealed_trial,
                negative_sealed_authority,
                negative_selection_frozen_event,
            ),
            ReasonCode.OOS_POLICY_VIOLATION,
        )
        return None

    def negative_bundle_extra_file() -> object:
        _assert_all_rejected(
            (
                lambda: _check_bundle_inventory_mutation("extra"),
                lambda: _check_bundle_inventory_mutation("missing"),
                lambda: _check_bundle_inventory_mutation("hash-mismatch"),
                lambda: _check_bundle_external_metadata_mutation(inputs),
            ),
            ReasonCode.ARTIFACT_CORRUPTED,
        )
        return None

    def quality_mutations() -> object:
        wrong_hash = snapshot_manifest.model_copy(update={"quality_report_hash": "0" * 64})
        missing_limitation = snapshot_manifest.model_copy(update={"limitations": ()})
        rejected_report = quality.model_copy(update={"passed": False})
        _assert_all_rejected(
            (
                lambda: _verify_quality_report(wrong_hash, quality, inputs.quality_report_bytes),
                lambda: _verify_quality_report(snapshot_manifest, None, None),
                lambda: _verify_quality_report(
                    missing_limitation, quality, inputs.quality_report_bytes
                ),
                lambda: _verify_quality_report(snapshot_manifest, rejected_report, b"{}"),
            ),
            ReasonCode.ARTIFACT_CORRUPTED,
        )
        return None

    def view_identity_mutations() -> object:
        wrong_hash = view_manifest.model_copy(update={"view_hash": "0" * 64})
        _assert_all_rejected(
            (
                lambda: _verify_view_metadata(wrong_hash, snapshot_manifest, spec),
                lambda: _verify_view_metadata(view_manifest, snapshot_manifest, None),
                _view_file_set_negative,
            ),
            ReasonCode.ARTIFACT_CORRUPTED,
        )
        return None

    def view_source_mutation() -> object:
        wrong_source = view_manifest.model_copy(update={"source_snapshot_hash": "0" * 64})
        return _verify_view_metadata(wrong_source, snapshot_manifest, spec)

    def qlib_spec_health_mutations() -> object:
        wrong_spec = spec.model_copy(update={"qlib_version": "0.0.0"})
        wrong_commit = spec.model_copy(update={"qlib_source_commit": "0" * 40})
        wrong_converter = spec.model_copy(update={"dump_bin_sha256": "0" * 64})
        wrong_health = spec.model_copy(update={"health_check_sha256": "0" * 64})
        unhealthy = view_manifest.model_copy(update={"health_check_passed": False})
        failed_samples = view_manifest.model_copy(
            update={
                "semantic_samples": (
                    view_manifest.semantic_samples[0].model_copy(update={"passed": False}),
                    *view_manifest.semantic_samples[1:],
                )
            }
        )
        return _assert_all_rejected(
            (
                lambda: _verify_view_metadata(view_manifest, snapshot_manifest, wrong_spec),
                lambda: _verify_view_metadata(view_manifest, snapshot_manifest, wrong_commit),
                lambda: _verify_view_metadata(view_manifest, snapshot_manifest, wrong_converter),
                lambda: _verify_view_metadata(view_manifest, snapshot_manifest, wrong_health),
                lambda: _verify_view_metadata(unhealthy, snapshot_manifest, spec),
                lambda: _verify_view_metadata(failed_samples, snapshot_manifest, spec),
            ),
            ReasonCode.ARTIFACT_CORRUPTED,
        )

    def root_substitution() -> object:
        return _assert_all_rejected(
            (
                lambda: _require_explicit_path(
                    fixture_snapshot,
                    inputs.snapshot_path,
                    "snapshot",
                ),
                lambda: _require_explicit_path(
                    p14d._single_sha_directory(
                        p14d.FIXTURE_ROOT / "no_selection" / "view"
                    ),
                    inputs.view_path,
                    "Qlib view",
                ),
                lambda: _require_explicit_path(
                    inputs.release_path.with_name("report-substitution.json"),
                    inputs.release_path,
                    "upstream release report",
                ),
                lambda: _assert_root_lineage(
                    snapshot_hash="0" * 64,
                    view_hash=inputs.view.view_hash,
                    release_hash=inputs.bindings.upstream_release_report_hash,
                ),
                lambda: _assert_root_lineage(
                    snapshot_hash=inputs.snapshot.snapshot_hash,
                    view_hash="0" * 64,
                    release_hash=inputs.bindings.upstream_release_report_hash,
                ),
                lambda: _assert_root_lineage(
                    snapshot_hash=inputs.snapshot.snapshot_hash,
                    view_hash=inputs.view.view_hash,
                    release_hash="0" * 64,
                ),
            ),
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
        )

    def unqualified_release() -> object:
        mutations = []
        for key, value in (
            ("status", "FAIL"),
            ("release_track", "UNQUALIFIED"),
            ("data_qualified", False),
            ("snapshot_hash", "0" * 64),
            ("qlib_view_hash", "0" * 64),
            ("validation_verdict", "PASS"),
        ):
            changed = dict(release_payload)
            changed[key] = value
            mutations.append(lambda payload=changed: _verify_release_qualification(payload))
        return _assert_all_rejected(mutations, ReasonCode.CAPABILITY_DENIED)

    def snapshot_hash_path_mismatch() -> object:
        wrong_hash = snapshot_manifest.model_copy(update={"snapshot_hash": "0" * 64})
        return _assert_all_rejected(
            (
                lambda: _require_explicit_path(
                    fixture_snapshot,
                    inputs.snapshot_path,
                    "snapshot",
                ),
                lambda: _verify_snapshot_metadata(wrong_hash),
            ),
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
        )

    def synthetic_snapshot() -> object:
        synthetic = snapshot_manifest.model_copy(
            update={"source_kind": SnapshotSourceKind.SYNTHETIC_FIXTURE}
        )
        alternate_provider = snapshot_manifest.model_copy(update={"provider": "alternate-source"})
        return _assert_all_rejected(
            (
                lambda: _verify_snapshot_metadata(synthetic),
                lambda: _verify_snapshot_metadata(alternate_provider),
            ),
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
        )

    evidence: dict[str, P14dqNegativeCaseEvidence] = {}
    evidence[P14DQ_NEGATIVE_CASES[0]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[0],
        snapshot_hash_path_mismatch,
        inputs=inputs,
        expected_reason=ReasonCode.SNAPSHOT_HASH_MISMATCH,
    )
    evidence[P14DQ_NEGATIVE_CASES[1]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[1],
        synthetic_snapshot,
        inputs=inputs,
        expected_reason=ReasonCode.SNAPSHOT_HASH_MISMATCH,
    )
    evidence[P14DQ_NEGATIVE_CASES[2]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[2],
        _snapshot_file_tamper_negative,
        inputs=inputs,
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    evidence[P14DQ_NEGATIVE_CASES[3]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[3],
        quality_mutations,
        inputs=inputs,
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    evidence[P14DQ_NEGATIVE_CASES[4]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[4],
        view_identity_mutations,
        inputs=inputs,
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    evidence[P14DQ_NEGATIVE_CASES[5]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[5],
        view_source_mutation,
        inputs=inputs,
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    evidence[P14DQ_NEGATIVE_CASES[6]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[6],
        qlib_spec_health_mutations,
        inputs=inputs,
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    evidence[P14DQ_NEGATIVE_CASES[7]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[7],
        mutated_release_bytes,
        inputs=inputs,
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    evidence[P14DQ_NEGATIVE_CASES[8]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[8],
        unqualified_release,
        inputs=inputs,
        expected_reason=ReasonCode.CAPABILITY_DENIED,
    )
    evidence[P14DQ_NEGATIVE_CASES[9]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[9],
        root_substitution,
        inputs=inputs,
        expected_reason=ReasonCode.SNAPSHOT_HASH_MISMATCH,
    )
    evidence[P14DQ_NEGATIVE_CASES[10]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[10],
        forbidden_handoff_mutations,
        inputs=inputs,
        expected_reason=ReasonCode.OOS_POLICY_VIOLATION,
    )
    evidence[P14DQ_NEGATIVE_CASES[11]] = _record_dq_negative(
        P14DQ_NEGATIVE_CASES[11],
        negative_bundle_extra_file,
        inputs=inputs,
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    if tuple(evidence) != P14DQ_NEGATIVE_CASES:
        raise QualificationError("P14-DQ negative case registry is incomplete or unordered")
    return tuple(evidence[case_id] for case_id in P14DQ_NEGATIVE_CASES)


def _tree_inventory_hash(root: Path, *, excluded: frozenset[str] = frozenset()) -> str:
    entries = tuple(
        {
            "logical_path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(path for path in root.rglob("*") if path.is_file())
        if path.relative_to(root).as_posix() not in excluded
    )
    if not entries:
        raise QualificationError("P14-DQ evidence tree is empty")
    return sha256_bytes(canonical_json_bytes(entries))


def _run_root_pipeline(
    root: Path,
    root_id: str,
    inputs: _ExternalInputs,
    policies: _Policies,
    code: CodeProvenance,
    *,
    workspace: Path,
) -> P14dqRootEvidence:
    if root_id not in {"root-A", "root-B"}:
        raise QualificationError("P14-DQ root id is invalid")
    _assert_root_lineage(
        snapshot_hash=inputs.snapshot.snapshot_hash,
        view_hash=inputs.view.view_hash,
        release_hash=inputs.bindings.upstream_release_report_hash,
    )
    context = _build_case_context(root / "natural", inputs, policies, code, workspace=workspace)
    run, restart_cases = _run_natural_with_restarts(context)
    campaign = _campaign_evidence(run)
    p14d_negatives = p14d._run_negative_cases(run)
    # The P14d mismatch case uses a frozen synthetic artifact as an injected substitute only.
    mismatch_copy = context.case_root.parent / "negative-mismatch-fixture"
    if mismatch_copy.exists():
        shutil.rmtree(mismatch_copy)
    dq_negatives = _dq_negative_cases(inputs, run)
    replay = _replay_case(run)
    p14d._strip_runtime_telemetry(root)
    tree_hash = _tree_inventory_hash(root, excluded=frozenset({"root-evidence.json"}))
    evidence = P14dqRootEvidence.create(
        root_id=cast(str, root_id),
        external_bindings_hash=inputs.bindings.content_hash,
        family_hash=P14DQ_FAMILY_HASH,
        candidate_manifest_hash=P14DQ_CANDIDATE_MANIFEST_HASH,
        finalization_profile_hash=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.content_hash,
        autonomous_campaign_policy_hash=context.campaign_policy.content_hash,
        autonomous_agent_run_policy_hash=context.agent_policy.content_hash,
        autonomous_compute_accounting_hash=autonomous_compute_accounting_policy_hash(),
        autonomous_execution_bindings_hash=context.execution_bindings.content_hash,
        multiple_testing_policy_hash=context.selection.multiple_testing_policy.content_hash,
        selection_policy_hash=context.selection.selection_policy.content_hash,
        campaign=campaign,
        p14d_negative_cases=p14d_negatives,
        p14dq_negative_cases=dq_negatives,
        restart_cases=restart_cases,
        replay_case=replay,
        artifact_tree_hash=tree_hash,
    )
    (root / "root-evidence.json").write_bytes(evidence.canonical_bytes())
    return evidence


def _all_file_digests(root: Path) -> tuple[P14dqQualificationFile, ...]:
    entries = sorted(
        (entry for entry in root.rglob("*") if entry.is_file()),
        key=lambda entry: entry.relative_to(root).as_posix(),
    )
    files = tuple(
        P14dqQualificationFile(
            logical_path=entry.relative_to(root).as_posix(),
            sha256=sha256_file(entry),
            size_bytes=entry.stat().st_size,
        )
        for entry in entries
    )
    paths = tuple(item.logical_path for item in files)
    if not files or paths != tuple(sorted(set(paths))):
        raise QualificationError("P14-DQ qualification file inventory is empty or invalid")
    return files


def _verify_p14dq_attempt(
    path: Path,
    *,
    require_content_addressed_name: bool = True,
) -> P14dqQualificationAttempt:
    try:
        report_bytes = (path / "attempt-report.json").read_bytes()
        report = P14dqQualificationAttempt.model_validate_json(report_bytes)
        if (
            (
                require_content_addressed_name
                and path.name != f"sha256-{report.attempt_hash}"
            )
            or report_bytes != canonical_json_bytes(report.model_dump(mode="python"))
        ):
            raise QualificationError("P14-DQ attempt path or canonical bytes do not match")
        tree = regular_tree_files(path)
        expected = {item.logical_path for item in report.files} | {"attempt-report.json"}
        actual = {item.relative_to(path).as_posix() for item in tree}
        if expected != actual:
            raise QualificationError("P14-DQ attempt exact-file inventory differs")
        for item in report.files:
            target = path / item.logical_path
            if (
                target.is_symlink()
                or target.stat().st_size != item.size_bytes
                or sha256_file(target) != item.sha256
            ):
                raise QualificationError("P14-DQ attempt file hash or size differs")
    except QualificationError:
        raise
    except (OSError, ValidationError, ValueError, TypeError) as error:
        raise QualificationError("P14-DQ attempt integrity verification failed") from error
    return report


def _preserve_failed_attempt(
    output_root: Path,
    staging: Path,
    error: BaseException,
) -> Path:
    report_path = staging / "qualification-report.json"
    if report_path.exists():
        report_path.unlink()
    p14d._strip_runtime_telemetry(staging)
    files = (
        _all_file_digests(staging)
        if any(item.is_file() for item in staging.rglob("*"))
        else ()
    )
    reason = getattr(error, "reason_code", ReasonCode.ARTIFACT_CORRUPTED)
    if not isinstance(reason, ReasonCode):
        reason = ReasonCode.ARTIFACT_CORRUPTED
    report = P14dqQualificationAttempt.create(reason_code=reason, files=files)
    encoded = canonical_json_bytes(report.model_dump(mode="python"))
    attempts_root = output_root / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    destination = attempts_root / f"sha256-{report.attempt_hash}"
    if destination.exists():
        stored = _verify_p14dq_attempt(destination)
        if stored != report:
            raise QualificationError("existing P14-DQ attempt conflicts with failed run evidence")
        return destination
    copy_root = Path(tempfile.mkdtemp(prefix=".p14dq-attempt-", dir=attempts_root))
    try:
        shutil.copytree(staging, copy_root, dirs_exist_ok=True)
        (copy_root / "attempt-report.json").write_bytes(encoded)
        copied = _verify_p14dq_attempt(copy_root, require_content_addressed_name=False)
        if copied != report:
            raise QualificationError("copied P14-DQ attempt differs from its inventory")
        publish_directory(copy_root, destination)
    finally:
        if copy_root.exists():
            shutil.rmtree(copy_root)
    return destination


def _verify_report_file_set(path: Path, report: P14dqQualificationReport) -> None:
    try:
        tree = regular_tree_files(path)
    except ArtifactIntegrityError as error:
        raise QualificationError("P14-DQ bundle tree contains an unsafe path") from error
    expected = {item.logical_path for item in report.files} | {"qualification-report.json"}
    actual = {item.relative_to(path).as_posix() for item in tree}
    if actual != expected:
        raise QualificationError("P14-DQ bundle exact-file set differs from its report")
    for item in report.files:
        target = path / item.logical_path
        if target.is_symlink() or target.stat().st_size != item.size_bytes:
            raise QualificationError("P14-DQ bundle file size or type differs from its manifest")
        if sha256_file(target) != item.sha256:
            raise QualificationError("P14-DQ bundle file hash differs from its manifest")


def _write_external_metadata(staging: Path, inputs: _ExternalInputs) -> None:
    external = staging / "external"
    external.mkdir(parents=True, exist_ok=True)
    (external / "snapshot-manifest.json").write_bytes(inputs.snapshot_manifest_bytes)
    (external / "snapshot-quality-report.json").write_bytes(inputs.quality_report_bytes)
    (external / "qlib-view-manifest.json").write_bytes(inputs.view_manifest_bytes)
    (external / "qlib-view-spec.json").write_bytes(inputs.view_spec_bytes)
    (external / "upstream-release-report.json").write_bytes(inputs.release_bytes)


def _write_frozen_provenance(
    staging: Path,
    workspace: Path,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
) -> None:
    (staging / "code-provenance.json").write_bytes(code.canonical_bytes())
    (staging / "runtime-fingerprint.json").write_bytes(runtime.canonical_bytes())
    frozen = staging / "frozen"
    frozen.mkdir(exist_ok=True)
    shutil.copyfile(workspace / "uv.lock", frozen / "uv.lock")
    shutil.copyfile(workspace / CONTRACT_PATH, frozen / "p14-dq-qualification-contract.md")
    policy_root = frozen / "policies"
    policy_root.mkdir(parents=True, exist_ok=True)
    for name, relative in POLICY_PATHS.items():
        shutil.copyfile(workspace / relative, policy_root / f"{name}.yaml")


def _policy_hashes(
    *,
    policies: _Policies,
    root: P14dqRootEvidence,
    contract_hash: str,
) -> tuple[P14dqNamedHash, ...]:
    family_template_manifest = _p14dq_family_manifest()
    template, family, manifest = family_template_manifest
    values = [
        P14dqNamedHash(
            name="autonomous_agent_run_policy", sha256=root.autonomous_agent_run_policy_hash
        ),
        P14dqNamedHash(
            name="autonomous_campaign_policy", sha256=root.autonomous_campaign_policy_hash
        ),
        P14dqNamedHash(
            name="autonomous_compute_accounting", sha256=root.autonomous_compute_accounting_hash
        ),
        P14dqNamedHash(
            name="autonomous_execution_bindings", sha256=root.autonomous_execution_bindings_hash
        ),
        P14dqNamedHash(name="backtest_policy", sha256=policies.backtest.content_hash),
        P14dqNamedHash(name="candidate_manifest", sha256=manifest.content_hash),
        P14dqNamedHash(name="cost_policy", sha256=policies.cost.content_hash),
        P14dqNamedHash(name="execution_authoring", sha256=policies.authoring.content_hash),
        P14dqNamedHash(
            name="finalization_profile",
            sha256=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.content_hash,
        ),
        P14dqNamedHash(name="multiple_testing_policy", sha256=root.multiple_testing_policy_hash),
        P14dqNamedHash(name="p14c_selection_plan", sha256=root.campaign.selection_plan_hash),
        P14dqNamedHash(name="p14dq_family", sha256=family.content_hash),
        P14dqNamedHash(name="p14dq_qualification_contract", sha256=contract_hash),
        P14dqNamedHash(name="p14dq_template", sha256=template.content_hash),
        P14dqNamedHash(name="research_policy", sha256=policies.research.content_hash),
        P14dqNamedHash(name="selection_policy", sha256=root.selection_policy_hash),
        P14dqNamedHash(name="validation_policy", sha256=policies.validation.content_hash),
        *policies.file_hashes,
    ]
    values = sorted(values, key=lambda item: item.name)
    if len({item.name for item in values}) != len(values):
        raise QualificationError("P14-DQ policy hash names are duplicated")
    return tuple(values)


def _stage_qualification(
    staging: Path,
    *,
    inputs: _ExternalInputs,
    policies: _Policies,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
) -> P14dqQualificationReport:
    _write_external_metadata(staging, inputs)
    _write_frozen_provenance(staging, ROOT, code, runtime)
    p14d._strip_runtime_telemetry(staging)
    files = _all_file_digests(staging)
    roots = tuple(
        P14dqRootEvidence.model_validate_json(
            (staging / root_name / "root-evidence.json").read_bytes()
        )
        for root_name in ("root-A", "root-B")
    )
    contract_hash = _frozen_contract_hash(ROOT)
    report = P14dqQualificationReport.create(
        implementation_commit_hash=code.commit_hash,
        code_provenance_hash=code.content_hash,
        lockfile_hash=code.lockfile_hash,
        runtime_fingerprint_hash=runtime.content_hash,
        qualification_contract_hash=contract_hash,
        external_bindings=inputs.bindings,
        family_hash=P14DQ_FAMILY_HASH,
        candidate_manifest_hash=P14DQ_CANDIDATE_MANIFEST_HASH,
        finalization_profile=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
        policy_hashes=_policy_hashes(policies=policies, root=roots[0], contract_hash=contract_hash),
        roots=cast(tuple[P14dqRootEvidence, P14dqRootEvidence], roots),
        principal_hash_summary=p14dq_principal_hash_summary(
            cast(tuple[P14dqRootEvidence, P14dqRootEvidence], roots)
        ),
        p14d_negative_case_count=len(P14D_NEGATIVE_CASES) * len(roots),
        p14dq_negative_case_count=len(P14DQ_NEGATIVE_CASES) * len(roots),
        restart_case_count=len(P14DQ_RESTART_CASES) * len(roots),
        limitations=P14DQ_LIMITATIONS,
        files=files,
    )
    (staging / "qualification-report.json").write_bytes(
        canonical_json_bytes(report.model_dump(mode="python"))
    )
    return report


def _publish_qualification(
    output_root: Path,
    staging: Path,
    report: P14dqQualificationReport,
) -> P14dqQualificationReport:
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"sha256-{report.qualification_hash}"
    if destination.exists():
        stored = verify_p14dq_bundle_integrity(destination)
        if stored != report:
            raise QualificationError("existing P14-DQ bundle conflicts with deterministic output")
        return stored
    copy_root = Path(tempfile.mkdtemp(prefix=".p14dq-publish-", dir=output_root))
    try:
        shutil.copytree(staging, copy_root, dirs_exist_ok=True)
        copied_report = _verify_p14dq_bundle_integrity(
            copy_root, require_content_addressed_name=False
        )
        if copied_report != report:
            raise QualificationError("copied P14-DQ bundle differs from its verified staging tree")
        publish_directory(copy_root, destination)
    finally:
        if copy_root.exists():
            shutil.rmtree(copy_root)
    return report


def _verify_reproducible_roots(
    roots: tuple[P14dqRootEvidence, P14dqRootEvidence],
    *,
    workspace: Path,
    implementation_commit_hash: str,
    lockfile_hash: str,
    runtime_fingerprint_hash: str,
    external_bindings: P14dqExternalBindings,
    snapshot_path: Path,
    view_path: Path,
    release_report_path: Path,
) -> None:
    workspace = workspace.resolve(strict=True)
    if workspace != ROOT.resolve():
        raise QualificationError("P14-DQ verifier workspace must be the runner's repository root")
    code = verify_code_provenance(
        workspace,
        expected_commit_hash=implementation_commit_hash,
        expected_lockfile_hash=lockfile_hash,
    )
    runtime = capture_runtime_fingerprint()
    if runtime.content_hash != runtime_fingerprint_hash:
        raise QualificationError("P14-DQ runtime fingerprint differs from the report")
    inputs = verify_external_inputs(
        workspace=workspace,
        snapshot_path=snapshot_path,
        view_path=view_path,
        release_report_path=release_report_path,
    )
    if inputs.bindings != external_bindings:
        raise QualificationError("explicit external inputs differ from the frozen report bindings")
    policies = _load_policies(workspace)
    with tempfile.TemporaryDirectory(prefix="p14dq-qualification-verify-") as temporary_name:
        temporary = Path(temporary_name)
        rebuilt_a = _run_root_pipeline(
            temporary / "root-A", "root-A", inputs, policies, code, workspace=workspace
        )
        rebuilt_b = _run_root_pipeline(
            temporary / "root-B", "root-B", inputs, policies, code, workspace=workspace
        )
    if rebuilt_a != roots[0] or rebuilt_b != roots[1]:
        raise QualificationError("P14-DQ roots did not reproduce from explicit external inputs")


def _qualify_from_provenance(
    *,
    workspace: Path,
    output_root: Path,
    snapshot_path: Path,
    view_path: Path,
    release_report_path: Path,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
) -> dict[str, object]:
    _frozen_contract_hash(workspace)
    inputs = verify_external_inputs(
        workspace=workspace,
        snapshot_path=snapshot_path,
        view_path=view_path,
        release_report_path=release_report_path,
    )
    policies = _load_policies(workspace)
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p14dq-roots-") as temporary_name:
        staging = Path(temporary_name) / "bundle"
        staging.mkdir()
        root_a = staging / "root-A"
        root_b = staging / "root-B"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        try:
            evidence_a = _run_root_pipeline(
                root_a, "root-A", inputs, policies, code, workspace=workspace
            )
            evidence_b = _run_root_pipeline(
                root_b, "root-B", inputs, policies, code, workspace=workspace
            )
            if evidence_a != evidence_b.model_copy(update={"root_id": evidence_a.root_id}):
                raise QualificationError(
                    "independent P14-DQ roots produced different principal evidence"
                )
            (root_a / "root-evidence.json").write_bytes(evidence_a.canonical_bytes())
            (root_b / "root-evidence.json").write_bytes(evidence_b.canonical_bytes())
            _verify_reproducible_roots(
                (evidence_a, evidence_b),
                workspace=workspace,
                implementation_commit_hash=code.commit_hash,
                lockfile_hash=code.lockfile_hash,
                runtime_fingerprint_hash=runtime.content_hash,
                external_bindings=inputs.bindings,
                snapshot_path=snapshot_path,
                view_path=view_path,
                release_report_path=release_report_path,
            )
            report = _stage_qualification(
                staging,
                inputs=inputs,
                policies=policies,
                code=code,
                runtime=runtime,
            )
            staged_report = _verify_p14dq_bundle_integrity(
                staging, require_content_addressed_name=False
            )
            if staged_report != report:
                raise QualificationError("staged P14-DQ report failed its integrity gate")
            verified = _publish_qualification(output_root, staging, report)
        except Exception as error:
            try:
                attempt_path = _preserve_failed_attempt(output_root, staging, error)
            except Exception as preserve_error:
                error.add_note(
                    "P14-DQ failed-attempt evidence could not be preserved: "
                    f"{type(preserve_error).__name__}"
                )
                raise
            raise QualificationAttemptError(error, attempt_path) from error
    artifact_path = output_root / f"sha256-{verified.qualification_hash}"
    return {
        "schema_version": "p14dq-qualification-runner-result/v1",
        "qualification_hash": verified.qualification_hash,
        "qualification_path": str(artifact_path),
        "implementation_commit_hash": verified.implementation_commit_hash,
        "lockfile_hash": verified.lockfile_hash,
        "runtime_fingerprint_hash": verified.runtime_fingerprint_hash,
        "external_bindings_hash": verified.external_bindings.content_hash,
        "principal_hash_summary": verified.principal_hash_summary,
        "principal_hashes_byte_exact": verified.principal_hashes_byte_exact,
        "natural_selection_verdict": verified.roots[0].campaign.selection_verdict,
        "p14d_negative_case_count": verified.p14d_negative_case_count,
        "p14dq_negative_case_count": verified.p14dq_negative_case_count,
        "restart_case_count": verified.restart_case_count,
        "status": verified.status,
        "verdict": verified.verdict,
    }


def run(
    *,
    workspace: Path,
    output_root: Path,
    snapshot_path: Path,
    view_path: Path,
    release_report_path: Path,
) -> dict[str, object]:
    """Run both independent roots from explicit immutable upstream paths and clean code."""

    workspace = workspace.resolve(strict=True)
    if workspace != ROOT.resolve():
        raise QualificationError("P14-DQ workspace must be the runner's repository root")
    code = capture_code_provenance(workspace)
    runtime = capture_runtime_fingerprint()
    return _qualify_from_provenance(
        workspace=workspace,
        output_root=output_root,
        snapshot_path=snapshot_path,
        view_path=view_path,
        release_report_path=release_report_path,
        code=code,
        runtime=runtime,
    )


def _load_bundle_external_metadata(path: Path, bindings: P14dqExternalBindings) -> None:
    external = path / "external"
    try:
        snapshot_manifest_bytes = (external / "snapshot-manifest.json").read_bytes()
        quality_bytes = (external / "snapshot-quality-report.json").read_bytes()
        view_manifest_bytes = (external / "qlib-view-manifest.json").read_bytes()
        view_spec_bytes = (external / "qlib-view-spec.json").read_bytes()
        release_bytes = (external / "upstream-release-report.json").read_bytes()
        snapshot = DataSnapshotManifest.model_validate_json(snapshot_manifest_bytes)
        quality = DataQualityReport.model_validate_json(quality_bytes)
        view = QlibViewManifest.model_validate_json(view_manifest_bytes)
        view_spec = QlibViewSpec.model_validate_json(view_spec_bytes)
    except (OSError, ValidationError, ValueError) as error:
        raise QualificationError(
            "P14-DQ bundle external metadata is missing or malformed"
        ) from error
    if (
        snapshot_manifest_bytes != _canonical_model_file(snapshot)
        or quality_bytes != quality.canonical_bytes()
        or view_manifest_bytes != _canonical_model_file(view)
        or view_spec_bytes != view_spec.canonical_bytes()
    ):
        raise QualificationError("P14-DQ bundle contains noncanonical external metadata")
    _verify_snapshot_metadata(snapshot)
    _verify_quality_report(snapshot, quality, quality_bytes)
    _verify_view_metadata(view, snapshot, view_spec)
    release_payload = _verify_release_bytes(release_bytes)
    release_input_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "data_qualified": release_payload.get("data_qualified"),
                "release_track": release_payload.get("release_track"),
                "snapshot_hash": release_payload.get("snapshot_hash"),
                "status": release_payload.get("status"),
                "view_hash": release_payload.get("qlib_view_hash"),
            }
        )
    )
    if (
        sha256_bytes(snapshot_manifest_bytes) != bindings.snapshot_manifest_file_hash
        or _manifest_inventory_hash(snapshot.files) != bindings.snapshot_files_inventory_hash
        or snapshot.snapshot_hash != bindings.snapshot_hash
        or sha256_bytes(quality_bytes) != bindings.quality_report_file_hash
        or quality.content_hash != bindings.quality_report_hash
        or sha256_bytes(view_manifest_bytes) != bindings.qlib_view_manifest_file_hash
        or _manifest_inventory_hash(view.files) != bindings.qlib_view_files_inventory_hash
        or view.view_hash != bindings.qlib_view_hash
        or view.view_spec_hash != bindings.view_spec_hash
        or sha256_bytes(view_spec_bytes) != bindings.view_spec_file_hash
        or view.qlib_version != bindings.qlib_version
        or view.qlib_source_commit != bindings.qlib_source_commit
        or view.dump_bin_sha256 != bindings.dump_bin_sha256
        or view.health_check_sha256 != bindings.health_check_sha256
        or _view_manifest_bindings_hash(view) != bindings.qlib_view_manifest_bindings_hash
        or sha256_bytes(release_bytes) != bindings.upstream_release_report_hash
        or release_input_hash != bindings.upstream_release_input_hash
    ):
        raise QualificationError("P14-DQ bundle external identities differ from the report")


def _load_frozen_policy_bundle(path: Path) -> _Policies:
    policy_root = path / "frozen" / "policies"
    loaded: dict[str, object] = {}
    file_hashes: list[P14dqNamedHash] = []
    contract_hashes: list[P14dqNamedHash] = []
    try:
        for name, contract_type_raw in POLICY_FILES.items():
            policy_path = policy_root / f"{name}.yaml"
            raw_hash = sha256_file(policy_path)
            if raw_hash != FROZEN_POLICY_FILE_HASHES[name]:
                raise QualificationError(f"frozen P14-DQ {name} policy bytes differ from baseline")
            file_hashes.append(P14dqNamedHash(name=f"{name}_file", sha256=raw_hash))
            contract_type = cast(type[object], contract_type_raw)
            contract = load_yaml_contract(policy_path, contract_type)
            loaded[name] = contract
            contract_hashes.append(
                P14dqNamedHash(name=name, sha256=cast(object, contract).content_hash)  # type: ignore[attr-defined]
            )
    except (OSError, ValidationError, ValueError) as error:
        raise QualificationError("P14-DQ frozen policy bytes are invalid") from error
    research = cast(ResearchPolicy, loaded["research_policy"])
    authoring = cast(ExperimentAuthoringSpec, loaded["execution_authoring"])
    _assert_frozen_policy_periods(research, authoring)
    return _Policies(
        research=research,
        validation=cast(ValidationPolicy, loaded["validation_policy"]),
        cost=cast(CostPolicy, loaded["cost_policy"]),
        backtest=cast(BacktestPolicy, loaded["backtest_policy"]),
        authoring=authoring,
        file_hashes=tuple(sorted(file_hashes, key=lambda item: item.name)),
        contract_hashes=tuple(sorted(contract_hashes, key=lambda item: item.name)),
    )


def _verify_p14dq_bundle_integrity(
    path: Path,
    *,
    require_content_addressed_name: bool,
) -> P14dqQualificationReport:
    """Verify bundle bytes; optionally enforce their final content-addressed path."""

    try:
        report_bytes = (path / "qualification-report.json").read_bytes()
        report = P14dqQualificationReport.model_validate_json(report_bytes)
        if (
            (
                require_content_addressed_name
                and path.name != f"sha256-{report.qualification_hash}"
            )
            or canonical_json_bytes(report.model_dump(mode="python")) != report_bytes
        ):
            raise QualificationError("P14-DQ report path or canonical bytes do not match")
        _verify_report_file_set(path, report)
        code_bytes = (path / "code-provenance.json").read_bytes()
        runtime_bytes = (path / "runtime-fingerprint.json").read_bytes()
        code = CodeProvenance.model_validate_json(code_bytes)
        runtime = RuntimeFingerprint.model_validate_json(runtime_bytes)
        if (
            code_bytes != code.canonical_bytes()
            or runtime_bytes != runtime.canonical_bytes()
            or code.content_hash != report.code_provenance_hash
            or code.commit_hash != report.implementation_commit_hash
            or code.lockfile_hash != report.lockfile_hash
            or sha256_file(path / "frozen" / "uv.lock") != report.lockfile_hash
            or runtime.content_hash != report.runtime_fingerprint_hash
            or report.qualification_contract_hash != FROZEN_CONTRACT_SHA256
            or sha256_file(path / "frozen" / "p14-dq-qualification-contract.md")
            != report.qualification_contract_hash
        ):
            raise QualificationError(
                "P14-DQ code, runtime, lockfile or contract provenance differs"
            )
        _load_bundle_external_metadata(path, report.external_bindings)
        policies = _load_frozen_policy_bundle(path)
        _p14dq_family_manifest()
        roots: list[P14dqRootEvidence] = []
        for root_name in ("root-A", "root-B"):
            root_path = path / root_name
            evidence_bytes = (root_path / "root-evidence.json").read_bytes()
            evidence = P14dqRootEvidence.model_validate_json(evidence_bytes)
            if evidence_bytes != evidence.canonical_bytes():
                raise QualificationError("P14-DQ root evidence is noncanonical")
            actual_tree_hash = _tree_inventory_hash(
                root_path, excluded=frozenset({"root-evidence.json"})
            )
            if actual_tree_hash != evidence.artifact_tree_hash:
                raise QualificationError("P14-DQ root artifact inventory hash differs")
            roots.append(evidence)
        if tuple(roots) != report.roots:
            raise QualificationError(
                "P14-DQ report roots differ from their canonical evidence files"
            )
        expected_policy_hashes = _policy_hashes(
            policies=policies,
            root=roots[0],
            contract_hash=report.qualification_contract_hash,
        )
        if report.policy_hashes != expected_policy_hashes:
            raise QualificationError("P14-DQ frozen policy hashes do not reproduce")
    except QualificationError:
        raise
    except (OSError, ValidationError, ValueError, TypeError, KeyError) as error:
        raise QualificationError("P14-DQ bundle integrity verification failed") from error
    return report


def verify_p14dq_bundle_integrity(path: Path) -> P14dqQualificationReport:
    """Verify the immutable P14-DQ bundle without claiming external inputs are present."""

    return _verify_p14dq_bundle_integrity(path, require_content_addressed_name=True)


def verify_p14dq_qualification_artifact(
    path: Path,
    *,
    workspace: Path,
    snapshot_path: Path,
    view_path: Path,
    release_report_path: Path,
) -> P14dqQualificationReport:
    """Verify bundle integrity, reverify external inputs, then rebuild both roots."""

    report = verify_p14dq_bundle_integrity(path)
    _verify_reproducible_roots(
        report.roots,
        workspace=workspace,
        implementation_commit_hash=report.implementation_commit_hash,
        lockfile_hash=report.lockfile_hash,
        runtime_fingerprint_hash=report.runtime_fingerprint_hash,
        external_bindings=report.external_bindings,
        snapshot_path=snapshot_path,
        view_path=view_path,
        release_report_path=release_report_path,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run both independent qualification roots")
    run_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    run_parser.add_argument(
        "--snapshot-path", type=Path, required=True, help="explicit frozen snapshot directory"
    )
    run_parser.add_argument(
        "--qlib-view-path", type=Path, required=True, help="explicit frozen Qlib-view directory"
    )
    run_parser.add_argument(
        "--upstream-release-report",
        type=Path,
        required=True,
        help="explicit frozen P2-P7 Data-qualified report",
    )
    run_parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/qualification/p14-dq")
    )
    verify_parser = subparsers.add_parser(
        "verify", help="verify bundle and rebuild both roots from explicit upstream inputs"
    )
    verify_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    verify_parser.add_argument("--artifact", type=Path, required=True)
    verify_parser.add_argument("--snapshot-path", type=Path, required=True)
    verify_parser.add_argument("--qlib-view-path", type=Path, required=True)
    verify_parser.add_argument("--upstream-release-report", type=Path, required=True)
    bundle_parser = subparsers.add_parser(
        "verify-bundle", help="verify bundle bytes and recorded upstream identities only"
    )
    bundle_parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            result = run(
                workspace=args.workspace,
                output_root=args.output_root,
                snapshot_path=args.snapshot_path,
                view_path=args.qlib_view_path,
                release_report_path=args.upstream_release_report,
            )
        elif args.command == "verify":
            report = verify_p14dq_qualification_artifact(
                args.artifact,
                workspace=args.workspace,
                snapshot_path=args.snapshot_path,
                view_path=args.qlib_view_path,
                release_report_path=args.upstream_release_report,
            )
            result = {
                "schema_version": "p14dq-qualification-verification/v1",
                "qualification_hash": report.qualification_hash,
                "status": report.status,
                "verdict": report.verdict,
                "external_bindings_hash": report.external_bindings.content_hash,
                "principal_hash_summary": report.principal_hash_summary,
            }
        else:
            report = verify_p14dq_bundle_integrity(args.artifact)
            result = {
                "schema_version": "p14dq-bundle-verification/v1",
                "qualification_hash": report.qualification_hash,
                "status": report.status,
                "verdict": report.verdict,
                "external_bindings_hash": report.external_bindings.content_hash,
                "external_inputs_reverified": False,
            }
    except Exception as error:
        reason = getattr(error, "reason_code", None)
        result = {
            "schema_version": "p14dq-qualification-runner-result/v1",
            "status": RunStatus.FAILED,
            "verdict": ValidationVerdict.NOT_EVALUATED,
            "reason_code": reason.value
            if isinstance(reason, ReasonCode)
            else ReasonCode.ARTIFACT_CORRUPTED.value,
            "error": str(error),
        }
        attempt_path = getattr(error, "attempt_path", None)
        if isinstance(attempt_path, str):
            result["attempt_path"] = attempt_path
        print(json.dumps(result, sort_keys=True, default=str))
        raise SystemExit(1) from error
    print(json.dumps(result, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
