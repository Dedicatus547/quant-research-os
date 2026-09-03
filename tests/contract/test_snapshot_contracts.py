from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts.snapshot import (
    ColumnManifest,
    DataQualityPolicy,
    DataQualityReport,
    DataQualityRule,
    DataSnapshotManifest,
    QualityGateResult,
    SnapshotBuildSpec,
    SnapshotFileManifest,
    SnapshotSourceKind,
)
from quantos.contracts.status import ReasonCode


def _file(path: str = "canonical/bars.parquet") -> SnapshotFileManifest:
    return SnapshotFileManifest(
        logical_path=path,
        sha256="a" * 64,
        size_bytes=10,
        media_type="application/vnd.apache.parquet",
        table_name="bars",
        row_count=1,
        min_date=date(2024, 1, 2),
        max_date=date(2024, 1, 2),
        columns=(ColumnManifest(name="trade_date", arrow_type="date32[day]", nullable=False),),
    )


def _manifest() -> DataSnapshotManifest:
    return DataSnapshotManifest.create(
        dataset_id="tiny",
        source_kind=SnapshotSourceKind.SYNTHETIC_FIXTURE,
        provider="synthetic",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        build_spec_hash="b" * 64,
        quality_policy_hash="c" * 64,
        quality_report_hash="d" * 64,
        normalizer_version="normalizer/v1",
        files=(_file(),),
        limitations=("SYNTHETIC_DATA_NOT_LIVE_EVIDENCE",),
        created_at=datetime(2024, 1, 3, tzinfo=UTC),
    )


def test_snapshot_build_spec_sorts_and_deduplicates_endpoints() -> None:
    spec = SnapshotBuildSpec(
        dataset_id="tiny",
        source_kind=SnapshotSourceKind.SYNTHETIC_FIXTURE,
        provider="synthetic",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        required_endpoints=("daily", "adj_factor", "daily"),
        normalizer_version="normalizer/v1",
        availability_policy_id="availability/v1",
    )
    assert spec.required_endpoints == ("adj_factor", "daily")


def test_snapshot_build_spec_rejects_invalid_range_and_unknown_fields() -> None:
    values = {
        "dataset_id": "tiny",
        "source_kind": "SYNTHETIC_FIXTURE",
        "provider": "synthetic",
        "start_date": date(2024, 1, 3),
        "end_date": date(2024, 1, 2),
        "required_endpoints": ("daily",),
        "normalizer_version": "normalizer/v1",
        "availability_policy_id": "availability/v1",
    }
    with pytest.raises(ValidationError):
        SnapshotBuildSpec.model_validate(values)
    values["end_date"] = date(2024, 1, 4)
    values["unexpected"] = True
    with pytest.raises(ValidationError):
        SnapshotBuildSpec.model_validate(values)


def test_quality_contract_requires_reason_only_for_failure() -> None:
    passing = QualityGateResult(
        rule=DataQualityRule.SCHEMA,
        passed=True,
        checked_rows=1,
        detail="schema valid",
    )
    report = DataQualityReport(
        policy_hash=DataQualityPolicy(policy_id="dq/v1").content_hash,
        passed=True,
        gates=(passing,),
    )
    assert report.passed
    with pytest.raises(ValidationError):
        QualityGateResult(
            rule=DataQualityRule.SCHEMA,
            passed=False,
            checked_rows=1,
            detail="schema invalid",
        )
    with pytest.raises(ValidationError):
        DataQualityReport(policy_hash="a" * 64, passed=False, gates=(passing,))


def test_manifest_is_self_hashed_and_rejects_tampering() -> None:
    manifest = _manifest()
    assert manifest.snapshot_hash == manifest.content_hash
    changed = manifest.model_dump(mode="python")
    changed["provider"] = "changed"
    with pytest.raises(ValidationError):
        DataSnapshotManifest.model_validate(changed)


def test_snapshot_file_manifest_rejects_unsafe_or_partial_metadata() -> None:
    with pytest.raises(ValidationError):
        _file("../escape.parquet")
    with pytest.raises(ValidationError):
        SnapshotFileManifest(
            logical_path="canonical/bars.parquet",
            sha256="a" * 64,
            size_bytes=1,
            media_type="application/vnd.apache.parquet",
            table_name="bars",
        )


def test_failing_gate_accepts_stable_reason_code() -> None:
    result = QualityGateResult(
        rule=DataQualityRule.PRIMARY_KEY,
        passed=False,
        checked_rows=2,
        reason_code=ReasonCode.SCHEMA_INVALID,
        detail="duplicate key",
    )
    assert result.reason_code is ReasonCode.SCHEMA_INVALID
