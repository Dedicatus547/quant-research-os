"""Operator-owned catalog and exact execution grants, never writable through MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from quantos.application.personal_research import (
    PersonalDatasetBinding,
    PersonalResearchService,
    Prepared,
)
from quantos.artifacts.store import ArtifactIntegrityError, opened_directory, read_regular_bytes_at
from quantos.contracts.base import CanonicalContract, sha256_bytes
from quantos.contracts.forward import ForwardDatasetAdmission
from quantos.contracts.hs300_adjusted import (
    HS300AdjustedDatasetManifest,
    PreparedHS300AdjustedStudy,
)
from quantos.contracts.hs300_cash import (
    ClassicOriginReuse,
    HS300CashDatasetManifest,
    PreparedHS300CashStudy,
    SignalReuseSpec,
)
from quantos.contracts.hs300_lifecycle import (
    HS300LifecycleDatasetManifest,
    PreparedHS300LifecycleStudy,
)
from quantos.contracts.personal_research import HS300DatasetManifest, PreparedHS300Study
from quantos.contracts.refs import SHA256_PATTERN


class _ServerDocument(CanonicalContract):
    """Engineering documents serialize paths as JSON strings, without changing contracts."""

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class CatalogRegistration(_ServerDocument):
    schema_version: Literal["personal-catalog-registration/v1"] = "personal-catalog-registration/v1"
    manifest_path: Path
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    provider_root: Path
    panel_path: Path
    pit_evidence_path: Path
    snapshot_path: Path | None = None


class CatalogRegistrationV2(_ServerDocument):
    schema_version: Literal["personal-catalog-registration/v2"] = "personal-catalog-registration/v2"
    manifest_path: Path
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    provider_root: Path
    panel_path: Path
    pit_evidence_path: Path
    snapshot_path: Path | None = None

    lifecycle_path: Path


class CatalogRegistrationV3(CatalogRegistrationV2):
    schema_version: Literal["personal-catalog-registration/v3"] = "personal-catalog-registration/v3"  # pyright: ignore[reportIncompatibleVariableOverride]
    cash_rules_path: Path
    classic_origin_path: Path
    signal_reuse_spec_path: Path


class CatalogRegistrationV4(CatalogRegistrationV3):
    schema_version: Literal["personal-catalog-registration/v4"] = "personal-catalog-registration/v4"  # pyright: ignore[reportIncompatibleVariableOverride]
    adjusted_facts_path: Path


class CatalogRegistrationV5(CatalogRegistrationV4):
    schema_version: Literal["personal-catalog-registration/v5"] = "personal-catalog-registration/v5"  # pyright: ignore[reportIncompatibleVariableOverride]
    field_mapping_profile: Literal["canonical-personal-fields/v1"] = "canonical-personal-fields/v1"


class CatalogRegistrationV6(CatalogRegistrationV2):
    """Canonical fields for new lifecycle inputs without legacy seven-arm reuse files."""

    schema_version: Literal["personal-catalog-registration/v6"] = "personal-catalog-registration/v6"  # pyright: ignore[reportIncompatibleVariableOverride]
    field_mapping_profile: Literal["canonical-personal-fields/v1"] = "canonical-personal-fields/v1"


class PersonalServerConfig(_ServerDocument):
    schema_version: Literal["personal-research-server-config/v1"] = (
        "personal-research-server-config/v1"
    )
    product_root: Path
    repo_root: Path
    catalog: tuple[CatalogRegistration, ...] = ()
    data_blockers: tuple[str, ...] = ()
    authorization_path: Path | None = None
    authorization_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_authorization_reference(self) -> PersonalServerConfig:
        if (self.authorization_path is None) != (self.authorization_sha256 is None):
            raise ValueError("authorization path and exact hash must be supplied together")
        return self


class PersonalServerConfigV2(_ServerDocument):
    schema_version: Literal["personal-research-server-config/v2"] = (
        "personal-research-server-config/v2"
    )
    product_root: Path
    repo_root: Path
    catalog: tuple[CatalogRegistrationV2 | CatalogRegistration, ...] = ()
    data_blockers: tuple[str, ...] = ()
    authorization_path: Path | None = None
    authorization_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_authorization_reference(self) -> PersonalServerConfigV2:
        if (self.authorization_path is None) != (self.authorization_sha256 is None):
            raise ValueError("authorization path and exact hash must be supplied together")
        return self


class PersonalServerConfigV3(PersonalServerConfigV2):
    schema_version: Literal["personal-research-server-config/v3"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "personal-research-server-config/v3"
    )
    catalog: tuple[CatalogRegistrationV3 | CatalogRegistrationV2 | CatalogRegistration, ...] = ()  # pyright: ignore[reportIncompatibleVariableOverride]


class PersonalServerConfigV4(PersonalServerConfigV3):
    schema_version: Literal["personal-research-server-config/v4"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "personal-research-server-config/v4"
    )
    catalog: tuple[
        CatalogRegistrationV4 | CatalogRegistrationV3 | CatalogRegistrationV2 | CatalogRegistration,
        ...,
    ] = ()  # pyright: ignore[reportIncompatibleVariableOverride]


class PersonalScopeRegistration(_ServerDocument):
    schema_version: Literal["personal-scope-registration/v1"] = "personal-scope-registration/v1"
    scope_path: Path
    scope_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_evidence_path: Path
    storage_policy_path: Path
    storage_policy_sha256: str = Field(pattern=SHA256_PATTERN)


class SnapshotArrivalRegistration(_ServerDocument):
    schema_version: Literal["personal-arrival-registration/v1"] = "personal-arrival-registration/v1"
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    metadata_path: Path
    metadata_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_path: Path


class PersonalServerConfigV5(PersonalServerConfigV4):
    schema_version: Literal["personal-research-server-config/v5"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "personal-research-server-config/v5"
    )
    research_scope: PersonalScopeRegistration | None = None
    forward_scope: PersonalScopeRegistration | None = None
    snapshot_arrivals: tuple[SnapshotArrivalRegistration, ...] = ()
    catalog: tuple[
        CatalogRegistrationV5
        | CatalogRegistrationV4
        | CatalogRegistrationV3
        | CatalogRegistrationV2
        | CatalogRegistration,
        ...,
    ] = ()  # pyright: ignore[reportIncompatibleVariableOverride]


class PersonalServerConfigV6(PersonalServerConfigV5):
    schema_version: Literal["personal-research-server-config/v6"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "personal-research-server-config/v6"
    )
    forward_dataset_admissions: tuple[ForwardDatasetAdmission, ...] = Field(
        default=(), max_length=61
    )
    catalog: tuple[
        CatalogRegistrationV6
        | CatalogRegistrationV5
        | CatalogRegistrationV4
        | CatalogRegistrationV3
        | CatalogRegistrationV2
        | CatalogRegistration,
        ...,
    ] = ()  # pyright: ignore[reportIncompatibleVariableOverride]


class HS300ExecutionAuthorization(_ServerDocument):
    schema_version: Literal["personal-hs300-execution-authorization/v1"] = (
        "personal-hs300-execution-authorization/v1"
    )
    prepared_hash: str = Field(pattern=SHA256_PATTERN)
    code_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    profile_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_ids: tuple[str, ...]
    approval_evidence_path: Path
    approval_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    expires_at: datetime
    storage_policy_path: Path
    storage_policy_hash: str = Field(pattern=SHA256_PATTERN)
    wall_seconds: int = Field(gt=0, le=86400)
    growth_bytes: int = Field(gt=0)
    market_acquisition_calls: Literal[0] = 0
    native_backtests: Literal[7] = 7
    training_calls: Literal[0] = 0
    research_sdk_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    external_disclosure: Literal["NONE_OFFLINE_LOCAL_ONLY"] = "NONE_OFFLINE_LOCAL_ONLY"

    @model_validator(mode="after")
    def finite_scope(self) -> HS300ExecutionAuthorization:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("authorization expiry must have an explicit timezone")
        if self.candidate_ids != (
            "main",
            "classic",
            "random-17",
            "random-41",
            "random-73",
            "random-101",
            "random-137",
        ):
            raise ValueError("authorization must retain the exact seven-candidate denominator")
        return self


class HS300LifecycleExecutionAuthorization(_ServerDocument):
    schema_version: Literal["personal-hs300-execution-authorization/v2"] = (
        "personal-hs300-execution-authorization/v2"
    )
    prepared_hash: str = Field(pattern=SHA256_PATTERN)
    code_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    profile_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_ids: tuple[str, ...]
    approval_evidence_path: Path
    approval_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    expires_at: datetime
    storage_policy_path: Path
    storage_policy_hash: str = Field(pattern=SHA256_PATTERN)
    wall_seconds: int = Field(gt=0, le=86400)
    growth_bytes: int = Field(gt=0)
    market_acquisition_calls: Literal[0] = 0
    native_backtests: Literal[7] = 7
    training_calls: Literal[0] = 0
    research_sdk_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    external_disclosure: Literal["NONE_OFFLINE_LOCAL_ONLY"] = "NONE_OFFLINE_LOCAL_ONLY"

    @model_validator(mode="after")
    def finite_scope(self) -> HS300LifecycleExecutionAuthorization:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("authorization expiry must have an explicit timezone")
        if self.candidate_ids != (
            "main",
            "classic",
            "random-17",
            "random-41",
            "random-73",
            "random-101",
            "random-137",
        ):
            raise ValueError("authorization must retain the exact seven-candidate denominator")
        return self

    lifecycle_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    lifecycle_source_hashes: dict[str, str]
    native_boundary_policy_hash: str = Field(pattern=SHA256_PATTERN)
    native_event_policy: Literal["HARD_STOP_EXPOSED_ARM_RETAIN_ALL_SEVEN"] = (
        "HARD_STOP_EXPOSED_ARM_RETAIN_ALL_SEVEN"
    )

    @model_validator(mode="after")
    def bound_lifecycle_sources(self) -> HS300LifecycleExecutionAuthorization:
        import re

        if not self.lifecycle_source_hashes or any(
            re.fullmatch(SHA256_PATTERN, digest) is None
            for digest in self.lifecycle_source_hashes.values()
        ):
            raise ValueError("exact lifecycle source hashes are required")
        return self


class HS300CashExecutionAuthorization(HS300LifecycleExecutionAuthorization):
    schema_version: Literal["personal-hs300-execution-authorization/v3"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "personal-hs300-execution-authorization/v3"
    )
    native_backtests: Literal[6] = 6  # pyright: ignore[reportIncompatibleVariableOverride]
    wall_seconds: int = Field(gt=0, le=3600)
    growth_bytes: int = Field(gt=0, le=4 * 1024**3)
    validation_calls: Literal[0] = 0
    cash_runtime_policy_hash: str = Field(pattern=SHA256_PATTERN)
    cash_rule_hashes: tuple[str, ...]
    native_source_hashes: dict[str, str]
    classic_origin_hash: str = Field(pattern=SHA256_PATTERN)
    signal_reuse_hash: str = Field(pattern=SHA256_PATTERN)


class HS300AdjustedExecutionAuthorization(HS300CashExecutionAuthorization):
    schema_version: Literal["personal-hs300-execution-authorization/v4"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "personal-hs300-execution-authorization/v4"
    )
    adjusted_unit_policy_hash: str = Field(pattern=SHA256_PATTERN)
    adjusted_facts_hash: str = Field(pattern=SHA256_PATTERN)
    adjusted_runtime_source_hashes: dict[str, str] = Field(min_length=1)
    future_quote_binding_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def bound_adjusted_runtime_sources(self) -> HS300AdjustedExecutionAuthorization:
        import re

        if any(
            re.fullmatch(SHA256_PATTERN, digest) is None
            for digest in self.adjusted_runtime_source_hashes.values()
        ):
            raise ValueError("exact adjusted runtime source hashes are required")
        return self


def _read(path: Path, expected_hash: str | None = None) -> bytes:
    if not path.is_absolute():
        raise ValueError("trusted server paths must be absolute")
    with opened_directory(path.parent) as descriptor:
        raw = read_regular_bytes_at(descriptor, path.name, max_bytes=16 * 1024 * 1024)
    if expected_hash is not None and sha256_bytes(raw) != expected_hash:
        raise ArtifactIntegrityError("trusted server file hash disagrees")
    return raw


def load_server_config(
    path: Path,
) -> (
    PersonalServerConfig
    | PersonalServerConfigV2
    | PersonalServerConfigV3
    | PersonalServerConfigV4
    | PersonalServerConfigV5
):
    import json

    raw = _read(path)
    config_type = (
        PersonalServerConfigV6
        if json.loads(raw).get("schema_version") == "personal-research-server-config/v6"
        else PersonalServerConfigV5
        if json.loads(raw).get("schema_version") == "personal-research-server-config/v5"
        else PersonalServerConfigV4
        if json.loads(raw).get("schema_version") == "personal-research-server-config/v4"
        else PersonalServerConfigV3
        if json.loads(raw).get("schema_version") == "personal-research-server-config/v3"
        else PersonalServerConfigV2
        if json.loads(raw).get("schema_version") == "personal-research-server-config/v2"
        else PersonalServerConfig
    )
    return config_type.model_validate_json(raw)


def make_trusted_service(
    root: Path, repo_root: Path, config_path: Path | None = None, *, worker_mode: bool = False
) -> PersonalResearchService:
    """Load the operator's explicit config, retaining default-deny when none exists.

    The MCP schema never accepts this path or an authorization write operation. The
    explicit local operator is the trust boundary, not a JSON field claiming approval.
    """
    path = config_path if config_path is not None else root / "server-config.json"
    if config_path is None and not path.exists() and not path.is_symlink():
        return PersonalResearchService(root, repo_root)
    config = load_server_config(path)
    if config.product_root != root or config.repo_root != repo_root:
        raise ValueError("trusted configuration roots disagree with explicit server roots")
    catalog: dict[str, PersonalDatasetBinding] = {}
    for registration in config.catalog:
        manifest_bytes = _read(registration.manifest_path, registration.manifest_sha256)
        manifest_type = (
            HS300AdjustedDatasetManifest
            if isinstance(registration, CatalogRegistrationV4)
            else HS300CashDatasetManifest
            if isinstance(registration, CatalogRegistrationV3)
            else HS300LifecycleDatasetManifest
            if isinstance(registration, CatalogRegistrationV2)
            else HS300DatasetManifest
        )
        manifest = manifest_type.model_validate_json(manifest_bytes)
        if manifest.dataset_id in catalog:
            raise ValueError("duplicate trusted dataset registration")
        for location in (
            registration.provider_root,
            registration.panel_path,
            registration.pit_evidence_path,
            registration.snapshot_path,
            registration.lifecycle_path
            if isinstance(registration, CatalogRegistrationV2)
            else None,
        ):
            if location is not None and not location.is_absolute():
                raise ValueError("trusted dataset paths must be absolute")
        if isinstance(registration, CatalogRegistrationV3):
            for location in (
                registration.cash_rules_path,
                registration.classic_origin_path,
                registration.signal_reuse_spec_path,
            ):
                if not location.is_absolute():
                    raise ValueError("trusted cash paths must be absolute")
        if (
            isinstance(registration, CatalogRegistrationV4)
            and not registration.adjusted_facts_path.is_absolute()
        ):
            raise ValueError("trusted adjusted facts path must be absolute")
        catalog[manifest.dataset_id] = PersonalDatasetBinding(
            manifest=manifest,
            provider_root=registration.provider_root,
            panel_path=registration.panel_path,
            pit_evidence_path=registration.pit_evidence_path,
            snapshot_path=registration.snapshot_path,
            field_mapping_profile=(
                registration.field_mapping_profile
                if isinstance(registration, (CatalogRegistrationV5, CatalogRegistrationV6))
                else "native-bins/v1"
            ),
            adjusted_facts_path=(
                registration.adjusted_facts_path
                if isinstance(registration, CatalogRegistrationV4)
                else None
            ),
            cash_rules_path=(
                registration.cash_rules_path
                if isinstance(registration, CatalogRegistrationV3)
                else None
            ),
            origin_reuse=(
                (ClassicOriginReuse.model_validate_json(_read(registration.classic_origin_path)),)
                if isinstance(registration, CatalogRegistrationV3)
                else ()
            ),
            signal_reuse=(
                SignalReuseSpec.model_validate_json(_read(registration.signal_reuse_spec_path))
                if isinstance(registration, CatalogRegistrationV3)
                else None
            ),
            lifecycle_path=(
                registration.lifecycle_path
                if isinstance(registration, CatalogRegistrationV2)
                else None
            ),
        )
    if config.authorization_path is None:
        service = PersonalResearchService(
            root, repo_root, catalog=catalog, data_blockers=config.data_blockers
        )
        if isinstance(config, PersonalServerConfigV5):
            from quantos.application.personal_product import configure_personal_product

            configure_personal_product(service, config, path, worker_mode=worker_mode)
        return service

    def grant_for(
        prepared: Prepared,
    ) -> HS300ExecutionAuthorization | HS300LifecycleExecutionAuthorization:
        # Re-read before every attempted execution: revocation/tampering fails closed.
        actual_config = load_server_config(path)
        if actual_config != config:
            raise PermissionError("trusted server configuration changed; restart the service")
        assert config.authorization_path is not None
        grant_type = (
            HS300AdjustedExecutionAuthorization
            if isinstance(prepared, PreparedHS300AdjustedStudy)
            else HS300CashExecutionAuthorization
            if isinstance(prepared, PreparedHS300CashStudy)
            else HS300LifecycleExecutionAuthorization
            if isinstance(prepared, PreparedHS300LifecycleStudy)
            else HS300ExecutionAuthorization
        )
        grant = grant_type.model_validate_json(
            _read(config.authorization_path, config.authorization_sha256)
        )
        _read(grant.approval_evidence_path, grant.approval_evidence_sha256)
        if grant.expires_at <= datetime.now(UTC):
            raise PermissionError("trusted execution authorization expired")
        if (
            not isinstance(prepared, (PreparedHS300Study, PreparedHS300LifecycleStudy))
            or prepared.dataset_manifest is None
        ):
            raise PermissionError("authorization applies only to the exact HS300 successor study")
        if (
            grant.prepared_hash != prepared.content_hash
            or grant.code_hash != prepared.code_hash
            or grant.dataset_manifest_hash != prepared.dataset_manifest.content_hash
            or grant.profile_hash != prepared.request.profile.content_hash
            or grant.candidate_ids != tuple(c.candidate_id for c in prepared.candidates)
        ):
            raise PermissionError("trusted authorization does not match the exact prepared study")
        if isinstance(prepared, PreparedHS300LifecycleStudy):
            if not isinstance(grant, HS300LifecycleExecutionAuthorization):
                raise PermissionError("lifecycle successor requires its own bound authorization")
            lifecycle_manifest = prepared.dataset_manifest
            assert isinstance(lifecycle_manifest, HS300LifecycleDatasetManifest)
            if (
                grant.lifecycle_manifest_hash != lifecycle_manifest.lifecycle_manifest_hash
                or grant.lifecycle_source_hashes != lifecycle_manifest.lifecycle_source_hashes
                or grant.native_boundary_policy_hash
                != lifecycle_manifest.native_boundary_policy_hash
            ):
                raise PermissionError(
                    "trusted lifecycle sources or native boundary policy disagree"
                )
        if isinstance(prepared, PreparedHS300CashStudy):
            if not isinstance(grant, HS300CashExecutionAuthorization):
                raise PermissionError("cash successor requires its own bound authorization")
            cash_manifest = prepared.dataset_manifest
            assert isinstance(cash_manifest, HS300CashDatasetManifest)
            if (
                grant.cash_runtime_policy_hash != cash_manifest.cash_runtime_policy_hash
                or grant.cash_rule_hashes
                != tuple(rule.content_hash for rule in cash_manifest.cash_rules)
                or grant.native_source_hashes != cash_manifest.native_source_hashes
                or len(prepared.origin_reuse) != 1
                or grant.classic_origin_hash != prepared.origin_reuse[0].content_hash
                or prepared.signal_reuse is None
                or grant.signal_reuse_hash != prepared.signal_reuse.content_hash
            ):
                raise PermissionError("trusted cash policy, rules or origin reuse disagree")
        if isinstance(prepared, PreparedHS300AdjustedStudy):
            if not isinstance(grant, HS300AdjustedExecutionAuthorization):
                raise PermissionError(
                    "adjusted-unit successor requires its own bound authorization"
                )
            adjusted_manifest = prepared.dataset_manifest
            assert isinstance(adjusted_manifest, HS300AdjustedDatasetManifest)
            if (
                grant.adjusted_unit_policy_hash != adjusted_manifest.adjusted_unit_policy_hash
                or grant.adjusted_facts_hash != adjusted_manifest.adjusted_facts.content_hash
                or grant.adjusted_runtime_source_hashes
                != adjusted_manifest.adjusted_runtime_source_hashes
                or grant.future_quote_binding_hash
                != adjusted_manifest.future_quote_binding.content_hash
            ):
                raise PermissionError(
                    "trusted adjusted-unit policy, facts, runtime or quote binding disagree"
                )
        return grant

    def guarded_executor(prepared: Prepared) -> Any:
        from quantos.application.hs300_worker import GuardedHS300Executor

        grant = grant_for(prepared)
        return GuardedHS300Executor(
            catalog,
            server_config_path=path,
            storage_policy_path=grant.storage_policy_path,
            storage_policy_hash=grant.storage_policy_hash,
            wall_seconds=grant.wall_seconds,
            growth_bytes=grant.growth_bytes,
        )

    def authorize(prepared: Prepared) -> str:
        grant = grant_for(prepared)
        guarded_executor(prepared).preflight(prepared)
        return grant.model_dump_json()

    def execute(
        prepared: Prepared, output_root: Path, cancelled: Callable[[], bool]
    ) -> dict[str, Any]:
        return guarded_executor(prepared)(prepared, output_root, cancelled)

    service = PersonalResearchService(
        root,
        repo_root,
        catalog=catalog,
        data_blockers=config.data_blockers,
        execution_authorizer=authorize,
        executor=execute,
    )
    if isinstance(config, PersonalServerConfigV5):
        from quantos.application.personal_product import configure_personal_product

        configure_personal_product(service, config, path, worker_mode=worker_mode)
    return service
