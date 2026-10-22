"""Bounded source-value checks; no vendor requests or market execution."""

from datetime import UTC, date, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hs300_lifecycle import (
    LifecycleFactBundle,
    LifecycleSourceArtifact,
    SecurityLifecycleFact,
    UnsupportedAccountEvent,
)
from quantos.data.lifecycle_sources import (
    parse_cash_entitlement_window,
    parse_exchange_delisting,
    verify_lifecycle_source_values,
)


def test_explicit_dates_and_issuer_required():
    raw = (
        "<p>证券代码\uff1a600001</p><p>决定自2025年3月4日起终止其股票在本所上市交易</p>"
    ).encode()
    assert parse_exchange_delisting(raw, expected_code="600001")["delist_date"] == "2025-03-04"
    with pytest.raises(ValueError, match="security"):
        parse_exchange_delisting(raw, expected_code="600002")
    page = "现金选择权股权登记日期间(即2024 年12 月9 日至 2025 年2 月5 日)"
    assert (
        parse_cash_entitlement_window(page, expected_code="600001")["window_start"] == "2024-12-09"
    )
    with pytest.raises(ValueError, match="missing or ambiguous"):
        parse_cash_entitlement_window("现金选择权股权登记日未知", expected_code="600001")


def test_facts_must_match_original_values_even_when_file_hashes_match(tmp_path):
    instrument = tmp_path / "instruments.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "instrument_id": "600001.SH",
                    "list_date": date(2000, 1, 1),
                    "delist_date": date(2025, 3, 4),
                }
            ]
        ),
        instrument,
    )
    spec = tmp_path / "derivation.json"
    spec.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "hs300-lifecycle-derivation-spec/v1",
                "rules": [
                    {"rule": "canonical-instrument-lifecycle/v1", "source_id": "instruments"}
                ],
            }
        )
    )
    sources = tuple(
        LifecycleSourceArtifact(
            source_id=name,
            kind=kind,
            logical_path=path.name,
            sha256=sha256_file(path),
            observed_at=datetime.now(UTC),
        )
        for name, kind, path in (
            ("instruments", "TUSHARE_PRO", instrument),
            ("derivation", "DERIVATION_SPEC", spec),
        )
    )
    fact = SecurityLifecycleFact(
        instrument_id="600001.SH",
        list_date=date(2000, 1, 1),
        delist_date=date(2025, 3, 4),
        source_ids=("instruments",),
    )
    event = UnsupportedAccountEvent(
        event_id="delist",
        instrument_id=fact.instrument_id,
        boundary_date=fact.delist_date,
        event_type="DELISTING",
        source_ids=("instruments",),
    )
    bundle = LifecycleFactBundle(
        coverage_start=date(2023, 1, 1),
        coverage_end=date(2025, 12, 31),
        source_vintage="historical_non_vintage",
        sources=sources,
        securities=(fact,),
        events=(event,),
        derivation_source_id="derivation",
    )
    verify_lifecycle_source_values(bundle, tmp_path)
    changed = bundle.model_copy(
        update={
            "securities": (fact.model_copy(update={"delist_date": date(2025, 3, 5)}),),
            "events": (event.model_copy(update={"boundary_date": date(2025, 3, 5)}),),
        }
    )
    with pytest.raises(ValueError, match="original instrument"):
        verify_lifecycle_source_values(changed, tmp_path)
    for extra in (
        {"related_instrument_ids": ("600002.SH",)},
        {"entitlement_window_start": date(2024, 1, 1)},
    ):
        changed = bundle.model_copy(update={"events": (event.model_copy(update=extra),)})
        with pytest.raises(ValueError, match="unverified boundary fields"):
            verify_lifecycle_source_values(changed, tmp_path)
