"""Source-binding composition tests; substituted native predicates grant no qualification.

Real copied file inventories and original paths are verified here. The separately
covered kernel/native scenario predicates are explicit doubles, so these fixtures
cannot represent a deployment, worker, business run, or acceptance bundle.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import (
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationRoot,
)
from quantos.infrastructure import hosted_budget_verification as budgets
from quantos.infrastructure import hosted_fault_verification as faults
from quantos.infrastructure import hosted_lifecycle_verification as lifecycle
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES
from quantos.infrastructure.hosted_budget_deployment import budget_deployment_declaration
from quantos.infrastructure.hosted_fault_cases import (
    CORRUPTION_FAULT_WINDOWS,
    FAULT_SNAPSHOT_PHASES,
)
from quantos.infrastructure.hosted_fault_verification import FAULT_PROCESS_PHASES
from quantos.infrastructure.hosted_lifecycle_cases import (
    HOSTED_LIFECYCLE_CASES,
    LIFECYCLE_SNAPSHOT_PHASES,
)
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory

CAMPAIGN = "a" * 64


def _matrix(tmp_path: Path, family: str):
    manager, export = tmp_path / "manager", tmp_path / "export"
    manager.mkdir()
    export.mkdir()
    lifecycle_matrix = family == "lifecycle"
    budget_matrix = family == "budget"
    names = (
        HOSTED_LIFECYCLE_CASES
        if lifecycle_matrix
        else tuple(HOSTED_BUDGET_CASES)
        if budget_matrix
        else tuple(CORRUPTION_FAULT_WINDOWS)
    )
    phases = (
        LIFECYCLE_SNAPSHOT_PHASES
        if lifecycle_matrix
        else budgets.BUDGET_SNAPSHOT_PHASES
        if budget_matrix
        else FAULT_SNAPSHOT_PHASES
    )
    qid = "Q06" if lifecycle_matrix or budget_matrix else "Q05"
    records, evidence, roots, observations = {}, [], [], {}
    child_deployments = {}
    source_prefix = ""
    deployment = SimpleNamespace(
        root=manager,
        spec=SimpleNamespace(campaign_hash=CAMPAIGN),
        bundle=SimpleNamespace(
            content_hash="c" * 64, campaign=SimpleNamespace(content_hash=CAMPAIGN)
        ),
        profile=SimpleNamespace(content_hash="d" * 64, exact_commit="e" * 40),
    )

    def publish(path: str, source: str, data: bytes):
        source = source_prefix + source
        atomic_write_bytes(manager / source, data)
        atomic_write_bytes(export / path, data)
        records[path] = HostedManagerExportFile(
            bundle_path=path, source_path=source, sha256=sha256_bytes(data), size_bytes=len(data)
        )
        return path

    for name in names:
        source_prefix = f"qualification-deployments/Q06/{name}/" if budget_matrix else ""
        case_manager = manager / source_prefix
        prefix = f"qualification-cases/{qid}/{name}"
        actual = case_manager / prefix / "authority/protocol/campaigns" / CAMPAIGN
        actual.mkdir(parents=True)
        identity = actual.stat()
        process_phases = (
            lifecycle.lifecycle_process_phases(name)
            if lifecycle_matrix
            else budgets.BUDGET_PROCESS_PHASES
            if budget_matrix
            else FAULT_PROCESS_PHASES
        )
        exits = [
            {"phase": phase, "pid": 200 + index, "exit_code": 0}
            for index, phase in enumerate(process_phases)
        ]
        observation = {
            "schema_version": "hosted-negative-observation/v1"
            if lifecycle_matrix or budget_matrix
            else "hosted-fault-observation/v1",
            "case": name,
            "process_exits": exits,
            "race_barrier": {"fixture": name},
        }
        observations[name] = observation
        for phase in phases:
            source_root = (
                f"{prefix}/authority"
                if not lifecycle_matrix and not budget_matrix and phase == "after"
                else f"{prefix}/channel/snapshots/{phase}/authority"
            )
            (case_manager / source_root / "protocol/campaigns" / CAMPAIGN).mkdir(
                parents=True, exist_ok=True
            )
            root_path = f"cases/{name}/{phase}"
            source_file = f"protocol/campaigns/{CAMPAIGN}/canary.json"
            publish(
                f"{root_path}/{source_file}", f"{source_root}/{source_file}", b'{"synthetic":true}'
            )
            inventory = raw_inventory(case_manager / source_root)
            sidecar = publish(
                f"inventories/{name}-{phase}.json",
                f"{prefix}/channel/phase-inventories/{phase}.json",
                inventory.canonical_bytes(),
            )
            roots.append(
                HostedQualificationRoot(
                    name=f"{name}-{phase}",
                    logical_path=root_path,
                    campaign_hash=CAMPAIGN,
                    raw_inventory_path=sidecar,
                )
            )
        if lifecycle_matrix or budget_matrix:
            atomic_write_bytes(
                case_manager / prefix / "authority" / source_file, b'{"synthetic":true}'
            )
        for phase, exit_record in zip(process_phases, exits, strict=True):
            payload = {
                "schema_version": "hosted-lifecycle-process-observation/v1"
                if lifecycle_matrix
                else "hosted-fault-process-observation/v1",
                "phase": phase,
                "lock_identity": [identity.st_dev, identity.st_ino],
            }
            for suffix, value in (("", payload), ("-exit", exit_record)):
                path = publish(
                    f"evidence/{name}-{phase}{suffix}.json",
                    f"{prefix}/channel/process-records/{phase}{suffix}.json",
                    canonical_json_bytes(value),
                )
                evidence.append(path)
        for label, value in (
            ("observation", observation),
            ("run", {"schema_version": "hosted-manager-negative-run/v1", "case": name}),
        ):
            path = publish(
                f"evidence/{name}-{label}.json",
                f"{prefix}/channel/{label}.json",
                canonical_json_bytes(value),
            )
            evidence.append(path)
        if lifecycle_matrix and name in HOSTED_LIFECYCLE_CASES[:2]:
            evidence.append(
                publish(
                    f"evidence/{name}-barrier.json",
                    f"{prefix}/channel/race-barrier.json",
                    canonical_json_bytes(observation["race_barrier"]),
                )
            )
        if budget_matrix:
            child = SimpleNamespace(
                root=case_manager,
                spec=SimpleNamespace(campaign_hash=CAMPAIGN),
                profile=SimpleNamespace(content_hash=sha256_bytes(name.encode())),
                bundle=SimpleNamespace(content_hash=sha256_bytes((name + "-inputs").encode())),
            )
            child_deployments[name] = child
            source_prefix = ""
            evidence.append(
                publish(
                    f"evidence/{name}-declaration.json",
                    f"evidence/budget-deployment-{name}.json",
                    canonical_json_bytes(budget_deployment_declaration(deployment, child, name)),
                )
            )
    sources = HostedVerifiedSources(deployment, records, "b" * 64)
    case = HostedQualificationCase(
        case_id=qid, roots=tuple(roots), evidence_paths=tuple(sorted(evidence))
    )
    return manager, export, sources, case, tuple(names), records, child_deployments


@pytest.mark.parametrize("family", ("fault", "lifecycle"))
@pytest.mark.parametrize(
    "damage",
    (
        None,
        "missing_root",
        "campaign",
        "sidecar_origin",
        "mixed_root",
        "changed_original",
        "changed_copy",
        "extra_directory",
        "missing_observation",
        "duplicate_run",
        "extra_process",
        "missing_exit",
        "changed_exit",
        "wrong_phase",
        "wrong_lock",
        "wrong_parent",
        "wrong_barrier",
    ),
)
def test_complete_matrix_keeps_case_phase_process_and_original_source_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: str, damage: str | None
) -> None:
    manager, export, sources, case, names, records, _children = _matrix(tmp_path, family)
    module = lifecycle if family == "lifecycle" else faults
    native_calls, source_calls = [], []

    def source_predicate(_evidence, _sources, **kwargs):
        source_calls.append(kwargs["name"])
        return {
            "service_process_security": [
                "NSpid:\t100 2" if damage != "wrong_parent" else "NSpid:\tnot-a-pid"
            ]
        }, ("c" * 64,)

    def native_predicate(name, roots, *args, parent_pid, sources):
        assert set(roots) == set(
            LIFECYCLE_SNAPSHOT_PHASES if family == "lifecycle" else FAULT_SNAPSHOT_PHASES
        )
        assert parent_pid == 2
        native_calls.append(name)
        return (sha256_bytes(name.encode()),)

    monkeypatch.setattr(module, "verify_managed_fixture_source", source_predicate)
    monkeypatch.setattr(
        module,
        "verify_lifecycle_scenario" if family == "lifecycle" else "verify_fault_recovery_scenario",
        native_predicate,
    )
    first = case.roots[0]
    first_name = names[0]
    prefix = f"qualification-cases/{case.case_id}/{first_name}"
    process_phase = (
        lifecycle.lifecycle_process_phases(first_name)[0]
        if family == "lifecycle"
        else FAULT_PROCESS_PHASES[0]
    )
    record_path = f"evidence/{first_name}-{process_phase}.json"
    if damage == "missing_root":
        case = case.model_copy(update={"roots": case.roots[1:]})
    elif damage == "campaign":
        case = case.model_copy(
            update={
                "roots": (first.model_copy(update={"campaign_hash": "d" * 64}), *case.roots[1:])
            }
        )
    elif damage == "sidecar_origin":
        records[first.raw_inventory_path] = records[first.raw_inventory_path].model_copy(
            update={"source_path": "evidence/unrelated.json"}
        )
    elif damage == "mixed_root":
        path = f"{first.logical_path}/protocol/campaigns/{CAMPAIGN}/canary.json"
        records[path] = records[path].model_copy(
            update={"source_path": f"unrelated/protocol/campaigns/{CAMPAIGN}/canary.json"}
        )
    elif damage == "changed_original":
        source = records[
            f"{first.logical_path}/protocol/campaigns/{CAMPAIGN}/canary.json"
        ].source_path
        (manager / source).write_bytes(b"changed")
    elif damage == "changed_copy":
        (export / first.logical_path / f"protocol/campaigns/{CAMPAIGN}/canary.json").write_bytes(
            b"changed"
        )
    elif damage == "extra_directory":
        (export / first.logical_path / "unrelated").mkdir()
    elif damage == "missing_observation":
        case = case.model_copy(
            update={
                "evidence_paths": tuple(
                    p for p in case.evidence_paths if p != f"evidence/{first_name}-observation.json"
                )
            }
        )
    elif damage == "duplicate_run":
        path = f"evidence/{first_name}-run.json"
        case = case.model_copy(update={"evidence_paths": (*case.evidence_paths, path)})
    elif damage == "extra_process":
        records[record_path] = records[record_path].model_copy(
            update={"source_path": f"{prefix}/channel/process-records/unexpected.json"}
        )
    elif damage == "missing_exit":
        case = case.model_copy(
            update={
                "evidence_paths": tuple(
                    p
                    for p in case.evidence_paths
                    if p != f"evidence/{first_name}-{process_phase}-exit.json"
                )
            }
        )
    elif damage in ("changed_exit", "wrong_phase", "wrong_lock", "wrong_barrier"):
        import json

        path = (
            f"evidence/{first_name}-{process_phase}-exit.json"
            if damage == "changed_exit"
            else f"evidence/{first_name}-barrier.json"
            if damage == "wrong_barrier" and family == "lifecycle"
            else record_path
        )
        value = json.loads((export / path).read_bytes())
        field = (
            "exit_code"
            if damage == "changed_exit"
            else "phase"
            if damage == "wrong_phase"
            else "fixture"
            if damage == "wrong_barrier"
            else "lock_identity"
        )
        value[field] = (
            7 if field == "exit_code" else "borrowed" if field != "lock_identity" else [1, 2]
        )
        (export / path).write_bytes(canonical_json_bytes(value))
    before = raw_inventory(manager), raw_inventory(export)
    predicate = (
        lifecycle.verify_q06_lifecycle_subset
        if family == "lifecycle"
        else faults.verify_q05_corruption_subset
    )
    # Locks and barriers are lifecycle-specific; durable wrapper delegates their
    # semantics to its real native scenario predicate, not the composition double.
    reject = damage is not None and not (
        family == "fault" and damage in ("wrong_lock", "wrong_barrier")
    )
    if reject:
        with pytest.raises((HostedQualificationError, ValueError)):
            predicate(export, case, sources)
        assert first_name not in native_calls
    else:
        checked = predicate(export, case, sources)
        assert native_calls == source_calls == list(names)
        assert all(sha256_bytes(name.encode()) in checked for name in names)
    assert before == (raw_inventory(manager), raw_inventory(export))


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "missing_variant",
        "wrong_declaration",
        "wrong_child_hash",
        "nested_origin",
        "borrowed_sidecar",
        "mixed_child",
        "changed_original",
        "extra_directory",
        "missing_process",
        "extra_process",
        "wrong_exit",
        "wrong_parent",
    ),
)
def test_budget_matrix_requires_each_frozen_child_and_nested_source_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    from quantos.infrastructure import hosted_budget_deployment as children_module

    manager, export, sources, case, names, records, children = _matrix(tmp_path, "budget")
    calls = []

    def read_child(parent, name, profile_hash):
        assert parent is sources.deployment
        child = children[name]
        if profile_hash != child.profile.content_hash:
            raise HostedQualificationError("substituted child profile hash")
        return child

    def fixed_source(_evidence, nested, **kwargs):
        assert nested.deployment is children[kwargs["name"]]
        assert all(
            not value.source_path.startswith("qualification-deployments/")
            for value in nested.files.values()
        )
        return {
            "service_process_security": [
                "NSpid:\t100 2" if damage != "wrong_parent" else "NSpid:\tinvalid"
            ]
        }, ("c" * 64,)

    def scenario(name, roots, processes, observation, *, parent_pid, sources):
        assert parent_pid == 2 and sources.deployment is children[name]
        assert set(roots) == set(budgets.BUDGET_SNAPSHOT_PHASES)
        assert set(processes) == set(budgets.BUDGET_PROCESS_PHASES)
        calls.append(name)
        return (sha256_bytes(name.encode()),)

    monkeypatch.setattr(children_module, "read_managed_budget_deployment", read_child)
    monkeypatch.setattr(budgets, "verify_managed_fixture_source", fixed_source)
    monkeypatch.setattr(budgets, "verify_budget_scenario", scenario)
    first = names[0]
    declaration = f"evidence/{first}-declaration.json"
    process = f"evidence/{first}-exercise.json"
    sidecar = f"inventories/{first}-before.json"
    root = case.roots[0]
    if damage == "missing_variant":
        case = case.model_copy(update={"roots": case.roots[4:]})
    elif damage in ("wrong_declaration", "wrong_child_hash", "wrong_exit"):
        import json

        path = f"evidence/{first}-exercise-exit.json" if damage == "wrong_exit" else declaration
        value = json.loads((export / path).read_bytes())
        value[
            "exit_code"
            if damage == "wrong_exit"
            else "child_profile_hash"
            if damage == "wrong_child_hash"
            else "parent_business_inputs_hash"
        ] = 9 if damage == "wrong_exit" else "f" * 64
        (export / path).write_bytes(canonical_json_bytes(value))
    elif damage == "nested_origin":
        records[process] = records[process].model_copy(
            update={
                "source_path": records[process].source_path.removeprefix(
                    f"qualification-deployments/Q06/{first}/"
                )
            }
        )
    elif damage == "borrowed_sidecar":
        records[sidecar] = records[sidecar].model_copy(
            update={
                "source_path": records[sidecar].source_path.replace(
                    f"/{first}/", f"/{names[1]}/", 1
                )
            }
        )
    elif damage in ("mixed_child", "changed_original"):
        path = f"{root.logical_path}/protocol/campaigns/{CAMPAIGN}/canary.json"
        if damage == "mixed_child":
            records[path] = records[path].model_copy(
                update={
                    "source_path": records[path].source_path.replace(
                        f"/{first}/", f"/{names[1]}/", 1
                    )
                }
            )
        else:
            (manager / records[path].source_path).write_bytes(b"changed original")
    elif damage == "extra_directory":
        (export / root.logical_path / "unrelated").mkdir()
    elif damage == "missing_process":
        case = case.model_copy(
            update={"evidence_paths": tuple(p for p in case.evidence_paths if p != process)}
        )
    elif damage == "extra_process":
        records[process] = records[process].model_copy(
            update={
                "source_path": records[process].source_path.replace(
                    "exercise.json", "unexpected.json"
                )
            }
        )
    before = raw_inventory(manager), raw_inventory(export)
    if damage is None:
        checked = budgets.verify_q06_budget_subset(export, case, sources)
        assert calls == list(names)
        assert all(sha256_bytes(name.encode()) in checked for name in names)
    else:
        with pytest.raises((HostedQualificationError, ValueError, KeyError)):
            budgets.verify_q06_budget_subset(export, case, sources)
        assert calls == []
    assert before == (raw_inventory(manager), raw_inventory(export))
