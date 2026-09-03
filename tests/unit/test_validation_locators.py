from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.validation import (
    CostStressLocator,
    ParameterStabilityLocator,
    SubperiodLocator,
    ValidationRunLocators,
)


def _artifact(tmp_path: Path, digit: str, *, root: str = "root") -> Path:
    return tmp_path / root / f"sha256-{digit * 64}"


def test_locators_require_explicit_hashes_and_independent_reproduction(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="mutable aliases"):
        ValidationRunLocators(
            snapshot_path=tmp_path / "latest" / f"sha256-{'1' * 64}",
            qlib_view_path=_artifact(tmp_path, "2"),
        )
    with pytest.raises(ValidationError, match="explicit"):
        ValidationRunLocators(
            snapshot_path=tmp_path / "snapshot",
            qlib_view_path=_artifact(tmp_path, "2"),
        )
    with pytest.raises(ValidationError, match="lowercase hexadecimal"):
        ValidationRunLocators(
            snapshot_path=_artifact(tmp_path, "G"),
            qlib_view_path=_artifact(tmp_path, "2"),
        )
    same = _artifact(tmp_path, "3")
    with pytest.raises(ValidationError, match="independent"):
        ValidationRunLocators(
            snapshot_path=_artifact(tmp_path, "1"),
            qlib_view_path=_artifact(tmp_path, "2"),
            baseline_backtest_path=same,
            reproduction_backtest_path=same,
        )


def test_locator_case_keys_and_periods_are_strict(tmp_path: Path) -> None:
    signal = _artifact(tmp_path, "3", root="signals")
    backtest = _artifact(tmp_path, "4", root="backtests")
    cost = CostStressLocator(multiplier=1.0, signal_path=signal, backtest_path=backtest)
    parameter = ParameterStabilityLocator(
        window=20,
        top_k=50,
        signal_path=signal,
        backtest_path=backtest,
    )
    period = SubperiodLocator(
        period_id="period",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        signal_path=signal,
        backtest_path=backtest,
    )

    for field, values, message in (
        ("cost_stress", (cost, cost), "multipliers"),
        ("parameter_stability", (parameter, parameter), "parameter"),
        ("subperiods", (period, period), "subperiod"),
    ):
        with pytest.raises(ValidationError, match=message):
            ValidationRunLocators(
                snapshot_path=_artifact(tmp_path, "1"),
                qlib_view_path=_artifact(tmp_path, "2"),
                **{field: values},
            )
    with pytest.raises(ValidationError, match="start"):
        period.model_copy(update={"start": date(2024, 2, 1)}).__class__.model_validate(
            {**period.model_dump(), "start": date(2024, 2, 1)}
        )


def test_pit_report_locator_is_hash_named(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="PIT report"):
        ValidationRunLocators(
            snapshot_path=_artifact(tmp_path, "1"),
            qlib_view_path=_artifact(tmp_path, "2"),
            pit_report_path=tmp_path / "pit.json",
        )
    locators = ValidationRunLocators(
        snapshot_path=_artifact(tmp_path, "1"),
        qlib_view_path=_artifact(tmp_path, "2"),
        pit_report_path=tmp_path / f"sha256-{'a' * 64}.json",
    )
    assert locators.pit_report_path is not None
