"""Deterministic command-line entry point."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, TypeVar, cast

import typer

from quantos.application.campaign_selection import (
    CampaignSelectionError,
    CampaignSelectionService,
)
from quantos.application.capabilities import publish_capability_report
from quantos.application.doctor import build_doctor_report
from quantos.application.pit import PITAuditService, load_canonical_pit_request_json
from quantos.config import load_yaml_contract, load_yaml_mapping
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSpec,
    ResearchFamilySpec,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    MultipleTestingPolicySpec,
    SelectionPolicySpec,
)
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.enumeration import CandidateEnumerationManifest, ResearchFactorTemplateSpec
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    ValidationPolicy,
)
from quantos.contracts.snapshot import DataQualityPolicy, SnapshotBuildSpec
from quantos.contracts.status import ReasonCode
from quantos.data import (
    QlibViewBuilder,
    QlibViewBuildError,
    SnapshotBuildError,
    SyntheticSnapshotBuilder,
    verify_qlib_view,
    verify_snapshot,
)
from quantos.data.tushare import (
    LiveTushareAcquisitionService,
    LiveTushareSnapshotBuilder,
    TushareAcquisitionError,
    TushareExecutionPolicy,
    TusharePlanExecutor,
    TushareSnapshotSource,
)
from quantos.validation.locators import ValidationRunLocators

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
tushare_app = typer.Typer(no_args_is_help=True)
snapshot_app = typer.Typer(no_args_is_help=True)
qlib_app = typer.Typer(no_args_is_help=True)
pit_app = typer.Typer(no_args_is_help=True)
backtest_app = typer.Typer(no_args_is_help=True)
experiment_app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
ledger_app = typer.Typer(no_args_is_help=True)
release_app = typer.Typer(no_args_is_help=True)
campaign_app = typer.Typer(no_args_is_help=True)
app.add_typer(tushare_app, name="tushare")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(qlib_app, name="qlib")
app.add_typer(pit_app, name="pit")
app.add_typer(backtest_app, name="backtest")
app.add_typer(experiment_app, name="experiment")
app.add_typer(registry_app, name="registry")
app.add_typer(ledger_app, name="ledger")
app.add_typer(release_app, name="release")
app.add_typer(campaign_app, name="campaign")

C = TypeVar("C", bound=CanonicalContract)


def _campaign_selection_inputs(
    campaign_path: Path,
    family_path: Path,
    budget_path: Path,
    template_path: Path,
    manifest_path: Path,
    multiple_testing_policy_path: Path,
    selection_policy_path: Path,
    event_chain_path: Path,
    qlib_view_path: Path,
    research_results_root: Path,
) -> tuple[
    CampaignSelectionService,
    tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...],
]:
    campaign = ResearchCampaignSpec.model_validate_json(campaign_path.read_bytes())
    family = ResearchFamilySpec.model_validate_json(family_path.read_bytes())
    budget = ResearchBudgetSpec.model_validate_json(budget_path.read_bytes())
    template = ResearchFactorTemplateSpec.model_validate_json(template_path.read_bytes())
    manifest = CandidateEnumerationManifest.model_validate_json(manifest_path.read_bytes())
    multiple_testing_policy = MultipleTestingPolicySpec.model_validate_json(
        multiple_testing_policy_path.read_bytes()
    )
    selection_policy = SelectionPolicySpec.model_validate_json(selection_policy_path.read_bytes())
    raw_payload: object = json.loads(event_chain_path.read_bytes())
    if not isinstance(raw_payload, list):
        raise ValueError("campaign event chain must be a JSON array")
    events: list[ResearchCampaignEvent | CampaignSelectionEvent] = []
    for raw_item in cast(list[object], raw_payload):
        if not isinstance(raw_item, dict):
            raise ValueError("campaign event chain contains a non-object value")
        item = cast(dict[str, object], raw_item)
        schema_version = item.get("schema_version")
        if schema_version == "research-campaign-event/v1":
            events.append(ResearchCampaignEvent.model_validate(item))
        elif schema_version == "campaign-selection-event/v1":
            events.append(CampaignSelectionEvent.model_validate(item))
        else:
            raise ValueError("campaign event chain contains an unsupported event schema")
    service = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple_testing_policy,
        selection_policy,
        qlib_view_path,
        (research_results_root,),
    )
    return service, tuple(events)


def _campaign_selection_command_inputs(
    campaign_path: Path,
    family_path: Path,
    budget_path: Path,
    template_path: Path,
    manifest_path: Path,
    multiple_testing_policy_path: Path,
    selection_policy_path: Path,
    event_chain_path: Path,
    qlib_view_path: Path,
    research_results_root: Path,
) -> tuple[
    CampaignSelectionService,
    tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...],
]:
    try:
        return _campaign_selection_inputs(
            campaign_path,
            family_path,
            budget_path,
            template_path,
            manifest_path,
            multiple_testing_policy_path,
            selection_policy_path,
            event_chain_path,
            qlib_view_path,
            research_results_root,
        )
    except (OSError, ValueError) as error:
        raise CampaignSelectionError(
            ReasonCode.SCHEMA_INVALID,
            "campaign selection inputs cannot be loaded",
        ) from error


@app.command()
def doctor() -> None:
    """Report offline and Data-qualified readiness without exposing secrets."""

    report = build_doctor_report()
    typer.echo(json.dumps(report.model_dump(mode="json"), sort_keys=True, ensure_ascii=False))
    if report.offline_status == "BLOCKED":
        raise typer.Exit(code=1)


@campaign_app.command("selection-report")
def campaign_selection_report(
    campaign_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    family_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    budget_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    template_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    multiple_testing_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    selection_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    event_chain_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    qlib_view_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    research_results_root: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, readable=True)
    ],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Parent for the immutable hash-addressed selection report.",
        ),
    ] = Path("artifacts/reports/campaign-selection"),
) -> None:
    """Recompute and publish a deterministic campaign selection report."""

    try:
        service, events = _campaign_selection_command_inputs(
            campaign_path,
            family_path,
            budget_path,
            template_path,
            manifest_path,
            multiple_testing_policy_path,
            selection_policy_path,
            event_chain_path,
            qlib_view_path,
            research_results_root,
        )
        report, path = service.publish_report(events, output_root)
    except CampaignSelectionError as error:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": error.reason_code,
                    "detail": str(error),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=22) from error
    typer.echo(
        json.dumps(
            {
                "status": report.run_status.value,
                "verdict": report.verdict.value,
                "report_hash": report.report_hash,
                "artifact_path": str(path),
            },
            sort_keys=True,
        )
    )
    if report.verdict.value == "NOT_EVALUATED":
        raise typer.Exit(code=23)


@campaign_app.command("selection-verify")
def campaign_selection_verify(
    report_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    campaign_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    family_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    budget_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    template_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    multiple_testing_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    selection_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    event_chain_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    qlib_view_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    research_results_root: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, readable=True)
    ],
) -> None:
    """Verify report bytes and rebuild the verdict from all explicit frozen inputs."""

    try:
        service, events = _campaign_selection_command_inputs(
            campaign_path,
            family_path,
            budget_path,
            template_path,
            manifest_path,
            multiple_testing_policy_path,
            selection_policy_path,
            event_chain_path,
            qlib_view_path,
            research_results_root,
        )
        report = service.verify_report(report_path, events)
    except CampaignSelectionError as error:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": error.reason_code,
                    "detail": str(error),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=22) from error
    typer.echo(
        json.dumps(
            {
                "status": "PASS",
                "verdict": report.verdict.value,
                "report_hash": report.report_hash,
            },
            sort_keys=True,
        )
    )


@tushare_app.command("probe")
def tushare_probe(
    evidence_root: Annotated[
        Path,
        typer.Option(
            "--evidence-root",
            file_okay=False,
            help="Root directory for immutable, secret-free capability evidence.",
        ),
    ] = Path("artifacts/evidence"),
) -> None:
    """Report whether a live capability probe can be attempted."""

    report = build_doctor_report()
    if not report.tushare_token_configured:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "capability-report/v1",
                    "status": "BLOCKED",
                    "reason_code": "TUSHARE_TOKEN_MISSING",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=2)

    token = os.environ["TUSHARE_TOKEN"]
    report = TushareSnapshotSource(token).probe_capabilities()
    evidence = publish_capability_report(report, evidence_root)
    payload = report.model_dump(mode="json")
    payload["evidence"] = evidence.model_dump(mode="json")
    typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    if not report.all_required_available:
        raise typer.Exit(code=4)


@snapshot_app.command("build-synthetic")
def build_synthetic_snapshot(
    fixture_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Parent directory for content-addressed snapshots.",
        ),
    ] = Path("artifacts/data/snapshots"),
) -> None:
    """Build the locked offline snapshot slice from a synthetic fixture."""

    try:
        result = SyntheticSnapshotBuilder().build(fixture_root, output_root)
    except SnapshotBuildError as error:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "snapshot-build-result/v1",
                    "status": "FAILED",
                    "reason_code": error.reason_code,
                    "detail": str(error),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=5) from error
    typer.echo(
        json.dumps(
            {
                "schema_version": "snapshot-build-result/v1",
                "status": "SUCCEEDED",
                "snapshot": result.reference.model_dump(mode="json"),
                "quality_report_hash": result.quality_report.content_hash,
            },
            sort_keys=True,
        )
    )


@snapshot_app.command("build-tushare")
def build_tushare_snapshot(
    spec_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    execution_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    quality_policy_path: Annotated[
        Path | None,
        typer.Option(
            "--quality-policy",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional explicit live-data quality policy.",
        ),
    ] = None,
    acquisition_root: Annotated[
        Path,
        typer.Option(
            "--acquisition-root",
            file_okay=False,
            help="Parent for hash-addressed resumable acquisition checkpoints.",
        ),
    ] = Path("artifacts/acquisition/tushare"),
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Parent directory for content-addressed snapshots.",
        ),
    ] = Path("artifacts/data/snapshots"),
) -> None:
    """Acquire through Tushare only, then publish through the offline snapshot gates."""

    if "TUSHARE_TOKEN" not in os.environ:
        typer.echo(
            json.dumps(
                {"status": "BLOCKED", "reason_code": "TUSHARE_TOKEN_MISSING"},
                sort_keys=True,
            )
        )
        raise typer.Exit(code=2)
    try:
        spec = load_yaml_contract(spec_path, SnapshotBuildSpec)
        policy = load_yaml_contract(execution_policy_path, TushareExecutionPolicy)
        quality_policy = (
            load_yaml_contract(quality_policy_path, DataQualityPolicy)
            if quality_policy_path is not None
            else DataQualityPolicy(policy_id="default-live-tushare-dq/v1")
        )
        acquisition_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "snapshot_build_spec_hash": spec.content_hash,
                    "execution_policy_hash": policy.content_hash,
                }
            )
        )
    except (OSError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": "SCHEMA_INVALID",
                    "detail": "snapshot or execution policy configuration is invalid",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=5) from None
    try:
        source = TushareSnapshotSource(os.environ["TUSHARE_TOKEN"])
        executor = TusharePlanExecutor(source.client, policy)
        result = LiveTushareAcquisitionService(
            executor, LiveTushareSnapshotBuilder(quality_policy)
        ).acquire_and_build(
            spec,
            acquisition_root / f"sha256-{acquisition_hash}",
            output_root,
        )
    except (SnapshotBuildError, TushareAcquisitionError) as error:
        reason_code = getattr(error, "reason_code", "SCHEMA_INVALID")
        typer.echo(
            json.dumps(
                {"status": "FAILED", "reason_code": reason_code, "detail": str(error)},
                sort_keys=True,
            )
        )
        raise typer.Exit(code=5) from None
    except Exception:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": "SOURCE_INCOMPLETE",
                    "detail": (
                        "Tushare acquisition initialization failed; provider detail suppressed"
                    ),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=5) from None
    typer.echo(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "snapshot": result.reference.model_dump(mode="json"),
                "quality_report_hash": result.quality_report.content_hash,
            },
            sort_keys=True,
        )
    )


@snapshot_app.command("verify")
def verify_snapshot_command(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
) -> None:
    """Verify a published snapshot manifest and all referenced file hashes."""

    try:
        manifest = verify_snapshot(path)
    except SnapshotBuildError as error:
        typer.echo(
            json.dumps(
                {"status": "FAILED", "reason_code": error.reason_code, "detail": str(error)},
                sort_keys=True,
            )
        )
        raise typer.Exit(code=6) from error
    typer.echo(
        json.dumps({"status": "PASS", "snapshot_hash": manifest.snapshot_hash}, sort_keys=True)
    )


@qlib_app.command("build-view")
def build_qlib_view(
    snapshot_path: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    qlib_source: Annotated[
        Path,
        typer.Option("--qlib-source", exists=True, file_okay=False, readable=True),
    ] = Path(".tools/qlib-0.9.7"),
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Parent directory for content-addressed Qlib views.",
        ),
    ] = Path("artifacts/data/qlib-views"),
) -> None:
    """Build a verified derived view using Qlib's official converter."""

    try:
        result = QlibViewBuilder().build(snapshot_path, output_root, qlib_source)
    except QlibViewBuildError as error:
        typer.echo(
            json.dumps(
                {"status": "FAILED", "reason_code": error.reason_code, "detail": str(error)},
                sort_keys=True,
            )
        )
        raise typer.Exit(code=7) from error
    typer.echo(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "view": result.reference.model_dump(mode="json"),
                "source_snapshot_hash": result.manifest.source_snapshot_hash,
            },
            sort_keys=True,
        )
    )


@qlib_app.command("verify-view")
def verify_qlib_view_command(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
) -> None:
    """Verify a Qlib view manifest and all derived file hashes."""

    try:
        manifest = verify_qlib_view(path)
    except QlibViewBuildError as error:
        typer.echo(
            json.dumps(
                {"status": "FAILED", "reason_code": error.reason_code, "detail": str(error)},
                sort_keys=True,
            )
        )
        raise typer.Exit(code=8) from error
    typer.echo(json.dumps({"status": "PASS", "view_hash": manifest.view_hash}, sort_keys=True))


@pit_app.command("audit")
def audit_pit(
    snapshot_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    evidence_root: Annotated[
        Path,
        typer.Option(
            "--evidence-root",
            file_okay=False,
            help="Root directory for immutable PIT audit evidence.",
        ),
    ] = Path("artifacts/evidence"),
) -> None:
    """Run and publish an experiment-time PIT audit from a strict JSON specification."""

    try:
        raw = json.loads(request_path.read_bytes())
        if not isinstance(raw, dict):
            raise ValueError("canonical PIT audit request must be a JSON object")
        request = load_canonical_pit_request_json(cast(dict[str, Any], raw))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        typer.echo(
            json.dumps(
                {"status": "FAILED", "reason_code": "SCHEMA_INVALID", "detail": str(error)},
                sort_keys=True,
            )
        )
        raise typer.Exit(code=9) from error

    service = PITAuditService()
    report = service.audit_snapshot(request, snapshot_path)
    evidence = service.publish(report, evidence_root)
    typer.echo(
        json.dumps(
            {
                "status": report.run_status,
                "verdict": report.verdict,
                "report_hash": report.content_hash,
                "evidence": evidence.model_dump(mode="json"),
            },
            sort_keys=True,
        )
    )
    if report.verdict == "REJECT":
        raise typer.Exit(code=10)


@backtest_app.command("run")
def run_reference_backtest(
    signal_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    view_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    cost_policy_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    backtest_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Parent directory for immutable content-addressed backtest results.",
        ),
    ] = Path("artifacts/research/backtests"),
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            exists=True,
            file_okay=False,
            readable=True,
            help="Clean Git repository root bound by the resolved experiment.",
        ),
    ] = Path("."),
) -> None:
    """Run Qlib's reference backtest from one explicit verified SignalArtifact."""

    from quantos.backtest.service import QlibBacktestService
    from quantos.research.qlib.universe import QlibResearchError

    try:
        resolved = ResolvedExperimentSpec.model_validate_json(
            (signal_path / "resolved-experiment.json").read_bytes()
        )
        cost_policy = load_yaml_contract(cost_policy_path, CostPolicy)
        backtest_policy = load_yaml_contract(backtest_policy_path, BacktestPolicy)
    except (OSError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": "SCHEMA_INVALID",
                    "detail": "signal or backtest policy input is invalid",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=11) from None

    try:
        result = QlibBacktestService().run(
            resolved,
            signal_path,
            view_path,
            cost_policy,
            backtest_policy,
            output_root,
            workspace=workspace,
        )
    except QlibResearchError as error:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": error.reason_code,
                    "detail": str(error),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=12) from error

    typer.echo(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "backtest": result.reference.model_dump(mode="json"),
                "backtest_config_hash": result.manifest.backtest_config_hash,
                "reconciliation_hash": result.manifest.reconciliation_hash,
            },
            sort_keys=True,
        )
    )


@backtest_app.command("verify")
def verify_reference_backtest(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Verify a normalized Qlib backtest manifest, schemas, hashes, and bindings."""

    from quantos.backtest.service import verify_backtest_artifact
    from quantos.research.qlib.universe import QlibResearchError

    try:
        manifest = verify_backtest_artifact(path)
    except QlibResearchError as error:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": error.reason_code,
                    "detail": str(error),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=13) from error
    typer.echo(
        json.dumps(
            {
                "status": "PASS",
                "result_hash": manifest.result_hash,
                "reconciliation_hash": manifest.reconciliation_hash,
            },
            sort_keys=True,
        )
    )


@release_app.command("data-qualified")
def data_qualified_release(
    snapshot_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    qlib_source: Annotated[
        Path,
        typer.Option("--qlib-source", exists=True, file_okay=False, readable=True),
    ] = Path(".tools/qlib-0.9.7"),
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Root for two independent immutable Data-qualified pipelines.",
        ),
    ] = Path("artifacts/releases/data-qualified-v0.1"),
    workspace: Annotated[
        Path,
        typer.Option("--workspace", exists=True, file_okay=False, readable=True),
    ] = Path("."),
    authoring_path: Annotated[
        Path, typer.Option("--authoring", exists=True, dir_okay=False, readable=True)
    ] = Path("configs/research/hs300_momentum_v1.yaml"),
    research_policy_path: Annotated[
        Path,
        typer.Option("--research-policy", exists=True, dir_okay=False, readable=True),
    ] = Path("configs/research/policy_v1.yaml"),
    validation_policy_path: Annotated[
        Path,
        typer.Option("--validation-policy", exists=True, dir_okay=False, readable=True),
    ] = Path("configs/validation/research_candidate_v1.yaml"),
    cost_policy_path: Annotated[
        Path,
        typer.Option("--cost-policy", exists=True, dir_okay=False, readable=True),
    ] = Path("configs/backtest/cost_v1.yaml"),
    backtest_policy_path: Annotated[
        Path,
        typer.Option("--backtest-policy", exists=True, dir_okay=False, readable=True),
    ] = Path("configs/backtest/policy_v1.yaml"),
    strategy_id: Annotated[str, typer.Option("--strategy-id")] = "hs300-momentum",
) -> None:
    """Run P3-P7 twice from one explicit real Tushare snapshot."""

    from quantos.application.data_qualified_release import run_data_qualified_release

    try:
        report = run_data_qualified_release(
            snapshot_path=snapshot_path,
            qlib_source=qlib_source,
            output_root=output_root,
            workspace=workspace,
            authoring=load_yaml_contract(authoring_path, ExperimentAuthoringSpec),
            research_policy=load_yaml_contract(research_policy_path, ResearchPolicy),
            validation_policy=load_yaml_contract(validation_policy_path, ValidationPolicy),
            base_cost=load_yaml_contract(cost_policy_path, CostPolicy),
            backtest_policy=load_yaml_contract(backtest_policy_path, BacktestPolicy),
            strategy_id=strategy_id,
        )
    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": getattr(error, "reason_code", "SOURCE_INCOMPLETE"),
                    "detail": str(error),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=19) from error
    typer.echo(json.dumps(report, sort_keys=True))


@experiment_app.command("run")
def run_validation_experiment(
    authoring_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    validation_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    research_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    locator_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Parent directory for immutable ValidationReport artifacts.",
        ),
    ] = Path("artifacts/validation"),
    event_root: Annotated[
        Path,
        typer.Option(
            "--event-root",
            file_okay=False,
            help="Root for immutable OOSAccessed events.",
        ),
    ] = Path("artifacts/events"),
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            exists=True,
            file_okay=False,
            readable=True,
            help="Git repository root used by the reproducibility gate.",
        ),
    ] = Path("."),
    development: Annotated[
        bool,
        typer.Option(
            "--development",
            help="Allow a NON_CANONICAL development report while retaining all artifact gates.",
        ),
    ] = False,
) -> None:
    """Validate explicit immutable evidence from a strict manual experiment YAML."""

    from quantos.validation.service import ValidationService

    try:
        authoring = load_yaml_contract(authoring_path, ExperimentAuthoringSpec)
        validation_policy = load_yaml_contract(validation_policy_path, ValidationPolicy)
        research_policy = load_yaml_contract(research_policy_path, ResearchPolicy)
        locators = ValidationRunLocators.model_validate(load_yaml_mapping(locator_path))
    except (OSError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "verdict": "NOT_EVALUATED",
                    "reason_code": "SCHEMA_INVALID",
                    "detail": "experiment, policy, or evidence locator YAML is invalid",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=13) from None
    result = ValidationService().run(
        authoring,
        validation_policy,
        research_policy,
        locators,
        output_root,
        event_root,
        workspace=workspace,
        canonical=not development,
    )
    typer.echo(
        json.dumps(
            {
                "status": result.report.run_status,
                "verdict": result.report.verdict,
                "canonical": result.report.canonical,
                "report": result.reference.model_dump(mode="json"),
            },
            sort_keys=True,
        )
    )
    if result.report.run_status == "FAILED":
        raise typer.Exit(code=15)
    if result.report.verdict == "REJECT":
        raise typer.Exit(code=14)


@experiment_app.command("verify")
def verify_validation_experiment(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Verify one immutable ValidationReport artifact and its frozen policy inputs."""

    from quantos.validation.service import ValidationError, verify_validation_report

    try:
        report = verify_validation_report(path)
    except ValidationError as error:
        typer.echo(
            json.dumps(
                {"status": "FAILED", "reason_code": error.reason_code, "detail": str(error)},
                sort_keys=True,
            )
        )
        raise typer.Exit(code=16) from error
    typer.echo(
        json.dumps(
            {
                "status": "PASS",
                "report_hash": report.report_hash,
                "run_status": report.run_status,
                "verdict": report.verdict,
            },
            sort_keys=True,
        )
    )


def _registry_failure(error: Exception, *, exit_code: int) -> None:
    from quantos.registry import RegistryError

    if not isinstance(error, RegistryError):  # pragma: no cover - internal CLI guard
        raise error
    typer.echo(
        json.dumps(
            {
                "status": "FAILED",
                "reason_code": error.reason_code,
                "detail": str(error),
            },
            sort_keys=True,
        )
    )
    raise typer.Exit(code=exit_code)


@registry_app.command("register-experiment")
def register_registry_experiment(
    validation_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    registry_root: Annotated[
        Path,
        typer.Option("--registry-root", file_okay=False, help="Append-only registry root."),
    ] = Path("artifacts/registry"),
    event_root: Annotated[
        Path | None,
        typer.Option(
            "--event-root",
            exists=True,
            file_okay=False,
            readable=True,
            help="Explicit root containing the ValidationReport OOSAccessed event.",
        ),
    ] = None,
    snapshot_path: Annotated[
        Path | None,
        typer.Option(
            "--snapshot-path",
            exists=True,
            file_okay=False,
            readable=True,
            help="Explicit immutable snapshot directory bound by the report.",
        ),
    ] = None,
    qlib_view_path: Annotated[
        Path | None,
        typer.Option(
            "--qlib-view-path",
            exists=True,
            file_okay=False,
            readable=True,
            help="Explicit immutable Qlib view directory bound by the report.",
        ),
    ] = None,
    signal_path: Annotated[
        Path | None,
        typer.Option(
            "--signal-path",
            exists=True,
            file_okay=False,
            readable=True,
            help="Explicit immutable SignalArtifact directory bound by the report.",
        ),
    ] = None,
) -> None:
    """Reverify and register one PASS, REJECT, or FAILED ValidationReport."""

    from quantos.registry import RegistryError, RegistryService

    try:
        result = RegistryService(registry_root).register_experiment(
            validation_path,
            event_root=event_root,
            snapshot_path=snapshot_path,
            qlib_view_path=qlib_view_path,
            signal_path=signal_path,
        )
    except RegistryError as error:
        _registry_failure(error, exit_code=17)
        return
    typer.echo(
        json.dumps(
            {
                "status": "REGISTERED",
                "experiment_id": result.manifest.experiment_id,
                "manifest_hash": result.manifest.manifest_hash,
                "run_status": result.manifest.run_status,
                "verdict": result.manifest.verdict,
                "index_hash": result.index.index_hash,
            },
            sort_keys=True,
        )
    )


@registry_app.command("register-strategy")
def register_registry_strategy(
    strategy_id: Annotated[str, typer.Argument()],
    strategy_spec_hash: Annotated[str, typer.Argument()],
    version: Annotated[int, typer.Option("--version", min=1)],
    registry_root: Annotated[Path, typer.Option("--registry-root", file_okay=False)] = Path(
        "artifacts/registry"
    ),
) -> None:
    """Append exactly the next immutable logical strategy version."""

    from quantos.registry import RegistryError, RegistryService

    try:
        record = RegistryService(registry_root).register_strategy(
            strategy_id, strategy_spec_hash, version=version
        )
    except RegistryError as error:
        _registry_failure(error, exit_code=17)
        return
    typer.echo(
        json.dumps(
            {"status": "REGISTERED", "strategy": record.model_dump(mode="json")},
            sort_keys=True,
        )
    )


@registry_app.command("transition")
def transition_registry_strategy(
    strategy_id: Annotated[str, typer.Argument()],
    version: Annotated[int, typer.Argument(min=1)],
    event_type: Annotated[str, typer.Argument()],
    experiment_id: Annotated[str, typer.Argument()],
    registry_root: Annotated[
        Path, typer.Option("--registry-root", exists=True, file_okay=False)
    ] = Path("artifacts/registry"),
) -> None:
    """Append a validation lifecycle event to a registered strategy version."""

    from quantos.contracts.events import EventType
    from quantos.registry import RegistryError, RegistryService

    try:
        parsed_type = EventType(event_type)
        record = RegistryService(registry_root).append_strategy_event(
            strategy_id, version, parsed_type, experiment_id
        )
    except ValueError:
        typer.echo(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason_code": "SCHEMA_INVALID",
                    "detail": "event_type is not a known immutable event type",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=17) from None
    except RegistryError as error:
        _registry_failure(error, exit_code=17)
        return
    typer.echo(
        json.dumps(
            {"status": "APPENDED", "strategy": record.model_dump(mode="json")},
            sort_keys=True,
        )
    )


@registry_app.command("list")
def list_registry(
    registry_root: Annotated[
        Path, typer.Option("--registry-root", exists=True, file_okay=False)
    ] = Path("artifacts/registry"),
) -> None:
    """List the complete rebuilt registry projection."""

    from quantos.registry import RegistryError, RegistryService

    try:
        index = RegistryService(registry_root).rebuild_index()
    except RegistryError as error:
        _registry_failure(error, exit_code=18)
        return
    typer.echo(
        json.dumps(
            {"status": "PASS", "index": index.model_dump(mode="json")},
            sort_keys=True,
        )
    )


@registry_app.command("show")
def show_registry_entry(
    logical_id: Annotated[str, typer.Argument()],
    registry_root: Annotated[
        Path, typer.Option("--registry-root", exists=True, file_okay=False)
    ] = Path("artifacts/registry"),
) -> None:
    """Show one experiment manifest or every version of one logical strategy."""

    from quantos.contracts.status import ReasonCode
    from quantos.registry import RegistryError, RegistryService

    service = RegistryService(registry_root)
    try:
        index = service.rebuild_index()
        experiment = next(
            (item for item in index.experiments if item.experiment_id == logical_id), None
        )
        strategy = next((item for item in index.strategies if item.strategy_id == logical_id), None)
        if experiment is not None:
            payload: object = service.get_experiment(logical_id).model_dump(mode="json")
            kind = "experiment"
        elif strategy is not None:
            payload = strategy.model_dump(mode="json")
            kind = "strategy"
        else:
            raise RegistryError(ReasonCode.SOURCE_INCOMPLETE, "registry ID was not found")
    except RegistryError as error:
        _registry_failure(error, exit_code=18)
        return
    typer.echo(
        json.dumps(
            {"status": "PASS", "kind": kind, "entry": payload},
            sort_keys=True,
        )
    )


@registry_app.command("verify")
def verify_registry(
    registry_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Reverify every manifest/event and rebuild the authoritative index."""

    from quantos.registry import RegistryError, RegistryService

    try:
        index = RegistryService(registry_root).verify()
    except RegistryError as error:
        _registry_failure(error, exit_code=18)
        return
    typer.echo(
        json.dumps(
            {
                "status": "PASS",
                "index_hash": index.index_hash,
                "experiment_count": len(index.experiments),
                "strategy_count": len(index.strategies),
            },
            sort_keys=True,
        )
    )


@registry_app.command("recover")
def recover_registry_partial_writes(
    registry_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Remove only abandoned atomic-writer temporary files."""

    from quantos.registry import RegistryService

    recovered = RegistryService(registry_root).recover_partial_writes()
    typer.echo(
        json.dumps(
            {"status": "RECOVERED", "files": recovered, "count": len(recovered)},
            sort_keys=True,
        )
    )


def _load_canonical_ledger_contract(path: Path, contract_type: type[C]) -> C:
    from quantos.application.ledger import ResearchLedgerError
    from quantos.contracts.status import ReasonCode

    try:
        encoded = path.read_bytes()
        contract = contract_type.model_validate_json(encoded)
    except (OSError, ValueError) as error:
        raise ResearchLedgerError(
            ReasonCode.ARTIFACT_CORRUPTED, "ledger CLI input is invalid"
        ) from error
    if encoded != canonical_json_bytes(contract.model_dump(mode="python")):
        raise ResearchLedgerError(
            ReasonCode.ARTIFACT_CORRUPTED, "ledger CLI input is not canonical"
        )
    return contract


def _ledger_failure(error: Exception, *, exit_code: int = 19) -> None:
    reason = getattr(error, "reason_code", "ARTIFACT_CORRUPTED")
    typer.echo(
        json.dumps(
            {"status": "FAILED", "reason_code": str(reason), "detail": str(error)},
            sort_keys=True,
        )
    )
    raise typer.Exit(code=exit_code)


def _parse_ledger_timestamp(value: str) -> datetime:
    from quantos.application.ledger import ResearchLedgerError
    from quantos.contracts.status import ReasonCode

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResearchLedgerError(
            ReasonCode.SCHEMA_INVALID, "ledger timestamp is not ISO-8601"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchLedgerError(
            ReasonCode.SCHEMA_INVALID, "ledger timestamp must be timezone-aware"
        )
    return parsed


@ledger_app.command("verify")
def verify_research_ledger(
    ledger_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    ledger_id: Annotated[str, typer.Argument()],
    created_at: Annotated[
        str,
        typer.Option("--created-at", help="Explicit timezone-aware snapshot timestamp."),
    ],
    snapshot_output: Annotated[
        Path | None,
        typer.Option("--snapshot-output", dir_okay=False),
    ] = None,
) -> None:
    """Verify canonical objects/events and deterministically rebuild a ledger snapshot."""

    from quantos.application.ledger import ResearchLedgerError, ResearchLedgerService
    from quantos.artifacts.store import ArtifactError, atomic_write_bytes

    try:
        snapshot = ResearchLedgerService(ledger_root).verify(
            ledger_id, created_at=_parse_ledger_timestamp(created_at)
        )
        if snapshot_output is not None:
            atomic_write_bytes(
                snapshot_output, canonical_json_bytes(snapshot.model_dump(mode="python"))
            )
    except (ResearchLedgerError, ArtifactError) as error:
        _ledger_failure(error)
        return
    typer.echo(
        json.dumps(
            {
                "status": "PASS",
                "snapshot_hash": snapshot.content_hash,
                "event_count": len(snapshot.source_event_hashes),
                "node_count": len(snapshot.node_object_hashes),
            },
            sort_keys=True,
        )
    )


@ledger_app.command("search")
def search_research_ledger(
    ledger_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    snapshot_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    policy_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    scope_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Run one bounded hash-bound lexical search over a verified ledger snapshot."""

    from quantos.application.ledger import ResearchLedgerError, ResearchLedgerService
    from quantos.contracts.ledger import (
        ResearchLedgerAccessScope,
        ResearchLedgerSearchPolicy,
        ResearchLedgerSearchRequest,
        ResearchLedgerSnapshot,
    )

    try:
        snapshot = _load_canonical_ledger_contract(snapshot_path, ResearchLedgerSnapshot)
        policy = _load_canonical_ledger_contract(policy_path, ResearchLedgerSearchPolicy)
        scope = _load_canonical_ledger_contract(scope_path, ResearchLedgerAccessScope)
        request = _load_canonical_ledger_contract(request_path, ResearchLedgerSearchRequest)
        result = ResearchLedgerService(ledger_root).search(
            snapshot=snapshot,
            policy=policy,
            scope=scope,
            request=request,
        )
    except ResearchLedgerError as error:
        _ledger_failure(error)
        return
    typer.echo(result.canonical_bytes().decode("utf-8"))


@ledger_app.command("context-pack")
def build_research_context_pack(
    ledger_root: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    snapshot_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    policy_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    scope_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    request_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    result_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    budget_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Build a byte-bounded immutable Agent context input from a verified search result."""

    from quantos.application.ledger import ResearchLedgerError, ResearchLedgerService
    from quantos.contracts.ledger import (
        ResearchContextBudgetPolicy,
        ResearchLedgerAccessScope,
        ResearchLedgerSearchPolicy,
        ResearchLedgerSearchRequest,
        ResearchLedgerSearchResult,
        ResearchLedgerSnapshot,
    )

    try:
        snapshot = _load_canonical_ledger_contract(snapshot_path, ResearchLedgerSnapshot)
        policy = _load_canonical_ledger_contract(policy_path, ResearchLedgerSearchPolicy)
        scope = _load_canonical_ledger_contract(scope_path, ResearchLedgerAccessScope)
        request = _load_canonical_ledger_contract(request_path, ResearchLedgerSearchRequest)
        result = _load_canonical_ledger_contract(result_path, ResearchLedgerSearchResult)
        budget = _load_canonical_ledger_contract(budget_path, ResearchContextBudgetPolicy)
        pack = ResearchLedgerService(ledger_root).build_context_pack(
            snapshot=snapshot,
            policy=policy,
            scope=scope,
            request=request,
            result=result,
            budget=budget,
        )
    except ResearchLedgerError as error:
        _ledger_failure(error)
        return
    typer.echo(pack.canonical_bytes().decode("utf-8"))


if __name__ == "__main__":  # pragma: no cover
    app()
