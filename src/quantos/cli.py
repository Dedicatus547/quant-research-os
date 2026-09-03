"""Deterministic command-line entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from quantos.application.capabilities import publish_capability_report
from quantos.application.doctor import build_doctor_report
from quantos.application.pit import PITAuditService, load_canonical_pit_request_json
from quantos.config import load_yaml_contract, load_yaml_mapping
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    ValidationPolicy,
)
from quantos.contracts.snapshot import SnapshotBuildSpec
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
app.add_typer(tushare_app, name="tushare")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(qlib_app, name="qlib")
app.add_typer(pit_app, name="pit")
app.add_typer(backtest_app, name="backtest")
app.add_typer(experiment_app, name="experiment")


@app.command()
def doctor() -> None:
    """Report offline and Data-qualified readiness without exposing secrets."""

    report = build_doctor_report()
    typer.echo(json.dumps(report.model_dump(mode="json"), sort_keys=True, ensure_ascii=False))
    if report.offline_status == "BLOCKED":
        raise typer.Exit(code=1)


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
        result = LiveTushareAcquisitionService(executor).acquire_and_build(
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


if __name__ == "__main__":  # pragma: no cover
    app()
