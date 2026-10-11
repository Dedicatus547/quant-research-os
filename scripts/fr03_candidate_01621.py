#!/usr/bin/env python3
"""Prepare one fixed SDK candidate or perform its single account/read preflight."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import signal
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from quantos.artifacts.store import atomic_write_bytes, exclusive_directory_lock  # noqa: E402
from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.infrastructure.hosted_storage import (  # noqa: E402
    StorageGuard,
    StorageRejected,
    configured_guard,
    supervise_storage_job,
)

VERSION = "0.162.1"
SDK_FILENAME = "openai_codex-0.162.1-py3-none-any.whl"
SDK_DIGEST = "ebb2254a7ae97432eda6c2fe9b48b5b7f2c59c6e1ea25686a45ceca11ddec4b2"
CLI_FILENAME = "openai_codex_cli_bin-0.162.1-py3-none-manylinux_2_17_x86_64.whl"
CLI_DIGEST = "b087e5e0b2285309a56336ca0c2375105bf56ffacf00b4efec7fbd7c22b51f7b"
PUBLISHING_COMMIT = "52950c592404f11cc245a83a27fb02f2c23bc0c1"


class _ProvenanceVerifier(Protocol):
    WHEEL_FILENAME: str
    RECORD_VERSION: str

    def _safe_wheel_members(self, archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]: ...

    def _record_entries(
        self, archive: zipfile.ZipFile, members: Mapping[str, zipfile.ZipInfo]
    ) -> dict[str, tuple[str, str]]: ...

    def verify_distribution_and_binary(
        self, distribution_path: Path, binary_path: Path, *, expected_distribution_sha256: str
    ) -> dict[str, object]: ...


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("metadata object is invalid")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("metadata list is invalid")
    return cast(list[object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("metadata string is invalid")
    return value


def publish(root: Path, name: str, value: object) -> None:
    atomic_write_bytes(root / name, canonical_json_bytes(value))


def require_supervised_budget(root: Path, expected_new_bytes: int = 1_073_741_824) -> None:
    """Direct entry points retain the current job budget and live global lease."""
    guard = configured_guard()
    guard.require_root(root)
    guard.require_lease()
    guard.check(expected_new_bytes)


def get_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("metadata byte bound exceeded")
    return _object(json.loads(raw))


def fetch_wheel(root: Path, package: str, filename: str, digest: str) -> Path:
    metadata_url = f"https://pypi.org/pypi/{package}/{VERSION}/json"
    metadata = get_json(metadata_url)
    files = [_object(item) for item in _list(metadata.get("urls"))]
    matches = [item for item in files if item.get("filename") == filename]
    if len(matches) != 1 or _object(matches[0].get("digests")).get("sha256") != digest:
        raise ValueError("official wheel metadata identity mismatch")
    entry = matches[0]
    publish(
        root,
        f"vendor/{package}-metadata.json",
        {
            "url": metadata_url,
            "version": VERSION,
            "file": entry,
            "requires_dist": _object(metadata.get("info")).get("requires_dist"),
        },
    )
    provenance_url = f"https://pypi.org/integrity/{package}/{VERSION}/{filename}/provenance"
    provenance = get_json(provenance_url)
    publish(root, f"vendor/{package}-publishing-provenance.json", provenance)
    # Retain PyPI's publishing statement without claiming independent Sigstore verification.
    bound = False
    for raw_bundle in _list(provenance.get("attestation_bundles", [])):
        bundle = _object(raw_bundle)
        publisher = _object(bundle.get("publisher", {}))
        if (
            publisher.get("repository") != "openai/codex"
            or publisher.get("workflow") != "python-sdk-cli-release.yml"
        ):
            continue
        for raw_attestation in _list(bundle.get("attestations", [])):
            attestation = _object(raw_attestation)
            statement = _object(
                json.loads(base64.b64decode(_string(_object(attestation["envelope"])["statement"])))
            )
            certificate = base64.b64decode(
                _string(_object(attestation["verification_material"])["certificate"])
            )
            if (
                statement.get("subject") == [{"name": filename, "digest": {"sha256": digest}}]
                and PUBLISHING_COMMIT.encode() in certificate
            ):
                bound = True
    if not bound:
        raise ValueError(
            "publishing provenance does not bind the expected artifact and publisher commit"
        )
    path = root / "vendor" / filename
    if path.exists():
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("retained wheel digest mismatch")
        return path
    url = entry["url"]
    if not isinstance(url, str) or not url.startswith("https://files.pythonhosted.org/"):
        raise ValueError("official wheel download URL is invalid")
    temporary = path.with_suffix(".download")
    if temporary.exists():
        raise ValueError("unfinished download requires explicit recovery")
    hasher = hashlib.sha256()
    count = 0
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("xb") as stream:
        while chunk := response.read(1_048_576):
            count += len(chunk)
            if count > 160_000_000:
                raise ValueError("wheel download byte bound exceeded")
            hasher.update(chunk)
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    if hasher.hexdigest() != digest or count != entry["size"]:
        raise ValueError("wheel download digest or size mismatch")
    os.link(temporary, path)
    temporary.unlink()
    descriptor = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def prepare(root: Path) -> None:
    require_supervised_budget(root)
    sdk = fetch_wheel(root, "openai-codex", SDK_FILENAME, SDK_DIGEST)
    cli = fetch_wheel(root, "openai-codex-cli-bin", CLI_FILENAME, CLI_DIGEST)
    overlay = root / "overlay"
    overlay.mkdir(exist_ok=True)
    spec = importlib.util.spec_from_file_location(
        "candidate_provenance", REPO / "scripts/verify_codex_runtime_identity_provenance.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verifier = cast(_ProvenanceVerifier, cast(object, module))
    # Parameterize the retained mechanical verifier in this private module instance only.
    verifier.WHEEL_FILENAME = CLI_FILENAME
    verifier.RECORD_VERSION = "openai_codex_cli_bin-0.162.1.dist-info/RECORD"
    for wheel in (sdk, cli):
        with zipfile.ZipFile(wheel) as archive:
            # Reuse these exact historical predicates in a private module instance.
            members = verifier._safe_wheel_members(archive)  # pyright: ignore[reportPrivateUsage]
            if wheel == sdk:
                verifier.RECORD_VERSION = "openai_codex-0.162.1.dist-info/RECORD"
                verifier._record_entries(archive, members)  # pyright: ignore[reportPrivateUsage]
                verifier.RECORD_VERSION = "openai_codex_cli_bin-0.162.1.dist-info/RECORD"
            for name, info in members.items():
                target = overlay / name
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ValueError("candidate overlay already contains a member")
                with archive.open(info) as source, target.open("xb") as destination:
                    while chunk := source.read(1_048_576):
                        destination.write(chunk)
                    destination.flush()
                    os.fsync(destination.fileno())
                os.chmod(target, stat.S_IMODE(info.external_attr >> 16) or 0o644)
    binary = overlay / "codex_cli_bin/bin/codex"
    identity = verifier.verify_distribution_and_binary(
        cli, binary, expected_distribution_sha256=CLI_DIGEST
    )
    sdk_metadata = (overlay / "openai_codex-0.162.1.dist-info/METADATA").read_text()
    if "openai-codex-cli-bin==0.162.1" not in sdk_metadata:
        raise ValueError("SDK wheel does not bind the selected runtime")
    publish(
        root,
        "candidate-provenance.json",
        {
            "schema_version": "fr03-codex-01621-preparation/v1",
            "sdk_version": VERSION,
            "sdk_wheel_sha256": SDK_DIGEST,
            "runtime_version": VERSION,
            "runtime": identity,
            "publishing_commit": PUBLISHING_COMMIT,
            "publishing_attestation_status": (
                "PYPI_PUBLISHER_METADATA_BOUND_NOT_INDEPENDENT_SIGSTORE_VERIFICATION"
            ),
            "historical_verifier_source_sha256": sha256_bytes(
                (REPO / "scripts/verify_codex_runtime_identity_provenance.py").read_bytes()
            ),
            "canonical_pin_changed": False,
            "model_provider_or_account_endpoint_used": False,
            "p10_result": "NOT_EVALUATED",
            "qualification": "NOT_QUALIFIED",
        },
    )


def preflight(root: Path, authentication_home: Path, expected_new_bytes: int) -> int:
    require_supervised_budget(root, expected_new_bytes)
    if not (root / "candidate-provenance.json").is_file():
        raise ValueError("candidate provenance must precede preflight")
    with exclusive_directory_lock(root):
        reservation = root / "account-read-reservation.json"
        if reservation.exists():
            raise ValueError("account/read allowance already consumed")
        publish(
            root,
            reservation.name,
            {
                "schema_version": "fr03-candidate-preflight-reservation/v1",
                "ordinal": 1,
                "candidate_provenance_hash": sha256_bytes(
                    (root / "candidate-provenance.json").read_bytes()
                ),
                "started_ns": time.time_ns(),
                "max_account_read_invocations": 1,
                "max_model_turns": 0,
            },
        )
    isolated_home = root / "isolated-codex-home"
    isolated_home.mkdir(mode=0o700)
    auth = authentication_home / "auth.json"
    if not auth.is_file():
        raise ValueError("existing authentication is unavailable")
    (isolated_home / "auth.json").symlink_to(auth)
    os.environ["CODEX_HOME"] = str(isolated_home)
    sys.path.insert(0, str(root / "overlay"))
    from codex_cli_bin import bundled_codex_path  # pyright: ignore[reportMissingTypeStubs]
    from openai_codex import Codex, CodexConfig

    started = time.monotonic()
    report: dict[str, object] = {
        "schema_version": "fr03-candidate-account-read/v1",
        "candidate_version": VERSION,
        "initialize_status": "NOT_EVALUATED",
        "account_read_status": "NOT_EVALUATED",
        "account_read_invocations": 0,
        "thread_start_count": 0,
        "turn_start_count": 0,
        "p10_result": "NOT_EVALUATED",
        "fr03_status": "NO_GO",
        "canonical_pin_changed": False,
        "expected_new_bytes": expected_new_bytes,
    }
    code = 1

    def timeout(signum: int, frame: object) -> None:
        raise TimeoutError("bounded account/read preflight deadline exceeded")

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(90)
    try:
        import openai_codex

        if openai_codex.__version__ != VERSION:
            raise ValueError("SDK identity mismatch")
        binary = Path(bundled_codex_path())
        expected = json.loads((root / "candidate-provenance.json").read_bytes())["runtime"][
            "binary_sha256_hashlib"
        ]
        with binary.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("runtime identity mismatch")
        with Codex(
            CodexConfig(
                cwd=str(REPO), env={"CODEX_HOME": str(isolated_home), "PATH": "/usr/bin:/bin"}
            )
        ) as codex:
            report["initialize_status"] = "PASS"
            server_info = codex.metadata.serverInfo
            if (
                server_info is None
                or server_info.version is None
                or server_info.version.partition(" ")[0] != VERSION
            ):
                raise ValueError("reported runtime version mismatch")
            report["account_read_invocations"] = 1
            account = codex.account(refresh_token=False)
            if account.account is None:
                raise ValueError("existing authentication was not available to candidate")
            report["account_read_status"] = "PASS"
            code = 0
    except Exception as error:
        report["account_read_status"] = (
            "FAILED" if report["account_read_invocations"] else "NOT_EVALUATED"
        )
        report["failure_type"] = type(error).__name__
        report["failure_message_sha256"] = sha256_bytes(str(error).encode("utf-8"))
    finally:
        signal.alarm(0)
    report["elapsed_seconds"] = time.monotonic() - started
    report["return_code"] = code
    publish(root, "account-read-report.json", report)
    return code


def supervise_reused_pool(root: Path, authentication_home: Path, scratch_root: Path) -> int:
    """One standalone metadata/account job, using an existing finite scratch mount."""
    base = configured_guard()
    base.require_root(root)
    policy = replace(base.policy, scratch_root=scratch_root.resolve(), scratch_quota_bytes=64 << 20)
    guard = StorageGuard(policy)
    facts = guard.check(32 << 20)
    if facts["scratch_available_bytes"] < 8 << 20:
        raise ValueError("standalone preflight scratch headroom is unavailable")
    auth = authentication_home.resolve() / "auth.json"
    if not auth.is_file() or auth.is_symlink():
        raise ValueError("existing read-only authentication source is unavailable")
    publish(root, "standalone-preflight-policy.json", json.loads(policy.canonical_bytes()))
    publish(
        root,
        f"standalone-preflight-budget-{time.time_ns()}.json",
        {
            "schema_version": "fr03-standalone-preflight-budget/v1",
            "expected_new_bytes": 32 << 20,
            "expected_scratch_growth_bytes": 4 << 20,
            "scratch_minimum_available_bytes": 8 << 20,
            "scratch_quota_bytes": 64 << 20,
            "initial_capacity": facts,
            "max_account_read_invocations": 1,
            "max_thread_starts": 0,
            "max_model_turns": 0,
            "timeout_seconds": 90,
            "noswap_required_by_frozen_storage_contract": False,
            "authentication_access": "READ_ONLY_BIND_ORIGINAL_NO_COPY",
            "policy_hash": guard.policy_hash,
        },
    )
    try:
        run = supervise_storage_job(
            guard,
            (
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--mode",
                "bounded-preflight",
                "--output-root",
                str(root),
                "--authentication-home",
                str(authentication_home),
                "--expected-new-bytes",
                str(32 << 20),
            ),
            stage="deployment",
            expected_new_bytes=32 << 20,
        )
    except StorageRejected:
        owner = _object(
            json.loads((policy.evidence_root / "storage-control/lease.lock").read_bytes())
        )
        run = Path(_string(owner["run"]))
        if run.parent != policy.evidence_root / "storage-control":
            raise ValueError("standalone guard exit source is unbound") from None
    exit_fact = _object(json.loads((run / "exit.json").read_bytes()))
    publish(
        root,
        f"standalone-preflight-exit-{run.name}.json",
        {
            "schema_version": "fr03-standalone-preflight-exit/v1",
            "guard_run": str(run),
            "guard_exit_hash": sha256_bytes((run / "exit.json").read_bytes()),
            "actual_exit": exit_fact,
            "qualification": "NOT_QUALIFIED",
        },
    )
    return 0 if exit_fact.get("return_code") == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=(
            "prepare",
            "preflight",
            "supervise-preflight",
            "supervise-reused-pool",
            "bounded-preflight",
        ),
        required=True,
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--authentication-home", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument(
        "--expected-new-bytes", type=int, choices=(32 << 20, 1 << 30), default=1 << 30
    )
    args = parser.parse_args()
    if args.mode == "supervise-reused-pool":
        if args.authentication_home is None or args.scratch_root is None:
            parser.error(
                "standalone supervision needs authentication and an existing scratch mount"
            )
        return supervise_reused_pool(
            args.output_root.resolve(), args.authentication_home, args.scratch_root
        )
    if args.mode == "bounded-preflight":
        if args.authentication_home is None:
            parser.error("bounded preflight needs authentication")
        guard = configured_guard()
        require_supervised_budget(args.output_root, args.expected_new_bytes)
        auth = args.authentication_home.resolve() / "auth.json"
        result = subprocess.run(
            (
                "/usr/bin/bwrap",
                "--unshare-pid",
                "--die-with-parent",
                "--new-session",
                "--ro-bind",
                "/",
                "/",
                "--dev-bind",
                "/dev",
                "/dev",
                "--bind",
                str(args.output_root),
                str(args.output_root),
                "--bind",
                str(guard.policy.scratch_root),
                str(guard.policy.scratch_root),
                "--bind",
                str(guard.policy.scratch_root),
                "/tmp",
                "--ro-bind",
                str(auth),
                str(auth),
                "--bind",
                str(guard.policy.evidence_root / "storage-control/lease.lock"),
                str(guard.policy.evidence_root / "storage-control/lease.lock"),
                "--proc",
                "/proc",
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--mode",
                "preflight",
                "--output-root",
                str(args.output_root),
                "--authentication-home",
                str(args.authentication_home),
                "--expected-new-bytes",
                str(args.expected_new_bytes),
            ),
            capture_output=True,
            timeout=110,
        )
        ordinal = len(tuple(args.output_root.glob("bounded-preflight-namespace-exit*.json"))) + 1
        publish(
            args.output_root,
            f"bounded-preflight-namespace-exit-{ordinal:02d}.json",
            {
                "schema_version": "fr03-bounded-preflight-namespace-exit/v1",
                "return_code": result.returncode,
                "stdout_bytes": len(result.stdout),
                "stdout_sha256": sha256_bytes(result.stdout),
                "stderr_bytes": len(result.stderr),
                "stderr_sha256": sha256_bytes(result.stderr),
                "read_only_filesystem_failure_observed": b"Read-only file system" in result.stderr,
                "storage_lease_failure_observed": b"STORAGE_SUPERVISOR" in result.stderr,
            },
        )
        return result.returncode
    if args.mode == "supervise-preflight":
        if args.scratch_root is None or args.authentication_home is None:
            parser.error(
                "supervised preflight needs exact scratch and existing authentication roots"
            )
        # noswap is set on the initial tmpfs mount; it cannot be enabled by remount.
        subprocess.run(["/usr/bin/umount", str(args.scratch_root)], check=True, capture_output=True)
        mounted = subprocess.run(
            [
                "/usr/bin/mount",
                "-t",
                "tmpfs",
                "-o",
                "size=536870912,nr_inodes=32768,noswap,nosuid,nodev,mode=700",
                "quantos-fr03-private-scratch",
                str(args.scratch_root),
            ],
            capture_output=True,
        )
        if mounted.returncode != 0:
            publish(
                args.output_root,
                "private-scratch-initial-mount-failure.json",
                {
                    "schema_version": "fr03-private-scratch/v1",
                    "return_code": mounted.returncode,
                    "stderr_sha256": sha256_bytes(mounted.stderr),
                    "live_started": False,
                },
            )
            return 1
        layout = subprocess.run(
            [
                "/usr/bin/findmnt",
                "-b",
                "-J",
                "-o",
                "TARGET,FSTYPE,OPTIONS,SIZE",
                str(args.scratch_root),
            ],
            check=True,
            capture_output=True,
        )
        observation = json.loads(layout.stdout)
        mounts = observation["filesystems"]
        if (
            len(mounts) != 1
            or "noswap" not in mounts[0]["options"]
            or int(mounts[0]["size"]) != 536870912
        ):
            raise ValueError("private scratch quota or noswap binding mismatch")
        publish(
            args.output_root,
            "private-scratch-observation.json",
            {
                "schema_version": "fr03-private-scratch/v1",
                "layout": observation,
                "memory_reservation_bytes": 536870912,
                "host_job_reservation_bytes": 1073741824,
                "namespace_lifetime": "OUTER_BWRAP_LIFETIME",
                "qualification": "NOT_QUALIFIED",
            },
        )
        guard = configured_guard()
        guard.check(1073741824)
        supervise_storage_job(
            guard,
            (
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--mode",
                "preflight",
                "--output-root",
                str(args.output_root),
                "--authentication-home",
                str(args.authentication_home),
            ),
            stage="deployment",
            expected_new_bytes=1073741824,
        )
        return 0
    guard = configured_guard()
    root = args.output_root.resolve()
    require_supervised_budget(root, args.expected_new_bytes)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.mode == "preflight" and args.authentication_home is None:
        parser.error("preflight requires existing authentication home")
    try:
        if args.mode == "prepare":
            prepare(root)
            return 0
        return preflight(root, args.authentication_home, args.expected_new_bytes)
    except Exception as error:
        publish(
            root,
            f"{args.mode}-failure.json",
            {
                "schema_version": "fr03-candidate-stage-failure/v1",
                "stage": args.mode,
                "failure_type": type(error).__name__,
                "message_sha256": sha256_bytes(str(error).encode()),
                "return_code": 1,
                "p10_result": "NOT_EVALUATED",
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
