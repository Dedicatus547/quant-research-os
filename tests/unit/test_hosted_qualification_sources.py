"""Original-byte origin checks on component fixtures; never deployment qualification."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted_qualification import (
    HOSTED_QUALIFICATION_CASES,
    HostedManagerExport,
    HostedQualificationCase,
    HostedQualificationFile,
    HostedQualificationManifest,
    HostedQualificationRoot,
    HostedRawInventory,
)
from quantos.infrastructure import hosted_qualification_sources as sources
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_manager import publish_manager_export
from quantos.infrastructure.hosted_verification import HostedQualificationError


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original, bundle = tmp_path / "original-manager", tmp_path / "uploaded-bundle"
    original.mkdir()
    bundle.mkdir()
    for name in ("install", "provenance", "evidence", "authority/protocol"):
        (original / name).mkdir(parents=True)
    (original / "install/module.py").write_bytes(b"frozen installed code")
    (original / "provenance/module.py").write_bytes(b"frozen source code")
    source_path = "authority/protocol/observation.json"
    logical_path = "cases/Q07/authority/protocol/observation.json"
    raw = canonical_json_bytes({"source": "TRUSTED_EXTERNAL_MANAGER", "verdict": "PASS"})
    (original / source_path).write_bytes(raw)
    uploaded = bundle / logical_path
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(raw)
    installation = install_inventory(original / "install")
    profile = SimpleNamespace(
        content_hash="d" * 64,
        exact_commit="e" * 40,
        lock_hash="f" * 64,
        provenance_inventory_hash=install_inventory(original / "provenance").content_hash,
    )
    deployment = SimpleNamespace(
        root=original,
        profile=profile,
        install=installation,
        capability=b"s" * 32,
        paths=SimpleNamespace(install=original / "install", provenance=original / "provenance"),
    )
    # This replaces only the tiny fixture's profile loading. Byte comparisons,
    # anchored traversal and actual install/provenance inventories remain real.
    monkeypatch.setattr(sources, "read_managed_deployment", lambda *args: deployment)
    export = publish_manager_export(deployment, ((logical_path, source_path),))
    assert isinstance(export, HostedManagerExport)
    (bundle / "manager-export.json").write_bytes(export.canonical_bytes())
    manifest = HostedQualificationManifest(
        exact_commit=profile.exact_commit,
        lockfile_hash=profile.lock_hash,
        runtime_fingerprint_hash="a" * 64,
        deployment_profile_hash=profile.content_hash,
        case_records=tuple(
            HostedQualificationCase(case_id=case) for case in HOSTED_QUALIFICATION_CASES
        ),
        verifier_result_hash="b" * 64,
        manager_export_hash=export.content_hash,
        limitations=("COMPONENT_ONLY_NOT_QUALIFIED",),
        files=tuple(
            sorted(
                (
                    HostedQualificationFile(
                        logical_path=logical_path,
                        sha256=export.files[0].sha256,
                        size_bytes=len(raw),
                    ),
                    HostedQualificationFile(
                        logical_path="manager-export.json",
                        sha256=export.content_hash,
                        size_bytes=len(export.canonical_bytes()),
                    ),
                    HostedQualificationFile(
                        logical_path="verifier-result.json", sha256="b" * 64, size_bytes=1
                    ),
                ),
                key=lambda item: item.logical_path,
            )
        ),
    )
    return original, bundle, manifest, export, logical_path, source_path


def test_export_compares_original_bytes_and_preserves_one_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original, bundle, manifest, export, logical, _source = _fixture(tmp_path, monkeypatch)
    verified = sources.verify_manager_export(bundle, manifest, original)
    assert verified.export_hash == export.content_hash
    root = HostedQualificationRoot(
        name="original",
        logical_path="cases/Q07/authority",
        campaign_hash="c" * 64,
        raw_inventory_path="cases/Q07/inventory.json",
    )
    inventory = HostedRawInventory(
        files=(
            HostedQualificationFile(
                logical_path="protocol/observation.json",
                sha256=export.files[0].sha256,
                size_bytes=export.files[0].size_bytes,
            ),
        )
    )
    assert verified.root_origin(root, inventory) == original / "authority"
    changed = inventory.model_copy(
        update={"files": (inventory.files[0].model_copy(update={"logical_path": "other.json"}),)}
    )
    with pytest.raises(HostedQualificationError, match="original manager files"):
        verified.root_origin(root, changed)
    assert (bundle / logical).read_bytes() == (original / _source).read_bytes()


@pytest.mark.parametrize(
    "mutation", ["original", "upload", "missing_record", "extra_file", "install", "nested_root"]
)
def test_source_labels_and_uploaded_claims_cannot_substitute_for_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    original, bundle, manifest, export, logical, source = _fixture(tmp_path, monkeypatch)
    if mutation == "original":
        (original / source).write_bytes(b"changed original")
    elif mutation == "upload":
        (bundle / logical).write_bytes(b"changed copied observation")
    elif mutation == "missing_record":
        (original / "evidence" / export.content_hash).write_bytes(b"lost source")
    elif mutation == "extra_file":
        manifest = manifest.model_copy(
            update={
                "files": tuple(
                    sorted(
                        (
                            *manifest.files,
                            HostedQualificationFile(
                                logical_path="extra.json", sha256="c" * 64, size_bytes=1
                            ),
                        ),
                        key=lambda item: item.logical_path,
                    )
                )
            }
        )
    elif mutation == "install":
        (original / "install/module.py").write_bytes(b"changed running code")
    else:
        original = bundle / "claimed-manager"
    with pytest.raises(HostedQualificationError):
        sources.verify_manager_export(bundle, manifest, original)
