"""Offline eligibility findings, never a dividend ledger or runtime exemption.

An observed zero on one distribution's registration date rules out that one
distribution in the ordinary closed account scope. A positive observation
cannot prove payment, and a later sale cannot erase the historical question.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


def assess_dividend_records(
    rules: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    *,
    candidate_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Assess exact EOD dates only, without carrying observations forward.

    Callers must verify source, extraction and original artifact bindings. This
    function does not accept a caller's "paid" flag as settlement evidence.
    Even an all-zero matrix does not establish a complete distribution inventory
    or clear other merger rights, external flows, initial rights or an event.
    """
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for observation in observations:
        key = (
            str(observation["candidate_id"]),
            str(observation["stock_id"]),
            str(observation["date"]),
        )
        date.fromisoformat(key[2])
        if key in index:
            raise ValueError("duplicate native close observation")
        index[key] = observation
    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate inventory must be explicit and unique")
    rule_keys: set[tuple[str, str]] = set()
    matrix: list[dict[str, Any]] = []
    for rule in rules:
        code, record_date = str(rule["instrument_id"]), str(rule["record_date"])
        date.fromisoformat(record_date)
        if (
            len(code) != 9
            or not code.endswith(".SH")
            or rule["registration_basis"] != "CLOSE_REGISTERED_OLD_SHARES"
            or (code, record_date) in rule_keys
        ):
            raise ValueError("invalid or duplicate distribution registration rule")
        rule_keys.add((code, record_date))
        stock_id = code[-2:] + code[:6]
        for candidate_id in candidate_ids:
            row = index.get((candidate_id, stock_id, record_date))
            amount: float | None = None
            status = "UNKNOWN_EXACT_REGISTRATION_CLOSE_UNOBSERVED"
            if row is not None and row.get("evidence_kind") == "OBSERVED_NATIVE_EOD":
                try:
                    value = row["amount"]
                    if isinstance(value, bool):
                        raise ValueError("boolean is not an amount")
                    amount = float(value)
                except (TypeError, ValueError):
                    status = "UNKNOWN_INVALID_NATIVE_AMOUNT"
                else:
                    if not math.isfinite(amount) or amount < 0:
                        amount = None
                        status = "UNKNOWN_INVALID_NATIVE_AMOUNT"
                    elif amount == 0:
                        status = "NOT_INCURRED_FOR_THIS_REGISTRATION"
                    else:
                        status = "POSITIVE_REGISTRATION_HOLDING_SETTLEMENT_NOT_PROVEN"
            matrix.append(
                {
                    "candidate_id": candidate_id,
                    "instrument_id": code,
                    "record_date": record_date,
                    "pay_date": rule["pay_date"],
                    "source_sha256": rule["source_sha256"],
                    "native_adjusted_amount": amount,
                    "status": status,
                    "payment_status": "NOT_PROVEN_BY_THIS_AUDIT",
                    "cash_amount": None,
                }
            )
    return {
        "schema_version": "merger-dividend-eligibility-audit/v1",
        "status": "NO_DISTRIBUTIONS_SUPPLIED"
        if not rules
        else "ENUMERATED_RECORDS_ASSESSED_NOT_EVENT_CLEARANCE",
        "rows": matrix,
        "record_zero_count": sum(
            row["status"] == "NOT_INCURRED_FOR_THIS_REGISTRATION" for row in matrix
        ),
        "positive_holding_payment_unproven_count": sum(
            row["status"] == "POSITIVE_REGISTRATION_HOLDING_SETTLEMENT_NOT_PROVEN" for row in matrix
        ),
        "unknown_count": sum(str(row["status"]).startswith("UNKNOWN_") for row in matrix),
        "complete_distribution_inventory_proven": False,
        "account_scope_required": "ORDINARY_FRESH_CASH_NO_EXTERNAL_OR_SEPARATE_RIGHTS_SOURCE",
        "grants_execution_authority": False,
        "clears_merger_boundary": False,
        "amount_semantics": "NATIVE_ADJUSTED_UNITS_NOT_RAW_SHARES; NO_CASH_ESTIMATE",
    }
