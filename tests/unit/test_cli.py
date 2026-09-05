import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from quantos.application import resolve_experiment
from quantos.cli import app
from quantos.config import load_yaml_contract
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.pit import (
    CanonicalPITAuditRequest,
    OperatorDelayPolicy,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
)
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import ExperimentAuthoringSpec
from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.data.snapshot import SnapshotBuildError, SyntheticSnapshotBuilder
from quantos.research.qlib import QlibResearchError
from quantos.validation import ValidationError

ROOT = Path(__file__).parents[2]
FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_snapshot_build_and_verify_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    output_root = tmp_path / "snapshots"
    built = runner.invoke(
        app,
        [
            "snapshot",
            "build-synthetic",
            str(FIXTURE),
            "--output-root",
            str(output_root),
        ],
    )
    assert built.exit_code == 0
    payload = json.loads(built.stdout)
    assert payload["status"] == "SUCCEEDED"
    snapshot_hash = payload["snapshot"]["sha256"]

    verified = runner.invoke(
        app, ["snapshot", "verify", str(output_root / f"sha256-{snapshot_hash}")]
    )
    assert verified.exit_code == 0
    assert json.loads(verified.stdout) == {"snapshot_hash": snapshot_hash, "status": "PASS"}


def test_doctor_and_tushare_probe_do_not_require_or_echo_token(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    runner = CliRunner()
    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 0
    assert json.loads(doctor.stdout)["tushare_token_configured"] is False

    probe = runner.invoke(app, ["tushare", "probe"])
    assert probe.exit_code == 2
    assert json.loads(probe.stdout)["reason_code"] == "TUSHARE_TOKEN_MISSING"


def test_live_snapshot_cli_blocks_without_token_and_suppresses_invalid_config(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    spec_path = tmp_path / "snapshot.yaml"
    policy_path = tmp_path / "policy.yaml"
    secret = "must-not-echo-this-token"
    spec_path.write_text(f"token: {secret}\n", encoding="utf-8")
    policy_path.write_text("policy_id: invalid\n", encoding="utf-8")
    runner = CliRunner()

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    blocked = runner.invoke(app, ["snapshot", "build-tushare", str(spec_path), str(policy_path)])
    assert blocked.exit_code == 2
    assert json.loads(blocked.stdout)["reason_code"] == "TUSHARE_TOKEN_MISSING"

    monkeypatch.setenv("TUSHARE_TOKEN", "configured-but-never-printed")
    invalid = runner.invoke(app, ["snapshot", "build-tushare", str(spec_path), str(policy_path)])
    assert invalid.exit_code == 5
    assert json.loads(invalid.stdout)["reason_code"] == "SCHEMA_INVALID"
    assert secret not in invalid.stdout


def test_live_snapshot_cli_loads_explicit_quality_policy_and_reports_hash(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    snapshot_hash = "a" * 64
    quality_hash = "b" * 64
    captured: dict[str, object] = {}

    class Source:
        def __init__(self, token: str) -> None:
            assert token == "configured-but-never-printed"
            self.client = object()

    class Executor:
        def __init__(self, client: object, policy: object) -> None:
            captured["client"] = client
            captured["execution_policy"] = policy

    class Builder:
        def __init__(self, policy: object) -> None:
            captured["quality_policy"] = policy

    class Service:
        def __init__(self, executor: object, builder: object) -> None:
            captured["executor"] = executor
            captured["builder"] = builder

        def acquire_and_build(self, *_args: object) -> object:
            return SimpleNamespace(
                reference=SimpleNamespace(
                    model_dump=lambda **_kwargs: {
                        "sha256": snapshot_hash,
                        "kind": "data_snapshot",
                    }
                ),
                quality_report=SimpleNamespace(content_hash=quality_hash),
            )

    monkeypatch.setenv("TUSHARE_TOKEN", "configured-but-never-printed")
    monkeypatch.setattr("quantos.cli.TushareSnapshotSource", Source)
    monkeypatch.setattr("quantos.cli.TusharePlanExecutor", Executor)
    monkeypatch.setattr("quantos.cli.LiveTushareSnapshotBuilder", Builder)
    monkeypatch.setattr("quantos.cli.LiveTushareAcquisitionService", Service)
    arguments = [
        "snapshot",
        "build-tushare",
        str(ROOT / "configs" / "tushare" / "snapshot.yaml"),
        str(ROOT / "configs" / "tushare" / "execution_policy_20260904.yaml"),
        "--quality-policy",
        str(ROOT / "configs" / "tushare" / "data_quality_20260905.yaml"),
        "--acquisition-root",
        str(tmp_path / "acquisition"),
        "--output-root",
        str(tmp_path / "snapshots"),
    ]
    runner = CliRunner()
    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["snapshot"]["sha256"] == snapshot_hash
    assert json.loads(result.stdout)["quality_report_hash"] == quality_hash
    assert captured["quality_policy"].index_weight_absolute_tolerance == 0.15
    assert "configured-but-never-printed" not in result.stdout

    class RejectedService(Service):
        def acquire_and_build(self, *_args: object) -> object:
            raise SnapshotBuildError(ReasonCode.SOURCE_INCOMPLETE, "quality rejected")

    monkeypatch.setattr("quantos.cli.LiveTushareAcquisitionService", RejectedService)
    rejected = runner.invoke(app, arguments)
    assert rejected.exit_code == 5
    assert json.loads(rejected.stdout)["reason_code"] == "SOURCE_INCOMPLETE"

    class UnexpectedService(Service):
        def acquire_and_build(self, *_args: object) -> object:
            raise RuntimeError("private provider detail")

    monkeypatch.setattr("quantos.cli.LiveTushareAcquisitionService", UnexpectedService)
    unexpected = runner.invoke(app, arguments)
    assert unexpected.exit_code == 5
    assert json.loads(unexpected.stdout)["reason_code"] == "SOURCE_INCOMPLETE"
    assert "private provider detail" not in unexpected.stdout


def _pit_request(snapshot_hash: str, *, signal_hour: int = 16) -> CanonicalPITAuditRequest:
    expression = SafeQlibExpressionSpec(
        expression_id="momentum_2d",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
            SafeExpressionNode(node_id="momentum", operator="return", inputs=("price",), window=2),
        ),
        output_node_id="momentum",
    )
    return CanonicalPITAuditRequest(
        snapshot_hash=snapshot_hash,
        instrument_id="000001.SZ",
        universe_index="000300.SH",
        expression=expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="cli-return-delay/v1", operator="return", delay_seconds=60
            ),
        ),
        schedule=DecisionSchedule(
            signal_time=datetime(2024, 1, 5, signal_hour, tzinfo=SHANGHAI),
            signal_available_at=datetime(2024, 1, 5, signal_hour, 1, tzinfo=SHANGHAI),
            decision_time=datetime(2024, 1, 5, signal_hour, 10, tzinfo=SHANGHAI),
            execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
        ),
    )


def test_pit_cli_publishes_pass_and_returns_nonzero_for_reject(tmp_path: Path) -> None:
    runner = CliRunner()
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    request_path = tmp_path / "pit.json"
    evidence_root = tmp_path / "evidence"
    passing = _pit_request(snapshot.manifest.snapshot_hash)
    request_path.write_text(passing.model_dump_json(), encoding="utf-8")

    passed = runner.invoke(
        app,
        [
            "pit",
            "audit",
            str(snapshot.path),
            str(request_path),
            "--evidence-root",
            str(evidence_root),
        ],
    )
    assert passed.exit_code == 0
    payload = json.loads(passed.stdout)
    assert payload["verdict"] == "PASS"
    assert (evidence_root / payload["evidence"]["logical_path"]).is_file()

    rejected = _pit_request(snapshot.manifest.snapshot_hash, signal_hour=15)
    request_path.write_text(rejected.model_dump_json(), encoding="utf-8")
    failed = runner.invoke(
        app,
        [
            "pit",
            "audit",
            str(snapshot.path),
            str(request_path),
            "--evidence-root",
            str(evidence_root),
        ],
    )
    assert failed.exit_code == 10
    rejected_payload = json.loads(failed.stdout)
    assert rejected_payload["verdict"] == "REJECT"
    assert (evidence_root / rejected_payload["evidence"]["logical_path"]).is_file()


def _resolved_backtest_input(signal_path: Path) -> tuple[CostPolicy, BacktestPolicy]:
    authoring = load_yaml_contract(
        ROOT / "configs" / "research" / "hs300_momentum_v1.yaml",
        ExperimentAuthoringSpec,
    )
    cost = load_yaml_contract(ROOT / "configs" / "backtest" / "cost_v1.yaml", CostPolicy)
    policy = load_yaml_contract(ROOT / "configs" / "backtest" / "policy_v1.yaml", BacktestPolicy)
    resolved = resolve_experiment(
        authoring,
        snapshot_hash="a" * 64,
        qlib_view_hash="b" * 64,
        qlib_version="0.9.7",
        qlib_view_spec_hash="c" * 64,
        pit_audit_evidence_hash="d" * 64,
        research_policy_hash="e" * 64,
        validation_policy_hash="f" * 64,
        cost_policy_hash=cost.content_hash,
        backtest_policy_hash=policy.content_hash,
        code_commit_hash="1" * 40,
        lockfile_hash="2" * 64,
    )
    signal_path.mkdir()
    (signal_path / "resolved-experiment.json").write_bytes(resolved.canonical_bytes())
    return cost, policy


def test_backtest_cli_runs_and_verifies_explicit_hash_bound_artifact(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    signal_path = tmp_path / "signal"
    view_path = tmp_path / "view"
    view_path.mkdir()
    cost, policy = _resolved_backtest_input(signal_path)
    result_hash = "3" * 64
    reconciliation_hash = "4" * 64
    reference = ArtifactRef(
        kind="backtest_result",
        sha256=result_hash,
        size_bytes=123,
        media_type="application/vnd.quantos.backtest-directory",
        logical_path=f"research/backtests/sha256-{result_hash}",
    )

    def fake_run(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            reference=reference,
            manifest=SimpleNamespace(
                backtest_config_hash="5" * 64,
                reconciliation_hash=reconciliation_hash,
            ),
        )

    monkeypatch.setattr("quantos.backtest.service.QlibBacktestService.run", fake_run)
    runner = CliRunner()
    executed = runner.invoke(
        app,
        [
            "backtest",
            "run",
            str(signal_path),
            str(view_path),
            str(ROOT / "configs" / "backtest" / "cost_v1.yaml"),
            str(ROOT / "configs" / "backtest" / "policy_v1.yaml"),
            "--output-root",
            str(tmp_path / "backtests"),
            "--workspace",
            str(ROOT),
        ],
    )

    assert executed.exit_code == 0
    payload = json.loads(executed.stdout)
    assert payload["status"] == "SUCCEEDED"
    assert payload["backtest"]["sha256"] == result_hash
    assert cost.content_hash != policy.content_hash

    monkeypatch.setattr(
        "quantos.backtest.service.verify_backtest_artifact",
        lambda _path: SimpleNamespace(
            result_hash=result_hash,
            reconciliation_hash=reconciliation_hash,
        ),
    )
    artifact_path = tmp_path / f"sha256-{result_hash}"
    artifact_path.mkdir()
    verified = runner.invoke(app, ["backtest", "verify", str(artifact_path)])
    assert verified.exit_code == 0
    assert json.loads(verified.stdout) == {
        "reconciliation_hash": reconciliation_hash,
        "result_hash": result_hash,
        "status": "PASS",
    }


def test_backtest_cli_reports_invalid_input_and_stable_execution_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    signal_path = tmp_path / "signal"
    view_path = tmp_path / "view"
    signal_path.mkdir()
    view_path.mkdir()
    (signal_path / "resolved-experiment.json").write_text("{}", encoding="utf-8")
    invalid_policy = tmp_path / "invalid.yaml"
    invalid_policy.write_text("policy_id: invalid\n", encoding="utf-8")
    runner = CliRunner()

    invalid = runner.invoke(
        app,
        [
            "backtest",
            "run",
            str(signal_path),
            str(view_path),
            str(invalid_policy),
            str(invalid_policy),
        ],
    )
    assert invalid.exit_code == 11
    assert json.loads(invalid.stdout)["reason_code"] == "SCHEMA_INVALID"

    _resolved_backtest_input(signal_path.parent / "valid-signal")

    def fail_run(*_args: object, **_kwargs: object) -> object:
        raise QlibResearchError(ReasonCode.QLIB_EXECUTION_FAILED, "reference backtest failed")

    monkeypatch.setattr("quantos.backtest.service.QlibBacktestService.run", fail_run)
    failed = runner.invoke(
        app,
        [
            "backtest",
            "run",
            str(signal_path.parent / "valid-signal"),
            str(view_path),
            str(ROOT / "configs" / "backtest" / "cost_v1.yaml"),
            str(ROOT / "configs" / "backtest" / "policy_v1.yaml"),
        ],
    )
    assert failed.exit_code == 12
    assert json.loads(failed.stdout)["reason_code"] == "QLIB_EXECUTION_FAILED"


def test_data_qualified_release_cli_loads_locked_configs_and_reports_result(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    snapshot_path = tmp_path / f"sha256-{'a' * 64}"
    snapshot_path.mkdir()
    expected = {
        "schema_version": "data-qualified-release-report/v1",
        "status": "PASS",
        "data_qualified": True,
        "validation_verdict": "REJECT",
    }
    monkeypatch.setattr(
        "quantos.application.data_qualified_release.run_data_qualified_release",
        lambda **_kwargs: expected,
    )

    result = CliRunner().invoke(
        app,
        [
            "release",
            "data-qualified",
            str(snapshot_path),
            "--qlib-source",
            str(ROOT / ".tools" / "qlib-0.9.7"),
            "--output-root",
            str(tmp_path / "release"),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == expected


def _validation_locator_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "locators.yaml"
    path.write_text(
        "\n".join(
            (
                "schema_version: validation-run-locators/v1",
                f"snapshot_path: {tmp_path / ('sha256-' + '1' * 64)}",
                f"qlib_view_path: {tmp_path / ('sha256-' + '2' * 64)}",
            )
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("status", "verdict", "expected_exit"),
    [
        ("SUCCEEDED", "PASS", 0),
        ("SUCCEEDED", "REJECT", 14),
        ("FAILED", "NOT_EVALUATED", 15),
    ],
)
def test_experiment_run_cli_preserves_validation_outcomes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    status: str,
    verdict: str,
    expected_exit: int,
) -> None:
    report_hash = "8" * 64
    reference = ArtifactRef(
        kind="validation_report",
        sha256=report_hash,
        size_bytes=10,
        media_type="application/vnd.quantos.validation+directory",
        logical_path=f"validation/sha256-{report_hash}",
    )

    def fake_run(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            report=SimpleNamespace(run_status=status, verdict=verdict, canonical=False),
            reference=reference,
        )

    monkeypatch.setattr("quantos.validation.service.ValidationService.run", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "experiment",
            "run",
            str(ROOT / "configs" / "research" / "hs300_momentum_v1.yaml"),
            str(ROOT / "configs" / "validation" / "engineering_v1.yaml"),
            str(ROOT / "configs" / "research" / "policy_v1.yaml"),
            str(_validation_locator_yaml(tmp_path)),
            "--development",
            "--output-root",
            str(tmp_path / "reports"),
            "--event-root",
            str(tmp_path / "events"),
        ],
    )

    assert result.exit_code == expected_exit
    payload = json.loads(result.stdout)
    assert payload["status"] == status
    assert payload["verdict"] == verdict


def test_experiment_cli_rejects_invalid_yaml_and_verifies_reports(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("invalid: true\n", encoding="utf-8")
    runner = CliRunner()
    failed = runner.invoke(
        app,
        ["experiment", "run", str(invalid), str(invalid), str(invalid), str(invalid)],
    )
    assert failed.exit_code == 13
    assert json.loads(failed.stdout)["reason_code"] == "SCHEMA_INVALID"

    artifact = tmp_path / "artifact"
    artifact.mkdir()
    monkeypatch.setattr(
        "quantos.validation.service.verify_validation_report",
        lambda _path: SimpleNamespace(
            report_hash="9" * 64,
            run_status="SUCCEEDED",
            verdict="PASS",
        ),
    )
    passed = runner.invoke(app, ["experiment", "verify", str(artifact)])
    assert passed.exit_code == 0
    assert json.loads(passed.stdout)["verdict"] == "PASS"

    def invalid_report(_path: Path) -> object:
        raise ValidationError(ReasonCode.ARTIFACT_CORRUPTED, "tampered")

    monkeypatch.setattr("quantos.validation.service.verify_validation_report", invalid_report)
    rejected = runner.invoke(app, ["experiment", "verify", str(artifact)])
    assert rejected.exit_code == 16
    assert json.loads(rejected.stdout)["reason_code"] == "ARTIFACT_CORRUPTED"
