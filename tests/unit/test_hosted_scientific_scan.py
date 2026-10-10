"""Large authority copies retain complete known-value scans, including decoded JSON."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure import hosted_replay_evidence as replay
from quantos.infrastructure.hosted_deployment import KnownValueGuard
from quantos.infrastructure.hosted_manager import (
    HostedManagedDeployment,
    capture_authority_snapshot,
)
from quantos.infrastructure.hosted_replay_verification import TAMPER_SCHEMAS
from quantos.infrastructure.hosted_verification import raw_inventory
from quantos.security.artifact_secrets import SecretArtifactRejected

CAPABILITY = b"component-only-sensitive-value32"


@pytest.fixture(autouse=True)
def synthetic_storage_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from quantos.infrastructure import hosted_manager

    # Known-value scan fixtures never establish a mounted production storage quota.
    monkeypatch.setattr(hosted_manager, "storage_checkpoint", lambda *_: None)


def _deployment(tmp_path: Path) -> HostedManagedDeployment:
    authority = tmp_path / "authority"
    authority.mkdir()
    return cast(
        HostedManagedDeployment,
        SimpleNamespace(
            root=tmp_path,
            paths=SimpleNamespace(authority=authority),
            capability=CAPABILITY,
            profile=SimpleNamespace(content_hash="a" * 64),
            bundle=SimpleNamespace(campaign=SimpleNamespace(content_hash="b" * 64)),
        ),
    )


def _large_json(*, sensitive: bool) -> bytes:
    # Mixed escapes evade a raw-only scanner but are caught by the full JSON scan.
    value = (
        "".join(chr(c) if i % 2 else f"\\u{c:04x}" for i, c in enumerate(CAPABILITY))
        if sensitive
        else "ordinary-scientific-component"
    )
    return b'{"padding":"' + b"0" * 4_194_304 + b'","value":"' + value.encode() + b'"}'


@pytest.mark.parametrize("sensitive", [False, True])
def test_manager_scientific_snapshot_preserves_full_scan(tmp_path: Path, sensitive: bool) -> None:
    deployment = _deployment(tmp_path)
    data = _large_json(sensitive=sensitive)
    scientific = deployment.paths.authority / "scientific.json"
    scientific.write_bytes(data)
    before = raw_inventory(deployment.paths.authority)
    with pytest.raises(ValueError, match="scan byte cap"):
        KnownValueGuard((CAPABILITY,))(data)
    target = tmp_path / "qualification-cases/Q12/component"
    if sensitive:
        with pytest.raises(SecretArtifactRejected):
            capture_authority_snapshot(deployment, "qualification-cases/Q12/component")
        assert not (target / scientific.name).exists()
    else:
        capture_authority_snapshot(deployment, "qualification-cases/Q12/component")
        assert raw_inventory(target) == before
        assert (target / scientific.name).read_bytes() == data
    assert raw_inventory(deployment.paths.authority) == before


@pytest.mark.parametrize("sensitive", [False, True])
def test_tamper_copy_scans_large_artifact_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sensitive: bool
) -> None:
    deployment = _deployment(tmp_path)
    authority = deployment.paths.authority
    data = _large_json(sensitive=sensitive)
    (authority / "0-scientific.json").write_bytes(data)
    for kind, schema in TAMPER_SCHEMAS.items():
        logical = (
            "business/execution-records/identities/receipt.json"
            if kind == "RECEIPT"
            else kind.lower() + ".json"
        )
        path = authority / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes({"schema_version": schema}))
    before = raw_inventory(authority)
    # This test covers the copy/scan boundary, not native research validity.
    monkeypatch.setattr(replay, "verify_tamper_case", lambda *args, **kwargs: "ComponentRejected")
    copied = tmp_path / "qualification-cases/Q09/tamper/request/authority/0-scientific.json"
    if sensitive:
        with pytest.raises(SecretArtifactRejected):
            replay.capture_replay_tampers(deployment)
        assert not copied.exists()
    else:
        evidence = replay.capture_replay_tampers(deployment)
        assert evidence.is_file()
        for kind in TAMPER_SCHEMAS:
            target = tmp_path / "qualification-cases/Q09/tamper" / kind.lower() / "authority"
            assert (target / "0-scientific.json").read_bytes() == data
    assert raw_inventory(authority) == before
