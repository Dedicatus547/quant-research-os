"""Atomic wrapper binds actual forensic sidecars and exact original phase copies.

Checkpoint fixtures use native fork/fsync windows. Kernel and recovery predicates
are explicit doubles: these roots have no installed source or Q05 qualification.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_atomic_verification import _checkpoint

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import (
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationRoot,
)
from quantos.infrastructure import hosted_atomic_verification as verifier
from quantos.infrastructure.hosted_fault_cases import ATOMIC_FAULT_WINDOWS, FAULT_SNAPSHOT_PHASES
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


def test_atomic_matrix_rejects_missing_physical_sidecars_and_mixed_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, exported = tmp_path / "manager", tmp_path / "bundle"
    exported.mkdir()
    records, roots, evidence = {}, [], []
    spec = None

    def copy(path, origin, data):
        atomic_write_bytes(exported / path, data)
        records[path] = HostedManagerExportFile(
            bundle_path=path, source_path=origin, sha256=sha256_bytes(data), size_bytes=len(data)
        )
        evidence.append(path)

    for name in ATOMIC_FAULT_WINDOWS:
        target = manager / "qualification-cases/Q05" / name
        _authority, crashed, facts, _bundle, spec, _domain, _window = _checkpoint(target, name)
        for phase in FAULT_SNAPSHOT_PHASES:
            origin = target / f"channel/snapshots/{phase}/authority"
            if phase == "before":
                origin.mkdir(parents=True)
            elif phase != "crashed":
                shutil.copytree(crashed, origin)
            inventory = raw_inventory(origin)
            logical = f"roots/{name}/{phase}"
            (exported / logical).mkdir(parents=True)
            for item in inventory.files:
                path = f"{logical}/{item.logical_path}"
                atomic_write_bytes(exported / path, (origin / item.logical_path).read_bytes())
                records[path] = HostedManagerExportFile(
                    bundle_path=path,
                    source_path=str((origin / item.logical_path).relative_to(manager)),
                    sha256=item.sha256,
                    size_bytes=item.size_bytes,
                )
            for directory in origin.rglob("*"):
                if directory.is_dir():
                    (exported / logical / directory.relative_to(origin)).mkdir(
                        exist_ok=True, parents=True
                    )
            sidecar = f"evidence/{name}-{phase}-inventory.json"
            source = target / f"channel/phase-inventories/{phase}.json"
            atomic_write_bytes(source, inventory.canonical_bytes())
            copy(sidecar, str(source.relative_to(manager)), inventory.canonical_bytes())
            roots.append(
                HostedQualificationRoot(
                    name=f"{name}-{phase}",
                    logical_path=logical,
                    campaign_hash=spec.campaign_hash,
                    raw_inventory_path=sidecar,
                )
            )
            if phase != "before":
                source = target / f"channel/phase-forensics/{phase}.json"
                atomic_write_bytes(source, facts.canonical_bytes())
                copy(
                    f"evidence/{name}-{phase}-forensics.json",
                    str(source.relative_to(manager)),
                    facts.canonical_bytes(),
                )
        exits = [
            {"phase": phase, "pid": 200 + index, "exit_code": 0}
            for index, phase in enumerate(("crash", "recovery-1", "recovery-2"))
        ]
        for phase, exit_fact in zip(("crash", "recovery-1", "recovery-2"), exits, strict=True):
            for suffix, payload in (("", {"phase": phase}), ("-exit", exit_fact)):
                source = target / f"channel/process-records/{phase}{suffix}.json"
                data = canonical_json_bytes(payload)
                atomic_write_bytes(source, data)
                copy(
                    f"evidence/{name}-{phase}{suffix}.json", str(source.relative_to(manager)), data
                )
        for label, payload in (
            (
                "observation",
                {
                    "schema_version": "hosted-negative-observation/v1",
                    "case": name,
                    "process_exits": exits,
                },
            ),
            (
                "run",
                {
                    "schema_version": "hosted-manager-negative-run/v1",
                    "case": name,
                    "authority_after_forensic_inventory": facts.model_dump(mode="json"),
                },
            ),
        ):
            source = target / f"channel/{label}.json"
            data = canonical_json_bytes(payload)
            atomic_write_bytes(source, data)
            copy(f"evidence/{name}-{label}.json", str(source.relative_to(manager)), data)
    deployment = SimpleNamespace(root=manager, spec=spec)
    sources = HostedVerifiedSources(deployment, records, "a" * 64)
    case = HostedQualificationCase(
        case_id="Q05", roots=tuple(roots), evidence_paths=tuple(sorted(evidence))
    )
    calls = []

    def scenario(name, copied_roots, facts, processes, observation, *, parent_pid, sources):
        assert parent_pid == 2
        assert set(copied_roots) == set(FAULT_SNAPSHOT_PHASES)
        assert set(facts) == {"crashed", "recovered", "after"}
        assert set(processes) == {"crash", "recovery-1", "recovery-2"}
        calls.append(name)
        return (sha256_bytes(name.encode()),)

    monkeypatch.setattr(
        verifier,
        "verify_managed_fixture_source",
        lambda *_args, **_kwargs: ({"service_process_security": ["NSpid:\t100 2"]}, ("b" * 64,)),
    )
    monkeypatch.setattr(verifier, "verify_atomic_recovery_scenario", scenario)

    def copied_inventories():
        # Atomic original authority can intentionally contain hardlinks; retain
        # it through the real forensic reader, not the unique-file raw reader.
        return tuple(
            raw_inventory(manager / "qualification-cases/Q05" / name / "channel")
            for name in ATOMIC_FAULT_WINDOWS
        ), raw_inventory(exported)

    before = copied_inventories()
    assert verifier.verify_q05_atomic_subset(exported, case, sources)
    assert calls == list(ATOMIC_FAULT_WINDOWS)
    assert before == copied_inventories()
    name = next(iter(ATOMIC_FAULT_WINDOWS))
    first_file = raw_inventory(exported / case.roots[1].logical_path).files[0].logical_path
    for damage in (
        "missing_root",
        "wrong_campaign",
        "wrong_sidecar_origin",
        "mixed_origin",
        "changed_copy",
        "extra_directory",
        "missing_forensics",
        "duplicate_forensics",
        "wrong_physical",
        "missing_observation",
        "duplicate_run",
        "wrong_run_physical",
        "extra_process",
        "missing_exit",
        "wrong_exit",
        "wrong_phase",
    ):
        calls.clear()
        changed_case = case
        file_changes, record_changes = {}, {}
        directory = None
        first = case.roots[1]
        process = f"evidence/{name}-crash.json"
        if damage == "missing_root":
            changed_case = case.model_copy(update={"roots": case.roots[1:]})
        elif damage == "wrong_campaign":
            changed_case = case.model_copy(
                update={
                    "roots": (
                        case.roots[0].model_copy(update={"campaign_hash": "0" * 64}),
                        *case.roots[1:],
                    )
                }
            )
        elif damage in {"wrong_sidecar_origin", "mixed_origin", "extra_process"}:
            path = (
                first.raw_inventory_path
                if damage == "wrong_sidecar_origin"
                else process
                if damage == "extra_process"
                else f"{first.logical_path}/{first_file}"
            )
            record_changes[path] = records[path]
            records[path] = records[path].model_copy(
                update={
                    "source_path": "unrelated/source.json"
                    if damage != "extra_process"
                    else f"qualification-cases/Q05/{name}/channel/process-records/extra.json"
                }
            )
        elif damage in {
            "missing_forensics",
            "missing_observation",
            "missing_exit",
            "duplicate_forensics",
            "duplicate_run",
        }:
            path = (
                f"evidence/{name}-crashed-forensics.json"
                if "forensics" in damage
                else f"evidence/{name}-observation.json"
                if damage == "missing_observation"
                else f"evidence/{name}-crash-exit.json"
                if damage == "missing_exit"
                else f"evidence/{name}-run.json"
            )
            changed_case = case.model_copy(
                update={
                    "evidence_paths": (*case.evidence_paths, path)
                    if damage.startswith("duplicate")
                    else tuple(x for x in case.evidence_paths if x != path)
                }
            )
        elif damage == "extra_directory":
            directory = exported / first.logical_path / "unrelated"
            directory.mkdir()
        else:
            path = (
                f"evidence/{name}-after-forensics.json"
                if damage == "wrong_physical"
                else f"evidence/{name}-run.json"
                if damage == "wrong_run_physical"
                else f"evidence/{name}-crash-exit.json"
                if damage == "wrong_exit"
                else process
                if damage == "wrong_phase"
                else f"{first.logical_path}/{first_file}"
            )
            original_bytes = (exported / path).read_bytes()
            file_changes[path] = original_bytes
            if damage == "changed_copy":
                data = b"changed"
            else:
                payload = json.loads(original_bytes)
                if damage == "wrong_physical":
                    payload["expected_publication_hash"] = "0" * 64
                elif damage == "wrong_run_physical":
                    payload["authority_after_forensic_inventory"] = {}
                else:
                    payload["exit_code" if damage == "wrong_exit" else "phase"] = (
                        7 if damage == "wrong_exit" else "borrowed"
                    )
                data = canonical_json_bytes(payload)
            (exported / path).write_bytes(data)
        with pytest.raises((HostedQualificationError, ValueError)):
            verifier.verify_q05_atomic_subset(exported, changed_case, sources)
        assert calls == []
        for path, data in file_changes.items():
            (exported / path).write_bytes(data)
        records.update(record_changes)
        if directory is not None:
            directory.rmdir()
        assert before == copied_inventories()
