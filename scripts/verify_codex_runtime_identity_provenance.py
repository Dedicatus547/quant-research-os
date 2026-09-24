#!/usr/bin/env python3
"""Materialize and verify offline provenance for the Codex 0.156.1 Linux runtime."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.integrations.codex.account_routing_diagnostic import (  # noqa: E402
    derive_account_routing_classification,
)

SCHEMA_VERSION = "fr03-codex-runtime-identity-provenance/v1"
PACKAGE_NAME = "openai-codex-cli-bin"
PACKAGE_VERSION = "0.156.1"
WHEEL_FILENAME = "openai_codex_cli_bin-0.156.1-py3-none-manylinux_2_17_x86_64.whl"
WHEEL_SHA256 = "84a12567ca54ba6ae4ed755911c04e7cdf658315f8719963c8daa8592d8fe068"
WHEEL_URL = (
    "https://files.pythonhosted.org/packages/fc/49/"
    "dd321e5e3ddb20d5aa768db20e7989d6e093d940f6bf30b742f1c70acac5/"
    "openai_codex_cli_bin-0.156.1-py3-none-manylinux_2_17_x86_64.whl"
)
PYPI_RELEASE_URL = "https://pypi.org/project/openai-codex-cli-bin/0.156.1/"
PUBLISHING_COMMIT = "8a3c4ea3b5a7c0e92cf24dae46ec87629a26bb7f"
PUBLISHING_WORKFLOW = ".github/workflows/python-sdk-cli-release.yml"
PUBLISHING_RUN = "https://github.com/openai/codex/actions/runs/35811786542/attempts/1"
BINARY_MEMBER = "codex_cli_bin/bin/codex"
RECORD_VERSION = "openai_codex_cli_bin-0.156.1.dist-info/RECORD"
HISTORICAL_FROZEN_SHA256 = "0b2e9301d6100dddda9b3d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f"
OBSERVED_BC_SHA256 = "0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f"

PREFLIGHT_RELATIVE_PATH = (
    "artifacts/qualification/fr03-codex-0.156.1/"
    "sha256-d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945"
)
DIAGNOSTIC_RELATIVE_PATH = (
    "artifacts/diagnostics/codex-account-routing-0.156.1-v2/"
    "sha256-1bc3433e953197df3d64bc4506dee3fd56c7613dc8998e65050a82b54377dfac"
)

EXPECTED_ARTIFACT_BINDINGS: dict[str, dict[str, object]] = {
    "candidate_preflight": {
        "path": PREFLIGHT_RELATIVE_PATH,
        "report_sha256": "d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945",
        "file_sha256": {
            "candidate-preflight-report.json": (
                "d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945"
            ),
            "compatibility-audit.json": (
                "cc80263c55eab95d8de74d584a58090dc4ccfc36c45a090afe00254e41de683b"
            ),
            "candidate-public-notifications.json": (
                "e3f105454b35874a016e7bee7c1439e1d3aaca2e6e5c51699794f365103e567c"
            ),
        },
    },
    "account_routing_diagnostic_v2": {
        "path": DIAGNOSTIC_RELATIVE_PATH,
        "report_sha256": "1bc3433e953197df3d64bc4506dee3fd56c7613dc8998e65050a82b54377dfac",
        "file_sha256": {
            "account-routing-report.json": (
                "1bc3433e953197df3d64bc4506dee3fd56c7613dc8998e65050a82b54377dfac"
            ),
            "account-routing-matrix.json": (
                "1f8a5511a477b608d1decd150d6f0afd1255c75ef812a5590343fe1a233ba21d"
            ),
            "upstream-source-audit.json": (
                "a328ea3af3cb465ac7e6cf4f571cf9f3eece93bf8d0b28bb259ca5ef342546e2"
            ),
        },
    },
}

DOES_NOT_MODIFY = [
    "runtime_observations",
    "account_read_outcomes",
    "rpc_error_results",
    "scenario_sequence",
    "historical_artifact_bytes",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


class ProvenanceError(ValueError):
    """Raised when package provenance or its offline record does not verify."""


def classify_identity_hashes(
    *, official_sha256: str, frozen_sha256: str, observed_sha256: str
) -> str:
    """Classify the three SHA-256 values mechanically."""

    for value in (official_sha256, frozen_sha256, observed_sha256):
        if _SHA256_RE.fullmatch(value) is None:
            raise ProvenanceError("all runtime identity values must be lowercase SHA-256")
    if official_sha256 == frozen_sha256 == observed_sha256:
        return "IDENTITY_CONFIRMED"
    if official_sha256 == observed_sha256:
        return "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR"
    if official_sha256 == frozen_sha256:
        return "OBSERVED_RUNTIME_BINARY_MISMATCH"
    return "RUNTIME_IDENTITY_PROVENANCE_CONFLICT"


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise ProvenanceError(f"{label} is unavailable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise ProvenanceError(f"{label} must be a non-empty regular file, not a symlink")
    return info


def _sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as error:
        raise ProvenanceError("cannot read an evidence file") from error


def _sha256sum_file(path: Path) -> str:
    try:
        result = subprocess.run(
            ["sha256sum", "--", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ProvenanceError("independent sha256sum calculation failed") from error
    digest = result.stdout.split(maxsplit=1)[0] if result.stdout else ""
    if _SHA256_RE.fullmatch(digest) is None:
        raise ProvenanceError("sha256sum returned an invalid digest")
    return digest


def _inspect_elf_x86_64(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            header = stream.read(64)
    except OSError as error:
        raise ProvenanceError("bundled executable cannot be read") from error
    if (
        len(header) < 64
        or header[:4] != b"\x7fELF"
        or header[4] != 2  # ELFCLASS64
        or header[5] != 1  # ELFDATA2LSB
        or int.from_bytes(header[16:18], "little") not in {2, 3}  # EXEC or DYN
        or int.from_bytes(header[18:20], "little") != 62  # EM_X86_64
    ):
        raise ProvenanceError("bundled file is not a Linux x86_64 ELF executable")


def _safe_wheel_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        name = info.filename
        pure = PurePosixPath(name)
        if not name or pure.is_absolute() or ".." in pure.parts or "\\" in name or name in members:
            raise ProvenanceError("wheel contains an unsafe or duplicate archive member")
        members[name] = info
    return members


def _record_entries(
    archive: zipfile.ZipFile, members: Mapping[str, zipfile.ZipInfo]
) -> dict[str, tuple[str, str]]:
    record_paths = [name for name in members if name.endswith(".dist-info/RECORD")]
    if record_paths != [RECORD_VERSION]:
        raise ProvenanceError("wheel must contain the exact package RECORD member")
    try:
        raw = archive.read(RECORD_VERSION)
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    except (KeyError, UnicodeDecodeError, csv.Error, OSError) as error:
        raise ProvenanceError("wheel RECORD is malformed") from error
    entries: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3 or not row[0] or row[0] in entries:
            raise ProvenanceError("wheel RECORD has malformed or duplicate rows")
        entries[row[0]] = (row[1], row[2])
    if RECORD_VERSION not in entries or entries[RECORD_VERSION] != ("", ""):
        raise ProvenanceError("wheel RECORD self-entry must omit its digest and size")
    member_names = {name for name, info in members.items() if not info.is_dir()}
    signature_names = {
        name
        for name in member_names
        if name.endswith((".dist-info/RECORD.jws", ".dist-info/RECORD.p7s"))
    }
    if set(entries) | signature_names != member_names:
        raise ProvenanceError("wheel RECORD entries do not match the archive member set")
    for name, info in members.items():
        if info.is_dir():
            continue
        entry = entries.get(name)
        if entry is None:
            if name.endswith((".dist-info/RECORD.jws", ".dist-info/RECORD.p7s")):
                continue
            raise ProvenanceError("wheel RECORD omits an archive member")
        digest, size_text = entry
        if name == RECORD_VERSION:
            continue
        if not digest or not size_text:
            raise ProvenanceError("wheel RECORD member digest or size is missing")
        try:
            algorithm, encoded = digest.split("=", 1)
            expected = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected_size = int(size_text)
        except (ValueError, TypeError) as error:
            raise ProvenanceError("wheel RECORD digest or size encoding is invalid") from error
        if algorithm != "sha256" or len(expected) != 32 or expected_size < 0:
            raise ProvenanceError("wheel RECORD must use SHA-256 and a valid size")
        hasher = hashlib.sha256()
        size = 0
        try:
            with archive.open(name) as stream:
                while chunk := stream.read(1024 * 1024):
                    hasher.update(chunk)
                    size += len(chunk)
        except (KeyError, OSError, zipfile.BadZipFile) as error:
            raise ProvenanceError("wheel member cannot be read for RECORD verification") from error
        if hasher.digest() != expected or size != expected_size:
            raise ProvenanceError("wheel RECORD digest or size does not match an archive member")
    return entries


def verify_distribution_and_binary(
    distribution_path: Path,
    binary_path: Path,
    *,
    expected_distribution_sha256: str = WHEEL_SHA256,
) -> dict[str, object]:
    """Check official wheel bytes, RECORD, extracted executable and two binary hashes."""

    wheel_info = _regular_file(distribution_path, "official distribution")
    binary_info = _regular_file(binary_path, "materialized executable")
    if distribution_path.name != WHEEL_FILENAME:
        raise ProvenanceError("distribution filename or platform tag is not the official target")
    distribution_sha256 = _sha256_file(distribution_path)
    if distribution_sha256 != expected_distribution_sha256:
        raise ProvenanceError("distribution SHA-256 does not match the official PyPI digest")
    _inspect_elf_x86_64(binary_path)
    binary_sha256_hashlib = _sha256_file(binary_path)
    binary_sha256_sha256sum = _sha256sum_file(binary_path)
    if binary_sha256_hashlib != binary_sha256_sha256sum:
        raise ProvenanceError("independent executable SHA-256 methods disagree")
    try:
        with zipfile.ZipFile(distribution_path) as archive:
            members = _safe_wheel_members(archive)
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ProvenanceError("wheel archive CRC check failed")
            entries = _record_entries(archive, members)
            executable = members.get(BINARY_MEMBER)
            if executable is None or executable.is_dir():
                raise ProvenanceError("wheel does not contain the expected bundled executable")
            unix_mode = executable.external_attr >> 16
            file_type = stat.S_IFMT(unix_mode)
            if file_type not in {0, stat.S_IFREG} or unix_mode & 0o111 == 0:
                raise ProvenanceError("bundled executable must be a regular executable member")
            archive_binary_sha256 = hashlib.sha256()
            archive_binary_size = 0
            try:
                with archive.open(executable) as source, binary_path.open("rb") as materialized:
                    while True:
                        archive_chunk = source.read(1024 * 1024)
                        binary_chunk = materialized.read(1024 * 1024)
                        if archive_chunk != binary_chunk:
                            raise ProvenanceError(
                                "materialized executable bytes differ from the wheel member"
                            )
                        if not archive_chunk:
                            break
                        archive_binary_sha256.update(archive_chunk)
                        archive_binary_size += len(archive_chunk)
            except (KeyError, OSError, zipfile.BadZipFile) as error:
                raise ProvenanceError("bundled executable cannot be read from the wheel") from error
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise ProvenanceError("official distribution is not a readable wheel archive") from error
    if archive_binary_size != binary_info.st_size:
        raise ProvenanceError("materialized executable size does not match the wheel member")
    archive_binary_sha = archive_binary_sha256.hexdigest()
    record_digest, record_size = entries[BINARY_MEMBER]
    if record_digest != "sha256=" + base64.urlsafe_b64encode(
        bytes.fromhex(archive_binary_sha)
    ).decode("ascii").rstrip("=") or record_size != str(archive_binary_size):
        raise ProvenanceError("wheel RECORD executable binding is invalid")
    if archive_binary_sha != binary_sha256_hashlib:
        raise ProvenanceError("wheel member SHA-256 differs from the materialized executable")
    return {
        "distribution_sha256": distribution_sha256,
        "distribution_size_bytes": wheel_info.st_size,
        "distribution_filename": distribution_path.name,
        "binary_sha256_hashlib": binary_sha256_hashlib,
        "binary_sha256_sha256sum": binary_sha256_sha256sum,
        "binary_size_bytes": archive_binary_size,
        "binary_archive_member": BINARY_MEMBER,
        "binary_mode_octal": oct(stat.S_IMODE(executable.external_attr >> 16)),
        "record_path": RECORD_VERSION,
        "record_digest": record_digest,
        "record_size_bytes": int(record_size),
    }


def _read_canonical_json(path: Path, label: str) -> object:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"{label} JSON cannot be read") from error
    if canonical_json_bytes(value) != raw:
        raise ProvenanceError(f"{label} must use canonical JSON encoding")
    return value


def _verify_affected_artifacts(
    repo_root: Path,
    *,
    expected_bindings: Mapping[str, Mapping[str, object]] = EXPECTED_ARTIFACT_BINDINGS,
) -> dict[str, object]:
    loaded: dict[str, object] = {}
    for artifact_id, expected in expected_bindings.items():
        relative_path = cast(str, expected["path"])
        artifact_path = repo_root / relative_path
        file_hashes = cast(dict[str, str], expected["file_sha256"])
        try:
            actual_names = {entry.name for entry in artifact_path.iterdir()}
        except OSError as error:
            raise ProvenanceError("referenced immutable artifact is unavailable") from error
        if actual_names != set(file_hashes):
            raise ProvenanceError("referenced immutable artifact file set changed")
        for file_name, expected_hash in file_hashes.items():
            file_path = artifact_path / file_name
            _regular_file(file_path, "referenced immutable artifact member")
            if _sha256_file(file_path) != expected_hash:
                raise ProvenanceError("referenced immutable artifact hash changed")
            loaded[f"{artifact_id}/{file_name}"] = _read_canonical_json(
                file_path, f"{artifact_id}/{file_name}"
            )
        if artifact_path.name != f"sha256-{expected['report_sha256']}":
            raise ProvenanceError("referenced immutable artifact address changed")
    preflight = loaded["candidate_preflight/candidate-preflight-report.json"]
    diagnostic = loaded["account_routing_diagnostic_v2/account-routing-report.json"]
    matrix = cast(object, loaded["account_routing_diagnostic_v2/account-routing-matrix.json"])
    if not all(isinstance(value, dict) for value in (preflight, diagnostic, matrix)):
        raise ProvenanceError("referenced artifact report and matrix must be JSON objects")
    preflight = cast(dict[str, object], preflight)
    diagnostic = cast(dict[str, object], diagnostic)
    matrix = cast(dict[str, object], matrix)
    candidate = preflight.get("candidate_runtime")
    if (
        preflight.get("schema_version") != "fr03-codex-runtime-preflight/v1"
        or not isinstance(candidate, dict)
        or candidate.get("runtime_binary_sha256") != HISTORICAL_FROZEN_SHA256
        or candidate.get("runtime_distribution") != PACKAGE_NAME
        or candidate.get("runtime_package_version") != PACKAGE_VERSION
        or diagnostic.get("schema_version") != "fr03-codex-account-routing-diagnostic/v2"
        or diagnostic.get("diagnostic_classification") != "INCONCLUSIVE"
        or diagnostic.get("p10_eligible") is not False
        or matrix.get("schema_version") != "fr03-codex-account-routing-matrix/v2"
    ):
        raise ProvenanceError("referenced artifacts do not contain the expected frozen evidence")
    return {"preflight": preflight, "diagnostic": diagnostic, "matrix": matrix}


def _corrected_matrix_classification(
    matrix: Mapping[str, object], *, authoritative_sha256: str
) -> tuple[str, list[dict[str, object]]]:
    raw_scenarios = matrix.get("scenarios")
    if not isinstance(raw_scenarios, list):
        raise ProvenanceError("diagnostic matrix scenarios must be an array")
    scenarios: list[dict[str, object]] = []
    ids: list[object] = []
    for value in cast(list[object], raw_scenarios):
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ProvenanceError("diagnostic scenario must be a JSON object")
        scenario = cast(dict[str, object], value)
        ids.append(scenario.get("scenario_id"))
        scenarios.append(dict(scenario))
    if ids != ["A", "B", "C"]:
        raise ProvenanceError("reclassification requires the existing A/B/C matrix only")
    for scenario in scenarios[1:]:
        if (
            scenario.get("runtime_binary_sha256") != authoritative_sha256
            or scenario.get("runtime_identity_verified") is not False
        ):
            raise ProvenanceError(
                "candidate identity correction does not match frozen observations"
            )
        scenario["runtime_identity_verified"] = True
    try:
        classification = derive_account_routing_classification(scenarios)
    except (TypeError, ValueError) as error:
        raise ProvenanceError("existing A/B/C observations cannot be classified") from error
    return classification, scenarios


def _expected_record(
    *,
    hashes: Mapping[str, object],
    implementation_commit: str,
    repo_root: Path,
    expected_bindings: Mapping[str, Mapping[str, object]] = EXPECTED_ARTIFACT_BINDINGS,
) -> dict[str, object]:
    if _COMMIT_RE.fullmatch(implementation_commit) is None:
        raise ProvenanceError("implementation commit must be a full Git SHA")
    evidence = _verify_affected_artifacts(repo_root, expected_bindings=expected_bindings)
    official_sha = cast(str, hashes["binary_sha256_hashlib"])
    frozen_sha = HISTORICAL_FROZEN_SHA256
    observed_sha = OBSERVED_BC_SHA256
    classification = classify_identity_hashes(
        official_sha256=official_sha,
        frozen_sha256=frozen_sha,
        observed_sha256=observed_sha,
    )
    reclassification: dict[str, object] | None = None
    if classification == "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR":
        old_report = cast(dict[str, object], evidence["diagnostic"])
        new_classification, corrected_scenarios = _corrected_matrix_classification(
            cast(dict[str, object], evidence["matrix"]), authoritative_sha256=official_sha
        )
        original_scenarios = cast(
            list[dict[str, object]], cast(dict[str, object], evidence["matrix"])["scenarios"]
        )
        if [
            {key: value for key, value in item.items() if key != "runtime_identity_verified"}
            for item in corrected_scenarios
        ] != [
            {key: value for key, value in item.items() if key != "runtime_identity_verified"}
            for item in original_scenarios
        ]:
            raise ProvenanceError("identity reclassification changed runtime observations")
        reclassification = {
            "prior_classification": old_report["diagnostic_classification"],
            "recomputed_classification": new_classification,
            "p10_eligible": False,
            "scenario_ids": ["A", "B", "C"],
            "runtime_identity_verified_overrides": {"A": True, "B": True, "C": True},
            "observation_fields_changed": [],
        }
    references = {key: dict(value) for key, value in expected_bindings.items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "implementation_commit": implementation_commit,
        "package": {
            "name": PACKAGE_NAME,
            "version": PACKAGE_VERSION,
            "official_distribution_filename": WHEEL_FILENAME,
            "platform_tag": "py3-none-manylinux_2_17_x86_64",
            "platform": "Linux x86_64, glibc 2.35 host; Python 3.11",
            "distribution_size_bytes": hashes["distribution_size_bytes"],
            "distribution_sha256": hashes["distribution_sha256"],
            "source_index": "PyPI",
            "official_release_url": PYPI_RELEASE_URL,
            "official_download_url": WHEEL_URL,
            "pypi_published_sha256": WHEEL_SHA256,
            "pypi_upload_date": "2026-09-23",
            "linux_x86_64_release_variants": [
                {
                    "filename": "openai_codex_cli_bin-0.156.1-py3-none-manylinux_2_17_x86_64.whl",
                    "tag": "py3-none-manylinux_2_17_x86_64",
                    "sha256": WHEEL_SHA256,
                },
                {
                    "filename": "openai_codex_cli_bin-0.156.1-py3-none-musllinux_1_1_x86_64.whl",
                    "tag": "py3-none-musllinux_1_1_x86_64",
                    "sha256": "950627ab801703e061f2404105ed8216bb9728befbb09d853003a2678b9dbab2",
                },
            ],
            "publishing_provenance": {
                "pypi_trusted_publishing_attestation": True,
                "attestation_status_source": PYPI_RELEASE_URL,
                "publishing_platform": "GitHub Actions",
                "repository": "openai/codex",
                "publishing_commit": PUBLISHING_COMMIT,
                "workflow": PUBLISHING_WORKFLOW,
                "workflow_run": PUBLISHING_RUN,
            },
        },
        "bundled_executable": {
            "archive_member_path": hashes["binary_archive_member"],
            "file_size_bytes": hashes["binary_size_bytes"],
            "archive_mode_octal": hashes["binary_mode_octal"],
            "file_type": "ELF64 Linux x86_64 regular executable",
            "record_path": hashes["record_path"],
            "record_digest": hashes["record_digest"],
            "record_size_bytes": hashes["record_size_bytes"],
            "sha256_method_1": "Python hashlib.file_digest(..., sha256)",
            "sha256_method_2": "sha256sum executable file",
            "sha256_method_1_value": hashes["binary_sha256_hashlib"],
            "sha256_method_2_value": hashes["binary_sha256_sha256sum"],
        },
        "identity_comparison": {
            "historical_frozen_sha256": frozen_sha,
            "observed_b_c_sha256": observed_sha,
            "authoritative_materialized_binary_sha256": official_sha,
            "classification": classification,
        },
        "affected_artifacts": references,
        "superseding_scope": "runtime_identity_assertion_only",
        "does_not_modify": list(DOES_NOT_MODIFY),
        "existing_matrix_reclassification": reclassification,
        "candidate_runtime_status": (
            "IDENTITY_CORRECTED_OFFLINE; P10 NOT_EVALUATED"
            if classification == "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR"
            else "IDENTITY_UNRESOLVED; candidate NOT_EVALUATED"
        ),
        "scenario_d_run": False,
        "p10_run": False,
        "model_provider_or_account_endpoint_used": False,
        "canonical_pin_changed": False,
        "fr03_status": "NO_GO",
        "p14d_c_status": "BLOCKED_UNIMPLEMENTED",
    }


def _verify_record_contract(
    record: Mapping[str, object],
    *,
    expected_bindings: Mapping[str, Mapping[str, object]] = EXPECTED_ARTIFACT_BINDINGS,
) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ProvenanceError("provenance record schema version is invalid")
    package = record.get("package")
    binary = record.get("bundled_executable")
    identity = record.get("identity_comparison")
    if not all(isinstance(value, dict) for value in (package, binary, identity)):
        raise ProvenanceError("provenance record package, executable, and identity must be objects")
    package = cast(dict[str, object], package)
    binary = cast(dict[str, object], binary)
    identity = cast(dict[str, object], identity)
    if (
        package.get("name") != PACKAGE_NAME
        or package.get("version") != PACKAGE_VERSION
        or package.get("official_distribution_filename") != WHEEL_FILENAME
        or package.get("platform_tag") != "py3-none-manylinux_2_17_x86_64"
        or package.get("source_index") != "PyPI"
        or package.get("official_release_url") != PYPI_RELEASE_URL
        or package.get("official_download_url") != WHEEL_URL
        or package.get("pypi_published_sha256") != WHEEL_SHA256
        or package.get("distribution_sha256") != WHEEL_SHA256
        or not isinstance(package.get("distribution_size_bytes"), int)
        or cast(int, package.get("distribution_size_bytes")) <= 0
        or package.get("platform") != "Linux x86_64, glibc 2.35 host; Python 3.11"
        or package.get("linux_x86_64_release_variants")
        != [
            {
                "filename": WHEEL_FILENAME,
                "tag": "py3-none-manylinux_2_17_x86_64",
                "sha256": WHEEL_SHA256,
            },
            {
                "filename": "openai_codex_cli_bin-0.156.1-py3-none-musllinux_1_1_x86_64.whl",
                "tag": "py3-none-musllinux_1_1_x86_64",
                "sha256": "950627ab801703e061f2404105ed8216bb9728befbb09d853003a2678b9dbab2",
            },
        ]
        or binary.get("archive_member_path") != BINARY_MEMBER
        or binary.get("sha256_method_1_value") != binary.get("sha256_method_2_value")
        or not isinstance(binary.get("file_size_bytes"), int)
        or cast(int, binary.get("file_size_bytes")) <= 0
        or binary.get("file_type") != "ELF64 Linux x86_64 regular executable"
        or binary.get("record_path") != RECORD_VERSION
    ):
        raise ProvenanceError("package or executable identity fields are inconsistent")
    publisher = package.get("publishing_provenance")
    if not isinstance(publisher, dict) or publisher != {
        "pypi_trusted_publishing_attestation": True,
        "attestation_status_source": PYPI_RELEASE_URL,
        "publishing_platform": "GitHub Actions",
        "repository": "openai/codex",
        "publishing_commit": PUBLISHING_COMMIT,
        "workflow": PUBLISHING_WORKFLOW,
        "workflow_run": PUBLISHING_RUN,
    }:
        raise ProvenanceError("PyPI publishing provenance binding is inconsistent")
    if _SHA256_RE.fullmatch(str(identity.get("authoritative_materialized_binary_sha256"))) is None:
        raise ProvenanceError("authoritative executable SHA-256 is invalid")
    recomputed = classify_identity_hashes(
        official_sha256=cast(str, identity["authoritative_materialized_binary_sha256"]),
        frozen_sha256=HISTORICAL_FROZEN_SHA256,
        observed_sha256=OBSERVED_BC_SHA256,
    )
    if (
        identity.get("historical_frozen_sha256") != HISTORICAL_FROZEN_SHA256
        or identity.get("observed_b_c_sha256") != OBSERVED_BC_SHA256
        or identity.get("classification") != recomputed
    ):
        raise ProvenanceError("identity comparison or classification is inconsistent")
    if record.get("affected_artifacts") != expected_bindings:
        raise ProvenanceError("affected immutable artifact binding changed")
    if (
        record.get("superseding_scope") != "runtime_identity_assertion_only"
        or record.get("does_not_modify") != DOES_NOT_MODIFY
    ):
        raise ProvenanceError("superseding scope must preserve all runtime observations")
    if (
        record.get("scenario_d_run") is not False
        or record.get("p10_run") is not False
        or record.get("model_provider_or_account_endpoint_used") is not False
        or record.get("canonical_pin_changed") is not False
        or record.get("fr03_status") != "NO_GO"
        or record.get("p14d_c_status") != "BLOCKED_UNIMPLEMENTED"
    ):
        raise ProvenanceError("record violates the offline task stop boundary")
    expected_candidate_status = (
        "IDENTITY_CORRECTED_OFFLINE; P10 NOT_EVALUATED"
        if recomputed == "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR"
        else "IDENTITY_UNRESOLVED; candidate NOT_EVALUATED"
    )
    if record.get("candidate_runtime_status") != expected_candidate_status:
        raise ProvenanceError("candidate runtime status disagrees with the identity classification")
    commit = record.get("implementation_commit")
    if not isinstance(commit, str) or _COMMIT_RE.fullmatch(commit) is None:
        raise ProvenanceError("record implementation commit is invalid")
    if recomputed == "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR":
        reclassification = record.get("existing_matrix_reclassification")
        if not isinstance(reclassification, dict) or (
            reclassification.get("prior_classification") != "INCONCLUSIVE"
            or reclassification.get("scenario_ids") != ["A", "B", "C"]
            or reclassification.get("runtime_identity_verified_overrides")
            != {"A": True, "B": True, "C": True}
            or reclassification.get("observation_fields_changed") != []
            or reclassification.get("p10_eligible") is not False
        ):
            raise ProvenanceError("identity-only reclassification scope is invalid")
    elif record.get("existing_matrix_reclassification") is not None:
        raise ProvenanceError("matrix cannot be reclassified without a proven identity correction")


def verify_provenance_record(
    record_path: Path,
    distribution_path: Path,
    binary_path: Path,
    repo_root: Path = ROOT,
) -> dict[str, object]:
    """Verify the content-addressed record, official wheel, binary, and frozen evidence offline."""

    record_value = _read_canonical_json(record_path, "provenance record")
    if not isinstance(record_value, dict) or not all(isinstance(key, str) for key in record_value):
        raise ProvenanceError("provenance record must be a JSON object")
    record = cast(dict[str, object], record_value)
    record_hash = sha256_bytes(record_path.read_bytes())
    if record_path.parent.name != f"sha256-{record_hash}":
        raise ProvenanceError("provenance record content address is invalid")
    _verify_record_contract(record)
    hashes = verify_distribution_and_binary(distribution_path, binary_path)
    expected_projection = {
        "distribution_sha256": cast(dict[str, object], record["package"])["distribution_sha256"],
        "distribution_size_bytes": cast(dict[str, object], record["package"])[
            "distribution_size_bytes"
        ],
        "binary_sha256_hashlib": cast(dict[str, object], record["bundled_executable"])[
            "sha256_method_1_value"
        ],
        "binary_sha256_sha256sum": cast(dict[str, object], record["bundled_executable"])[
            "sha256_method_2_value"
        ],
        "binary_size_bytes": cast(dict[str, object], record["bundled_executable"])[
            "file_size_bytes"
        ],
        "binary_archive_member": cast(dict[str, object], record["bundled_executable"])[
            "archive_member_path"
        ],
        "binary_mode_octal": cast(dict[str, object], record["bundled_executable"])[
            "archive_mode_octal"
        ],
        "record_path": cast(dict[str, object], record["bundled_executable"])["record_path"],
        "record_digest": cast(dict[str, object], record["bundled_executable"])["record_digest"],
        "record_size_bytes": cast(dict[str, object], record["bundled_executable"])[
            "record_size_bytes"
        ],
    }
    if any(hashes.get(key) != value for key, value in expected_projection.items()):
        raise ProvenanceError("materialized distribution or executable hashes differ from record")
    evidence = _verify_affected_artifacts(repo_root)
    identity = cast(dict[str, object], record["identity_comparison"])
    classification = cast(str, identity["classification"])
    reclassification = record.get("existing_matrix_reclassification")
    if classification == "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR":
        new_classification, _ = _corrected_matrix_classification(
            cast(dict[str, object], evidence["matrix"]),
            authoritative_sha256=cast(str, identity["authoritative_materialized_binary_sha256"]),
        )
        if not isinstance(reclassification, dict) or (
            reclassification.get("recomputed_classification") != new_classification
        ):
            raise ProvenanceError("offline A/B/C reclassification does not replay")
    return {
        "record_sha256": record_hash,
        "offline_verification": "PASS",
        "distribution_sha256": hashes["distribution_sha256"],
        "authoritative_materialized_binary_sha256": hashes["binary_sha256_hashlib"],
        "classification": classification,
        "recomputed_matrix_classification": (
            cast(dict[str, object], reclassification).get("recomputed_classification")
            if isinstance(reclassification, dict)
            else None
        ),
        "verified_artifact_ids": list(EXPECTED_ARTIFACT_BINDINGS),
        "provider_request_count": 0,
    }


def materialize_record(
    distribution_path: Path,
    binary_path: Path,
    *,
    repo_root: Path = ROOT,
    implementation_commit: str,
    output_root: Path | None = None,
) -> tuple[dict[str, object], Path]:
    """Write a new immutable provenance record after checking clean Git and all local inputs."""

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise ProvenanceError("formal provenance materialization requires a clean worktree")
    hashes = verify_distribution_and_binary(distribution_path, binary_path)
    record = _expected_record(
        hashes=hashes,
        implementation_commit=implementation_commit,
        repo_root=repo_root,
    )
    classification = cast(dict[str, object], record["identity_comparison"])["classification"]
    if classification != "FROZEN_RUNTIME_IDENTITY_BINDING_ERROR":
        raise ProvenanceError(
            "authoritative package identity did not prove the frozen binding wrong; "
            "stop without superseding"
        )
    record_bytes = canonical_json_bytes(record)
    record_hash = sha256_bytes(record_bytes)
    destination_root = output_root or (
        repo_root / "artifacts/diagnostics/codex-runtime-identity-provenance/v1"
    )
    destination = destination_root / f"sha256-{record_hash}"
    destination.mkdir(parents=True, exist_ok=False)
    record_path = destination / "runtime-identity-provenance.json"
    record_path.write_bytes(record_bytes)
    return record, record_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--verify-record", type=Path)
    actions.add_argument("--materialize", action="store_true")
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_record:
            result = verify_provenance_record(
                args.verify_record, args.distribution, args.binary, args.repo_root
            )
        else:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=args.repo_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            record, record_path = materialize_record(
                args.distribution,
                args.binary,
                repo_root=args.repo_root,
                implementation_commit=commit,
                output_root=args.output_root,
            )
            result = verify_provenance_record(
                record_path, args.distribution, args.binary, args.repo_root
            )
            result["record_path"] = str(record_path)
            result["classification"] = cast(dict[str, object], record["identity_comparison"])[
                "classification"
            ]
        print(json.dumps(result, sort_keys=True, indent=2))
    except (OSError, ProvenanceError, subprocess.SubprocessError) as error:
        print(f"provenance verification failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
