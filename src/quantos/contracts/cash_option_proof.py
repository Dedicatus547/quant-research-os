"""Bounded source and conditional no-acquisition proofs; no execution authority."""

from datetime import date
from typing import Literal

from pydantic import Field

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN


class ContinuousCashOptionRule(CanonicalContract):
    schema_version: Literal["continuous-cash-option-rule/v1"] = "continuous-cash-option-rule/v1"
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.SH$")
    source_id: str
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    window_start: date
    window_end: date
    physical_pages: tuple[int, ...]
    predicate: Literal["CONTINUOUS_HOLDING_DISPOSAL_REDUCES_LATER_BUY_DOES_NOT_INCREASE"] = (
        "CONTINUOUS_HOLDING_DISPOSAL_REDUCES_LATER_BUY_DOES_NOT_INCREASE"
    )
    registration_start_exact_time: None = None
    scope: Literal["ORDINARY_NATIVE_MODEL_NO_EXTERNAL_OR_SEPARATE_RIGHTS_SOURCE"] = (
        "ORDINARY_NATIVE_MODEL_NO_EXTERNAL_OR_SEPARATE_RIGHTS_SOURCE"
    )


class ConditionalCashOptionProof(CanonicalContract):
    schema_version: Literal["conditional-cash-option-proof/v1"] = "conditional-cash-option-proof/v1"
    candidate_id: str
    old_prepared_hash: str = Field(pattern=SHA256_PATTERN)
    rule_hash: str = Field(pattern=SHA256_PATTERN)
    observation_hash: str = Field(pattern=SHA256_PATTERN)
    signal_sha256: str = Field(pattern=SHA256_PATTERN)
    target_witness_sha256: str = Field(pattern=SHA256_PATTERN)
    session: date
    status: Literal["CONDITIONAL_NO_ACQUISITION", "NOT_PROVEN"]
    reasons: tuple[str, ...]
    native_source_hashes: dict[str, str]
    evidence_kind: Literal["DERIVED_CONDITIONAL_NOT_OBSERVED_SESSION_CLOSE"] = (
        "DERIVED_CONDITIONAL_NOT_OBSERVED_SESSION_CLOSE"
    )
    successor_runtime_recheck_required: Literal[True] = True
    old_terminal_state_changed: Literal[False] = False
    grants_execution_authority: Literal[False] = False
    covers_merger_or_delisting: Literal[False] = False
