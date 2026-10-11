"""Independent effective DatasetH split evidence; frozen ResearchResult/v1 is unchanged."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, PositiveInt, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research import ResearchSegment
from quantos.contracts.research_result import ResearchResultSourceFile


class QlibModelDataSegment(CanonicalContract):
    schema_version: Literal["qlib-model-data-segment/v1"] = "qlib-model-data-segment/v1"
    declared: ResearchSegment
    effective: ResearchSegment
    observed_sessions: tuple[date, ...]
    sample_rows: PositiveInt
    sample_index_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def ordered_nonempty_samples(self) -> Self:
        if not self.observed_sessions or self.observed_sessions != tuple(
            sorted(set(self.observed_sessions))
        ):
            raise ValueError("observed DatasetH sessions must be nonempty and canonical")
        if not all(
            self.effective.start <= day <= self.effective.end for day in self.observed_sessions
        ):
            raise ValueError("observed DatasetH samples exceed effective segment")
        if self.sample_rows < len(self.observed_sessions):
            raise ValueError("DatasetH sample rows cannot be fewer than its sessions")
        return self


class QlibModelDataSplitAudit(CanonicalContract):
    schema_version: Literal["qlib-model-data-split-audit/v1"] = "qlib-model-data-split-audit/v1"
    split_policy: Literal["calendar-session-purge/v1"] = "calendar-session-purge/v1"
    resolved_spec_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    calendar_hash: str = Field(pattern=SHA256_PATTERN)
    purge_trading_days: PositiveInt
    label_horizon_trading_sessions: PositiveInt
    train: QlibModelDataSegment
    valid: QlibModelDataSegment
    test: QlibModelDataSegment
    source_files: tuple[ResearchResultSourceFile, ...]

    @model_validator(mode="after")
    def native_sources_exact(self) -> Self:
        if tuple(item.logical_path for item in self.source_files) != (
            "label.pkl",
            "metrics.json",
            "pred.pkl",
            "sig_analysis/ic.pkl",
            "sig_analysis/ric.pkl",
        ):
            raise ValueError("split audit must bind the exact original native source inventory")
        return self
