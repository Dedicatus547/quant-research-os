"""Synthetic origin semantics; these records cannot qualify a real deployment."""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_campaign import _fixture, _response

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedAgentResponse
from quantos.contracts.hosted_qualification import (
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationRoot,
)
from quantos.infrastructure.hosted_deployment import HostedNamespacePaths, namespace_command
from quantos.infrastructure.hosted_negative_origin import CASES, verify_q03
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


def _case(tmp_path: Path, mutation: str | None):
    f = _fixture(tmp_path / "component")
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    response = HostedAgentResponse.model_validate_json(_response(f, request))
    manager = tmp_path / "synthetic-manager"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (manager / "evidence").mkdir(parents=True)
    paths = HostedNamespacePaths(
        *(
            manager / name
            for name in (
                "install",
                "projection",
                "channel",
                "authority",
                "config",
                "provenance",
                "inputs",
            )
        )
    )
    deployment = SimpleNamespace(
        root=manager,
        paths=paths,
        spec=f.spec,
        profile=SimpleNamespace(content_hash="d" * 64),
        bundle=SimpleNamespace(campaign=SimpleNamespace(content_hash=f.spec.campaign_hash)),
        configuration=SimpleNamespace(principals=[SimpleNamespace(uid=1000, gid=1000)]),
        install=SimpleNamespace(
            files=[
                SimpleNamespace(
                    relative_path="python/lib/python3.11/site-packages/quantos/infrastructure/hosted_negative_probe.py",
                    bytes_hash="c" * 64,
                ),
                SimpleNamespace(relative_path="python-seeded", bytes_hash="e" * 64),
            ]
        ),
    )
    records = {}
    roots = []
    evidence = []

    def export(logical: str, source: str, data: bytes):
        output = bundle / logical
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        origin = manager / source
        if not origin.exists():
            origin.parent.mkdir(parents=True, exist_ok=True)
            origin.write_bytes(data)
        records[logical] = HostedManagerExportFile(
            bundle_path=logical, source_path=source, sha256=sha256_bytes(data), size_bytes=len(data)
        )

    for name in CASES:
        target = manager / "qualification-cases/Q03" / name
        authority = target / "authority"
        authority.mkdir(parents=True)
        for directory in ("protocol", "business", "business-locks"):
            if (f.root / directory).exists():
                shutil.copytree(f.root / directory, authority / directory)
        clock = [f.spec.started_at]
        service = HostedProtocolService(
            HostedProtocolStore(authority / "protocol"),
            clock=lambda captured_clock=clock: captured_clock[0],
            verify_inputs=lambda _: None,
        )
        raw = response.canonical_bytes()
        seen = cancellation = None
        if name in ("expired", "cancelled"):
            seen = service.submit(request.content_hash, b"{}", "negative.fixture")
            if name == "cancelled":
                cancellation = service.cancel(request.content_hash, "negative.fixture")
            else:
                clock[0] = request.expires_at
        elif name == "conflict":
            seen = service.submit(request.content_hash, raw, "negative.fixture")
            cancellation = service.cancel(request.content_hash, "negative.fixture")
            raw = canonical_json_bytes({**response.model_dump(mode="json"), "transport_ordinal": 2})
        else:
            raw = canonical_json_bytes(
                {
                    **response.model_dump(mode="json"),
                    name: 2 if name == "transport_ordinal" else "0" * 64,
                }
            )
        before = raw_inventory(authority)
        shutil.copytree(authority, target / "channel/before/authority")
        receipt = service.submit(request.content_hash, raw, "negative.fixture")
        after = raw_inventory(authority)
        observation = {
            "schema_version": "hosted-negative-observation/v1",
            "case": name,
            "deployment_profile_hash": "d" * 64,
            "campaign_hash": f.spec.campaign_hash,
            "request_hash": request.content_hash,
            "receipt_hash": receipt.content_hash,
            "response_json": raw.decode(),
            "before_inventory": before.model_dump(mode="json"),
            "after_inventory": after.model_dump(mode="json"),
            "primary_clock": receipt.recorded_at.isoformat(),
            "repeat_clock": (request.expires_at + timedelta(seconds=1)).isoformat(),
            "repeat_receipt_hash": receipt.content_hash,
            "seen_receipt_hash": seen.content_hash if seen else None,
            "cancellation_receipt_hash": cancellation.content_hash if cancellation else None,
            "fixture_kind": "TRANSPORT_NEGATIVE_FIXTURE",
            "execute_calls": [],
            "workflow_calls": [],
            "network_attempts": [],
            "python_executable": "/install/python-seeded",
            "python_flags": {
                "isolated": 1,
                "ignore_environment": 1,
                "no_user_site": 1,
                "safe_path": True,
                "hash_randomization": 0,
            },
        }
        if name == CASES[0]:
            if mutation == "flags_bool":
                observation["python_flags"]["isolated"] = True
            elif mutation == "network":
                observation["network_attempts"] = ["SOCKET_CONNECT"]
            elif mutation == "repeat":
                observation["repeat_receipt_hash"] = "f" * 64
            elif mutation == "repeat_clock":
                observation["repeat_clock"] = request.issued_at.isoformat()
        observation_bytes = canonical_json_bytes(observation)
        (target / "channel/negative-observation.json").write_bytes(observation_bytes)
        for phase, inventory, origin in (
            ("before", before, target / "channel/before/authority"),
            ("after", after, authority),
        ):
            logical = f"cases/Q03/{name}/{phase}/authority"
            for item in inventory.files:
                export(
                    f"{logical}/{item.logical_path}",
                    (origin / item.logical_path).relative_to(manager).as_posix(),
                    (origin / item.logical_path).read_bytes(),
                )
            inventory_path = f"cases/Q03/{name}/{phase}-inventory.json"
            export(
                inventory_path,
                f"qualification-cases/Q03/{name}/{phase}-inventory.json",
                inventory.canonical_bytes(),
            )
            roots.append(
                HostedQualificationRoot(
                    name=f"{name}-{phase}",
                    logical_path=logical,
                    campaign_hash=f.spec.campaign_hash,
                    raw_inventory_path=inventory_path,
                )
            )
        command = (
            "/install/python-seeded",
            "-m",
            "quantos.infrastructure.hosted_negative_probe",
            "--profile-hash",
            "d" * 64,
            "--case",
            name,
        )
        case_paths = replace(paths, authority=authority, channel=target / "channel")
        argv = namespace_command(
            "service", case_paths, command, service_capability_fds=(17,), info_fd=18
        )
        prelaunch = {
            "schema_version": "hosted-manager-negative-prelaunch/v1",
            "case": name,
            "deployment_profile_hash": "d" * 64,
            "authority_root": str(authority),
            "argv": argv,
            "program_hash": "c" * 64,
            "authority_before_inventory": {
                "schema_version": "hosted-raw-inventory/v1",
                "files": [],
            },
        }
        if name == CASES[0] and mutation == "not_fresh":
            prelaunch["authority_before_inventory"] = before.model_dump(mode="json")
        prelaunch_bytes = canonical_json_bytes(prelaunch)
        run = {
            "schema_version": "hosted-manager-negative-run/v1",
            "case": name,
            "deployment_profile_hash": "d" * 64,
            "campaign_hash": f.spec.campaign_hash,
            "authority_root": str(authority),
            "argv": argv,
            "program_hash": "c" * 64,
            "prelaunch_hash": sha256_bytes(prelaunch_bytes),
            "return_code": 0,
            "observation_failure_type": None,
            "observation_hash": sha256_bytes(observation_bytes),
            "authority_after_inventory": after.model_dump(mode="json"),
            "channel_inventory": raw_inventory(target / "channel").model_dump(mode="json"),
            "manager_namespace_identities": {
                field: f"{field}:[11]" for field in ("net", "pid", "mnt", "user")
            },
            "manager_child_observation": {
                "container_information": {
                    "child-pid": 34,
                    "net-namespace": 22,
                    "pid-namespace": 22,
                    "mnt-namespace": 22,
                },
                "wrapper_pid": 33,
                "init_pid": 34,
                "service_pid": 35,
                "service_command": list(command),
                "service_executable_hash": "e" * 64,
                "service_namespace_identities": {
                    field: f"{field}:[22]" for field in ("net", "pid", "mnt", "user")
                },
                "service_process_security": [
                    "Uid:\t1000 1000 1000 1000",
                    "Gid:\t1000 1000 1000 1000",
                    "CapEff:\t0000000000000000",
                ],
            },
        }
        if name == CASES[0]:
            if mutation == "return_bool":
                run["return_code"] = False
            elif mutation == "bad_program":
                run["program_hash"] = "f" * 64
            elif mutation == "no_kernel":
                run["manager_child_observation"] = None
            elif mutation == "same_namespace":
                run["manager_child_observation"]["service_namespace_identities"] = run[
                    "manager_namespace_identities"
                ]
            elif mutation == "wrong_uid":
                run["manager_child_observation"]["service_process_security"][0] = "Uid:\t0 0 0 0"
            elif mutation == "container_namespace":
                run["manager_child_observation"]["container_information"]["net-namespace"] = 23
            elif mutation == "container_pid":
                run["manager_child_observation"]["container_information"]["child-pid"] = 35
            elif mutation == "missing_manager_namespace":
                del run["manager_namespace_identities"]["net"]
        run_bytes = canonical_json_bytes(run)
        for label, data, source in (
            (
                "observation",
                observation_bytes,
                f"qualification-cases/Q03/{name}/channel/negative-observation.json",
            ),
            (
                "prelaunch",
                prelaunch_bytes,
                f"evidence/negative-prelaunch-{sha256_bytes(prelaunch_bytes)}.json",
            ),
            ("run", run_bytes, f"evidence/negative-run-{sha256_bytes(run_bytes)}.json"),
        ):
            logical = f"cases/Q03/{name}/{label}.json"
            export(logical, source, data)
            evidence.append(logical)
    case = HostedQualificationCase(
        case_id="Q03", roots=tuple(roots), evidence_paths=tuple(sorted(evidence))
    )
    if mutation == "missing_matrix":
        case = case.model_copy(update={"roots": case.roots[:-1]})
    return bundle, case, HostedVerifiedSources(deployment, records, "a" * 64)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "flags_bool",
        "network",
        "container_namespace",
        "container_pid",
        "missing_manager_namespace",
        "repeat",
        "repeat_clock",
        "return_bool",
        "bad_program",
        "no_kernel",
        "same_namespace",
        "wrong_uid",
        "not_fresh",
        "missing_matrix",
    ],
)
def test_q03_requires_complete_original_run_bindings(tmp_path: Path, mutation: str | None):
    bundle, case, sources = _case(tmp_path, mutation)
    before = raw_inventory(bundle), raw_inventory(sources.deployment.root)
    if mutation is None:
        assert verify_q03(bundle, case, sources)
    else:
        with pytest.raises((HostedQualificationError, ValueError)):
            verify_q03(bundle, case, sources)
    assert before == (raw_inventory(bundle), raw_inventory(sources.deployment.root))


@pytest.mark.parametrize("missing", ["specs", "campaigns"])
def test_q03_missing_exported_protocol_never_creates_directories(tmp_path: Path, missing: str):
    bundle, case, sources = _case(tmp_path, None)
    absent = bundle / case.roots[0].logical_path / "protocol" / missing
    shutil.rmtree(absent)
    before = raw_inventory(bundle), raw_inventory(sources.deployment.root)
    with pytest.raises(HostedQualificationError):
        verify_q03(bundle, case, sources)
    assert not absent.exists()
    assert before == (raw_inventory(bundle), raw_inventory(sources.deployment.root))
