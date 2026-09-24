from __future__ import annotations

import base64
import copy
import csv
import hashlib
import importlib.util
import io
import stat
import sys
import zipfile
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_codex_runtime_identity_provenance_test_module",
    ROOT / "scripts/verify_codex_runtime_identity_provenance.py",
)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def _elf_fixture() -> bytes:
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16:18] = (2).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[52:54] = (64).to_bytes(2, "little")
    return bytes(header) + b"fixture executable bytes"


def _row(name: str, payload: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
    return (name, "sha256=" + digest.decode("ascii").rstrip("="), str(len(payload)))


def _write_wheel(path: Path, executable: bytes | None = None) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = executable if executable is not None else _elf_fixture()
    member_names = {
        verifier.BINARY_MEMBER: payload,
        "openai_codex_cli_bin-0.156.1.dist-info/METADATA": (
            b"Name: openai-codex-cli-bin\nVersion: 0.156.1\n"
        ),
    }
    rows = [_row(name, data) for name, data in member_names.items()]
    rows.append((verifier.RECORD_VERSION, "", ""))
    record_file = io.StringIO(newline="")
    csv.writer(record_file, lineterminator="\n").writerows(rows)
    member_names[verifier.RECORD_VERSION] = record_file.getvalue().encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in member_names.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(info, content)
    return payload


def _write_expected_artifacts(tmp_path: Path) -> dict[str, dict[str, object]]:
    bindings: dict[str, dict[str, object]] = {}
    artifacts: dict[str, dict[str, bytes]] = {
        "candidate_preflight": {
            "candidate-preflight-report.json": verifier.canonical_json_bytes(
                {
                    "schema_version": "fr03-codex-runtime-preflight/v1",
                    "candidate_runtime": {
                        "runtime_binary_sha256": verifier.HISTORICAL_FROZEN_SHA256,
                        "runtime_distribution": verifier.PACKAGE_NAME,
                        "runtime_package_version": verifier.PACKAGE_VERSION,
                    },
                }
            ),
            "compatibility-audit.json": verifier.canonical_json_bytes({"audit": "test"}),
            "candidate-public-notifications.json": b"[]",
        },
        "account_routing_diagnostic_v2": {
            "account-routing-report.json": verifier.canonical_json_bytes(
                {
                    "schema_version": "fr03-codex-account-routing-diagnostic/v2",
                    "diagnostic_classification": "INCONCLUSIVE",
                    "p10_eligible": False,
                }
            ),
            "account-routing-matrix.json": verifier.canonical_json_bytes(
                {"schema_version": "fr03-codex-account-routing-matrix/v2"}
            ),
            "upstream-source-audit.json": verifier.canonical_json_bytes({"audit": "test"}),
        },
    }
    for artifact_id, files in artifacts.items():
        hashes: dict[str, str] = {}
        for name, payload in files.items():
            hashes[name] = hashlib.sha256(payload).hexdigest()
        report_name = (
            "candidate-preflight-report.json"
            if artifact_id == "candidate_preflight"
            else "account-routing-report.json"
        )
        report_hash = hashes[report_name]
        directory = tmp_path / artifact_id / f"sha256-{report_hash}"
        directory.mkdir(parents=True)
        for name, payload in files.items():
            (directory / name).write_bytes(payload)
        bindings[artifact_id] = {
            "path": f"{artifact_id}/sha256-{report_hash}",
            "report_sha256": report_hash,
            "file_sha256": hashes,
        }
    return bindings


@pytest.mark.parametrize(
    ("official", "expected"),
    [
        ("b" * 64, "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR"),
        ("a" * 64, "OBSERVED_RUNTIME_BINARY_MISMATCH"),
        ("c" * 64, "RUNTIME_IDENTITY_PROVENANCE_CONFLICT"),
        ("a" * 64, "IDENTITY_CONFIRMED"),
    ],
)
def test_three_way_identity_classification(official: str, expected: str) -> None:
    if expected in {
        "OBSERVED_RUNTIME_BINARY_MISMATCH",
        "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR",
        "RUNTIME_IDENTITY_PROVENANCE_CONFLICT",
    }:
        frozen, observed = "a" * 64, "b" * 64
    else:
        frozen = observed = "a" * 64
    assert (
        verifier.classify_identity_hashes(
            official_sha256=official,
            frozen_sha256=frozen,
            observed_sha256=observed,
        )
        == expected
    )


def test_record_classification_uses_historical_three_values() -> None:
    assert (
        verifier.classify_identity_hashes(
            official_sha256=verifier.OBSERVED_BC_SHA256,
            frozen_sha256=verifier.HISTORICAL_FROZEN_SHA256,
            observed_sha256=verifier.OBSERVED_BC_SHA256,
        )
        == "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR"
    )


def test_verified_wheel_record_and_materialized_binary_match(tmp_path: Path) -> None:
    wheel = tmp_path / verifier.WHEEL_FILENAME
    binary = tmp_path / "codex"
    expected_binary = _write_wheel(wheel)
    binary.write_bytes(expected_binary)

    result = verifier.verify_distribution_and_binary(
        wheel,
        binary,
        expected_distribution_sha256=verifier._sha256_file(wheel),
    )

    expected_hash = hashlib.sha256(expected_binary).hexdigest()
    assert result["binary_sha256_hashlib"] == expected_hash
    assert result["binary_sha256_sha256sum"] == expected_hash
    assert result["binary_size_bytes"] == len(expected_binary)
    assert result["record_path"] == verifier.RECORD_VERSION


def test_tampered_wheel_digest_is_rejected(tmp_path: Path) -> None:
    wheel = tmp_path / verifier.WHEEL_FILENAME
    binary = tmp_path / "codex"
    original = _write_wheel(wheel)
    binary.write_bytes(original)
    wheel.write_bytes(wheel.read_bytes() + b"tamper")

    with pytest.raises(verifier.ProvenanceError, match="official PyPI digest"):
        verifier.verify_distribution_and_binary(
            wheel,
            binary,
            expected_distribution_sha256=hashlib.sha256(b"different official wheel").hexdigest(),
        )


def test_tampered_materialized_binary_is_rejected(tmp_path: Path) -> None:
    wheel = tmp_path / verifier.WHEEL_FILENAME
    binary = tmp_path / "codex"
    expected = _write_wheel(wheel)
    binary.write_bytes(expected[:-1] + b"!")

    with pytest.raises(verifier.ProvenanceError, match="differ from the wheel member"):
        verifier.verify_distribution_and_binary(
            wheel,
            binary,
            expected_distribution_sha256=verifier._sha256_file(wheel),
        )


def test_tampered_wheel_record_digest_is_rejected(tmp_path: Path) -> None:
    wheel = tmp_path / verifier.WHEEL_FILENAME
    binary = tmp_path / "codex"
    expected = _write_wheel(wheel)
    binary.write_bytes(expected)
    with zipfile.ZipFile(wheel) as original:
        members = [(info, original.read(info.filename)) for info in original.infolist()]
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as changed:
        for info, payload in members:
            changed.writestr(
                info,
                payload + b" changed" if info.filename == verifier.BINARY_MEMBER else payload,
            )

    with pytest.raises(verifier.ProvenanceError, match="RECORD"):
        verifier.verify_distribution_and_binary(
            wheel,
            binary,
            expected_distribution_sha256=verifier._sha256_file(wheel),
        )


def test_affected_artifact_hash_change_is_rejected(tmp_path: Path) -> None:
    bindings = _write_expected_artifacts(tmp_path)
    verifier._verify_affected_artifacts(tmp_path, expected_bindings=bindings)
    relative = cast(dict[str, object], bindings["candidate_preflight"])["path"]
    changed = tmp_path / str(relative) / "candidate-preflight-report.json"
    changed.write_bytes(b'{"schema_version":"tampered"}')

    with pytest.raises(verifier.ProvenanceError, match="artifact hash changed"):
        verifier._verify_affected_artifacts(tmp_path, expected_bindings=bindings)


def _minimal_p1_record(bindings: dict[str, dict[str, object]]) -> dict[str, object]:
    observed = verifier.OBSERVED_BC_SHA256
    return {
        "schema_version": verifier.SCHEMA_VERSION,
        "implementation_commit": "1" * 40,
        "package": {
            "name": verifier.PACKAGE_NAME,
            "version": verifier.PACKAGE_VERSION,
            "official_distribution_filename": verifier.WHEEL_FILENAME,
            "platform_tag": "py3-none-manylinux_2_17_x86_64",
            "source_index": "PyPI",
            "official_release_url": verifier.PYPI_RELEASE_URL,
            "official_download_url": verifier.WHEEL_URL,
            "pypi_published_sha256": verifier.WHEEL_SHA256,
            "distribution_sha256": verifier.WHEEL_SHA256,
            "distribution_size_bytes": 100,
            "platform": "Linux x86_64, glibc 2.35 host; Python 3.11",
            "linux_x86_64_release_variants": [
                {
                    "filename": verifier.WHEEL_FILENAME,
                    "tag": "py3-none-manylinux_2_17_x86_64",
                    "sha256": verifier.WHEEL_SHA256,
                },
                {
                    "filename": "openai_codex_cli_bin-0.156.1-py3-none-musllinux_1_1_x86_64.whl",
                    "tag": "py3-none-musllinux_1_1_x86_64",
                    "sha256": "950627ab801703e061f2404105ed8216bb9728befbb09d853003a2678b9dbab2",
                },
            ],
            "publishing_provenance": {
                "pypi_trusted_publishing_attestation": True,
                "attestation_status_source": verifier.PYPI_RELEASE_URL,
                "publishing_platform": "GitHub Actions",
                "repository": "openai/codex",
                "publishing_commit": verifier.PUBLISHING_COMMIT,
                "workflow": verifier.PUBLISHING_WORKFLOW,
                "workflow_run": verifier.PUBLISHING_RUN,
            },
        },
        "bundled_executable": {
            "archive_member_path": verifier.BINARY_MEMBER,
            "file_size_bytes": 100,
            "file_type": "ELF64 Linux x86_64 regular executable",
            "record_path": verifier.RECORD_VERSION,
            "sha256_method_1_value": observed,
            "sha256_method_2_value": observed,
        },
        "identity_comparison": {
            "authoritative_materialized_binary_sha256": observed,
            "historical_frozen_sha256": verifier.HISTORICAL_FROZEN_SHA256,
            "observed_b_c_sha256": observed,
            "classification": "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR",
        },
        "affected_artifacts": bindings,
        "superseding_scope": "runtime_identity_assertion_only",
        "does_not_modify": list(verifier.DOES_NOT_MODIFY),
        "existing_matrix_reclassification": {
            "prior_classification": "INCONCLUSIVE",
            "recomputed_classification": "UPSTREAM_ACCOUNT_ROUTING_FAILURE",
            "p10_eligible": False,
            "scenario_ids": ["A", "B", "C"],
            "runtime_identity_verified_overrides": {"A": True, "B": True, "C": True},
            "observation_fields_changed": [],
        },
        "candidate_runtime_status": "IDENTITY_CORRECTED_OFFLINE; P10 NOT_EVALUATED",
        "scenario_d_run": False,
        "p10_run": False,
        "model_provider_or_account_endpoint_used": False,
        "canonical_pin_changed": False,
        "fr03_status": "NO_GO",
        "p14d_c_status": "BLOCKED_UNIMPLEMENTED",
    }


def test_record_rejects_changed_affected_artifact_reference(tmp_path: Path) -> None:
    bindings = _write_expected_artifacts(tmp_path)
    record = _minimal_p1_record(copy.deepcopy(bindings))
    affected = cast(dict[str, object], record["affected_artifacts"])
    candidate = cast(dict[str, object], affected["candidate_preflight"])
    candidate["report_sha256"] = "f" * 64

    with pytest.raises(verifier.ProvenanceError, match="affected immutable artifact binding"):
        verifier._verify_record_contract(record, expected_bindings=bindings)


def test_record_rejects_superseding_runtime_observations(tmp_path: Path) -> None:
    bindings = _write_expected_artifacts(tmp_path)
    record = _minimal_p1_record(copy.deepcopy(bindings))
    record["superseding_scope"] = "runtime_observations"

    with pytest.raises(verifier.ProvenanceError, match="scope"):
        verifier._verify_record_contract(record, expected_bindings=bindings)
