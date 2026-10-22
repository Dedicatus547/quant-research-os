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


def _read(path: Path, expected_hash: str | None = None) -> bytes:
    if not path.is_absolute():
        raise ValueError("trusted server paths must be absolute")
    with opened_directory(path.parent) as descriptor:
        raw = read_regular_bytes_at(descriptor, path.name, max_bytes=16 * 1024 * 1024)
    if expected_hash is not None and sha256_bytes(raw) != expected_hash:
        raise ArtifactIntegrityError("trusted server file hash disagrees")
    return raw


def load_server_config(path: Path) -> PersonalServerConfig:
    return PersonalServerConfig.model_validate_json(_read(path))


def make_trusted_service(
    root: Path, repo_root: Path, config_path: Path | None = None
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
        manifest = HS300DatasetManifest.model_validate_json(
            _read(registration.manifest_path, registration.manifest_sha256)
        )
        if manifest.dataset_id in catalog:
            raise ValueError("duplicate trusted dataset registration")
        for location in (
            registration.provider_root,
            registration.panel_path,
            registration.pit_evidence_path,
            registration.snapshot_path,
        ):
            if location is not None and not location.is_absolute():
                raise ValueError("trusted dataset paths must be absolute")
        catalog[manifest.dataset_id] = PersonalDatasetBinding(
            manifest=manifest,
            provider_root=registration.provider_root,
            panel_path=registration.panel_path,
            pit_evidence_path=registration.pit_evidence_path,
            snapshot_path=registration.snapshot_path,
        )
    if config.authorization_path is None:
        return PersonalResearchService(
            root, repo_root, catalog=catalog, data_blockers=config.data_blockers
        )

    def grant_for(prepared: Prepared) -> HS300ExecutionAuthorization:
        # Re-read before every attempted execution: revocation/tampering fails closed.
        actual_config = load_server_config(path)
        if actual_config != config:
            raise PermissionError("trusted server configuration changed; restart the service")
        assert config.authorization_path is not None
        grant = HS300ExecutionAuthorization.model_validate_json(
            _read(config.authorization_path, config.authorization_sha256)
        )
        _read(grant.approval_evidence_path, grant.approval_evidence_sha256)
        if grant.expires_at <= datetime.now(UTC):
            raise PermissionError("trusted execution authorization expired")
        if not isinstance(prepared, PreparedHS300Study) or prepared.dataset_manifest is None:
            raise PermissionError("authorization applies only to the exact HS300 successor study")
        if (
            grant.prepared_hash != prepared.content_hash
            or grant.code_hash != prepared.code_hash
            or grant.dataset_manifest_hash != prepared.dataset_manifest.content_hash
            or grant.profile_hash != prepared.request.profile.content_hash
            or grant.candidate_ids != tuple(c.candidate_id for c in prepared.candidates)
        ):
            raise PermissionError("trusted authorization does not match the exact prepared study")
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

    return PersonalResearchService(
        root,
        repo_root,
        catalog=catalog,
        data_blockers=config.data_blockers,
        execution_authorizer=authorize,
        executor=execute,
    )
