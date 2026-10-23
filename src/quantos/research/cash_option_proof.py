"""Source-bound, conditional stock-ID absence proof, never portfolio accounting.

For the pinned native path, targets/current holdings bound possible order IDs.
This proves what continuing that path cannot acquire; it does not invent a
completed session, a native rights ledger, a fill, cash or a resume checkpoint.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import Path

from quantos.artifacts.store import confined_regular_file
from quantos.contracts.base import sha256_bytes
from quantos.contracts.cash_option_proof import (
    ConditionalCashOptionProof,
    ContinuousCashOptionRule,
)
from quantos.contracts.hs300_lifecycle import LifecycleFactBundle, NativeBoundaryObservation
from quantos.data.lifecycle_sources import (
    _pdf_pages,  # pyright: ignore[reportPrivateUsage]
    parse_cash_entitlement_window,
)


def derive_continuous_cash_rule(
    facts: LifecycleFactBundle, source_root: Path, instrument_id: str
) -> ContinuousCashOptionRule:
    specifications = {
        "600837.SH": ("haitong-halt-cash", 4, (6, 7)),
        "601989.SH": ("csic-halt-cash", 3, (3, 6)),
    }
    source_id, continuous_page, disposal_pages = specifications[instrument_id]
    source = next(item for item in facts.sources if item.source_id == source_id)
    if source.kind not in {"OFFICIAL_COMPANY", "OFFICIAL_EXCHANGE"}:
        raise ValueError("cash eligibility requires its official original")
    raw = confined_regular_file(source_root, source.logical_path).read_bytes()
    if sha256_bytes(raw) != source.sha256:
        raise ValueError("cash eligibility original hash changed")
    pages = _pdf_pages(raw)

    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value)

    if f"证券代码\uff1a{instrument_id[:6]}" not in normalize("".join(pages)):
        raise ValueError("cash eligibility original issuer differs")
    continuous = normalize(pages[continuous_page - 1])
    disposal = normalize("".join(pages[p - 1] for p in disposal_pages))
    if (
        "一直持续持有代表该反对权利的" not in continuous
        or "直至" not in continuous
        or "现金选择权实施日" not in continuous
        or "股份数量相应减少" not in disposal
        or "股份数量不增加" not in disposal
        or "股票买入行为" not in disposal
        or ("股票处置行为" not in disposal and "股票卖出行为" not in disposal)
    ):
        raise ValueError("cash eligibility necessary continuous/monotone rules missing")
    window = parse_cash_entitlement_window(pages[4], expected_code=instrument_id[:6])
    return ContinuousCashOptionRule.model_validate(
        dict(
            instrument_id=instrument_id,
            source_id=source_id,
            source_sha256=source.sha256,
            window_start=window["window_start"],
            window_end=window["window_end"],
            physical_pages=tuple(sorted({5, continuous_page, *disposal_pages})),
        )
    )


def prove_conditional_no_acquisition(
    *,
    candidate_id: str,
    old_prepared_hash: str,
    rule: ContinuousCashOptionRule,
    observation: NativeBoundaryObservation,
    target_weights: Mapping[str, float],
    signal_sha256: str,
    target_witness_sha256: str,
    native_source_hashes: dict[str, str],
    expected_native_source_hashes: Mapping[str, str],
) -> ConditionalCashOptionProof:
    """Apply the reviewed stock-ID closure lemma only to its exact frozen runtime.

    Caller must verify the old outcome/receipt, source/panel and signal identities,
    calendar shift and actual original target function. Native source hashes bind
    the reviewed lemma: OrderGen target support -> Exchange target/current support
    -> synchronous Simulator supplied orders -> Position order.stock_id updates.
    No already observed closing position is asserted by this conditional result.
    """
    affected = rule.instrument_id[-2:] + rule.instrument_id[:6]
    reasons: list[str] = []
    if not rule.window_start <= observation.session <= rule.window_end:
        reasons.append("observed session is outside the necessary continuous window")
    if not (
        observation.native_classes_verified
        and observation.fresh_cash_no_initial_holdings_no_external_flow
        and observation.sequential_history_complete
    ):
        reasons.append("complete native ordinary-account lineage is unproven")
    holdings = observation.all_holdings
    if holdings is None or any(not math.isfinite(v) for v in holdings.values()):
        reasons.append("native holdings are missing or nonfinite")
    elif holdings.get(affected, 0) != 0 or affected in holdings:
        # Require absence of the key too: native order support includes current keys.
        reasons.append("affected security is in native current-position support")
    previous = observation.previous_unfilled_orders
    if previous is None or any(
        order.qlib_id == affected and order.amount > order.deal_amount for order in previous
    ):
        reasons.append("affected prior unfilled order absence is unproven")
    generated = observation.current_generated_orders
    if generated is None or any(
        order.qlib_id == affected and order.amount > order.deal_amount for order in generated
    ):
        reasons.append("known current affected order or missing order observation")
    if affected in target_weights or any(
        not math.isfinite(weight) or weight < 0 for weight in target_weights.values()
    ):
        reasons.append("affected security may be acquired from the actual target support")
    if not expected_native_source_hashes or native_source_hashes != expected_native_source_hashes:
        reasons.append("native order-support lemma runtime identity differs")
    required_observed = {
        "qlib.backtest.account",
        "qlib.backtest.position",
        "qlib.backtest.executor",
        "qlib.backtest.decision",
        "qlib.contrib.strategy.order_generator",
    }
    if set(observation.native_source_hashes) != required_observed or any(
        native_source_hashes.get(name.replace(".", "/") + ".py") != digest
        for name, digest in observation.native_source_hashes.items()
    ):
        reasons.append("observed native account/runtime hashes differ from reviewed sources")
    if observation.observed_pending_rights and affected in observation.observed_pending_rights:
        reasons.append("known independent affected rights cannot be excluded by stock absence")
    return ConditionalCashOptionProof(
        candidate_id=candidate_id,
        old_prepared_hash=old_prepared_hash,
        rule_hash=rule.content_hash,
        observation_hash=observation.content_hash,
        signal_sha256=signal_sha256,
        target_witness_sha256=target_witness_sha256,
        session=observation.session,
        status="NOT_PROVEN" if reasons else "CONDITIONAL_NO_ACQUISITION",
        reasons=tuple(reasons),
        native_source_hashes=native_source_hashes,
    )
