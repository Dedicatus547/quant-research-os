"""Outer runtime identity binding; synthetic gates here grant no qualification."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_hosted_business_verification import _validation

from quantos.application.provenance import capture_runtime_fingerprint
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted_qualification import (
    HOSTED_QUALIFICATION_CASES,
    HostedQualificationCase,
    HostedQualificationGate,
    HostedQualificationManifest,
    HostedQualificationRoot,
    HostedQualificationVerification,
)
from quantos.contracts.validation import ValidationReport
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    verify_runtime_binding,
)


@pytest.mark.parametrize(
    "mutation", [None, "outer_hash", "noncanonical", "missing_reports", "native_hash", "pending"]
)
def test_runtime_identity_cannot_borrow_unrelated_native_environment(
    tmp_path: Path, mutation: str | None
) -> None:
    fingerprint = capture_runtime_fingerprint()
    (tmp_path / "deployment").mkdir()
    encoded = fingerprint.canonical_bytes()
    (tmp_path / "deployment/runtime-fingerprint.json").write_bytes(
        b" " + encoded if mutation == "noncanonical" else encoded
    )
    authority = tmp_path / "live/authority"
    authority.mkdir(parents=True)
    if mutation != "missing_reports":
        original = _validation()
        fields = {
            key: getattr(original, key)
            for key in type(original).model_fields
            if key not in {"schema_version", "report_hash"}
        }
        fields["runtime_fingerprint_hash"] = (
            "e" * 64 if mutation == "native_hash" else fingerprint.content_hash
        )
        report = ValidationReport.create(**fields)
        target = authority / "validation" / f"sha256-{report.content_hash}" / "manifest.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(canonical_json_bytes(report.model_dump(mode="json")))
    inventory = raw_inventory(authority)
    (tmp_path / "live/inventory.json").write_bytes(inventory.canonical_bytes())
    (tmp_path / "verifier-result.json").write_bytes(b"{}")
    case = HostedQualificationCase(
        case_id="Q11",
        roots=(
            HostedQualificationRoot(
                name="native",
                logical_path="live/authority",
                campaign_hash="a" * 64,
                raw_inventory_path="live/inventory.json",
            ),
        ),
    )
    manifest = HostedQualificationManifest(
        exact_commit="a" * 40,
        lockfile_hash="a" * 64,
        runtime_fingerprint_hash="f" * 64 if mutation == "outer_hash" else fingerprint.content_hash,
        deployment_profile_hash="a" * 64,
        verifier_result_hash="a" * 64,
        case_records=tuple(
            case if key == "Q11" else HostedQualificationCase(case_id=key)
            for key in HOSTED_QUALIFICATION_CASES
        ),
        files=raw_inventory(tmp_path).files,
        limitations=("SYNTHETIC_NOT_QUALIFIED",),
    )
    result = HostedQualificationVerification(
        gates=tuple(
            HostedQualificationGate(
                case_id=key,
                verdict="PASS" if key == "Q11" and mutation != "pending" else "NOT_EVALUATED",
                reason="SYNTHETIC_RUNTIME_BINDING_INPUT_ONLY",
            )
            for key in HOSTED_QUALIFICATION_CASES
        ),
        eligibility="NOT_QUALIFIED",
    )
    before = raw_inventory(tmp_path)
    if mutation in (None, "pending"):
        verify_runtime_binding(tmp_path, manifest, result)
    else:
        with pytest.raises(HostedQualificationError):
            verify_runtime_binding(tmp_path, manifest, result)
    assert raw_inventory(tmp_path) == before
