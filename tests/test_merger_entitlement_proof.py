from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pyarrow as pa
import pytest

from quantos.data.tushare.dividend_acquisition import FIELDS, _SafeClient
from quantos.research.merger_entitlement_proof import assess_dividend_records
from quantos.research.merger_entitlement_sources import derive_dividend_rule, derive_merger_rule


def _rule() -> dict[str, Any]:
    return {
        "instrument_id": "600837.SH",
        "record_date": "2023-07-27",
        "pay_date": "2023-07-28",
        "source_sha256": "a" * 64,
        "registration_basis": "CLOSE_REGISTERED_OLD_SHARES",
    }


def _close(day: str, amount: object, kind: str = "OBSERVED_NATIVE_EOD") -> dict[str, Any]:
    return {
        "candidate_id": "random-17",
        "stock_id": "SH600837",
        "date": day,
        "amount": amount,
        "evidence_kind": kind,
    }


def test_later_sale_and_payment_flag_do_not_discharge_dividend() -> None:
    rule = {**_rule(), "paid_evidence": True}
    rows = [_close("2023-07-27", 329.625), _close("2023-07-28", 0)]
    result = assess_dividend_records([rule], rows, candidate_ids=("random-17",))
    assert result["positive_holding_payment_unproven_count"] == 1
    assert result["rows"][0]["payment_status"] == "NOT_PROVEN_BY_THIS_AUDIT"
    assert result["rows"][0]["cash_amount"] is None
    assert not result["clears_merger_boundary"]


def test_no_carry_forward_or_derived_future_close() -> None:
    for rows in ([_close("2023-07-26", 0)], [_close("2023-07-27", 0, "DERIVED_ZERO")]):
        result = assess_dividend_records([_rule()], rows, candidate_ids=("random-17",))
        assert result["unknown_count"] == 1
        assert result["record_zero_count"] == 0


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -1, None, True])
def test_invalid_amount_cannot_prove_zero(amount: object) -> None:
    result = assess_dividend_records(
        [_rule()], [_close("2023-07-27", amount)], candidate_ids=("random-17",)
    )
    assert result["unknown_count"] == 1
    assert not result["grants_execution_authority"]


def test_zero_is_only_one_distribution_not_complete_inventory() -> None:
    result = assess_dividend_records(
        [_rule()], [_close("2023-07-27", 0)], candidate_ids=("random-17",)
    )
    assert result["record_zero_count"] == 1
    assert not result["complete_distribution_inventory_proven"]
    with pytest.raises(ValueError, match="duplicate native"):
        assess_dividend_records(
            [_rule()], [_close("2023-07-27", 0)] * 2, candidate_ids=("random-17",)
        )


def test_snapshot_discards_provider_metadata_and_rejects_secret_cells() -> None:
    secret = "dummy-credential-for-boundary-test"
    values = dict.fromkeys(FIELDS)
    values.update(ts_code="600837.SH", end_date="20221231", ann_date="20230617", div_proc="实施")
    frame = pd.DataFrame([values], columns=FIELDS)
    frame.attrs["untrusted"] = secret
    frame.index.name = secret
    frame.columns.name = secret

    class FakeSDK:
        def query(self, *args: object, **kwargs: object) -> pd.DataFrame:
            return frame

    client = _SafeClient(cast(Any, SimpleNamespace(client=FakeSDK())), secret)
    clean = client.query("dividend", fields=",".join(FIELDS), ts_code="600837.SH", limit="2000")
    assert not clean.attrs and clean.index.name is None and clean.columns.name is None
    metadata = cast(Any, pa).Table.from_pandas(clean).schema.metadata or {}
    assert all(secret.encode() not in item for pair in metadata.items() for item in pair)
    frame.loc[0, "div_proc"] = secret
    with pytest.raises(RuntimeError, match="unsafe provider"):
        client.query("dividend", fields=",".join(FIELDS), ts_code="600837.SH", limit="2000")


def test_non_pdf_and_wrong_issuer_cannot_supply_notice_terms() -> None:
    for derive in (derive_dividend_rule, derive_merger_rule):
        with pytest.raises(ValueError, match="actual PDF"):
            derive(b"<html>status 200, not an announcement</html>", "600837.SH")
        with pytest.raises(ValueError, match="unsupported"):
            derive(b"%PDF-1.7", "000001.SZ")
