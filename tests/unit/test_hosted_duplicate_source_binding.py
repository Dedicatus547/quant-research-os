"""Read-only Q02 semantic verifier over copied functional fork observations.

Records explicitly normalize executable paths in a new synthetic manager tree.
Kernel/source attestation is not invoked and business admission is an explicit
predicate double; this verifies protocol/receipt/budget/prefix binding only.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_duplicate_probe import (
    test_actual_barrier_receipt_resume_and_cap_reuse as _run_control,
)

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import (
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationRoot,
)
from quantos.infrastructure import hosted_duplicate_verification as verifier
from quantos.infrastructure.hosted_fixture_frames import DUPLICATE_SNAPSHOT_PHASES
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


def _verify_copies(root: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    import test_hosted_duplicate_probe as functional

    original_spec = functional._spec

    def two_request_spec(*args, **kwargs):
        spec = original_spec(*args, **kwargs)
        # Q02 needs per-request cap 2 while retaining global cap 4. The older
        # fork control also exercises global cap 2, a distinct fixture policy.
        return spec.model_copy(
            update={
                "hosted_budget": spec.hosted_budget.model_copy(update={"max_unique_submissions": 4})
            }
        )

    monkeypatch.setattr(functional, "_spec", two_request_spec)
    original = root / "functional"
    original.mkdir(parents=True)
    _run_control(original, monkeypatch, name)
    manager, exported = root / "synthetic-manager", root / "bundle"
    target = manager / "qualification-cases/Q02" / name
    shutil.copytree(original / "channel", target / "channel")
    shutil.copytree(original / "authority", target / "authority")
    exported.mkdir()
    campaign = next((target / "authority/protocol/campaigns").iterdir()).name
    deployment = SimpleNamespace(
        root=manager, bundle=SimpleNamespace(campaign=SimpleNamespace(content_hash=campaign))
    )
    records, roots, evidence = {}, [], []

    def copy_file(bundle_path, source_path, data):
        atomic_write_bytes(exported / bundle_path, data)
        records[bundle_path] = HostedManagerExportFile(
            bundle_path=bundle_path,
            source_path=source_path,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
        )

    for phase in DUPLICATE_SNAPSHOT_PHASES:
        origin = target / (
            "authority" if phase == "after" else f"channel/snapshots/{phase}/authority"
        )
        inventory = raw_inventory(origin)
        logical = f"roots/{phase}"
        for item in inventory.files:
            source_path = str((origin / item.logical_path).relative_to(manager))
            copy_file(
                f"{logical}/{item.logical_path}",
                source_path,
                (origin / item.logical_path).read_bytes(),
            )
        sidecar = f"inventories/{phase}.json"
        source_path = f"qualification-cases/Q02/{name}/channel/phase-inventories/{phase}.json"
        atomic_write_bytes(manager / source_path, inventory.canonical_bytes())
        copy_file(sidecar, source_path, inventory.canonical_bytes())
        roots.append(
            HostedQualificationRoot(
                name=f"{name}-{phase}",
                logical_path=logical,
                campaign_hash=campaign,
                raw_inventory_path=sidecar,
            )
        )
    for phase in verifier.PROCESS_PHASES:
        source = target / f"channel/process-records/{phase}.json"
        payload = json.loads(source.read_bytes())
        payload["python_executable"] = "/install/python-seeded"
        source.write_bytes(canonical_json_bytes(payload))
        path = f"evidence/{phase}.json"
        copy_file(path, str(source.relative_to(manager)), source.read_bytes())
        evidence.append(path)
    observation = json.loads((target / "channel/negative-observation.json").read_bytes())
    case = HostedQualificationCase(
        case_id="Q02", roots=tuple(roots), evidence_paths=tuple(sorted(evidence))
    )
    sources = HostedVerifiedSources(deployment, records, "b" * 64)
    monkeypatch.setattr(verifier, "verify_business_admission_fixture", lambda *_args: ("e" * 64,))
    kernel = {"service_process_security": [f"NSpid:\t{os.getpid()}"]}
    before = raw_inventory(manager), raw_inventory(exported)
    assert verifier.verify_duplicate_fixture(exported, case, name, observation, kernel, sources)
    assert before == (raw_inventory(manager), raw_inventory(exported))
    for damage in (
        "missing_process",
        "wrong_parent",
        "wrong_pid",
        "wrong_clock",
        "wrong_lock",
        "wrong_response",
        "side_effect",
        "wrong_exit",
        "missing_cap",
        "missing_root",
        "mixed_source",
        "changed_copy",
        "wrong_budget",
        "wrong_cancellation",
    ):
        if damage == "wrong_cancellation" and name == "accepted":
            continue  # Admission/source predicate is an explicit double here.
        mutated_case, mutated_observation, mutated_kernel = case, dict(observation), kernel
        source_record = records[evidence[0]]
        data = (exported / evidence[0]).read_bytes()
        payload = json.loads(data)
        if damage in {
            "wrong_parent",
            "wrong_pid",
            "wrong_clock",
            "wrong_lock",
            "wrong_response",
            "side_effect",
        }:
            field, value = {
                "wrong_parent": ("parent_pid", 0),
                "wrong_pid": ("pid", os.getpid()),
                "wrong_clock": ("clock", "1999-01-01T00:00:00+00:00"),
                "wrong_lock": ("lock_after", [1, 2]),
                "wrong_response": ("response_hash", "0" * 64),
                "side_effect": ("network_attempts", ["UNAUTHORIZED"]),
            }[damage]
            payload[field] = value
            (exported / evidence[0]).write_bytes(canonical_json_bytes(payload))
        elif damage == "missing_process":
            mutated_case = case.model_copy(update={"evidence_paths": tuple(evidence[1:])})
        elif damage == "wrong_exit":
            mutated_observation["process_exits"] = []
        elif damage == "missing_cap":
            mutated_observation["cap_receipt_hashes"] = []
        elif damage == "missing_root":
            mutated_case = case.model_copy(update={"roots": case.roots[1:]})
        elif damage == "mixed_source":
            records[evidence[0]] = source_record.model_copy(
                update={"source_path": "unrelated/process.json"}
            )
        elif damage == "changed_copy":
            first = roots[0]
            path = (
                exported
                / first.logical_path
                / raw_inventory(exported / first.logical_path).files[0].logical_path
            )
            original_bytes = path.read_bytes()
            path.write_bytes(b"changed")
        elif damage == "wrong_budget":
            mutated_observation["receipt_hash"] = "0" * 64
        else:
            mutated_observation["business_cancellation_hash"] = "0" * 64
        with pytest.raises(
            (ArtifactIntegrityError, HostedQualificationError, ValueError, KeyError)
        ):
            verifier.verify_duplicate_fixture(
                exported, mutated_case, name, mutated_observation, mutated_kernel, sources
            )
        (exported / evidence[0]).write_bytes(data)
        records[evidence[0]] = source_record
        if damage == "changed_copy":
            path.write_bytes(original_bytes)
        assert before == (raw_inventory(manager), raw_inventory(exported))


@pytest.mark.fresh_offline_process
def test_duplicate_receipt_accounting_rejects_unrelated_processes_and_phase_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("accepted", "rejected"):
        with monkeypatch.context() as scoped:
            _verify_copies(tmp_path / name, scoped, name)
