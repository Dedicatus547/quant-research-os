from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts.qlib_view import (
    ConverterInputDigest,
    InstrumentCodeMapping,
    QlibSemanticSample,
    QlibViewFile,
    QlibViewManifest,
    QlibViewSpec,
)


def _mapping() -> InstrumentCodeMapping:
    return InstrumentCodeMapping(instrument_id="600000.SH", qlib_id="SH600000")


def _sample(actual: float = 10.0, passed: bool = True) -> QlibSemanticSample:
    return QlibSemanticSample(
        qlib_id="SH600000",
        trade_date=date(2024, 1, 2),
        field="$close",
        expected=10.0,
        actual=actual,
        absolute_tolerance=1e-6,
        passed=passed,
    )


def test_instrument_mapping_is_reversible() -> None:
    assert _mapping().qlib_id == "SH600000"
    with pytest.raises(ValidationError):
        InstrumentCodeMapping(instrument_id="600000.SH", qlib_id="SZ600000")


def test_view_spec_requires_locked_fields_and_sorted_collision_free_mappings() -> None:
    spec = QlibViewSpec(
        source_snapshot_hash="a" * 64,
        qlib_version="0.9.7",
        qlib_source_commit="b" * 40,
        dump_bin_sha256="c" * 64,
        health_check_sha256="d" * 64,
        mappings=(
            InstrumentCodeMapping(instrument_id="000001.SZ", qlib_id="SZ000001"),
            _mapping(),
        ),
    )
    assert spec.include_fields[-1] == "is_st"
    with pytest.raises(ValidationError):
        QlibViewSpec(
            source_snapshot_hash="a" * 64,
            qlib_version="0.9.7",
            qlib_source_commit="b" * 40,
            dump_bin_sha256="c" * 64,
            health_check_sha256="d" * 64,
            include_fields=("close",),
            mappings=(_mapping(),),
        )


def test_semantic_sample_outcome_must_match_tolerance() -> None:
    assert _sample().passed
    with pytest.raises(ValidationError):
        _sample(actual=11.0, passed=True)


def test_view_manifest_is_self_hashed_and_rejects_tampering() -> None:
    manifest = QlibViewManifest.create(
        source_snapshot_hash="a" * 64,
        view_spec_hash="b" * 64,
        qlib_version="0.9.7",
        qlib_source_commit="c" * 40,
        dump_bin_sha256="1" * 64,
        health_check_sha256="2" * 64,
        converter_inputs=(ConverterInputDigest(qlib_id="SH600000", sha256="d" * 64, row_count=1),),
        files=(QlibViewFile(logical_path="calendars/day.txt", sha256="e" * 64, size_bytes=1),),
        health_check_passed=True,
        semantic_samples=(_sample(),),
        created_at=datetime(2024, 1, 3, tzinfo=UTC),
    )
    assert manifest.view_hash == manifest.content_hash
    changed = manifest.model_dump(mode="python")
    changed["qlib_version"] = "changed"
    with pytest.raises(ValidationError):
        QlibViewManifest.model_validate(changed)


def test_view_file_rejects_unsafe_path() -> None:
    with pytest.raises(ValidationError):
        QlibViewFile(logical_path="../escape.bin", sha256="e" * 64, size_bytes=1)
