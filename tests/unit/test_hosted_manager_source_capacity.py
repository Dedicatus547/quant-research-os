"""Stopped-source copying preserves large typed indexes without widening other limits.

Synthetic local roots are transport-copy fixtures, never hosted qualification evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_manager_export import _deployment, _mappings

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted_qualification import HostedManagerExport, HostedRawInventory
from quantos.infrastructure import hosted_manager as manager
from quantos.infrastructure import hosted_verification as verification
from quantos.infrastructure.hosted_verification import (
    MAX_MANAGER_EXPORT_BYTES,
    HostedQualificationError,
    raw_inventory,
)
from quantos.security import SecretArtifactRejected


def _source_deployment(root: Path, capability: bytes = b"S" * 32) -> SimpleNamespace:
    deployment = _deployment(root, capability)
    authority, channel = root / "authority", root / "channel"
    (authority / "protocol").mkdir(parents=True)
    channel.mkdir()
    (root / "request-projections").mkdir()
    (authority / "protocol/request.json").write_bytes(b'{"synthetic":"transport-only"}')
    (root / "request-projections/context.json").write_bytes(b'{"synthetic":"review-only"}')
    deployment.paths = SimpleNamespace(authority=authority, channel=channel)
    deployment.spec = SimpleNamespace(content_hash="c" * 64)
    return deployment


@pytest.fixture(scope="module")
def large_source_export(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    root = tmp_path_factory.mktemp("large-typed-source-index")
    deployment = _source_deployment(root)
    exported = manager.publish_manager_export(deployment, _mappings(35000))
    data = (root / "evidence" / exported.content_hash).read_bytes()
    assert 16_777_216 < len(data) < MAX_MANAGER_EXPORT_BYTES
    return data


def _retain_index(deployment: SimpleNamespace, data: bytes, filename: str | None = None) -> Path:
    path = deployment.root / "evidence" / (filename or sha256_bytes(data))
    path.write_bytes(data)
    return path


def _roots(deployment: SimpleNamespace) -> dict[str, Path]:
    return {
        "protocol": deployment.paths.authority / "protocol",
        "evidence": deployment.root / "evidence",
        "request-projections": deployment.root / "request-projections",
    }


def _assert_rejected_unchanged(
    deployment: SimpleNamespace,
    destination: Path,
    error: type[Exception] | tuple[type[Exception], ...],
) -> None:
    before = {name: raw_inventory(root) for name, root in _roots(deployment).items()}
    with pytest.raises(error):
        manager.export_live_source(deployment, destination)
    assert not list((deployment.root / "evidence").glob("source-export-*.json"))
    assert {name: raw_inventory(root) for name, root in _roots(deployment).items()} == before


def test_live_source_copies_over_sixteen_mib_index_and_binds_all_original_roots(
    tmp_path: Path, large_source_export: bytes
) -> None:
    deployment = _source_deployment(tmp_path)
    original = _retain_index(deployment, large_source_export)
    before = {name: raw_inventory(root) for name, root in _roots(deployment).items()}
    destination = tmp_path / "stopped-source"
    digest = manager.export_live_source(deployment, destination)
    assert (destination / "evidence" / original.name).read_bytes() == large_source_export
    assert raw_inventory(destination).content_hash == digest
    for name in before:
        assert raw_inventory(destination / name) == before[name]
    assert raw_inventory(deployment.paths.authority / "protocol") == before["protocol"]
    assert raw_inventory(tmp_path / "request-projections") == before["request-projections"]
    records = list((tmp_path / "evidence").glob("source-export-*.json"))
    assert len(records) == 1 and records[0].name == f"source-export-{digest}.json"
    record = json.loads(records[0].read_bytes())
    assert record["source_inventory"] == raw_inventory(destination).model_dump(mode="json")
    assert record["source_roots"] == {
        name: inventory.model_dump(mode="json") for name, inventory in before.items()
    }
    assert record["deployment_profile_hash"] == deployment.profile.content_hash
    assert record["hosted_spec_hash"] == deployment.spec.content_hash
    assert record["qualification_eligibility"] == "NOT_QUALIFIED"
    after_files = raw_inventory(tmp_path / "evidence").files
    assert (
        tuple(item for item in after_files if item.logical_path != records[0].name)
        == before["evidence"].files
    )


@pytest.mark.parametrize("field,value", (("exact_commit", "d" * 40), ("content_hash", "d" * 64)))
def test_foreign_commit_or_deployment_index_rejected(
    tmp_path: Path, large_source_export: bytes, field: str, value: str
) -> None:
    deployment = _source_deployment(tmp_path)
    _retain_index(deployment, large_source_export)
    setattr(deployment.profile, field, value)
    _assert_rejected_unchanged(deployment, tmp_path / "stopped-source", ArtifactIntegrityError)


@pytest.mark.parametrize("damage", ("hash-filename", "content-change", "noncanonical"))
def test_large_source_index_requires_actual_canonical_hash_filename_and_content(
    tmp_path: Path, large_source_export: bytes, damage: str
) -> None:
    deployment = _source_deployment(tmp_path)
    data, filename = large_source_export, None
    if damage == "hash-filename":
        filename = "d" * 64
    elif damage == "content-change":
        filename = sha256_bytes(data)
        exported = HostedManagerExport.model_validate_json(data)
        data = exported.model_copy(update={"exact_commit": "d" * 40}).canonical_bytes()
    else:
        data += b"\n"
    _retain_index(deployment, data, filename)
    _assert_rejected_unchanged(
        deployment, tmp_path / "stopped-source", (ArtifactIntegrityError, ValueError)
    )


@pytest.mark.parametrize("field,value", (("sha256", "d" * 64), ("size_bytes", -1)))
def test_large_source_original_inventory_hash_and_size_remain_required(
    tmp_path: Path,
    large_source_export: bytes,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    deployment = _source_deployment(tmp_path)
    _retain_index(deployment, large_source_export)
    source = tmp_path / "evidence"
    actual = raw_inventory(source)
    if field == "size_bytes":
        value = actual.files[0].size_bytes + 1
    changed = HostedRawInventory(files=(actual.files[0].model_copy(update={field: value}),))
    original_inventory = verification.raw_inventory

    def inventory(root: Path) -> HostedRawInventory:
        return changed if root == source else original_inventory(root)

    monkeypatch.setattr(verification, "raw_inventory", inventory)
    _assert_rejected_unchanged(deployment, tmp_path / "stopped-source", ArtifactIntegrityError)


def test_large_source_export_still_rejects_known_sensitive_bytes(
    tmp_path: Path, large_source_export: bytes
) -> None:
    deployment = _source_deployment(tmp_path, large_source_export[1_048_560:1_048_592])
    _retain_index(deployment, large_source_export)
    _assert_rejected_unchanged(deployment, tmp_path / "stopped-source", SecretArtifactRejected)


@pytest.mark.parametrize("damage", ("unknown-large-json", "over-thirtytwo-mib"))
def test_unknown_or_over_capacity_evidence_is_rejected_without_terminal_source_record(
    tmp_path: Path, damage: str
) -> None:
    deployment = _source_deployment(tmp_path)
    data = (
        b"{}" + b" " * 4_194_304
        if damage == "unknown-large-json"
        else b"x" * (MAX_MANAGER_EXPORT_BYTES + 1)
    )
    _retain_index(deployment, data)
    _assert_rejected_unchanged(
        deployment, tmp_path / "stopped-source", (ValueError, HostedQualificationError)
    )


@pytest.mark.parametrize("root_name", ("protocol", "request-projections"))
def test_ordinary_protocol_and_projection_read_caps_are_not_widened(
    tmp_path: Path, root_name: str
) -> None:
    deployment = _source_deployment(tmp_path)
    (_roots(deployment)[root_name] / "ordinary.json").write_bytes(b"{}" + b" " * 4_194_304)
    _assert_rejected_unchanged(deployment, tmp_path / "stopped-source", ValueError)
