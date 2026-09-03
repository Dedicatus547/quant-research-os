"""Strict runtime-only locators for already published validation evidence.

Paths are deliberately not canonical evidence.  Every target is re-opened and
verified by content hash before a validation gate may use it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _explicit_hash_path(value: Path) -> Path:
    forbidden = {"latest", "current", "auto"}
    if any(part.lower() in forbidden for part in value.parts):
        raise ValueError("validation locators cannot contain mutable aliases")
    if not value.name.startswith("sha256-") or len(value.name) != 71:
        raise ValueError("artifact directory must have an explicit sha256-<hash> name")
    suffix = value.name.removeprefix("sha256-")
    if any(character not in "0123456789abcdef" for character in suffix):
        raise ValueError("artifact directory hash must be lowercase hexadecimal")
    return value


class _LocatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VariantArtifactLocator(_LocatorModel):
    signal_path: Path
    backtest_path: Path

    _signal_is_explicit = field_validator("signal_path")(_explicit_hash_path)
    _backtest_is_explicit = field_validator("backtest_path")(_explicit_hash_path)


class CostStressLocator(VariantArtifactLocator):
    multiplier: float = Field(gt=0)


class ParameterStabilityLocator(VariantArtifactLocator):
    window: int = Field(gt=0)
    top_k: int = Field(gt=0)


class SubperiodLocator(VariantArtifactLocator):
    period_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    start: date
    end: date

    @model_validator(mode="after")
    def range_is_ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("subperiod locator start cannot be after end")
        return self


class ValidationRunLocators(_LocatorModel):
    """Filesystem locations only; hashes are always resolved from verified manifests."""

    schema_version: Literal["validation-run-locators/v1"] = "validation-run-locators/v1"
    snapshot_path: Path
    qlib_view_path: Path
    signal_path: Path | None = None
    baseline_backtest_path: Path | None = None
    reproduction_backtest_path: Path | None = None
    pit_report_path: Path | None = None
    cost_stress: tuple[CostStressLocator, ...] = ()
    parameter_stability: tuple[ParameterStabilityLocator, ...] = ()
    subperiods: tuple[SubperiodLocator, ...] = ()

    _snapshot_is_explicit = field_validator("snapshot_path")(_explicit_hash_path)
    _view_is_explicit = field_validator("qlib_view_path")(_explicit_hash_path)

    @field_validator(
        "signal_path",
        "baseline_backtest_path",
        "reproduction_backtest_path",
    )
    @classmethod
    def optional_artifact_is_explicit(cls, value: Path | None) -> Path | None:
        return None if value is None else _explicit_hash_path(value)

    @field_validator("pit_report_path")
    @classmethod
    def pit_report_is_explicit(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        if value.name in {"latest", "current", "auto"}:
            raise ValueError("PIT report locator cannot be a mutable alias")
        if not value.name.startswith("sha256-") or value.suffix != ".json":
            raise ValueError("PIT report must have an explicit sha256-<hash>.json name")
        return value

    @model_validator(mode="after")
    def locator_keys_are_unique(self) -> Self:
        multipliers = [item.multiplier for item in self.cost_stress]
        parameters = [(item.window, item.top_k) for item in self.parameter_stability]
        periods = [item.period_id for item in self.subperiods]
        if len(multipliers) != len(set(multipliers)):
            raise ValueError("cost stress multipliers must be unique")
        if len(parameters) != len(set(parameters)):
            raise ValueError("parameter stability cases must be unique")
        if len(periods) != len(set(periods)):
            raise ValueError("subperiod locator IDs must be unique")
        if (
            self.baseline_backtest_path is not None
            and self.reproduction_backtest_path is not None
            and self.baseline_backtest_path.resolve() == self.reproduction_backtest_path.resolve()
        ):
            raise ValueError("reproduction evidence must come from an independent output root")
        return self
