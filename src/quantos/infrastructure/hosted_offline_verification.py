"""Read-only predicates for manager-invoked native offline runs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedRawInventory
from quantos.infrastructure.hosted_business_verification import HostedVerifiedBusiness
from quantos.infrastructure.hosted_deployment import namespace_command
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HostedQualificationError(message)


def verify_offline_observation(
    data: bytes,
    *,
    mode: str,
    sources: HostedVerifiedSources,
    facts: HostedVerifiedBusiness,
) -> dict[str, object]:
    """Check program-observed counts/environment after original-source binding."""
    observation = strict_json_object(data, max_bytes=65536)
    _require(
        observation.get("schema_version") == "hosted-offline-observation/v1"
        and observation.get("mode") == mode
        and observation.get("deployment_profile_hash") == sources.deployment.profile.content_hash
        and observation.get("campaign_hash") == facts.report.campaign_hash
        and observation.get("report_hash") == facts.report.content_hash
        and observation.get("python_executable") == "/install/python-seeded"
        and observation.get("python_hash_seed_environment") == "0"
        and observation.get("network_attempts") == [],
        "offline native observation bindings/network differ",
    )
    expected_flags: dict[str, object] = {
        "isolated": 1,
        "ignore_environment": 1,
        "no_user_site": 1,
        "safe_path": True,
        "hash_randomization": 0,
    }
    flags = observation.get("python_flags")
    _require(isinstance(flags, dict), "offline Python initialization is absent")
    actual_flags = cast(dict[str, object], flags)
    _require(
        actual_flags == expected_flags
        and all(
            type(actual_flags[name]) is type(expected) for name, expected in expected_flags.items()
        )
        and observation.get("numeric_environment")
        == {
            name: "1"
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "offline Python seed/numeric environment differs",
    )
    for name in ("execute_calls", "workflow_calls"):
        calls = observation.get(name)
        _require(isinstance(calls, list), "offline native call count is absent")
        values = cast(list[object], calls)
        _require(
            all(isinstance(value, str) for value in values), "offline native call identities differ"
        )
        identities = cast(list[str], values)
        if mode == "RECEIPT_REUSE":
            _require(not identities, "receipt reuse invoked native execution")
        else:
            _require(
                tuple(sorted(identities)) == facts.execution_identities
                and len(set(identities)) == len(identities)
                and bool(identities),
                "fresh root did not run one pipeline per verified execution",
            )
    return observation


def verify_offline_manager_run(
    bundle: Path,
    case: HostedQualificationCase,
    sources: HostedVerifiedSources,
    *,
    authority: Path,
    original_authority: Path,
    mode: str,
    facts: HostedVerifiedBusiness,
) -> tuple[str, ...]:
    """Bind observations to the original fixed manager invocation and source inventory."""
    matches: list[tuple[bytes, dict[str, object]]] = []
    for path in case.evidence_paths:
        mapping = sources.files[path]
        if not mapping.source_path.startswith("evidence/offline-run-"):
            continue
        encoded = read_relative(bundle, path)
        fact = strict_json_object(encoded, max_bytes=16_777_216)
        if fact.get("schema_version") == "hosted-manager-offline-run/v1" and fact.get(
            "authority_root"
        ) == str(original_authority):
            matches.append((encoded, fact))
    _require(len(matches) == 1, "offline original manager invocation is missing or ambiguous")
    encoded, record = matches[0]
    deployment = sources.deployment
    prelaunch_hash = record.get("prelaunch_hash")
    _require(
        isinstance(prelaunch_hash, str)
        and len(prelaunch_hash) == 64
        and all(character in "0123456789abcdef" for character in prelaunch_hash),
        "offline durable prelaunch identity is absent",
    )
    prelaunch_path = f"evidence/offline-prelaunch-{prelaunch_hash}.json"
    _require(
        any(sources.files[path].source_path == prelaunch_path for path in case.evidence_paths),
        "offline original prelaunch was not exported",
    )
    prelaunch_bytes = read_relative(deployment.root, prelaunch_path)
    _require(
        sha256_bytes(prelaunch_bytes) == prelaunch_hash, "offline original prelaunch bytes differ"
    )
    prelaunch = strict_json_object(prelaunch_bytes, max_bytes=16_777_216)
    _require(
        prelaunch.get("schema_version") == "hosted-manager-offline-prelaunch/v1"
        and all(
            prelaunch.get(name) == record.get(name)
            for name in (
                "deployment_profile_hash",
                "mode",
                "argv",
                "source_root",
                "authority_root",
                "authority_before_inventory",
            )
        ),
        "offline completion differs from its durable prelaunch",
    )
    _require(
        record.get("mode") == mode
        and record.get("deployment_profile_hash") == deployment.profile.content_hash
        and record.get("campaign_hash") == facts.report.campaign_hash
        and type(record.get("return_code")) is int
        and record.get("return_code") == 0,
        "offline manager invocation failed or differs",
    )
    source_value = record.get("source_root")
    _require(isinstance(source_value, str), "offline original source root is absent")
    source = Path(cast(str, source_value))
    _require(
        source.is_absolute() and source.is_relative_to(deployment.root),
        "offline source escaped original manager root",
    )
    source_inventory = HostedRawInventory.model_validate(record["source_inventory"])
    _require(
        prelaunch.get("source_inventory_hash") == source_inventory.content_hash,
        "offline prelaunch source inventory differs",
    )
    verify_raw_inventory(source, source_inventory)
    _require(
        raw_inventory(source / "protocol")
        == raw_inventory(deployment.paths.authority / "protocol"),
        "offline source protocol differs from original live protocol",
    )
    before = HostedRawInventory.model_validate(record["authority_before_inventory"])
    after = HostedRawInventory.model_validate(record["authority_after_inventory"])
    verify_raw_inventory(authority, after)
    if mode == "REEXECUTE":
        imported = HostedRawInventory(
            files=tuple(
                item.model_copy(update={"logical_path": "saved-protocol/" + item.logical_path})
                for item in raw_inventory(source / "protocol").files
            )
        )
        _require(
            bool(before.files) and before == imported,
            "fresh root contained prior business results",
        )
        paths = replace(
            deployment.paths,
            authority=original_authority,
            channel=original_authority.parent / "channel",
        )
        _require(
            original_authority != deployment.paths.authority, "fresh root reused live authority"
        )
    else:
        _require(
            original_authority == deployment.paths.authority,
            "receipt reuse did not use original native receipts",
        )
        paths = deployment.paths
        _require(
            tuple(item for item in before.files if item.logical_path != "offline-observation.json")
            == tuple(
                item for item in after.files if item.logical_path != "offline-observation.json"
            ),
            "receipt reuse changed original native authority",
        )
    argv_value = record.get("argv")
    _require(
        isinstance(argv_value, list)
        and all(isinstance(value, str) for value in cast(list[object], argv_value)),
        "offline actual argv is absent",
    )
    argv = tuple(cast(list[str], argv_value))
    destination = "/tmp/hosted-service-capability-0"
    _require(argv.count(destination) == 1, "offline private descriptor differs")
    index = argv.index(destination)
    _require(
        index > 1 and argv[index - 2] == "--file", "offline descriptor was not private staged data"
    )
    descriptor = int(argv[index - 1])
    _require(descriptor >= 3, "offline private descriptor is invalid")
    command = (
        "/install/python-seeded",
        "-m",
        "quantos.infrastructure.hosted_offline",
        "--profile-hash",
        deployment.profile.content_hash,
        "--mode",
        mode,
        "--source-inventory-hash",
        source_inventory.content_hash,
    )
    _require(
        argv
        == namespace_command(
            "service",
            paths,
            command,
            service_capability_fds=(descriptor,),
            offline_source_root=source,
        ),
        "offline invocation differs from fixed network-isolated program",
    )
    program_path = "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_offline.py"
    program_hash = next(
        item.bytes_hash for item in deployment.install.files if item.relative_path == program_path
    )
    _require(
        record.get("offline_program_hash") == program_hash,
        "offline program differs from frozen installation",
    )
    observation_bytes = read_relative(authority, "offline-observation.json", max_bytes=65536)
    _require(
        sha256_bytes(observation_bytes) == record.get("observation_hash"),
        "offline observation differs from original manager capture",
    )
    observation = verify_offline_observation(
        observation_bytes, mode=mode, sources=sources, facts=facts
    )
    _require(
        observation.get("model_source_inventory_hash") == source_inventory.content_hash
        and observation.get("source_inventory_hash")
        == raw_inventory(source / "protocol").content_hash,
        "offline saved proposal/protocol source inventory differs",
    )
    return tuple(
        sorted(
            (
                sha256_bytes(encoded),
                sha256_bytes(observation_bytes),
                program_hash,
                source_inventory.content_hash,
                sha256_bytes(prelaunch_bytes),
            )
        )
    )
