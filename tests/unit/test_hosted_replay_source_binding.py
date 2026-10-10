"""Replay wrapper composition with explicit business/installed-run predicates.

Real inventories and original source-prefix bindings remain enabled. Synthetic
predicates have no live, native Qlib, C11, or Q09/Q10 qualification authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import (
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationRoot,
    HostedRawInventory,
)
from quantos.infrastructure import hosted_replay_verification as replay
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


def _source_fixture(tmp_path: Path, qid: str):
    manager, bundle = tmp_path / "manager", tmp_path / "bundle"
    manager.mkdir()
    bundle.mkdir()
    records, roots, observations = {}, [], []

    def root(name, logical):
        source = f"synthetic-original/{name}"
        data = b'{"fixture":"principal"}'
        atomic_write_bytes(manager / source / "principal.json", data)
        atomic_write_bytes(bundle / logical / "principal.json", data)
        inventory = raw_inventory(manager / source)
        records[f"{logical}/principal.json"] = HostedManagerExportFile(
            bundle_path=f"{logical}/principal.json",
            source_path=f"{source}/principal.json",
            sha256=sha256_bytes(data),
            size_bytes=len(data),
        )
        sidecar = f"inventories/{name}.json"
        atomic_write_bytes(bundle / sidecar, inventory.canonical_bytes())
        return (
            HostedQualificationRoot(
                name=name, logical_path=logical, campaign_hash="a" * 64, raw_inventory_path=sidecar
            ),
            inventory,
            manager / source,
        )

    for name in ("reuse",) if qid == "Q09" else ("root-a", "root-b"):
        entry, inventory, source = root(name, f"cases/{qid}/{name}")
        roots.append(entry)
        observations.append(
            {
                "authority_root": str(source),
                "raw_inventory": inventory.model_dump(mode="json"),
                "principal_inventory": inventory.model_dump(mode="json"),
                "runtime_inventory": HostedRawInventory(files=()).model_dump(mode="json"),
            }
        )
    observation = {
        "schema_version": "hosted-manager-replay-comparison/v1"
        if qid == "Q10"
        else "hosted-manager-replay-tamper/v1",
        "deployment_profile_hash": "d" * 64,
        "campaign_hash": "a" * 64,
        "qualification_eligibility": "NOT_QUALIFIED",
    }
    if qid == "Q10":
        observation.update(roots=observations, projections=[])
    else:
        observation.update(
            baseline_inventory_hash=raw_inventory(bundle / roots[0].logical_path).content_hash
        )
        cases = []
        for kind in replay.TAMPER_SCHEMAS:
            entry, _inventory, _source = root(kind.lower(), f"cases/Q09/tamper/{kind.lower()}")
            cases.append(
                {
                    "kind": kind,
                    "root": entry.model_dump(mode="json"),
                    "logical_path": "principal.json",
                    "error_type": "FixtureRejection",
                }
            )
        observation["cases"] = cases
    atomic_write_bytes(bundle / "observation.json", canonical_json_bytes(observation))
    deployment = SimpleNamespace(
        root=manager,
        profile=SimpleNamespace(content_hash="d" * 64),
        bundle=SimpleNamespace(campaign=SimpleNamespace(content_hash="a" * 64)),
    )
    sources = HostedVerifiedSources(deployment, records, "e" * 64)
    case = HostedQualificationCase(
        case_id=qid, roots=tuple(roots), evidence_paths=("observation.json",)
    )
    return manager, bundle, sources, case, observation, records


@pytest.mark.parametrize(
    "qid,damage",
    [
        (qid, damage)
        for qid in ("Q09", "Q10")
        for damage in (
            None,
            "root_count",
            "missing_live_sources",
            "mixed_root",
            "wrong_profile",
            "wrong_facts",
            "missing_observation",
            "duplicate_observation",
            "noncanonical",
        )
    ]
    + [("Q10", damage) for damage in ("same_original", "c11_scope", "principal_bytes")]
    + [
        ("Q09", damage)
        for damage in (
            "tamper_count",
            "tamper_shape",
            "tamper_prefix",
            "tamper_campaign",
            "tamper_kind",
        )
    ],
)
def test_replay_wrappers_keep_roots_observations_and_all_original_sources_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qid: str, damage: str | None
) -> None:
    manager, bundle, sources, case, observation, records = _source_fixture(tmp_path, qid)
    native_calls = []
    monkeypatch.setattr(
        replay,
        "verify_original_live_source",
        lambda _sources: ("0" * 64,) if damage == "missing_live_sources" else (),
    )
    monkeypatch.setattr(
        replay, "_business", lambda *_args: SimpleNamespace(artifact_hashes=("b" * 64,))
    )

    def offline(_bundle, _case, _sources, **kwargs):
        assert kwargs["mode"] == ("RECEIPT_REUSE" if qid == "Q09" else "REEXECUTE")
        assert kwargs["original_authority"].is_relative_to(manager)
        native_calls.append(kwargs["authority"])
        return ("c" * 64,)

    monkeypatch.setattr(replay, "verify_offline_manager_run", offline)
    monkeypatch.setattr(
        replay,
        "principal_business_inventory",
        lambda authority, _facts: (raw_inventory(authority), HostedRawInventory(files=())),
    )
    monkeypatch.setattr(
        replay,
        "c11_business_projection_paths",
        lambda authority, *_args: (
            frozenset({"unreferenced"})
            if damage == "c11_scope" and authority.name == "root-b"
            else frozenset()
        ),
    )
    # The real cross-root comparison remains active with no time projections.
    monkeypatch.setattr(replay, "verify_tamper_case", lambda *_args, **_kwargs: "FixtureRejection")
    if damage == "root_count":
        case = case.model_copy(update={"roots": ()})
    elif damage == "mixed_root":
        path = f"{case.roots[0].logical_path}/principal.json"
        records[path] = records[path].model_copy(update={"source_path": "unrelated/file.json"})
    elif damage == "wrong_profile":
        observation["deployment_profile_hash"] = "0" * 64
    elif damage == "wrong_facts":
        if qid == "Q10":
            observation["roots"][0]["runtime_inventory"] = {"untrusted": True}
        else:
            observation["cases"][0]["error_type"] = "UnprovenRejection"
    elif damage == "missing_observation":
        case = case.model_copy(update={"evidence_paths": ()})
    elif damage == "duplicate_observation":
        atomic_write_bytes(bundle / "duplicate.json", canonical_json_bytes(observation))
        case = case.model_copy(update={"evidence_paths": ("duplicate.json", "observation.json")})
    elif damage == "same_original":
        first, second = case.roots
        path = f"{second.logical_path}/principal.json"
        records[path] = records[path].model_copy(
            update={"source_path": records[f"{first.logical_path}/principal.json"].source_path}
        )
    elif damage == "principal_bytes":
        second = case.roots[1]
        path = bundle / second.logical_path / "principal.json"
        path.write_bytes(b'{"fixture":"different principal"}')
        (bundle / second.raw_inventory_path).write_bytes(
            raw_inventory(path.parent).canonical_bytes()
        )
        record_path = f"{second.logical_path}/principal.json"
        records[record_path] = records[record_path].model_copy(
            update={"sha256": sha256_bytes(path.read_bytes()), "size_bytes": path.stat().st_size}
        )
    elif damage == "tamper_count":
        observation["cases"] = observation["cases"][:-1]
    elif damage == "tamper_shape":
        observation["cases"][0] = "untrusted nonobject"
    elif damage == "tamper_kind":
        observation["cases"][0]["kind"] = "EVENT"
    elif damage in {"tamper_prefix", "tamper_campaign"}:
        observation["cases"][0]["root"][
            "logical_path" if damage == "tamper_prefix" else "campaign_hash"
        ] = "cases/Q09/borrowed/request" if damage == "tamper_prefix" else "0" * 64
    (bundle / "observation.json").write_bytes(
        json.dumps(observation, indent=2).encode()
        if damage == "noncanonical"
        else canonical_json_bytes(observation)
    )
    before = raw_inventory(manager), raw_inventory(bundle)
    predicate = replay.verify_q09 if qid == "Q09" else replay.verify_q10
    if damage is None:
        checked = predicate(bundle, case, sources)
        assert "b" * 64 in checked and "c" * 64 in checked
        assert len(native_calls) == (1 if qid == "Q09" else 2)
    else:
        with pytest.raises((HostedQualificationError, ValueError)):
            predicate(bundle, case, sources)
    assert before == (raw_inventory(manager), raw_inventory(bundle))
