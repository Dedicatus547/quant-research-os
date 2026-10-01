"""An unqualified bundle cannot promote itself by rewriting its outer indexes."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from quantos.application.provenance import capture_runtime_fingerprint
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted_qualification import (
    HOSTED_QUALIFICATION_CASES,
    HostedQualificationCase,
    HostedQualificationManifest,
)
from quantos.infrastructure import hosted_verification as verifier


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "manifest_bytes",
        "path",
        "extra",
        "missing",
        "file_bytes",
        "length",
        "forged_gates",
        "runtime_hash",
        "runtime_bytes",
        "frozen_contract",
        "manager_source",
    ),
)
def test_unqualified_bundle_recomputes_exact_bytes_runtime_and_derived_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    staging = tmp_path / "staging"
    (staging / "deployment").mkdir(parents=True)
    cases = tuple(HostedQualificationCase(case_id=key) for key in HOSTED_QUALIFICATION_CASES)
    result = verifier.verify_staging(staging, cases)
    assert result.eligibility == "NOT_QUALIFIED"
    assert all(gate.verdict == "NOT_EVALUATED" for gate in result.gates)
    fingerprint = capture_runtime_fingerprint()
    runtime_path = staging / "deployment/runtime-fingerprint.json"
    runtime_path.write_bytes(fingerprint.canonical_bytes())
    result_path = staging / "verifier-result.json"
    result_path.write_bytes(result.canonical_bytes())
    if damage == "forged_gates":
        forged = result.model_copy(
            update={
                "gates": tuple(
                    gate.model_copy(update={"verdict": "PASS"}) for gate in result.gates
                ),
                "eligibility": "ELIGIBLE_FOR_HM09_REVIEW",
            }
        )
        result_path.write_bytes(forged.canonical_bytes())
    elif damage == "runtime_bytes":
        runtime_path.write_bytes(b" " + fingerprint.canonical_bytes())
    manifest = HostedQualificationManifest(
        exact_commit="a" * 40,
        lockfile_hash="b" * 64,
        runtime_fingerprint_hash=(
            "c" * 64 if damage == "runtime_hash" else fingerprint.content_hash
        ),
        deployment_profile_hash="d" * 64,
        case_records=cases,
        verifier_result_hash=sha256_bytes(result_path.read_bytes()),
        limitations=("SYNTHETIC_UNQUALIFIED_NO_ORIGINAL_SOURCES",),
        files=verifier.raw_inventory(staging).files,
    )
    if damage == "length":
        manifest = manifest.model_copy(
            update={
                "files": tuple(
                    file.model_copy(update={"size_bytes": file.size_bytes + 1})
                    if file.logical_path == "verifier-result.json"
                    else file
                    for file in manifest.files
                )
            }
        )
    (staging / "qualification-manifest.json").write_bytes(manifest.canonical_bytes())
    target = tmp_path / (
        "incorrect-path" if damage == "path" else f"sha256-{manifest.qualification_hash}"
    )
    staging.rename(target)
    if damage == "manifest_bytes":
        path = target / "qualification-manifest.json"
        path.write_bytes(b" " + path.read_bytes())
    elif damage == "extra":
        (target / "unlisted").write_bytes(b"unlisted original canary")
    elif damage == "missing":
        (target / "verifier-result.json").unlink()
    elif damage == "file_bytes":
        (target / "verifier-result.json").write_bytes(b"{}")
    elif damage == "frozen_contract":
        copied = tmp_path / "frozen-source"
        for name in (
            "hosted-contract-v1.md",
            "hosted-acceptance-v1.md",
            "hm02-freeze-manifest.json",
        ):
            destination = copied / "docs/hosted" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(verifier.ROOT / "docs/hosted" / name, destination)
        (copied / "docs/hosted/hosted-contract-v1.md").write_bytes(b"changed contract")
        monkeypatch.setattr(verifier, "ROOT", copied)
    before = verifier.raw_inventory(target)
    if damage is None:
        assert verifier.verify_bundle(target) == manifest
        assert verifier.verify_staging(target, manifest.case_records) == result
    else:
        with pytest.raises(verifier.HostedQualificationError):
            verifier.verify_bundle(
                target,
                manager_root=tmp_path / "absent-manager" if damage == "manager_source" else None,
            )
    assert verifier.raw_inventory(target) == before
