from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.application import resolve_experiment
from quantos.config import load_yaml_contract
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    ValidationPolicy,
)

ROOT = Path(__file__).parents[2]


def test_authoring_spec_resolves_to_hash_bound_canonical_spec() -> None:
    authoring = load_yaml_contract(
        ROOT / "configs" / "research" / "hs300_momentum_v1.yaml",
        ExperimentAuthoringSpec,
    )
    resolved = resolve_experiment(
        authoring,
        snapshot_hash="a" * 64,
        qlib_view_hash="b" * 64,
        qlib_version="0.9.7",
        qlib_view_spec_hash="c" * 64,
        pit_audit_evidence_hash="d" * 64,
        research_policy_hash="e" * 64,
        validation_policy_hash="f" * 64,
        cost_policy_hash="0" * 64,
        backtest_policy_hash="6" * 64,
        code_commit_hash="1" * 40,
        lockfile_hash="2" * 64,
    )

    assert resolved.authoring_spec_hash == authoring.content_hash
    assert resolved.expression.nodes[-1].operator == "return"
    assert resolved.expression.nodes[-1].window == 20
    assert resolved.snapshot_hash == "a" * 64
    assert resolved.strategy.execution_lag_trading_sessions == 1


def test_resolved_spec_rejects_missing_hashes_and_lag_drift() -> None:
    authoring = load_yaml_contract(
        ROOT / "configs" / "research" / "hs300_momentum_v1.yaml",
        ExperimentAuthoringSpec,
    )
    resolved = resolve_experiment(
        authoring,
        snapshot_hash="a" * 64,
        qlib_view_hash="b" * 64,
        qlib_version="0.9.7",
        qlib_view_spec_hash="c" * 64,
        pit_audit_evidence_hash="d" * 64,
        research_policy_hash="e" * 64,
        validation_policy_hash="f" * 64,
        cost_policy_hash="0" * 64,
        backtest_policy_hash="6" * 64,
        code_commit_hash="1" * 40,
        lockfile_hash="2" * 64,
    )
    payload = resolved.model_dump(mode="python")
    payload.pop("snapshot_hash")
    with pytest.raises(ValidationError):
        ResolvedExperimentSpec.model_validate(payload)

    changed = resolved.model_dump(mode="python")
    changed["strategy"]["input_lag_trading_days"] = 2
    with pytest.raises(ValidationError):
        ResolvedExperimentSpec.model_validate(changed)


def test_engineering_and_research_validation_policies_are_separate() -> None:
    engineering = load_yaml_contract(
        ROOT / "configs" / "validation" / "engineering_v1.yaml", ValidationPolicy
    )
    research = load_yaml_contract(
        ROOT / "configs" / "validation" / "research_candidate_v1.yaml", ValidationPolicy
    )

    assert engineering.soft_gates == ()
    assert {item.metric for item in research.soft_gates} == {
        "oos_sharpe",
        "max_drawdown",
        "annualized_turnover",
    }
    assert engineering.content_hash != research.content_hash


def test_research_policy_freezes_splits_purge_and_model_determinism() -> None:
    policy = load_yaml_contract(ROOT / "configs" / "research" / "policy_v1.yaml", ResearchPolicy)

    assert policy.train.end < policy.validation.start < policy.test.start
    assert policy.purge_trading_days == 5
    assert policy.random_seed == 1729
    assert policy.num_threads == 1

    invalid = policy.model_dump(mode="python")
    invalid["purge_trading_days"] = 0
    with pytest.raises(ValidationError, match="forward-label horizon"):
        ResearchPolicy.model_validate(invalid)


def test_cost_policy_is_hash_bound_qlib_exchange_configuration() -> None:
    policy = load_yaml_contract(ROOT / "configs" / "backtest" / "cost_v1.yaml", CostPolicy)
    backtest = load_yaml_contract(ROOT / "configs" / "backtest" / "policy_v1.yaml", BacktestPolicy)

    assert policy.deal_price == "open"
    assert policy.trade_unit_shares == 100
    assert policy.price_limit_fields == "$limit_buy,$limit_sell"
    assert backtest.engine == "Qlib SimulatorExecutor"
    assert backtest.limit_precheck_semantics.startswith("conservative_")
