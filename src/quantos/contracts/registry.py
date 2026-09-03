"""Public contracts for the append-only filesystem registry."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Self

from pydantic import Field, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.provenance import RuntimeFingerprint
from quantos.contracts.refs import SHA256_PATTERN, ArtifactRef
from quantos.contracts.snapshot import SnapshotSourceKind
from quantos.contracts.status import RunStatus, StrategyStatus, ValidationVerdict

LOGICAL_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class RegistryExperimentManifest(CanonicalContract):
    """Immutable registry record for one fully verified ValidationReport."""

    schema_version: Literal["registry-experiment-manifest/v1"] = "registry-experiment-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"manifest_hash", "registered_at"})

    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    experiment_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    authoring_spec_hash: str = Field(pattern=SHA256_PATTERN)
    strategy_spec_hash: str = Field(pattern=SHA256_PATTERN)
    resolved_experiment_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    validation_policy_hash: str = Field(pattern=SHA256_PATTERN)
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint: RuntimeFingerprint
    code_commit_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    code_worktree_clean: Literal[True] | None = None
    snapshot_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    snapshot_source_kind: SnapshotSourceKind | None = None
    snapshot_build_spec_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    data_quality_policy_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    data_quality_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    qlib_view_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    qlib_view_spec_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    qlib_version: str | None = Field(default=None, min_length=1)
    qlib_source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    dump_bin_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    health_check_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    qlib_run_id: str | None = Field(default=None, min_length=1)
    pit_audit_evidence_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    cost_policy_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    backtest_policy_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    source_expression_or_model_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    signal_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    backtest_result_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    validation_report_hash: str = Field(pattern=SHA256_PATTERN)
    artifact_hashes: tuple[str, ...]
    run_status: RunStatus
    verdict: ValidationVerdict
    canonical: bool
    oos_access_event: ArtifactRef | None = None
    oos_access_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    limitations: tuple[str, ...]
    registered_at: datetime

    @field_validator("registered_at")
    @classmethod
    def registered_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registered_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bindings_are_consistent(self) -> Self:
        if self.run_status is RunStatus.FAILED:
            if self.verdict is not ValidationVerdict.NOT_EVALUATED:
                raise ValueError("failed registry experiments must be NOT_EVALUATED")
        elif self.verdict is ValidationVerdict.NOT_EVALUATED:
            raise ValueError("successful registry experiments must have a final verdict")
        snapshot_provenance = (
            self.snapshot_hash,
            self.snapshot_source_kind,
            self.snapshot_build_spec_hash,
            self.data_quality_policy_hash,
            self.data_quality_report_hash,
        )
        if any(item is None for item in snapshot_provenance) != all(
            item is None for item in snapshot_provenance
        ):
            raise ValueError("snapshot provenance fields must be present together")
        if self.runtime_fingerprint.content_hash != self.runtime_fingerprint_hash:
            raise ValueError("runtime fingerprint does not match its registry hash binding")
        code_provenance = (
            self.code_commit_hash,
            self.lockfile_hash,
            self.code_worktree_clean,
        )
        if any(item is None for item in code_provenance) != all(
            item is None for item in code_provenance
        ):
            raise ValueError("code provenance fields must be present together")
        qlib_provenance = (
            self.resolved_experiment_hash,
            self.code_commit_hash,
            self.lockfile_hash,
            self.qlib_view_hash,
            self.qlib_view_spec_hash,
            self.qlib_version,
            self.qlib_source_commit,
            self.dump_bin_sha256,
            self.health_check_sha256,
            self.pit_audit_evidence_hash,
            self.cost_policy_hash,
            self.backtest_policy_hash,
            self.source_expression_or_model_hash,
        )
        if self.signal_artifact_hash is not None and any(item is None for item in qlib_provenance):
            raise ValueError("a registered signal requires complete resolved Qlib provenance")
        if self.artifact_hashes != tuple(sorted(set(self.artifact_hashes))):
            raise ValueError("registered artifact hashes must be sorted and unique")
        required_artifacts = {
            item
            for item in (
                self.snapshot_hash,
                self.qlib_view_hash,
                self.signal_artifact_hash,
                self.backtest_result_hash,
                self.validation_report_hash,
            )
            if item is not None
        }
        if not required_artifacts.issubset(self.artifact_hashes):
            raise ValueError("registered artifact hashes omit a principal artifact")
        if (self.oos_access_event is None) != (self.oos_access_event_hash is None):
            raise ValueError("OOS event reference and content hash must be present together")
        if self.verdict is ValidationVerdict.PASS:
            required = (
                self.resolved_experiment_hash,
                self.snapshot_hash,
                self.qlib_view_hash,
                self.signal_artifact_hash,
                self.backtest_result_hash,
                self.oos_access_event_hash,
            )
            if any(item is None for item in required):
                raise ValueError("passing registry experiments require the complete artifact chain")
        if self.manifest_hash != self.content_hash:
            raise ValueError("manifest_hash does not match registry experiment content")
        return self

    @classmethod
    def create(cls, **values: Any) -> Self:
        provisional = cls.model_construct(manifest_hash="0" * 64, **values)
        digest = sha256_bytes(canonical_json_bytes(provisional.canonical_payload()))
        payload = provisional.model_dump(mode="python")
        payload["manifest_hash"] = digest
        return cls.model_validate(payload)


class RegistryExperimentIndexEntry(CanonicalContract):
    schema_version: Literal["registry-experiment-index-entry/v1"] = (
        "registry-experiment-index-entry/v1"
    )
    experiment_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    validation_report_hash: str = Field(pattern=SHA256_PATTERN)
    run_status: RunStatus
    verdict: ValidationVerdict
    canonical: bool
    snapshot_source_kind: SnapshotSourceKind | None = None
    event_hashes: tuple[str, ...]

    @field_validator("event_hashes")
    @classmethod
    def event_hashes_are_nonempty_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("experiment event hashes must be nonempty and unique")
        return value


class StrategyVersionRecord(CanonicalContract):
    schema_version: Literal["strategy-version-record/v1"] = "strategy-version-record/v1"
    strategy_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    version: PositiveInt
    strategy_spec_hash: str = Field(pattern=SHA256_PATTERN)
    status: StrategyStatus
    validation_experiment_id: str | None = Field(default=None, pattern=LOGICAL_ID_PATTERN)
    validation_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    event_hashes: tuple[str, ...]

    @field_validator("event_hashes")
    @classmethod
    def events_are_nonempty_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("strategy version event hashes must be nonempty and unique")
        return value

    @model_validator(mode="after")
    def validation_binding_matches_status(self) -> Self:
        bound = (
            self.validation_experiment_id is not None and self.validation_report_hash is not None
        )
        if self.status is StrategyStatus.DRAFT and bound:
            raise ValueError("draft strategy versions cannot bind validation evidence")
        if self.status is not StrategyStatus.DRAFT and not bound:
            raise ValueError("non-draft strategy versions require validation evidence")
        return self


class RegistryStrategyRecord(CanonicalContract):
    schema_version: Literal["registry-strategy-record/v1"] = "registry-strategy-record/v1"
    strategy_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    versions: tuple[StrategyVersionRecord, ...]

    @model_validator(mode="after")
    def versions_are_monotonic(self) -> Self:
        if not self.versions or tuple(item.version for item in self.versions) != tuple(
            range(1, len(self.versions) + 1)
        ):
            raise ValueError("strategy versions must be contiguous and start at one")
        if any(item.strategy_id != self.strategy_id for item in self.versions):
            raise ValueError("strategy version belongs to another logical strategy")
        return self


class RegistryIndex(CanonicalContract):
    """Rebuildable projection; immutable manifests and events remain authoritative."""

    schema_version: Literal["registry-index/v1"] = "registry-index/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"index_hash", "generated_at"})

    index_hash: str = Field(pattern=SHA256_PATTERN)
    experiments: tuple[RegistryExperimentIndexEntry, ...]
    strategies: tuple[RegistryStrategyRecord, ...]
    source_manifest_hashes: tuple[str, ...]
    source_event_hashes: tuple[str, ...]
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def generated_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def projection_is_canonical(self) -> Self:
        experiment_ids = [item.experiment_id for item in self.experiments]
        strategy_ids = [item.strategy_id for item in self.strategies]
        if experiment_ids != sorted(experiment_ids) or len(experiment_ids) != len(
            set(experiment_ids)
        ):
            raise ValueError("registry experiments must be sorted and unique")
        if strategy_ids != sorted(strategy_ids) or len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("registry strategies must be sorted and unique")
        for values, label in (
            (self.source_manifest_hashes, "manifest"),
            (self.source_event_hashes, "event"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"registry source {label} hashes must be sorted and unique")
        if self.source_manifest_hashes != tuple(
            sorted(item.manifest_hash for item in self.experiments)
        ):
            raise ValueError("registry manifest hash projection is inconsistent")
        projected_events = {digest for item in self.experiments for digest in item.event_hashes} | {
            digest
            for strategy in self.strategies
            for version in strategy.versions
            for digest in version.event_hashes
        }
        if self.source_event_hashes != tuple(sorted(projected_events)):
            raise ValueError("registry event hash projection is inconsistent")
        if self.index_hash != self.content_hash:
            raise ValueError("index_hash does not match registry projection content")
        return self

    @classmethod
    def create(cls, **values: Any) -> Self:
        provisional = cls.model_construct(index_hash="0" * 64, **values)
        digest = sha256_bytes(canonical_json_bytes(provisional.canonical_payload()))
        payload = provisional.model_dump(mode="python")
        payload["index_hash"] = digest
        return cls.model_validate(payload)
