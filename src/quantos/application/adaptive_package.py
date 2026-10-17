"""Local retained-environment package controls; preparation never grants live authority."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quantos.application.adaptive_store import read, save
from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_storage import StorageGuard, StoragePolicy, require_bounded_bwrap


def verified_package(package: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(read(package / "release-manifest.json"))
    proposal = json.loads(read(package / "proposed-combination.json"))
    if sha256_bytes(read(package / "proposed-combination.json")) != manifest["proposal_sha256"]:
        raise ArtifactIntegrityError("package proposal differs")
    if socket.gethostname() != manifest["host"] or os.getuid() != manifest["uid"]:
        raise ArtifactIntegrityError("package host differs")
    verify_code_provenance(
        Path(manifest["workspace"]),
        expected_commit_hash=manifest["commit"],
        expected_lockfile_hash=manifest["lockfile_sha256"],
    )
    for pin in manifest["pins"]:
        if sha256_file(Path(pin["path"])) != pin["sha256"]:
            raise ArtifactIntegrityError("package pinned original differs")
    import quantos

    if Path(quantos.__file__).parent != Path(manifest["workspace"]) / "src/quantos":
        raise ArtifactIntegrityError("package source import differs")
    from importlib.metadata import version

    for name, expected in manifest["distribution_versions"].items():
        if version(name) != expected:
            raise ArtifactIntegrityError("package retained environment differs")
    return manifest, proposal


def package_main(package: Path, argv: list[str]) -> int:
    mode = argv[0] if argv else "--describe"
    if mode == "--describe":
        print(read(package / "proposed-combination.json").decode())
        return 0
    manifest, proposal = verified_package(package)
    if mode == "--verify":
        print(
            json.dumps(
                {
                    "status": "OFFLINE_PINS_VERIFIED",
                    "pins": len(manifest["pins"]),
                    "commit": manifest["commit"],
                    "model_calls": 0,
                    "scientific_executions": 0,
                }
            )
        )
        return 0
    if mode == "--authorize":
        # Only an operator acting on explicit user approval may invoke this mode.
        # The generated offline package initially contains no authorization record.
        if len(argv) != 2 or not argv[1].strip():
            raise ValueError("authorization requires the actual user approval text")
        now = datetime.now(UTC)
        save(
            package / "authorization.json",
            {
                "schema_version": "adaptive-package-authorization/v1",
                "status": "AUTHORIZED",
                "task_hash": manifest["task_hash"],
                "manifest_sha256": sha256_bytes(read(package / "release-manifest.json")),
                "proposal_sha256": manifest["proposal_sha256"],
                "user_approval": argv[1],
                "approved_at": now,
                "launch_not_after": now + timedelta(hours=24),
                "egress_authorized": True,
                "live_run_authorized": True,
            },
        )
        return 0
    if mode not in {"--run-approved", "--resume-approved", "--reconcile-approved"}:
        raise ValueError("unsupported package operation")
    authority = json.loads(read(package / "authorization.json"))
    now = datetime.now(UTC)
    approved = datetime.fromisoformat(authority["approved_at"])
    expires = datetime.fromisoformat(authority["launch_not_after"])
    if (
        authority["status"] != "AUTHORIZED"
        or authority["task_hash"] != manifest["task_hash"]
        or authority["manifest_sha256"] != sha256_bytes(read(package / "release-manifest.json"))
        or authority["proposal_sha256"] != manifest["proposal_sha256"]
        or authority["egress_authorized"] is not True
        or authority["live_run_authorized"] is not True
        or not authority["user_approval"]
        or approved.tzinfo is None
        or expires.tzinfo is None
        or not approved <= now < expires
        or not timedelta(0) < expires - approved <= timedelta(hours=24)
    ):
        raise ArtifactIntegrityError("exact package authority missing or expired")
    policy = json.loads(read(Path(manifest["storage_policy"]["path"])))
    for name in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
        policy[name] = Path(policy[name])
    capacity = StorageGuard(StoragePolicy(**policy)).check(proposal["resources"]["growth_bytes"])
    require_bounded_bwrap()
    live = Path(manifest["output_root"])
    if mode == "--run-approved":
        (live / "first-launch-claim").mkdir(exist_ok=False)
        seconds = proposal["wall_seconds"]
    else:
        activation = json.loads(read(live / "activation.json"))
        if activation["task_hash"] != manifest["task_hash"]:
            raise ArtifactIntegrityError("recovery activation differs")
        seconds = (
            max(1, int((datetime.fromisoformat(activation["deadline"]) - now).total_seconds()))
            if mode == "--resume-approved"
            else 900
        )
        if mode == "--resume-approved" and datetime.fromisoformat(activation["deadline"]) <= now:
            raise TimeoutError("task deadline cannot be extended")
    prior_operations = tuple((live / "operator").glob("operation-*"))
    if len(prior_operations) >= 3:
        raise ArtifactIntegrityError("one start plus two recovery operations exhausted")
    operation = live / "operator" / f"operation-{len(prior_operations) + 1:04d}"
    operation.mkdir(parents=True, exist_ok=False)
    command = [
        manifest["python"],
        "-B",
        str(Path(manifest["workspace"]) / "scripts/adaptive_research.py"),
        "reconcile" if mode == "--reconcile-approved" else "run",
        "--spec",
        manifest["spec_path"],
        "--spec-sha256",
        manifest["task_hash"],
    ]
    if mode != "--reconcile-approved":
        command.append("--approved")
    guard = [
        manifest["python"],
        "-B",
        str(Path(manifest["workspace"]) / "scripts/hosted_storage_guard.py"),
        "--policy",
        manifest["storage_policy"]["path"],
        "--policy-sha256",
        manifest["storage_policy"]["sha256"],
        "--stage",
        "matrix",
        "--expected-new-bytes",
        str(proposal["resources"]["growth_bytes"]),
        "--",
        *command,
    ]
    argv = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "PYTHONPATH",
        manifest["pythonpath"],
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev-bind",
        "/dev",
        "/dev",
    ]
    for path in manifest["readonly_inputs"]:
        argv += ["--ro-bind", path, path]
    argv += ["/usr/bin/timeout", "--signal=TERM", "--kill-after=30s", f"{seconds}s", *guard]
    save(
        operation / "prelaunch.json",
        {
            "schema_version": "adaptive-package-launch/v1",
            "task_hash": manifest["task_hash"],
            "mode": mode,
            "argv": argv,
            "capacity": capacity,
            "authorization_sha256": sha256_bytes(read(package / "authorization.json")),
            "started_at": now,
            "wall_seconds": seconds,
        },
    )
    result = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    save(
        operation / "process-exit.json",
        {
            "schema_version": "adaptive-package-process-exit/v1",
            "actual_exit": result.returncode,
            "observed_by": "PARENT_SUBPROCESS_WAIT",
            "ended_at": datetime.now(UTC),
            "task_hash": manifest["task_hash"],
        },
    )
    return result.returncode
