"""Read-only vendor-unit semantics and source-bound zero-input event proofs.

Native Qlib owns execution, holdings and cash. No rights are paid, created,
settled or declared observably empty by this successor.
"""

from __future__ import annotations

import importlib
import math
import pickle
import struct
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from types import CodeType
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from quantos.artifacts.store import atomic_write_bytes, confined_regular_file, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hs300_adjusted import (
    AdjustedUnitFactBundle,
    AdjustedUnitPolicy,
    FixedNativeQuoteBinding,
    HS300AdjustedDatasetManifest,
    VendorAdjustedUnitSemantics,
    ZeroHoldingMergerRule,
)
from quantos.contracts.hs300_lifecycle import NativeBoundaryObservation, UnsupportedAccountEvent
from quantos.research.hs300_cash_runtime import (
    CashRuntimeBoundaryTopKStrategy,
    cash_native_runtime_identity,
    evaluate_cash_boundary,
    verify_hs300_cash_binding,
)
from quantos.research.hs300_lifecycle_data import load_lifecycle_facts
from quantos.research.hs300_native_boundary import (
    NativeAccountBoundaryStop,
    evaluate_native_boundary,
)
from quantos.research.merger_entitlement_sources import derive_dividend_rule, derive_merger_rule

_QUOTE_FIELDS = ("open", "close", "factor", "volume", "change", "is_st")


def adjusted_native_runtime_identity() -> dict[str, str]:
    """Exact loader, quote, native account and project wrapper source identities."""
    names = (
        "qlib.config",
        "qlib.data.data",
        "qlib.data.cache",
        "qlib.data.ops",
        "qlib.data.base",
        "qlib.data.storage",
        "qlib.data.storage.storage",
        "qlib.data.storage.file_storage",
        "qlib.backtest.high_performance_ds",
        "qlib.utils.index_data",
        "quantos.backtest.strategy",
        "quantos.data.qlib_view",
        "quantos.research.hs300_data",
        "quantos.research.hs300_lifecycle_data",
        "quantos.research.merger_entitlement_sources",
        "quantos.data.lifecycle_sources",
        "quantos.contracts.hs300_adjusted",
        "quantos.research.hs300_exchange",
        "quantos.research.hs300_native_boundary",
        "quantos.research.hs300_cash_runtime",
        "quantos.research.hs300_adjusted_runtime",
    )
    return {
        **cash_native_runtime_identity(),
        **{
            name: sha256_file(Path(cast(Any, importlib.import_module(name)).__file__))
            for name in names
        },
    }


def _code_id(instrument: str) -> str:
    return instrument[-2:] + instrument[:6]


def _read_fixed_bins(
    provider: Path, binding: FixedNativeQuoteBinding
) -> tuple[list[date], dict[str, tuple[int, tuple[float, ...]]]]:
    calendar_path = confined_regular_file(provider, "calendars/day.txt")
    if sha256_file(calendar_path) != binding.calendar_sha256:
        raise ValueError("fixed native calendar original differs")
    calendar = [date.fromisoformat(line[:10]) for line in calendar_path.read_text().splitlines()]
    if calendar != sorted(set(calendar)):
        raise ValueError("fixed native calendar is not ordered and unique")
    bins: dict[str, tuple[int, tuple[float, ...]]] = {}
    for logical, digest in binding.quote_files.items():
        path = confined_regular_file(provider, logical)
        if sha256_file(path) != digest:
            raise ValueError("fixed native quote original differs")
        raw = path.read_bytes()
        if len(raw) < 4 or len(raw) % 4:
            raise ValueError("fixed native quote bin layout differs")
        values = struct.unpack("<" + "f" * (len(raw) // 4), raw)
        start = int(values[0])
        if start < 0 or start != values[0] or start + len(values) - 1 > len(calendar):
            raise ValueError("fixed native quote bin calendar range differs")
        bins[logical] = start, values[1:]
    return calendar, bins


def _bin_value(
    bins: dict[str, tuple[int, tuple[float, ...]]], code: str, field: str, index: int
) -> float | None:
    start, values = bins[f"features/{_code_id(code).lower()}/{field}.day.bin"]
    return values[index - start] if start <= index < start + len(values) else None


def _verify_vendor_semantics_sources(
    facts: AdjustedUnitFactBundle, originals: dict[str, bytes]
) -> None:
    class VisibleText(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.hidden = 0
            self.parts: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            del attrs
            if tag in {"script", "style"}:
                self.hidden += 1

        def handle_endtag(self, tag: str) -> None:
            if tag in {"script", "style"}:
                self.hidden -= 1

        def handle_data(self, data: str) -> None:
            if not self.hidden:
                self.parts.append(data)

    document_ids: set[str] = set()
    sources = {source.source_id: source for source in facts.official_sources}
    for source_id in facts.vendor_semantics_source_ids:
        source = sources[source_id]
        parsed = urlparse(source.url or "")
        query = parse_qs(parsed.query)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "tushare.pro"
            or parsed.path != "/document/2"
            or query.get("doc_id") not in (["146"], ["109"])
            or source.kind != "OFFICIAL_COMPANY"
        ):
            raise ValueError(
                "vendor model semantics require the two official Tushare document URLs"
            )
        document_ids.add(query["doc_id"][0])
        raw = originals[source_id]
        if not raw.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            raise ValueError("vendor model semantics source is not original HTML")
        parser = VisibleText()
        parser.feed(raw.decode("utf-8"))
        text = "".join("".join(parser.parts).split())
        if "分红再投" not in text or "复权" not in text:
            raise ValueError("vendor original HTML lacks the declared adjustment convention")
    if document_ids != {"109", "146"}:
        raise ValueError("both distinct official vendor convention documents are required")


def verify_hs300_adjusted_binding(binding: Any) -> None:
    """Verify one new explicit tuple, retaining all base cash/lifecycle checks."""
    verify_hs300_cash_binding(binding)
    manifest = binding.manifest
    if not isinstance(manifest, HS300AdjustedDatasetManifest):
        raise ValueError("vendor-unit execution requires its explicit successor dataset")
    if manifest.adjusted_unit_policy_hash != AdjustedUnitPolicy().content_hash:
        raise ValueError("vendor-unit policy differs")
    if manifest.adjusted_runtime_source_hashes != adjusted_native_runtime_identity():
        raise ValueError("vendor-unit native quote/account runtime differs")
    if binding.adjusted_facts_path is None:
        raise ValueError("vendor-unit facts original is missing")
    facts_path = Path(binding.adjusted_facts_path)
    facts = AdjustedUnitFactBundle.model_validate_json(facts_path.read_bytes())
    if facts != manifest.adjusted_facts or facts.semantics != VendorAdjustedUnitSemantics():
        raise ValueError("vendor-unit facts or semantics original differs")
    originals: dict[str, bytes] = {}
    for source in facts.official_sources:
        path = confined_regular_file(facts_path.parent, source.logical_path)
        if sha256_file(path) != source.sha256:
            raise ValueError("vendor-unit official source original differs")
        originals[source.source_id] = path.read_bytes()
    _verify_vendor_semantics_sources(facts, originals)
    for dividend in facts.dividends:
        rule = derive_dividend_rule(originals[dividend.source_id], dividend.instrument_id)
        if sha256_bytes(canonical_json_bytes(rule)) != dividend.source_rule_sha256 or any(
            str(getattr(dividend, name)) != str(rule[name])
            for name in ("record_date", "ex_date", "pay_date", "cash_div_tax")
        ):
            raise ValueError("vendor-unit dividend terms differ from official PDF")
    lifecycle = load_lifecycle_facts(binding.lifecycle_path, manifest.lifecycle_manifest_hash)
    events = {event.event_id: event for event in lifecycle.events}
    bound_events: set[str] = set()
    for merger in facts.mergers:
        rule = derive_merger_rule(originals[merger.source_id], merger.instrument_id)
        if sha256_bytes(canonical_json_bytes(rule)) != merger.source_rule_sha256 or any(
            str(getattr(merger, name)) != str(rule[name])
            for name in (
                "record_date",
                "ratio",
                "issuer_instrument_id",
                "registration_basis",
                "fractional_rule",
            )
        ):
            raise ValueError("vendor-unit merger terms differ from official PDF")
        for event_id in merger.event_ids:
            event = events.get(event_id)
            if (
                event is None
                or event_id in bound_events
                or event.event_type not in {"MERGER_EXCHANGE", "DELISTING"}
                or event.instrument_id != merger.instrument_id
                or event.boundary_date < merger.boundary_date
            ):
                raise ValueError("vendor-unit merger rule references a different native event")
            bound_events.add(event_id)
        if not any(
            events[event_id].event_type == "MERGER_EXCHANGE"
            and events[event_id].boundary_date == merger.boundary_date
            for event_id in merger.event_ids
        ):
            raise ValueError("vendor-unit merger rule lacks the exact initial hard boundary")
    quote = manifest.future_quote_binding
    if (
        quote.qlib_view_hash != manifest.qlib_view_hash
        or quote.calendar_sha256 != manifest.qlib_files.get("calendars/day.txt")
        or set(quote.sessions_by_instrument) != {rule.instrument_id for rule in facts.mergers}
    ):
        raise ValueError("vendor-unit future quote view or security inventory differs")
    required = {
        f"features/{_code_id(rule.instrument_id).lower()}/{field}.day.bin"
        for rule in facts.mergers
        for field in _QUOTE_FIELDS
    }
    if set(quote.quote_files) != required or any(
        manifest.qlib_files.get(path) != digest for path, digest in quote.quote_files.items()
    ):
        raise ValueError("vendor-unit complete quote-field bindings differ")
    calendar, bins = _read_fixed_bins(Path(binding.provider_root), quote)
    for rule in facts.mergers:
        sessions = tuple(day for day in calendar if rule.boundary_date <= day <= manifest.end_date)
        if (
            quote.sessions_by_instrument[rule.instrument_id] != sessions
            or rule.record_date not in sessions
        ):
            raise ValueError(
                "vendor-unit future sessions do not cover boundary through research end"
            )
        for day in sessions:
            value = _bin_value(bins, rule.instrument_id, "close", calendar.index(day))
            if value is not None and not math.isnan(value):
                raise ValueError("source-bound merger window has a usable close")


def _verify_method_code(instance: Any, methods: tuple[str, ...]) -> None:
    """Compare executing critical method code with its actual bound source file."""
    for name in methods:
        method = getattr(instance, name)
        function = getattr(method, "__func__", method)
        function = getattr(function, "__wrapped__", function)
        actual = getattr(function, "__code__", None)
        if actual is None or name in getattr(instance, "__dict__", {}):
            raise ValueError("native method was overridden on its runtime instance")
        path = Path(actual.co_filename)
        module = importlib.import_module(function.__module__)
        if path.resolve() != Path(cast(Any, module).__file__).resolve():
            raise ValueError("native method code is not from its bound module")
        module_code = compile(
            path.read_bytes(), str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize
        )

        def find(code: CodeType, qualname: str = actual.co_qualname) -> list[CodeType]:
            found = [code] if code.co_qualname == qualname else []
            for constant in code.co_consts:
                if isinstance(constant, CodeType):
                    found.extend(find(constant))
            return found

        originals = find(module_code)
        if (
            len(originals) != 1
            or originals[0] != actual
            or originals[0].co_filename != actual.co_filename
            or originals[0].co_linetable != actual.co_linetable
        ):
            raise ValueError("executing native method code differs from frozen source")


def _all_match(value: Any, expected: float | None) -> bool:
    if value is None:
        return expected is None or math.isnan(expected)
    raw = getattr(value, "data", value)
    values = np.asarray(raw, dtype=float).reshape(-1)
    if expected is None or math.isnan(expected):
        return bool(np.isnan(values).all())
    return bool(values.size and (values == expected).all())


def verify_effective_native_quote(
    strategy: Any,
    rule: ZeroHoldingMergerRule,
    quote_binding: FixedNativeQuoteBinding,
    provider_root: Path,
    fixed: tuple[list[Any], dict[str, tuple[int, tuple[float, ...]]]],
) -> dict[str, Any]:
    """Inspect the real executor's effective quote, never a development substitute."""
    NumpyQuote = cast(Any, importlib.import_module("qlib.backtest.high_performance_ds")).NumpyQuote
    C = cast(Any, importlib.import_module("qlib.config")).C
    HS300OpenLimitExchange = cast(
        Any, importlib.import_module("quantos.research.hs300_exchange")
    ).HS300OpenLimitExchange

    exchange = strategy.trade_exchange
    executor = strategy.executor
    if (
        type(exchange) is not HS300OpenLimitExchange
        or executor.trade_exchange is not exchange
        or strategy.common_infra.get("trade_exchange") is not exchange
        or type(exchange.quote) is not NumpyQuote
        or exchange.quote_cls is not NumpyQuote
        or exchange.extra_quote is not None
        or exchange.freq != "day"
        or exchange.trade_w_adj_price
        or getattr(strategy, "_trade_exchange", None) is not None
    ):
        raise ValueError("native effective exchange/quote path differs")
    providers = C["provider_uri"]
    if not isinstance(providers, dict):
        raise ValueError("native provider configuration is not the local fixed provider mapping")
    roots = list(cast(dict[str, Any], providers).values())
    if (
        not roots
        or any(Path(str(root)).resolve() != provider_root.resolve() for root in roots)
        or C["expression_cache"] is not None
        or C["dataset_cache"] is not None
    ):
        raise ValueError("native provider or cache configuration differs")
    _verify_method_code(
        exchange,
        (
            "get_quote_from_qlib",
            "check_stock_suspended",
            "is_stock_tradable",
            "get_close",
            "deal_order",
        ),
    )
    # NumpyQuote.get_data is lru_cache wrapped: inspect its executing original.
    _verify_method_code(exchange.quote, ("get_all_stock", "get_data"))
    account = strategy.common_infra.get("trade_account")
    _verify_method_code(
        account, ("update_order", "update_current_position", "update_hist_positions")
    )
    _verify_method_code(
        account.current_position,
        ("_buy_stock", "_sell_stock", "update_order", "update_stock_price", "settle_commit"),
    )
    calendar, bins = fixed
    if not exchange.quote_df.index.is_unique:
        raise ValueError("native effective quote has duplicate keys")
    rows: list[dict[str, Any]] = []
    for day in quote_binding.sessions_by_instrument[rule.instrument_id]:
        index = calendar.index(day)
        if index + 1 >= len(calendar):
            raise ValueError("native future interval lacks its next calendar endpoint")
        start = pd.Timestamp(day)
        end = pd.Timestamp(calendar[index + 1]) - pd.Timedelta(seconds=1)
        code = _code_id(rule.instrument_id)
        key = (code, start)
        for field in _QUOTE_FIELDS:
            expected = _bin_value(bins, rule.instrument_id, field, index)
            column = "$" + field
            if column not in exchange.quote_df:
                raise ValueError("native effective quote omitted a bound field")
            frame_value = (
                exchange.quote_df.loc[key, column] if key in exchange.quote_df.index else None
            )
            effective = exchange.quote.get_data(code, start, end, column)
            if not _all_match(frame_value, expected) or not _all_match(effective, expected):
                raise ValueError("native effective quote differs from immutable feature bytes")
        if (
            not exchange.check_stock_suspended(code, start, end)
            or exchange.is_stock_tradable(code, start, end, 0)
            or exchange.is_stock_tradable(code, start, end, 1)
            or not _all_match(exchange.get_close(code, start, end), None)
        ):
            raise ValueError("native effective quote permits an acquisition in the fixed window")
        rows.append(
            {
                "session": day,
                "effective_close": None,
                "suspended": True,
                "buy_tradable": False,
                "sell_tradable": False,
            }
        )
    return {
        "schema_version": "hs300-effective-native-quote-proof/v1",
        "instrument_id": rule.instrument_id,
        "rule_hash": rule.content_hash,
        "quote_binding_hash": quote_binding.content_hash,
        "actual_exchange_class": "quantos.research.hs300_exchange.HS300OpenLimitExchange",
        "actual_quote_class": "qlib.backtest.high_performance_ds.NumpyQuote",
        "provider_uri": str(provider_root.resolve()),
        "sessions": rows,
        "conclusion": "ACTUAL_NATIVE_QUOTE_NO_ACQUISITION_PATH",
        "not_claimed": "NO_FUTURE_ACCOUNT_CLOSE_OR_ACTUAL_DIVIDEND_PAYMENT_OBSERVATION",
    }


def evaluate_adjusted_zero_boundary(
    event: UnsupportedAccountEvent,
    observation: NativeBoundaryObservation,
    rule: ZeroHoldingMergerRule,
    *,
    phase: str,
    actual_target: dict[str, float] | None,
    effective_quote_proof_hash: str | None,
    facts_hash: str,
) -> dict[str, Any]:
    """Derive a zero merger input in this scoped model; never settle a right."""
    affected = {_code_id(code) for code in (event.instrument_id, *event.related_instrument_ids)}
    reasons: list[str] = []
    unknown = not (
        observation.native_classes_verified
        and observation.fresh_cash_no_initial_holdings_no_external_flow
        and observation.sequential_history_complete
        and observation.all_holdings is not None
        and observation.previous_unfilled_orders is not None
        and observation.current_generated_orders is not None
        and event.event_id in rule.event_ids
        and event.instrument_id == rule.instrument_id
        and event.event_type in {"MERGER_EXCHANGE", "DELISTING"}
        and effective_quote_proof_hash is not None
    )
    holdings = observation.all_holdings or {}
    if any(not math.isfinite(amount) for amount in holdings.values()):
        unknown = True
    exposed = any(holdings.get(code, 0) != 0 for code in affected)
    if exposed:
        reasons.append("affected current native quantity is nonzero")
    if affected.intersection(observation.observed_pending_rights or ()):
        exposed = True
        reasons.append("observed independent rights remain a hard boundary")
    if (
        observation.pending_rights_observability == "OBSERVABLE"
        and observation.observed_pending_rights is None
    ):
        unknown = True
    for orders in (observation.previous_unfilled_orders, observation.current_generated_orders):
        if orders is not None and any(
            order.qlib_id in affected and order.amount != 0 for order in orders
        ):
            exposed = True
            reasons.append("affected prior pending or actual generated native order")
    if phase == "generated":
        if actual_target is None or any(
            not math.isfinite(weight) or weight < 0 for weight in actual_target.values()
        ):
            unknown = True
            reasons.append("actual target invocation is unavailable")
        elif affected.intersection(actual_target):
            exposed = True
            reasons.append("actual target supports an affected security")
    if unknown:
        reasons.append(
            "source-bound model, ordinary account lineage, observations "
            "or effective quote proof missing"
        )
    status = (
        "HARD_STOP_EXPOSURE"
        if exposed
        else "HARD_STOP_UNKNOWN"
        if unknown
        else "CLEARED_DERIVED_ZERO_MERGER_INPUT"
        if phase == "generated"
        else "PENDING_ACTUAL_GENERATION"
    )
    return {
        "event_id": event.event_id,
        "event_hash": event.content_hash,
        "observation_hash": observation.content_hash,
        "policy_hash": AdjustedUnitPolicy().content_hash,
        "adjusted_facts_hash": facts_hash,
        "rule_hash": rule.content_hash,
        "effective_quote_proof_hash": effective_quote_proof_hash,
        "status": status,
        "rights_conclusion": "DERIVED_ZERO_OLD_SHARE_INPUT_IN_VENDOR_UNIT_MODEL"
        if status == "CLEARED_DERIVED_ZERO_MERGER_INPUT"
        else "UNPROVEN",
        "native_rights_observability": observation.pending_rights_observability,
        "ordinary_dividend_scope": "VENDOR_FACTOR_ONLY_NO_SEPARATE_CASH_RECEIVABLE",
        "future_account_eod_observed": False,
        "actual_dividend_payment_proven": False,
        "reasons": reasons,
    }


class AdjustedUnitBoundaryTopKStrategy(CashRuntimeBoundaryTopKStrategy):
    def __init__(
        self,
        *,
        adjusted_facts: dict[str, Any],
        adjusted_unit_policy_hash: str,
        adjusted_runtime_source_hashes: dict[str, str],
        future_quote_binding: dict[str, Any],
        provider_root: str,
        **kwargs: Any,
    ) -> None:
        if adjusted_unit_policy_hash != AdjustedUnitPolicy().content_hash:
            raise ValueError("adjusted-unit runtime policy differs")
        if adjusted_runtime_source_hashes != adjusted_native_runtime_identity():
            raise ValueError("adjusted-unit runtime source identity differs")
        self._adjusted_facts = AdjustedUnitFactBundle.model_validate(adjusted_facts)
        self._adjusted_hashes = adjusted_runtime_source_hashes
        self._fixed_quote_binding = FixedNativeQuoteBinding.model_validate(future_quote_binding)
        self._provider_root = Path(provider_root)
        if not self._provider_root.is_absolute():
            raise ValueError("adjusted-unit provider must be explicit absolute path")
        self._fixed = _read_fixed_bins(self._provider_root, self._fixed_quote_binding)
        self._merger_by_event = {
            event_id: rule for rule in self._adjusted_facts.mergers for event_id in rule.event_ids
        }
        self._quote_proofs: dict[str, tuple[Any, Any, Any, Any, str]] = {}
        super().__init__(**kwargs)

    def _effective_quote_proof(self, rule: ZeroHoldingMergerRule) -> str:
        exchange = cast(Any, self).trade_exchange
        cached = self._quote_proofs.get(rule.instrument_id)
        if cached is not None:
            if (
                cached[0] is not exchange
                or cached[1] is not exchange.quote
                or cached[2] is not exchange.quote_df
                or cached[3] is not exchange.quote.data
                or exchange.extra_quote is not None
                or cast(Any, self).executor.trade_exchange is not exchange
                or cast(Any, self).common_infra.get("trade_exchange") is not exchange
            ):
                raise ValueError("previously bound effective native quote instance changed")
            return cached[4]
        proof = verify_effective_native_quote(
            cast(Any, self), rule, self._fixed_quote_binding, self._provider_root, self._fixed
        )
        raw = canonical_json_bytes(proof)
        digest = sha256_bytes(raw)
        # Same native quote proof is content-addressed; each boundary references it.
        atomic_write_bytes(self._boundary_root / f"effective-quote-{digest}.proof", raw)
        self._quote_proofs[rule.instrument_id] = (
            exchange,
            exchange.quote,
            exchange.quote_df,
            exchange.quote.data,
            digest,
        )
        return digest

    def _cash_boundaries(
        self,
        events: list[UnsupportedAccountEvent],
        observation: NativeBoundaryObservation,
        phase: str,
    ) -> None:
        decisions: list[dict[str, Any]] = []
        for event in events:
            cash_rule = self._cash_rules.get(event.instrument_id)
            merger = self._merger_by_event.get(event.event_id)
            if event.event_type == "CASH_OPTION" and cash_rule is not None:
                decision = evaluate_cash_boundary(
                    event,
                    observation,
                    cash_rule,
                    phase=phase,
                    actual_target=self._actual_target,
                    locked_proof_hash=self._cash_locked.get(event.event_id),
                )
            elif merger is not None:
                quote_hash = None
                try:
                    quote_hash = self._effective_quote_proof(merger)
                except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
                    quote_error = type(error).__name__
                else:
                    quote_error = None
                decision = evaluate_adjusted_zero_boundary(
                    event,
                    observation,
                    merger,
                    phase=phase,
                    actual_target=self._actual_target,
                    effective_quote_proof_hash=quote_hash,
                    facts_hash=self._adjusted_facts.content_hash,
                )
                decision["effective_quote_error_type"] = quote_error
            else:
                decision = evaluate_native_boundary(
                    event, observation, self._facts.policy
                ).model_dump(mode="json")
            decisions.append(decision)
        payload = {
            "schema_version": "hs300-native-boundary-receipt/v3",
            "events": {event.event_id: event.content_hash for event in events},
            "observation": observation,
            "decisions": decisions,
            "actual_target": self._actual_target if phase == "generated" else None,
            "phase": phase,
            "lifecycle_manifest_hash": self._facts.content_hash,
            "adjusted_facts_hash": self._adjusted_facts.content_hash,
            "model_semantics_hash": self._adjusted_facts.semantics.content_hash,
            "adjusted_unit_policy_hash": AdjustedUnitPolicy().content_hash,
            "native_source_hashes": self._adjusted_hashes,
            "native_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
        }
        raw = canonical_json_bytes(payload)
        atomic_write_bytes(
            self._boundary_root / f"{observation.session.isoformat()}-{phase}.json", raw
        )
        for decision in decisions:
            if decision["status"] == "CLEARED_DERIVED_CASH_INELIGIBILITY":
                self._cash_locked.setdefault(decision["event_id"], sha256_bytes(raw))
        stopped = next((item for item in decisions if item["status"].startswith("HARD_STOP")), None)
        if stopped is not None:
            account = cast(Any, self).common_infra.get("trade_account")
            for name, value in (
                ("position", account.current_position),
                ("portfolio", account.get_portfolio_metrics()),
                ("indicator", account.get_trade_indicator()),
            ):
                atomic_write_bytes(
                    self._boundary_root / f"{observation.session.isoformat()}-partial-{name}.pkl",
                    pickle.dumps(value, protocol=4),
                )
            raise NativeAccountBoundaryStop(stopped["event_id"])
