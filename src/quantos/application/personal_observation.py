"""Finite offline observations over trusted immutable snapshots.

This module records arrival and publication semantics. Qlib signal compilation is
injected by the trusted server; it never acquires data or maintains an account.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal, Self, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pydantic import Field, field_validator, model_validator

from quantos.application.personal_research import PersonalDatasetBinding
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    confined_regular_file,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    verify_file,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalExecutionPolicy, PersonalStrategy
from quantos.contracts.refs import SHA256_PATTERN
from quantos.research.qlib.personal_expression import FIELD_MAPPING, required_history

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_BYTES = 4 * 1024 * 1024
_MAX_RECORDS = 500
_UNIT_COLUMNS = ("close", "volume", "adjustment_factor")
# Frozen before comparisons: prices/factors/quantity floats use these tolerances.
_RTOL = _ATOL = 1e-12


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps require an explicit timezone")
    return value.astimezone(UTC)


def _hash(value: str) -> str:
    if re.fullmatch(SHA256_PATTERN, value) is None:
        raise ValueError("observation references require an exact SHA256")
    return value


def _read(directory: Path, name: str) -> bytes:
    with opened_directory(directory) as descriptor:
        return read_regular_bytes_at(descriptor, name, max_bytes=_MAX_BYTES)


def _write(directory: Path, name: str, value: object) -> None:
    with opened_directory(directory, create=True) as descriptor:
        atomic_write_bytes_at(descriptor, name, canonical_json_bytes(value))


def _object(directory: Path, name: str) -> dict[str, Any]:
    raw = _read(directory, name)
    decoded: Any = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ArtifactIntegrityError("observation authority must be a canonical object")
    value = cast(dict[str, Any], decoded)
    if canonical_json_bytes(value) != raw:
        raise ArtifactIntegrityError("observation authority must be canonical JSON")
    return value


class SnapshotArrival(CanonicalContract):
    """Operator-bound metadata; never accepted as an MCP observation argument."""

    schema_version: Literal["personal-snapshot-arrival/v1"] = "personal-snapshot-arrival/v1"
    acquired_at: datetime
    source_visible_at: datetime
    received_at: datetime
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    previous_snapshot_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    units: Literal["supplier_adjusted_price_and_quantity"] = "supplier_adjusted_price_and_quantity"
    corporate_actions: Literal["KNOWN_NONE_IN_SCOPE", "UNSUPPORTED_OR_UNKNOWN"] = (
        "UNSUPPORTED_OR_UNKNOWN"
    )

    @field_validator("acquired_at", "source_visible_at", "received_at")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def ordered_arrival(self) -> Self:
        if max(self.acquired_at, self.source_visible_at) > self.received_at:
            raise ValueError("source visibility/acquisition cannot follow receipt")
        return self


class SnapshotArrivalV2(SnapshotArrival):
    schema_version: Literal["personal-snapshot-arrival/v2"] = "personal-snapshot-arrival/v2"  # pyright: ignore[reportIncompatibleVariableOverride]
    corporate_actions: Literal["SUPPORTED_IN_DECLARED_SOURCE_SCOPE", "UNSUPPORTED_OR_UNKNOWN"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "UNSUPPORTED_OR_UNKNOWN"
    )
    assessment_hash: str = Field(pattern=SHA256_PATTERN)
    assessment_end_date: date
    fresh_account_start: date


def parse_snapshot_arrival(value: Mapping[str, Any]) -> SnapshotArrival:
    model = (
        SnapshotArrivalV2
        if value.get("schema_version") == "personal-snapshot-arrival/v2"
        else SnapshotArrival
    )
    return model.model_validate(value)


def corporate_actions_supported(arrival: SnapshotArrival | None, day: date | None = None) -> bool:
    if isinstance(arrival, SnapshotArrivalV2):
        return arrival.corporate_actions == "SUPPORTED_IN_DECLARED_SOURCE_SCOPE" and (
            day is None or day == arrival.assessment_end_date
        )
    return arrival is not None and arrival.corporate_actions == "KNOWN_NONE_IN_SCOPE"


class PersonalObservationRequest(CanonicalContract):
    schema_version: Literal["personal-observation-request/v1"] = "personal-observation-request/v1"
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    strategy: PersonalStrategy
    policy: PersonalExecutionPolicy = Field(default_factory=PersonalExecutionPolicy)
    planned_dates: tuple[date, ...] = Field(min_length=1, max_length=120)
    benchmark: str = Field(default="SH000300", pattern=r"^(SH|SZ)[0-9]{6}$")

    @model_validator(mode="after")
    def finite_dates(self) -> Self:
        if tuple(sorted(set(self.planned_dates))) != self.planned_dates:
            raise ValueError("planned_dates must be ordered and unique")
        return self


ObservationCompiler = Callable[
    [PersonalDatasetBinding, PersonalStrategy, date, datetime], dict[str, Any]
]
ObservationAuthorizer = Callable[[dict[str, Any]], str | None]


class ObservationPITError(ValueError):
    """An unknown input identity/time/status cannot become an eligible score."""


class PersonalObservationService:
    """Immutable plans and append-only observations, with explicit crash reconciliation."""

    def __init__(
        self,
        root: Path,
        catalog: Mapping[str, PersonalDatasetBinding],
        compiler: ObservationCompiler,
        *,
        metadata: Mapping[str, SnapshotArrival] | None = None,
        authorizer: ObservationAuthorizer | None = None,
        compiler_runtime_hash: str | None = None,
    ) -> None:
        self.root = root.absolute()
        self.catalog = dict(catalog)
        self.metadata = dict(metadata or {})
        self.compiler = compiler
        self.authorizer = authorizer
        self.compiler_runtime_hash = (
            None if compiler_runtime_hash is None else _hash(compiler_runtime_hash)
        )
        for key, binding in self.catalog.items():
            if key != binding.manifest.dataset_id:
                raise ValueError("trusted observation catalog identity disagrees")
        with opened_directory(self.root, create=True):
            pass

    def _binding(self, dataset_id: str) -> PersonalDatasetBinding:
        try:
            return self.catalog[dataset_id]
        except KeyError as error:
            raise ValueError("dataset_id is not registered by the trusted server") from error

    def _input(self, dataset_id: str) -> tuple[dict[str, Any], list[date]]:
        binding = self._binding(dataset_id)
        manifest = binding.manifest
        logical = "calendars/day.txt"
        expected = manifest.qlib_files.get(logical)
        if expected is None:
            raise ValueError("explicit calendar hash is required")
        calendar_path = confined_regular_file(binding.provider_root, logical)
        raw = _read(calendar_path.parent, calendar_path.name)
        if sha256_bytes(raw) != expected:
            raise ArtifactIntegrityError("observation calendar hash disagrees")
        sessions = [date.fromisoformat(line.strip()) for line in raw.decode().splitlines()]
        if not sessions or sorted(set(sessions)) != sessions:
            raise ValueError("calendar sessions must be ordered and unique")
        metadata = self.metadata.get(dataset_id)
        result = {
            "schema_version": "personal-observation-input/v1",
            "dataset_id": dataset_id,
            "dataset_manifest_hash": manifest.content_hash,
            "snapshot_hash": manifest.snapshot_hash,
            "qlib_view_hash": manifest.qlib_view_hash,
            "panel_sha256": manifest.panel_sha256,
            "pit_evidence_hash": manifest.pit_evidence_hash,
            "source_vintage": manifest.source_vintage,
            "kind": manifest.kind,
            "calendar_sha256": expected,
            "arrival": None if metadata is None else metadata.canonical_payload(),
        }
        if binding.field_mapping_profile != "native-bins/v1":
            from quantos.research.personal_signal import dataset_binding_hash

            result.update(
                dataset_binding_hash=dataset_binding_hash(binding),
                field_mapping_profile=binding.field_mapping_profile,
            )
        input_hash = sha256_bytes(canonical_json_bytes(result))
        _write(self.root / "inputs", input_hash + ".json", result)
        return {**result, "input_hash": input_hash}, sessions

    def _stored_input(self, input_hash: str) -> dict[str, Any]:
        result = _object(self.root / "inputs", _hash(input_hash) + ".json")
        if sha256_bytes(canonical_json_bytes(result)) != input_hash:
            raise ArtifactIntegrityError("observation input identity changed")
        return {**result, "input_hash": input_hash}

    def snapshot_prepare(self, dataset_id: str) -> dict[str, Any]:
        """Admit existing offline input identities; this never calls acquisition."""
        with exclusive_directory_lock(self.root):
            data, sessions = self._input(dataset_id)
            verify_file(self._binding(dataset_id).panel_path, data["panel_sha256"])
            return {
                **data,
                "readiness": "METADATA_REQUIRED" if data["arrival"] is None else "REGISTERED",
                "calendar_start": sessions[0].isoformat(),
                "calendar_end": sessions[-1].isoformat(),
                "acquisition_calls": 0,
                "execution_authorization_inherited": False,
            }

    def input_manifest(self, input_hash: str) -> dict[str, Any]:
        """Read a hash-bound admitted input without accepting a caller path."""
        with exclusive_directory_lock(self.root):
            return self._stored_input(input_hash)

    def prepare(self, value: Mapping[str, Any]) -> dict[str, Any]:
        request = PersonalObservationRequest.model_validate(value)
        with exclusive_directory_lock(self.root):
            key = self.root / "keys" / (request.idempotency_key + ".json")
            if key.exists() or key.is_symlink():
                existing = _object(key.parent, key.name)
                if existing["request_hash"] != request.content_hash:
                    raise ValueError("observation idempotency key belongs to a different request")
                return self._plan(existing["observation_id"])
            data, sessions = self._input(request.dataset_id)
            if any(day not in sessions for day in request.planned_dates):
                raise ValueError("planned dates must be actual sessions in the explicit calendar")
            gaps: list[str] = []
            if data["arrival"] is None:
                gaps.append("SNAPSHOT_ARRIVAL_METADATA_REQUIRED")
            if self.compiler_runtime_hash is None:
                gaps.append("COMPILER_RUNTIME_IDENTITY_REQUIRED")
            if data["arrival"] is not None and not corporate_actions_supported(
                parse_snapshot_arrival(data["arrival"])
            ):
                gaps.append("CORPORATE_ACTION_SCOPE_UNKNOWN")
            expressions = [
                item
                for item in (
                    request.strategy.score,
                    request.strategy.eligibility,
                    request.strategy.market_condition,
                )
                if item is not None
            ]
            fields: set[str] = {"adjusted_close"}
            for expression in expressions:
                for node in expression.nodes:
                    field = getattr(node, "field_name", None)
                    if field is not None:
                        fields.add(str(field))
            native_fields = {FIELD_MAPPING[field].removeprefix("$") for field in fields}
            if (
                self._binding(request.dataset_id).field_mapping_profile
                == "canonical-personal-fields/v1"
            ):
                native_fields.discard("amount_cny")
            feature_fields: dict[str, set[str]] = {}
            for logical in self._binding(request.dataset_id).manifest.qlib_files:
                match = re.fullmatch(r"features/((?:sh|sz)[0-9]{6})/([a-z_]+)\.day\.bin", logical)
                if match is not None:
                    feature_fields.setdefault(match[1], set()).add(match[2])
            if not feature_fields or any(
                not native_fields <= present for present in feature_fields.values()
            ):
                gaps.append("QLIB_REQUIRED_FIELDS_UNMAPPED:" + ",".join(sorted(fields)))
            if (
                sessions.index(request.planned_dates[0])
                < max(required_history(e) for e in expressions) + 1
            ):
                gaps.append("WARMUP_CALENDAR_INSUFFICIENT")
            payload = {
                "schema_version": "personal-observation-plan/v1",
                "request": request.canonical_payload(),
                "request_hash": request.content_hash,
                "strategy_hash": request.strategy.content_hash,
                "policy_hash": request.policy.content_hash,
                "initial_input_hash": data["input_hash"],
                "calendar_sessions": [day.isoformat() for day in sessions],
                "compiler_runtime_hash": self.compiler_runtime_hash,
                "coordinator_hash": sha256_bytes(Path(__file__).read_bytes()),
                "frozen_at": datetime.now(UTC).isoformat(),
                "readiness": "BLOCKED" if gaps else "READY_FOR_AUTHORIZATION",
                "gaps": gaps,
                "scope": "ENGINEERING_REPLAY" if data["kind"] == "synthetic" else "FORWARD_ONLY",
                "validation_verdict": "NOT_EVALUATED",
            }
            observation_id = sha256_bytes(canonical_json_bytes(payload))
            plan = {**payload, "observation_id": observation_id}
            _write(self.root / "observations" / observation_id, "plan.json", plan)
            _write(
                key.parent,
                key.name,
                {"request_hash": request.content_hash, "observation_id": observation_id},
            )
            return plan

    def _plan(self, observation_id: str) -> dict[str, Any]:
        plan = _object(self.root / "observations" / _hash(observation_id), "plan.json")
        payload = {key: item for key, item in plan.items() if key != "observation_id"}
        if plan.get("observation_id") != observation_id or (
            sha256_bytes(canonical_json_bytes(payload)) != observation_id
        ):
            raise ArtifactIntegrityError("observation plan identity changed")
        request = PersonalObservationRequest.model_validate(plan["request"])
        if request.content_hash != plan["request_hash"] or (
            request.strategy.content_hash != plan["strategy_hash"]
            or request.policy.content_hash != plan["policy_hash"]
        ):
            raise ArtifactIntegrityError("observation strategy/policy identity changed")
        self._stored_input(plan["initial_input_hash"])
        return plan

    def _records(self, observation_id: str) -> list[dict[str, Any]]:
        root = self.root / "observations" / observation_id / "records"
        if not root.exists() and not root.is_symlink():
            return []
        with opened_directory(root):
            names = sorted(path.name for path in root.iterdir())
        if len(names) > _MAX_RECORDS:
            raise ArtifactIntegrityError("observation record limit exceeded")
        records: list[dict[str, Any]] = []
        previous: str | None = None
        for sequence, name in enumerate(names, 1):
            match = re.fullmatch(r"([0-9]{8})-([a-f0-9]{64})\.json", name)
            if match is None or int(match[1]) != sequence:
                raise ArtifactIntegrityError("observation record sequence disagrees")
            record = _object(root, name)
            payload = {key: item for key, item in record.items() if key != "record_hash"}
            if (
                record.get("record_hash") != match[2]
                or sha256_bytes(canonical_json_bytes(payload)) != match[2]
                or record.get("previous_record_hash") != previous
                or record.get("observation_id") != observation_id
                or record.get("sequence") != sequence
            ):
                raise ArtifactIntegrityError("observation record hash chain disagrees")
            if record.get("input_hash") is not None:
                self._stored_input(record["input_hash"])
            records.append(record)
            previous = match[2]
        return records

    def plan(self, observation_id: str) -> dict[str, Any]:
        """Read the exact frozen request, strategy and policy through the verifier."""
        with exclusive_directory_lock(self.root):
            return self._plan(observation_id)

    def record(self, observation_id: str, record_hash: str) -> dict[str, Any]:
        """Read one chain-bound record and revalidate its SignalArtifact originals."""
        with exclusive_directory_lock(self.root):
            plan = self._plan(observation_id)
            expected = _hash(record_hash)
            record = next(
                (item for item in self._records(observation_id) if item["record_hash"] == expected),
                None,
            )
            if record is None:
                raise ValueError("record_hash is not in this observation version")
            signal = record.get("signal")
            if signal is not None:
                self._signal(
                    {"directory": signal["directory"], "artifact_hash": signal["artifact_hash"]},
                    self._stored_input(record["input_hash"]),
                    plan,
                    date.fromisoformat(record["day"]),
                )
            return record

    @staticmethod
    def _panel(binding: PersonalDatasetBinding, lower: date, upper: date) -> Any:
        """One bounded read per snapshot in an observation, after its content check."""
        verify_file(binding.panel_path, binding.manifest.panel_sha256)
        if binding.panel_path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("observation panel exceeds the bounded input budget")
        schema: Any = cast(Any, pq).read_schema(binding.panel_path)
        columns = [
            name
            for name in (
                "trade_date",
                "qlib_id",
                "close",
                "volume",
                "adjustment_factor",
                "amount_cny",
                "is_member",
                "is_listed",
                "is_st",
                "is_suspended",
                "available_at",
                "lifecycle_state",
            )
            if name in schema.names
        ]
        required = {
            "trade_date",
            "qlib_id",
            "close",
            "volume",
            "available_at",
            "is_member",
            "is_st",
            "is_suspended",
        }
        if not required <= set(columns):
            raise ObservationPITError("observation PIT panel fields missing")
        frame: Any = (
            cast(Any, pq)
            .read_table(
                binding.panel_path,
                columns=columns,
                filters=[("trade_date", ">=", lower), ("trade_date", "<=", upper)],
            )
            .to_pandas()
        )
        frame["trade_date"] = cast(Any, pd).to_datetime(frame["trade_date"]).dt.date
        if frame.duplicated(["trade_date", "qlib_id"]).any():
            raise ObservationPITError("observation panel keys duplicated")
        if len(frame) > 200_000:
            raise ValueError("observation panel over row budget")
        if binding.field_mapping_profile == "canonical-personal-fields/v1":
            from quantos.research.personal_fields import augment_canonical_fields

            frame = augment_canonical_fields(binding, frame)
        for name in ("is_member", "is_st", "is_suspended"):
            if frame[name].isna().any() or not frame[name].isin([True, False]).all():
                raise ObservationPITError("observation member/status unknown")
        return frame

    def _continuity(
        self,
        current: dict[str, Any],
        previous: dict[str, Any],
        frame: Any,
        lower: date,
        upper: date,
    ) -> tuple[bool, list[str]]:
        if current["input_hash"] == previous["input_hash"]:
            return True, []
        arrival = current["arrival"]
        reasons: list[str] = []
        if arrival is None or arrival["previous_snapshot_hash"] != previous["snapshot_hash"]:
            reasons.append("SNAPSHOT_PREDECESSOR_UNBOUND")
        if current["snapshot_hash"] == previous["snapshot_hash"]:
            reasons.append("SAME_SNAPSHOT_NEW_DERIVATIVE_IDENTITY")
        old = self._panel(self._binding(previous["dataset_id"]), lower, upper)
        overlap_end = min(upper, old.trade_date.max()) if not old.empty else upper
        new = frame.loc[frame.trade_date <= overlap_end]
        if not set(_UNIT_COLUMNS) <= set(old.columns) or not set(_UNIT_COLUMNS) <= set(new.columns):
            return False, [*reasons, "UNIT_COMPARISON_FIELDS_MISSING"]
        keys = ["trade_date", "qlib_id"]
        old = old.set_index(keys).sort_index()
        new = new.set_index(keys).sort_index()
        successor = (
            arrival is not None and arrival.get("schema_version") == "personal-snapshot-arrival/v2"
        )
        if successor:
            from quantos.application.forward_continuity import align_historical_prefix

            try:
                new = align_historical_prefix(old, new)
            except ValueError:
                return False, [*reasons, "HISTORICAL_GRID_CHANGED_OR_UNOBSERVABLE"]
        if old.empty or not old.index.equals(new.index):
            return False, [*reasons, "HISTORICAL_GRID_CHANGED_OR_UNOBSERVABLE"]
        for name in _UNIT_COLUMNS:
            left = np.asarray(old[name], dtype=float)
            right = np.asarray(new[name], dtype=float)
            if name == "adjustment_factor" and successor:
                from quantos.application.forward_continuity import source_observable_factors

                if not source_observable_factors(old) or not source_observable_factors(new):
                    reasons.append("ADJUSTMENT_FACTOR_UNOBSERVABLE")
            elif name == "adjustment_factor" and (
                not np.isfinite(left).all()
                or not np.isfinite(right).all()
                or (left <= 0).any()
                or (right <= 0).any()
            ):
                reasons.append("ADJUSTMENT_FACTOR_UNOBSERVABLE")
            if not np.isclose(left, right, rtol=_RTOL, atol=_ATOL, equal_nan=True).all():
                reasons.append("HISTORICAL_UNITS_OR_PRICE_REVISED:" + name)
        for name in ("amount_cny", "available_at", "is_member", "is_st", "is_suspended"):
            if name in old and name in new and not old[name].equals(new[name]):
                reasons.append("HISTORICAL_INPUT_REVISED:" + name)
        return not reasons, reasons

    @staticmethod
    def _signal(
        reference: Mapping[str, Any], data: dict[str, Any], plan: dict[str, Any], day: date
    ) -> dict[str, Any]:
        from quantos.research.personal_signal import load_strategy_signal

        if set(reference) != {"directory", "artifact_hash"}:
            raise ValueError("compiler must return a bound SignalArtifact directory/hash")
        directory = Path(str(reference["directory"]))
        if not directory.is_absolute() or any("sealed" in part.lower() for part in directory.parts):
            raise ValueError("compiler artifact directory is outside the permitted local scope")
        artifact, native = load_strategy_signal(directory, _hash(str(reference["artifact_hash"])))
        if (
            artifact.strategy_hash != plan["strategy_hash"]
            or artifact.dataset_hash
            != data.get("dataset_binding_hash", data["dataset_manifest_hash"])
            or artifact.snapshot_hash != data["snapshot_hash"]
            or artifact.qlib_view_hash != data["qlib_view_hash"]
            or artifact.panel_sha256 != data["panel_sha256"]
            or artifact.pit_evidence_hash != data["pit_evidence_hash"]
            or artifact.runtime_hash != plan["compiler_runtime_hash"]
            or artifact.start_date != day
            or artifact.end_date != day
        ):
            raise ArtifactIntegrityError("observation SignalArtifact dependency identity disagrees")
        count = int(native["score"].notna().sum())
        return {
            "directory": str(directory),
            "artifact_hash": artifact.content_hash,
            "row_count": artifact.row_count,
            "finite_score_count": count,
        }

    def _finish(self, observation_id: str, record: dict[str, Any]) -> dict[str, Any]:
        records = self._records(observation_id)
        digest = record["record_hash"]
        payload = {key: item for key, item in record.items() if key != "record_hash"}
        if record.get("observation_id") != observation_id or (
            sha256_bytes(canonical_json_bytes(payload)) != digest
        ):
            raise ArtifactIntegrityError("observation completion hash disagrees")
        signal = record.get("signal")
        if signal is not None:
            self._signal(
                {"directory": signal["directory"], "artifact_hash": signal["artifact_hash"]},
                self._stored_input(record["input_hash"]),
                self._plan(observation_id),
                date.fromisoformat(record["day"]),
            )
        if any(item["record_hash"] == digest for item in records):
            return record
        if len(records) >= _MAX_RECORDS:
            raise ValueError("observation record budget exhausted")
        if record["sequence"] != len(records) + 1 or record["previous_record_hash"] != (
            records[-1]["record_hash"] if records else None
        ):
            raise ArtifactIntegrityError("completion cannot be appended to a changed chain")
        directory = self.root / "observations" / observation_id / "records"
        _write(directory, f"{record['sequence']:08d}-{digest}.json", record)
        return record

    def observe(
        self,
        observation_id: str,
        day: date | str,
        dataset_id: str,
        observed_at: datetime | str,
        *,
        recompute: bool = False,
    ) -> dict[str, Any]:
        day = date.fromisoformat(day) if isinstance(day, str) else day
        observed_at = (
            datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if isinstance(observed_at, str)
            else observed_at
        )
        observed_at = _aware(observed_at)
        recorded_at = datetime.now(UTC)
        if observed_at > recorded_at:
            raise ValueError("observed_at cannot claim a future receipt")
        with exclusive_directory_lock(self.root):
            plan = self._plan(observation_id)
            request = PersonalObservationRequest.model_validate(plan["request"])
            if day not in request.planned_dates:
                raise ValueError("day is not a planned actual session")
            cutoff = datetime.combine(day, time(23, 59), _SHANGHAI).astimezone(UTC)
            if observed_at < cutoff:
                raise ValueError("daily after-close signal cutoff has not been reached")
            operation = {
                "observation_id": observation_id,
                "day": day.isoformat(),
                "dataset_id": dataset_id,
                "recompute": recompute,
            }
            attempt_hash = sha256_bytes(canonical_json_bytes(operation))
            attempt = self.root / "observations" / observation_id / "attempts" / attempt_hash
            completion = attempt / "completion.json"
            if completion.exists() or completion.is_symlink():
                return self._finish(observation_id, _object(attempt, completion.name))
            if (attempt / "intent.json").exists() or (attempt / "intent.json").is_symlink():
                return {
                    "observation_id": observation_id,
                    "attempt_hash": attempt_hash,
                    "status": "UNKNOWN",
                    "reason": "INTENT_WITHOUT_COMPLETION_RECONCILE_NO_REISSUE",
                }
            records = self._records(observation_id)
            if records and records[-1]["status"] == "STOPPED":
                raise ValueError("observation version is stopped; prepare a new version")
            original = [
                item
                for item in records
                if item.get("day") == day.isoformat() and not item.get("recompute")
            ]
            if bool(original) != recompute:
                raise ValueError(
                    "existing day requires explicit recompute; recompute requires an original"
                )
            prior = [d.isoformat() for d in request.planned_dates if d < day]
            completed = {item.get("day") for item in records if not item.get("recompute")}
            if not recompute and not set(prior) <= completed:
                raise ValueError("record preceding planned days, including missing days, first")
            if plan["readiness"] == "BLOCKED":
                raise PermissionError("observation plan is blocked: " + ",".join(plan["gaps"]))
            if plan["compiler_runtime_hash"] != self.compiler_runtime_hash:
                raise PermissionError("compiler runtime changed; prepare a new observation version")
            data, sessions = self._input(dataset_id)
            initial = self._stored_input(plan["initial_input_hash"])
            if data["kind"] != initial["kind"]:
                raise PermissionError(
                    "observation cannot change between synthetic and market scope"
                )
            if any(date.fromisoformat(s) not in sessions for s in plan["calendar_sessions"]):
                raise ArtifactIntegrityError("new view removed a frozen calendar session")
            context = {**operation, "plan": plan, "input": data}
            receipt = None if self.authorizer is None else self.authorizer(context)
            if not isinstance(receipt, str) or not receipt or len(receipt) > 16000:
                raise PermissionError("observation requires trusted server-side authorization")
            _write(
                attempt,
                "intent.json",
                {
                    **operation,
                    "attempt_hash": attempt_hash,
                    "recorded_at": recorded_at.isoformat(),
                    "observed_at": observed_at.isoformat(),
                    "authorization_receipt_hash": sha256_bytes(receipt.encode()),
                    "input_hash": data["input_hash"],
                },
            )
            previous_input = (
                self._stored_input(records[-1]["input_hash"])
                if records
                else self._stored_input(plan["initial_input_hash"])
            )
            arrival = None if data["arrival"] is None else parse_snapshot_arrival(data["arrival"])
            after_fact = recompute or (
                plan["scope"] != "ENGINEERING_REPLAY"
                and datetime.fromisoformat(plan["frozen_at"]) > cutoff
            )
            if arrival is not None and arrival.received_at > cutoff:
                after_fact = True
            following = [
                date.fromisoformat(s) for s in plan["calendar_sessions"] if s > day.isoformat()
            ]
            next_session = following[0] if following else None
            deadline = (
                None
                if next_session is None
                else datetime.combine(next_session, time(9, 30), _SHANGHAI).astimezone(UTC)
            )
            publication_clock = (
                observed_at if plan["scope"] == "ENGINEERING_REPLAY" else recorded_at
            )
            if deadline is not None and publication_clock >= deadline:
                after_fact = True
            record: dict[str, Any] = {
                "schema_version": "personal-observation-record/v1",
                **operation,
                "sequence": len(records) + 1,
                "previous_record_hash": records[-1]["record_hash"] if records else None,
                "attempt_hash": attempt_hash,
                "input_hash": data["input_hash"],
                "previous_input_hash": previous_input["input_hash"],
                "snapshot_hash": data["snapshot_hash"],
                "qlib_view_hash": data["qlib_view_hash"],
                "strategy_hash": plan["strategy_hash"],
                "policy_hash": plan["policy_hash"],
                "input_cutoff": cutoff.isoformat(),
                "next_execution_session": None
                if next_session is None
                else next_session.isoformat(),
                "publication_deadline": None if deadline is None else deadline.isoformat(),
                "source_max_available_at": None,
                "acquired_at": None if arrival is None else arrival.acquired_at.isoformat(),
                "source_visible_at": None
                if arrival is None
                else arrival.source_visible_at.isoformat(),
                "received_at": None if arrival is None else arrival.received_at.isoformat(),
                "observed_at": observed_at.isoformat(),
                "recorded_at": recorded_at.isoformat(),
                "signal_published_at": None,
                "after_the_fact": after_fact,
                "revises_record_hash": original[-1]["record_hash"] if original else None,
                "scope": plan["scope"],
                "continuous_compatible": True,
                "continuity_reasons": [],
                "signal": None,
                "status": "MISSING",
                "reason": "SNAPSHOT_ARRIVAL_METADATA_REQUIRED",
                "actual_exit": "NOT_STARTED",
                "validation_verdict": "NOT_EVALUATED",
            }
            try:
                self._evaluate(
                    record, plan, request, data, previous_input, arrival, observed_at, cutoff
                )
            except ObservationPITError:
                record.update(
                    status="STOPPED", reason="PIT_HARD_REJECTION", actual_exit="NOT_STARTED"
                )
            except Exception as error:
                record.update(
                    status="FAILED",
                    reason="OBSERVATION_EXECUTION_" + type(error).__name__,
                    actual_exit="IN_PROCESS_EXCEPTION",
                )
            record["record_hash"] = sha256_bytes(canonical_json_bytes(record))
            _write(attempt, "completion.json", record)
            return self._finish(observation_id, record)

    def _evaluate(
        self,
        record: dict[str, Any],
        plan: dict[str, Any],
        request: PersonalObservationRequest,
        data: dict[str, Any],
        previous: dict[str, Any],
        arrival: SnapshotArrival | None,
        observed_at: datetime,
        cutoff: datetime,
    ) -> None:
        if arrival is None:
            return
        if not corporate_actions_supported(arrival, date.fromisoformat(record["day"])):
            record.update(status="STOPPED", reason="UNSUPPORTED_OR_UNKNOWN_CORPORATE_ACTION")
            return
        if arrival.received_at > observed_at or (
            arrival.source_visible_at > cutoff and not record["recompute"]
        ):
            record["reason"] = "SOURCE_NOT_AVAILABLE_AT_OBSERVATION_OR_SIGNAL_CUTOFF"
            return
        calendar = [date.fromisoformat(day) for day in plan["calendar_sessions"]]
        lower = calendar[max(0, calendar.index(request.planned_dates[0]) - 120)]
        day = date.fromisoformat(record["day"])
        frame = self._panel(self._binding(data["dataset_id"]), lower, day)
        current = frame.loc[frame.trade_date == day]
        if current.empty:
            record["reason"] = "PLANNED_SESSION_INPUT_MISSING"
            return
        if (
            "lifecycle_state" in frame
            and frame.lifecycle_state.astype(str)
            .str.contains("UNKNOWN|UNSUPPORTED", regex=True)
            .any()
        ):
            record.update(status="STOPPED", reason="PANEL_LIFECYCLE_STATE_UNKNOWN")
            return
        consumed = frame.loc[frame.is_member | (frame.qlib_id == request.benchmark)]
        try:
            unknown_time = any(
                pd.Timestamp(value).tzinfo is None for value in consumed.available_at
            )
        except (ValueError, TypeError):
            unknown_time = True
        if unknown_time:
            record.update(status="STOPPED", reason="PIT_UNKNOWN_INPUT_TIME")
            return
        times: Any = cast(Any, pd).to_datetime(consumed.available_at, utc=True, errors="coerce")
        if times.isna().any():
            record.update(status="STOPPED", reason="PIT_UNKNOWN_INPUT_TIME")
            return
        if not times.empty:
            record["source_max_available_at"] = times.max().isoformat()
        daily_cutoffs: Any = cast(Any, pd).to_datetime(
            consumed.trade_date.astype(str)
        ).dt.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=23, minutes=59)
        if (times > daily_cutoffs.dt.tz_convert("UTC")).any():
            record["reason"] = "PIT_FUTURE_INPUT_EXCLUDED"
            return
        live = consumed.loc[~consumed.is_suspended]
        prices = np.asarray(live["close"], dtype=float)
        quantities = np.asarray(live["volume"], dtype=float)
        if (
            not np.isfinite(prices).all()
            or not np.isfinite(quantities).all()
            or ((prices <= 0).any() or (quantities < 0).any())
        ):
            record["reason"] = "REQUIRED_MARKET_OBSERVATIONS_MISSING"
            return
        previous_days = self._records(plan["observation_id"])
        completed_days = [date.fromisoformat(r["day"]) for r in previous_days if r.get("day")]
        overlap_end = min(day, max(completed_days)) if completed_days else day
        compatible, reasons = self._continuity(data, previous, frame, lower, overlap_end)
        if any(not item.get("continuous_compatible", True) for item in previous_days):
            compatible = False
            reasons.append("PREVIOUS_CHAIN_INCOMPATIBLE")
        record["continuous_compatible"] = compatible
        record["continuity_reasons"] = reasons
        if not compatible:
            record["after_the_fact"] = True
        reference = self.compiler(
            self._binding(data["dataset_id"]), request.strategy, day, datetime.now(UTC)
        )
        signal = self._signal(reference, data, plan, day)
        published = datetime.now(UTC)
        if record["scope"] != "ENGINEERING_REPLAY" and (
            record["publication_deadline"] is None
            or published >= datetime.fromisoformat(record["publication_deadline"])
        ):
            record["after_the_fact"] = True
        record.update(
            status="EMITTED" if signal["finite_score_count"] else "ABSTAIN",
            reason="AFTER_THE_FACT_RECOMPUTATION"
            if record["after_the_fact"]
            else "AS_OF_INPUT_SIGNAL",
            signal=signal,
            signal_published_at=published.isoformat(),
            actual_exit="IN_PROCESS_RETURN",
        )

    def recover(self, observation_id: str, attempt_hash: str) -> dict[str, Any]:
        """Publish an already durable completion; never rerun an uncertain compiler."""
        with exclusive_directory_lock(self.root):
            self._plan(observation_id)
            attempt = self.root / "observations" / observation_id / "attempts" / _hash(attempt_hash)
            intent = _object(attempt, "intent.json")
            if intent["observation_id"] != observation_id or intent["attempt_hash"] != attempt_hash:
                raise ArtifactIntegrityError("observation recovery intent identity disagrees")
            if not (attempt / "completion.json").exists():
                return {
                    "observation_id": observation_id,
                    "attempt_hash": attempt_hash,
                    "status": "UNKNOWN",
                    "reason": "NO_DURABLE_COMPLETION_NO_REISSUE",
                }
            return self._finish(observation_id, _object(attempt, "completion.json"))

    def stop(self, observation_id: str, reason: str = "USER_STOP") -> dict[str, Any]:
        if not reason.strip() or len(reason) > 1000:
            raise ValueError("stop reason must contain 1..1000 characters")
        with exclusive_directory_lock(self.root):
            self._plan(observation_id)
            records = self._records(observation_id)
            if records and records[-1]["status"] == "STOPPED":
                return records[-1]
            payload = {
                "schema_version": "personal-observation-record/v1",
                "observation_id": observation_id,
                "sequence": len(records) + 1,
                "previous_record_hash": records[-1]["record_hash"] if records else None,
                "day": None,
                "status": "STOPPED",
                "reason": reason,
                "recorded_at": datetime.now(UTC).isoformat(),
                "input_hash": records[-1]["input_hash"] if records else None,
                "actual_exit": "NOT_STARTED",
                "validation_verdict": "NOT_EVALUATED",
            }
            return self._finish(
                observation_id,
                {
                    **payload,
                    "record_hash": sha256_bytes(canonical_json_bytes(payload)),
                },
            )

    def status(self, observation_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative; limit must be 1..100")
        with exclusive_directory_lock(self.root):
            plan = self._plan(observation_id)
            records = self._records(observation_id)
            root = self.root / "observations" / observation_id / "attempts"
            unknown: list[str] = []
            if root.exists():
                with opened_directory(root):
                    for path in root.iterdir():
                        _hash(path.name)
                        intent = _object(path, "intent.json")
                        if (
                            intent["attempt_hash"] != path.name
                            or intent["observation_id"] != observation_id
                        ):
                            raise ArtifactIntegrityError("observation attempt identity disagrees")
                        if not (path / "completion.json").exists():
                            unknown.append(path.name)
            page = records[offset : offset + limit]
            return {
                "schema_version": "personal-observation-status/v1",
                "observation_id": observation_id,
                "strategy_hash": plan["strategy_hash"],
                "policy_hash": plan["policy_hash"],
                "readiness": plan["readiness"],
                "gaps": plan["gaps"],
                "state": "STOPPED" if records and records[-1]["status"] == "STOPPED" else "ACTIVE",
                "record_count": len(records),
                "records": page,
                "next_offset": offset + len(page) if offset + len(page) < len(records) else None,
                "unknown_attempts": sorted(unknown),
                "validation_verdict": "NOT_EVALUATED",
                "limits": [
                    "Engineering replay is not future performance",
                    "Source non-vintage remains non-vintage; "
                    "arrival metadata grants no qualification",
                    "Late/revision records append and never replace issued or missing observations",
                    "This status verifies the chain; signals are revalidated when issued/recovered",
                ],
            }
