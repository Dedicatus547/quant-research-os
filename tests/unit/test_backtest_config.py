from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quantos.application import resolve_experiment
from quantos.backtest import translate_backtest_config
from quantos.config import load_yaml_contract
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.research import ExperimentAuthoringSpec
from quantos.contracts.temporal import DecisionSchedule
from quantos.research.qlib import QlibResearchError

ROOT = Path(__file__).parents[2]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _schedule(day: int, execution_day: int) -> DecisionSchedule:
    return DecisionSchedule(
        signal_time=datetime(2024, 1, day, 15, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, day, 15, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, day, 15, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, execution_day, 9, 30, tzinfo=SHANGHAI),
    )


def _resolved() -> tuple[object, CostPolicy, BacktestPolicy]:
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
    return resolved, cost, policy


def test_backtest_translation_has_no_implicit_qlib_defaults() -> None:
    resolved, cost, policy = _resolved()

    config = translate_backtest_config(
        resolved,
        signal_artifact_hash="3" * 64,
        cost_policy=cost,
        backtest_policy=policy,
        schedules=(_schedule(5, 8), _schedule(12, 15)),
        exchange_codes=("SH600000", "SZ000001"),
    )

    assert config.executor == "Qlib SimulatorExecutor"
    assert config.deal_price == "$open"
    assert config.limit_threshold_fields == (
        "$limit_buy+$is_st",
        "$limit_sell+$is_st",
    )
    assert config.volume_threshold == ("current", "$volume*0.10000000000000001")
    assert config.trade_unit_shares == 100
    assert config.settlement == "None"
    assert config.exchange_codes == ("SH600000", "SZ000001")
    assert config.position_type == "Position"
    assert len(config.known_limitations) == 2


def test_backtest_translation_rejects_policy_drift_and_unsorted_dates() -> None:
    resolved, cost, policy = _resolved()
    changed_cost = cost.model_copy(update={"open_cost_rate": 0.001})

    with pytest.raises(QlibResearchError, match="does not match"):
        translate_backtest_config(
            resolved,
            signal_artifact_hash="3" * 64,
            cost_policy=changed_cost,
            backtest_policy=policy,
            schedules=(_schedule(5, 8),),
            exchange_codes=("SH600000",),
        )
    with pytest.raises(QlibResearchError, match="sorted"):
        translate_backtest_config(
            resolved,
            signal_artifact_hash="3" * 64,
            cost_policy=cost,
            backtest_policy=policy,
            schedules=(_schedule(12, 15), _schedule(5, 8)),
            exchange_codes=("SH600000",),
        )

    with pytest.raises(QlibResearchError, match="exchange codes"):
        translate_backtest_config(
            resolved,
            signal_artifact_hash="3" * 64,
            cost_policy=cost,
            backtest_policy=policy,
            schedules=(_schedule(5, 8),),
            exchange_codes=(),
        )
