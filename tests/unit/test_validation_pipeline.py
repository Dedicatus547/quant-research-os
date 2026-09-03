from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantos.config import load_yaml_contract
from quantos.contracts.pit import (
    CanonicalPITAuditRequest,
    OperatorDelayPolicy,
    PITAuditReport,
    PITEvidenceMode,
    PITGateId,
    PITGateResult,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
)
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    HardGateId,
    ResearchPolicy,
    ResearchSegment,
    SoftGateThreshold,
    SoftMetric,
    ValidationPolicy,
    ValidationSubperiod,
)
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule
from quantos.contracts.validation import ValidationGateId, ValidationMetric
from quantos.validation import ValidationRunLocators, ValidationService
from quantos.validation import service as validation_service

ROOT = Path(__file__).parents[2]


def _authoring() -> ExperimentAuthoringSpec:
    return load_yaml_contract(
        ROOT / "configs" / "research" / "hs300_momentum_v1.yaml",
        ExperimentAuthoringSpec,
    )


def _research() -> ResearchPolicy:
    return ResearchPolicy(
        policy_id="test",
        train=ResearchSegment(start=date(2023, 1, 1), end=date(2023, 3, 31)),
        validation=ResearchSegment(start=date(2023, 4, 1), end=date(2023, 6, 30)),
        test=ResearchSegment(start=date(2023, 7, 1), end=date(2023, 12, 31)),
        purge_trading_days=1,
        label_horizon_trading_sessions=1,
        random_seed=1,
        num_threads=1,
        num_boost_round=2,
        early_stopping_rounds=1,
    )


def _policy(*, reject: bool = False) -> ValidationPolicy:
    return ValidationPolicy(
        policy_id="test",
        hard_gates=tuple(HardGateId),
        soft_gates=(
            (
                SoftGateThreshold(
                    metric=SoftMetric.OOS_SHARPE,
                    comparison="min",
                    threshold=1.0,
                ),
            )
            if reject
            else ()
        ),
        minimum_oos_observations=1,
        parameter_windows=(20,),
        parameter_top_k=(50,),
        subperiods=(
            ValidationSubperiod(
                period_id="test",
                start=date(2023, 7, 1),
                end=date(2023, 12, 31),
            ),
        ),
        minimum_subperiod_observations=1,
    )


def _locators(tmp_path: Path) -> ValidationRunLocators:
    values: list[Path] = []
    for index in range(5):
        path = tmp_path / f"root-{index}" / f"sha256-{str(index) * 64}"
        values.append(path)
    return ValidationRunLocators(
        snapshot_path=values[0],
        qlib_view_path=values[1],
        signal_path=values[2],
        baseline_backtest_path=values[3],
        reproduction_backtest_path=values[4],
    )


def _artifact_path(tmp_path: Path, digit: str) -> Path:
    return tmp_path / f"sha256-{digit * 64}"


def _reference() -> ArtifactRef:
    return ArtifactRef(
        kind="fake",
        sha256="f" * 64,
        size_bytes=1,
        media_type="application/json",
        logical_path="fake/item.json",
    )


def _pass_stage(*_args: object) -> validation_service._StageOutput:
    return validation_service._StageOutput("passed", (_reference(),))


def _patch_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("_g0", "_g1", "_g2", "_g3", "_g4", "_g5", "_g6", "_g7", "_g8", "_g9", "_g10"):
        monkeypatch.setattr(ValidationService, name, _pass_stage)


def test_hard_reject_short_circuits_without_becoming_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_passes(monkeypatch)

    def reject(*_args: object) -> validation_service._StageOutput:
        raise validation_service._GateRejected(
            ReasonCode.LOOK_AHEAD, "future input", (_reference(),)
        )

    monkeypatch.setattr(ValidationService, "_g2", reject)
    result = ValidationService().run(
        _authoring(),
        _policy(),
        _research(),
        _locators(tmp_path),
        tmp_path / "reports",
        tmp_path / "events",
        canonical=False,
        now=datetime(2024, 1, 1, tzinfo=UTC),
    )

    assert result.report.run_status is RunStatus.SUCCEEDED
    assert result.report.verdict is ValidationVerdict.REJECT
    assert result.report.gates[2].reason_code is ReasonCode.LOOK_AHEAD
    assert all(gate.verdict is ValidationVerdict.NOT_EVALUATED for gate in result.report.gates[3:])


def test_standalone_snapshot_bound_pit_reject_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_hash = "1" * 64
    shanghai = ZoneInfo("Asia/Shanghai")
    expression = SafeQlibExpressionSpec(
        expression_id="momentum",
        nodes=(
            SafeExpressionNode(
                node_id="price",
                operator="field",
                field_name="adjusted_close",
            ),
            SafeExpressionNode(
                node_id="momentum",
                operator="return",
                inputs=("price",),
                window=20,
            ),
        ),
        output_node_id="momentum",
    )
    schedule = DecisionSchedule(
        signal_time=datetime(2024, 1, 5, 15, 0, tzinfo=shanghai),
        signal_available_at=datetime(2024, 1, 5, 15, 1, tzinfo=shanghai),
        decision_time=datetime(2024, 1, 5, 15, 10, tzinfo=shanghai),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=shanghai),
    )
    request = CanonicalPITAuditRequest(
        snapshot_hash=snapshot_hash,
        instrument_id="000001.SZ",
        universe_index="000300.SH",
        expression=expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="test-delay/v1",
                operator="return",
                delay_seconds=60,
            ),
        ),
        schedule=schedule,
    )
    pit = PITAuditReport(
        audit_spec_hash=request.content_hash,
        canonical_request_hash=request.content_hash,
        snapshot_hash=snapshot_hash,
        expression_spec_hash=expression.content_hash,
        schedule=schedule,
        instrument_id=request.instrument_id,
        universe_index=request.universe_index,
        evidence_mode=PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND,
        verdict=ValidationVerdict.REJECT,
        gates=(
            PITGateResult(
                gate_id=PITGateId.DERIVED_AVAILABILITY,
                verdict=ValidationVerdict.REJECT,
                reason_code=ReasonCode.LOOK_AHEAD,
                detail="derived value is not available",
            ),
        ),
        output_temporal=None,
    )
    pit_path = tmp_path / f"sha256-{pit.content_hash}.json"
    pit_path.write_bytes(pit.canonical_bytes())
    locators = ValidationRunLocators(
        snapshot_path=_artifact_path(tmp_path, "1"),
        qlib_view_path=_artifact_path(tmp_path, "2"),
        pit_report_path=pit_path,
    )

    monkeypatch.setattr(ValidationService, "_g0", _pass_stage)

    def snapshot_stage(
        _service: ValidationService, state: validation_service._RunState
    ) -> validation_service._StageOutput:
        state.snapshot = SimpleNamespace(snapshot_hash=snapshot_hash)  # type: ignore[assignment]
        return validation_service._StageOutput("snapshot", (_reference(),))

    monkeypatch.setattr(ValidationService, "_g1", snapshot_stage)
    result = ValidationService().run(
        _authoring(),
        _policy(),
        _research(),
        locators,
        tmp_path / "reports",
        tmp_path / "events",
        canonical=False,
    )

    assert result.report.run_status is RunStatus.SUCCEEDED
    assert result.report.verdict is ValidationVerdict.REJECT
    assert result.report.gates[2].reason_code is ReasonCode.LOOK_AHEAD


def test_execution_failure_is_failed_not_evaluated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_passes(monkeypatch)

    def fail(*_args: object) -> validation_service._StageOutput:
        raise validation_service._ExecutionFailed(ReasonCode.QLIB_EXECUTION_FAILED, "Qlib failed")

    monkeypatch.setattr(ValidationService, "_g4", fail)
    result = ValidationService().run(
        _authoring(),
        _policy(),
        _research(),
        _locators(tmp_path),
        tmp_path / "reports",
        tmp_path / "events",
        canonical=False,
    )

    assert result.report.run_status is RunStatus.FAILED
    assert result.report.verdict is ValidationVerdict.NOT_EVALUATED
    assert result.report.gates[4].verdict is ValidationVerdict.NOT_EVALUATED


def test_soft_threshold_reject_continues_remaining_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_passes(monkeypatch)
    observed = ValidationMetric(
        metric=SoftMetric.OOS_SHARPE,
        value=0.5,
        source=_reference(),
        detail="Qlib metric",
    )

    def soft_stage(*_args: object) -> validation_service._StageOutput:
        return validation_service._StageOutput("observed", (_reference(),), metrics=(observed,))

    monkeypatch.setattr(ValidationService, "_g5", soft_stage)
    result = ValidationService().run(
        _authoring(),
        _policy(reject=True),
        _research(),
        _locators(tmp_path),
        tmp_path / "reports",
        tmp_path / "events",
        canonical=False,
        event_id=UUID("12345678-1234-5678-1234-567812345678"),
    )

    assert result.report.verdict is ValidationVerdict.REJECT
    assert result.report.gates[5].reason_code is ReasonCode.SOFT_THRESHOLD_NOT_MET
    assert result.report.gates[-1].verdict is ValidationVerdict.PASS
    assert result.report.metrics == (observed,)


def test_unexpected_stage_error_is_sanitized_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_passes(monkeypatch)

    def explode(*_args: object) -> validation_service._StageOutput:
        raise RuntimeError("private provider detail")

    monkeypatch.setattr(ValidationService, "_g3", explode)
    result = ValidationService().run(
        _authoring(),
        _policy(),
        _research(),
        _locators(tmp_path),
        tmp_path / "reports",
        tmp_path / "events",
        canonical=False,
    )
    gate = result.report.gates[3]
    assert result.report.run_status is RunStatus.FAILED
    assert gate.reason_code is ReasonCode.QLIB_EXECUTION_FAILED
    assert "private" not in gate.reason
    assert gate.gate_id is ValidationGateId.G3_FACTOR_RESEARCH


def test_oos_metric_extraction_reuses_qlib_risk_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backtest = tmp_path / "backtest"
    backtest.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "trade_date": date(2024, 1, 2),
                    "return": 0.01,
                    "cost": 0.001,
                    "turnover": 0.2,
                },
                {
                    "trade_date": date(2024, 1, 3),
                    "return": -0.005,
                    "cost": 0.001,
                    "turnover": 0.4,
                },
            ]
        ),
        backtest / "portfolio.parquet",
    )
    monkeypatch.setattr(
        validation_service,
        "_QLIB_RISK_ANALYSIS",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"risk": [0.12, 1.5, -0.2]},
            index=["annualized_return", "information_ratio", "max_drawdown"],
        ),
    )

    extracted = validation_service._extract_metrics(
        backtest,
        _reference(),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        annualization_factor=250,
    )

    values = {item.metric: item.value for item in extracted.metrics}
    assert extracted.observation_count == 2
    assert values[SoftMetric.OOS_SHARPE] == 1.5
    assert values[SoftMetric.MAX_DRAWDOWN] == 0.2
    assert values[SoftMetric.ANNUALIZED_RETURN] == 0.12
    assert values[SoftMetric.ANNUALIZED_TURNOVER] == pytest.approx(75.0)

    empty = validation_service._extract_metrics(
        backtest,
        _reference(),
        start=date(2025, 1, 1),
        end=date(2025, 1, 31),
        annualization_factor=250,
    )
    assert empty.observation_count == 0
    assert empty.metrics == ()


def test_metric_extraction_fails_closed_on_schema_and_qlib_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backtest = tmp_path / "backtest"
    backtest.mkdir()
    pq.write_table(
        pa.Table.from_pylist([{"trade_date": date(2024, 1, 2)}]),
        backtest / "portfolio.parquet",
    )
    with pytest.raises(validation_service._GateRejected) as schema:
        validation_service._extract_metrics(
            backtest,
            _reference(),
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            annualization_factor=250,
        )
    assert schema.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    monkeypatch.setattr(
        validation_service,
        "_QLIB_RISK_ANALYSIS",
        lambda *_args, **_kwargs: pd.DataFrame({"unexpected": [1.0]}),
    )
    with pytest.raises(validation_service._ExecutionFailed) as drift:
        validation_service._risk_values(pd.Series([0.1]))
    assert drift.value.reason_code is ReasonCode.QLIB_EXECUTION_FAILED

    monkeypatch.setattr(
        validation_service,
        "_QLIB_RISK_ANALYSIS",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("qlib failed")),
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "trade_date": date(2024, 1, 2),
                    "return": 0.01,
                    "cost": 0.001,
                    "turnover": 0.2,
                }
            ]
        ),
        backtest / "portfolio.parquet",
    )
    with pytest.raises(validation_service._ExecutionFailed, match="risk analysis failed"):
        validation_service._extract_metrics(
            backtest,
            _reference(),
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            annualization_factor=250,
        )
