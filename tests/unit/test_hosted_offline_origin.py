"""Manager observation semantics; fixtures never substitute for native/live origins."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import HostedManagerExportFile, HostedQualificationCase
from quantos.infrastructure.hosted_deployment import (
    MOUNT_POLICY_BYTES,
    HostedNamespacePaths,
    namespace_command,
)
from quantos.infrastructure.hosted_offline_verification import verify_offline_manager_run
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


@pytest.mark.parametrize("mode", ["RECEIPT_REUSE", "REEXECUTE"])
@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "prelaunch",
        "prelaunch_binding",
        "return_bool",
        "return_failed",
        "source",
        "source_alias",
        "source_traversal",
        "protocol",
        "before",
        "argv_network",
        "argv_program",
        "descriptor",
        "program",
        "observation",
        "counts",
        "missing_record",
    ],
)
def test_offline_original_capture_and_fixed_launch_are_cross_bound(
    tmp_path: Path, mode: str, mutation: str | None
) -> None:
    manager, bundle = tmp_path / "manager", tmp_path / "bundle"
    original = manager / "authority" if mode == "RECEIPT_REUSE" else manager / "replay/a/authority"
    paths = HostedNamespacePaths(
        **{
            name: manager / name
            for name in (
                "install",
                "projection",
                "channel",
                "authority",
                "configuration",
                "provenance",
                "offline_inputs",
            )
        }
    )
    source = manager / "saved-source"
    for base in (source / "protocol", paths.authority / "protocol"):
        base.mkdir(parents=True, exist_ok=True)
        (base / "object.json").write_bytes(b"frozen protocol")
    source_inventory = raw_inventory(source)
    original.mkdir(parents=True, exist_ok=True)
    if mode == "REEXECUTE":
        (original / "saved-protocol").mkdir()
        (original / "saved-protocol/object.json").write_bytes(b"frozen protocol")
    before = raw_inventory(original)
    calls = [] if mode == "RECEIPT_REUSE" else ["a" * 64, "b" * 64]
    observation = {
        "schema_version": "hosted-offline-observation/v1",
        "mode": mode,
        "deployment_profile_hash": "d" * 64,
        "campaign_hash": "c" * 64,
        "report_hash": "e" * 64,
        "python_executable": "/install/python-seeded",
        "python_hash_seed_environment": "0",
        "network_attempts": [],
        "python_flags": {
            "isolated": 1,
            "ignore_environment": 1,
            "no_user_site": 1,
            "safe_path": True,
            "hash_randomization": 0,
        },
        "numeric_environment": {
            name: "1"
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "execute_calls": calls,
        "workflow_calls": calls,
        "model_source_inventory_hash": source_inventory.content_hash,
        "source_inventory_hash": raw_inventory(source / "protocol").content_hash,
    }
    if mutation == "counts":
        observation["workflow_calls"] = ["b" * 64]
    encoded_observation = canonical_json_bytes(observation)
    atomic_write_bytes(original / "offline-observation.json", encoded_observation)
    argv = list(
        namespace_command(
            "service",
            paths
            if mode == "RECEIPT_REUSE"
            else HostedNamespacePaths(
                paths.install,
                paths.projection,
                original.parent / "channel",
                original,
                paths.configuration,
                paths.provenance,
                paths.offline_inputs,
            ),
            (
                "/install/python-seeded",
                "-m",
                "quantos.infrastructure.hosted_offline",
                "--profile-hash",
                "d" * 64,
                "--mode",
                mode,
                "--source-inventory-hash",
                source_inventory.content_hash,
            ),
            service_capability_fds=(44,),
            offline_source_root=source,
        )
    )
    if mutation == "argv_network":
        argv.insert(1, "--share-net")
    elif mutation == "argv_program":
        argv[argv.index("quantos.infrastructure.hosted_offline")] = "unfrozen.module"
    elif mutation == "descriptor":
        argv[argv.index("--file") + 1] = "0"
    record = {
        "schema_version": "hosted-manager-offline-run/v1",
        "mode": mode,
        "deployment_profile_hash": "d" * 64,
        "campaign_hash": "c" * 64,
        "authority_root": str(original),
        "source_root": str(source),
        "argv": argv,
        "source_inventory": source_inventory.model_dump(mode="json"),
        "authority_before_inventory": before.model_dump(mode="json"),
        "authority_after_inventory": raw_inventory(original).model_dump(mode="json"),
        "return_code": 0,
        "observation_hash": sha256_bytes(encoded_observation),
        "offline_program_hash": "f" * 64,
    }
    if mutation == "return_bool":
        record["return_code"] = False
    elif mutation == "return_failed":
        record["return_code"] = 1
    elif mutation == "source":
        record["source_root"] = str(tmp_path / "outside")
    elif mutation == "source_alias":
        (manager / "alias").symlink_to(source, target_is_directory=True)
        record["source_root"] = str(manager / "alias")
    elif mutation == "source_traversal":
        record["source_root"] = str(manager / ".." / "manager/saved-source")
    elif mutation == "protocol":
        (paths.authority / "protocol/object.json").write_bytes(b"different protocol")
    elif mutation == "before":
        record["authority_before_inventory"] = {"files": []}
    elif mutation == "program":
        record["offline_program_hash"] = "a" * 64
    elif mutation == "observation":
        record["observation_hash"] = "a" * 64
    prelaunch = {
        name: record[name]
        for name in (
            "deployment_profile_hash",
            "mode",
            "argv",
            "source_root",
            "authority_root",
            "authority_before_inventory",
        )
    }
    prelaunch.update(
        schema_version="hosted-manager-offline-prelaunch/v1",
        source_inventory_hash=source_inventory.content_hash,
    )
    if mutation == "prelaunch_binding":
        prelaunch["mode"] = "WRONG"
    prelaunch_bytes = canonical_json_bytes(prelaunch)
    prelaunch_hash = sha256_bytes(prelaunch_bytes)
    record["prelaunch_hash"] = prelaunch_hash
    records = {}
    encoded_record = canonical_json_bytes(record)
    for name, data, relative in (
        ("prelaunch", prelaunch_bytes, f"evidence/offline-prelaunch-{prelaunch_hash}.json"),
        ("run", encoded_record, f"evidence/offline-run-{sha256_bytes(encoded_record)}.json"),
    ):
        atomic_write_bytes(manager / relative, data)
        logical = f"cases/Q09/{name}.json"
        atomic_write_bytes(bundle / logical, data)
        records[logical] = HostedManagerExportFile(
            bundle_path=logical,
            source_path=relative,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
        )
    if mutation == "prelaunch":
        records.pop("cases/Q09/prelaunch.json")
    elif mutation == "missing_record":
        records.pop("cases/Q09/run.json")
    deployment = SimpleNamespace(
        root=manager,
        paths=paths,
        profile=SimpleNamespace(
            content_hash="d" * 64, mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES)
        ),
        install=SimpleNamespace(
            files=(
                SimpleNamespace(
                    relative_path="python/lib/python3.11/site-packages/quantos/infrastructure/hosted_offline.py",
                    bytes_hash="f" * 64,
                ),
            )
        ),
    )
    sources = HostedVerifiedSources(deployment, records, "0" * 64)
    case = HostedQualificationCase(case_id="Q09", evidence_paths=tuple(sorted(records)))
    facts = SimpleNamespace(
        report=SimpleNamespace(campaign_hash="c" * 64, content_hash="e" * 64),
        execution_identities=("a" * 64, "b" * 64),
    )

    def action() -> tuple[str, ...]:
        return verify_offline_manager_run(
            bundle,
            case,
            sources,
            authority=original,
            original_authority=original,
            mode=mode,
            facts=facts,
        )

    if mutation is None:
        assert len(action()) == 5
    else:
        with pytest.raises((HostedQualificationError, ArtifactIntegrityError, OSError, ValueError)):
            action()
