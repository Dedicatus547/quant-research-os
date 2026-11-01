"""Explicit vendor-adjusted-unit successor; historical policies stay unchanged."""

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.hs300_cash import (
    HS300CashDatasetManifest,
    HS300CashProfile,
    HS300CashStudyRequest,
    PreparedHS300CashStudy,
)
from quantos.contracts.hs300_lifecycle import LifecycleSourceArtifact
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path


class VendorAdjustedUnitSemantics(CanonicalContract):
    schema_version: Literal["vendor-adjusted-unit-semantics/v1"] = (
        "vendor-adjusted-unit-semantics/v1"
    )
    valuation_scope: Literal["VENDOR_ADJUSTED_PRICE_AND_QUANTITY_UNITS"] = (
        "VENDOR_ADJUSTED_PRICE_AND_QUANTITY_UNITS"
    )
    price: Literal["CANONICAL_RAW_OHLC_TIMES_VENDOR_ADJUSTMENT_FACTOR"] = (
        "CANONICAL_RAW_OHLC_TIMES_VENDOR_ADJUSTMENT_FACTOR"
    )
    quantity: Literal["RAW_EQUIVALENT_SHARES_DIVIDED_BY_SAME_DAY_FACTOR"] = (
        "RAW_EQUIVALENT_SHARES_DIVIDED_BY_SAME_DAY_FACTOR"
    )
    ordinary_cash_dividends: Literal["VENDOR_FACTOR_ONLY_NO_SEPARATE_CASH_RECEIVABLE"] = (
        "VENDOR_FACTOR_ONLY_NO_SEPARATE_CASH_RECEIVABLE"
    )
    tax_and_payment: Literal["NOT_MODELED_NO_ACTUAL_PAYMENT_OR_NET_TOTAL_RETURN_CLAIM"] = (
        "NOT_MODELED_NO_ACTUAL_PAYMENT_OR_NET_TOTAL_RETURN_CLAIM"
    )
    account_lineage: Literal["FRESH_NATIVE_CASH_NO_EXTERNAL_FLOW_OR_OTHER_SHARE_SOURCE"] = (
        "FRESH_NATIVE_CASH_NO_EXTERNAL_FLOW_OR_OTHER_SHARE_SOURCE"
    )
    unsupported_events: Literal["NO_ACCOUNT_MUTATION_ZERO_INPUT_PROOF_OR_HARD_STOP"] = (
        "NO_ACCOUNT_MUTATION_ZERO_INPUT_PROOF_OR_HARD_STOP"
    )


class AdjustedUnitPolicy(CanonicalContract):
    schema_version: Literal["hs300-adjusted-unit-policy/v1"] = "hs300-adjusted-unit-policy/v1"
    semantics_hash: str = VendorAdjustedUnitSemantics().content_hash
    cash_options: Literal["UNCHANGED_ACTUAL_TARGET_AND_GENERATED_CASH_RULE"] = (
        "UNCHANGED_ACTUAL_TARGET_AND_GENERATED_CASH_RULE"
    )
    merger_and_delisting: Literal["SOURCE_BOUND_ZERO_INPUT_NATIVE_EFFECTIVE_QUOTE_PROOF"] = (
        "SOURCE_BOUND_ZERO_INPUT_NATIVE_EFFECTIVE_QUOTE_PROOF"
    )
    unknown_or_exposed: Literal["HARD_STOP_NOT_EVALUATED"] = "HARD_STOP_NOT_EVALUATED"
    absent_native_ledger: Literal["NOT_EVIDENCE_OF_EMPTY_OR_PAID_RIGHTS"] = (
        "NOT_EVIDENCE_OF_EMPTY_OR_PAID_RIGHTS"
    )
    accounting: Literal["NO_ACCOUNT_OR_RIGHTS_LEDGER_MUTATION"] = (
        "NO_ACCOUNT_OR_RIGHTS_LEDGER_MUTATION"
    )


class AdjustedDividendFact(CanonicalContract):
    schema_version: Literal["hs300-adjusted-dividend-fact/v1"] = "hs300-adjusted-dividend-fact/v1"
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    source_id: str
    source_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    record_date: date
    ex_date: date
    pay_date: date
    cash_div_tax: Decimal = Field(gt=0)
    use: Literal["NOTICE_TERMS_ONLY_NO_MODEL_CASH_CREDIT_OR_PAYMENT_PROOF"] = (
        "NOTICE_TERMS_ONLY_NO_MODEL_CASH_CREDIT_OR_PAYMENT_PROOF"
    )

    @model_validator(mode="after")
    def dates(self) -> Self:
        if not self.record_date < self.ex_date or self.pay_date < self.record_date:
            raise ValueError("dividend notice dates are inconsistent")
        return self


class ZeroHoldingMergerRule(CanonicalContract):
    schema_version: Literal["hs300-zero-holding-merger-rule/v1"] = (
        "hs300-zero-holding-merger-rule/v1"
    )
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    issuer_instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    source_id: str
    source_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    record_date: date
    ratio: Decimal = Field(gt=0)
    boundary_date: date
    event_ids: tuple[str, ...] = Field(min_length=1)
    registration_basis: Literal["CLOSE_REGISTERED_OLD_SHARES"] = "CLOSE_REGISTERED_OLD_SHARES"
    fractional_rule: Literal["INTEGER_SHARES_REMAINDER_RANK_RANDOM_TIES"] = (
        "INTEGER_SHARES_REMAINDER_RANK_RANDOM_TIES"
    )
    proof: Literal["ZERO_OLD_SHARE_INPUT_NO_CONVERSION_OR_FRACTIONAL_ALLOCATION"] = (
        "ZERO_OLD_SHARE_INPUT_NO_CONVERSION_OR_FRACTIONAL_ALLOCATION"
    )

    @model_validator(mode="after")
    def dates_and_ids(self) -> Self:
        if self.boundary_date > self.record_date or len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("merger boundary or event identities are inconsistent")
        return self


class AdjustedUnitFactBundle(CanonicalContract):
    schema_version: Literal["hs300-adjusted-unit-facts/v1"] = "hs300-adjusted-unit-facts/v1"
    semantics: VendorAdjustedUnitSemantics = Field(default_factory=VendorAdjustedUnitSemantics)
    official_sources: tuple[LifecycleSourceArtifact, ...] = Field(min_length=1)
    vendor_semantics_source_ids: tuple[str, ...] = Field(min_length=2, max_length=2)
    dividends: tuple[AdjustedDividendFact, ...] = Field(min_length=1)
    mergers: tuple[ZeroHoldingMergerRule, ...] = Field(min_length=1)
    source_vintage: Literal["historical_non_vintage"] = "historical_non_vintage"

    @model_validator(mode="after")
    def identities(self) -> Self:
        ids = {source.source_id for source in self.official_sources}
        if len(ids) != len(self.official_sources):
            raise ValueError("duplicate adjusted-unit source")
        if (
            len(set(self.vendor_semantics_source_ids)) != 2
            or not set(self.vendor_semantics_source_ids) <= ids
        ):
            raise ValueError("two bound official vendor semantics documents are required")
        if any(
            source.kind not in {"OFFICIAL_EXCHANGE", "OFFICIAL_COMPANY"}
            for source in self.official_sources
        ):
            raise ValueError("adjusted-unit event terms require official original sources")
        if any(fact.source_id not in ids for fact in (*self.dividends, *self.mergers)):
            raise ValueError("adjusted-unit event references an unbound source")
        dividend_keys = [(fact.instrument_id, fact.record_date) for fact in self.dividends]
        if len(dividend_keys) != len(set(dividend_keys)):
            raise ValueError("duplicate adjusted-unit dividend event")
        if len({rule.instrument_id for rule in self.mergers}) != len(self.mergers):
            raise ValueError("duplicate adjusted-unit merger security")
        if self.semantics != VendorAdjustedUnitSemantics():
            raise ValueError("adjusted-unit model semantics differ")
        return self


class FixedNativeQuoteBinding(CanonicalContract):
    schema_version: Literal["hs300-fixed-native-quote-binding/v1"] = (
        "hs300-fixed-native-quote-binding/v1"
    )
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    calendar_sha256: str = Field(pattern=SHA256_PATTERN)
    quote_files: dict[str, str] = Field(min_length=1)
    sessions_by_instrument: dict[str, tuple[date, ...]] = Field(min_length=1)
    extra_quote: Literal["NONE"] = "NONE"
    cache_policy: Literal["EXPRESSION_AND_DATASET_CACHE_DISABLED"] = (
        "EXPRESSION_AND_DATASET_CACHE_DISABLED"
    )

    @model_validator(mode="after")
    def paths_and_dates(self) -> Self:
        import re

        for path, digest in self.quote_files.items():
            validate_logical_path(path)
            if re.fullmatch(SHA256_PATTERN, digest) is None:
                raise ValueError("invalid fixed quote hash")
        for code, sessions in self.sessions_by_instrument.items():
            if re.fullmatch(r"^[0-9]{6}\.(SH|SZ)$", code) is None:
                raise ValueError("invalid fixed quote security")
            if not sessions or tuple(sorted(set(sessions))) != sessions:
                raise ValueError("fixed quote sessions must be ordered, unique and nonempty")
        return self


class HS300AdjustedProfile(HS300CashProfile):
    schema_version: Literal["hs300-daily-trend-tushare-lifecycle/v3"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "hs300-daily-trend-tushare-lifecycle/v3"
    )
    valuation_scope: Literal["VENDOR_ADJUSTED_PRICE_AND_QUANTITY_UNITS"] = (
        "VENDOR_ADJUSTED_PRICE_AND_QUANTITY_UNITS"
    )
    model_semantics_hash: str = VendorAdjustedUnitSemantics().content_hash
    adjusted_unit_policy_hash: str = AdjustedUnitPolicy().content_hash


class HS300AdjustedStudyRequest(HS300CashStudyRequest):
    schema_version: Literal["personal-study-request/v6"] = "personal-study-request/v6"  # pyright: ignore[reportIncompatibleVariableOverride]
    profile: HS300AdjustedProfile = Field(default_factory=HS300AdjustedProfile)  # pyright: ignore[reportIncompatibleVariableOverride]


class HS300AdjustedDatasetManifest(HS300CashDatasetManifest):
    schema_version: Literal["personal-dataset/v5"] = "personal-dataset/v5"  # pyright: ignore[reportIncompatibleVariableOverride]
    adjusted_facts: AdjustedUnitFactBundle
    adjusted_unit_policy_hash: str = Field(pattern=SHA256_PATTERN)
    adjusted_runtime_source_hashes: dict[str, str] = Field(min_length=1)
    future_quote_binding: FixedNativeQuoteBinding


class PreparedHS300AdjustedStudy(PreparedHS300CashStudy):
    schema_version: Literal["personal-study-prepared/v5"] = "personal-study-prepared/v5"  # pyright: ignore[reportIncompatibleVariableOverride]
    request: HS300AdjustedStudyRequest  # pyright: ignore[reportIncompatibleVariableOverride]
    dataset_manifest: HS300AdjustedDatasetManifest | None  # pyright: ignore[reportIncompatibleVariableOverride]

    @model_validator(mode="after")
    def adjusted_bindings(self) -> Self:
        profile = self.request.profile
        if (
            profile.adjusted_unit_policy_hash != AdjustedUnitPolicy().content_hash
            or profile.model_semantics_hash != VendorAdjustedUnitSemantics().content_hash
        ):
            raise ValueError("adjusted-unit profile policy or semantics differ")
        if self.dataset_manifest is not None:
            manifest = self.dataset_manifest
            if (
                manifest.adjusted_unit_policy_hash != profile.adjusted_unit_policy_hash
                or manifest.adjusted_facts.semantics.content_hash != profile.model_semantics_hash
                or manifest.future_quote_binding.qlib_view_hash != manifest.qlib_view_hash
            ):
                raise ValueError("adjusted-unit dataset policy, semantics or view differs")
        if self.readiness == "READY_FOR_AUTHORIZATION" and (
            self.signal_reuse is None or len(self.origin_reuse) != 1
        ):
            raise ValueError(
                "adjusted-unit successor requires exact seven signals and classic origin"
            )
        return self
