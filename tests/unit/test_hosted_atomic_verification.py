"""Finite native registration geometry; synthetic inputs do not grant qualification."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_atomic_forensics import _crash, _inputs, _spec

from quantos.application.campaign_selection import publish_selection_plan
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedQualificationRoot
from quantos.infrastructure.hosted_atomic_forensics import (
    atomic_forensic_inventory,
    native_registration_publication,
)
from quantos.infrastructure.hosted_atomic_snapshot import snapshot_atomic_authority
from quantos.infrastructure.hosted_atomic_verification import verify_atomic_publication_checkpoint
from quantos.infrastructure.hosted_fault_cases import (
    ATOMIC_FAULT_WINDOWS,
    FAULT_SNAPSHOT_PHASES,
    MANAGEMENT_FAULT_WINDOWS,
)
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    verify_case,
)


def _checkpoint(tmp_path: Path, case: str):
    inputs = _inputs(tmp_path / "inputs")
    spec = _spec(inputs)
    bundle = SimpleNamespace(initial_ledger_files=(), selection_plan=inputs.selection.plan)
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    channel.mkdir()
    publish_selection_plan(
        bundle.selection_plan, authority / "business" / spec.campaign_hash / "selection-plans"
    )
    domain, window = ATOMIC_FAULT_WINDOWS[case]
    if domain != "spec":
        (authority / "business-locks" / spec.campaign_hash).mkdir(parents=True)
    _crash(authority, spec, domain, window)
    target, expected = native_registration_publication(spec, domain)
    facts = snapshot_atomic_authority(
        "crashed", authority, channel, target_path=target, expected_bytes=expected, window=window
    )
    return authority, channel / "snapshots/crashed/authority", facts, bundle, spec, domain, window


@pytest.mark.parametrize("case", tuple(ATOMIC_FAULT_WINDOWS))
def test_native_checkpoint_requires_exact_registration_byte_and_directory_closure(
    tmp_path: Path, case: str
) -> None:
    authority, copy, facts, bundle, spec, domain, window = _checkpoint(tmp_path, case)
    target, expected = native_registration_publication(spec, domain)
    before = atomic_forensic_inventory(
        authority, target_path=target, expected_bytes=expected, window=window
    )
    assert verify_atomic_publication_checkpoint(
        copy, facts, bundle, spec, domain=domain, window=window
    )
    assert (
        atomic_forensic_inventory(
            authority, target_path=target, expected_bytes=expected, window=window
        )
        == before
    )


@pytest.mark.parametrize(
    "damage",
    (
        "extra_file",
        "extra_directory",
        "missing_plan",
        "wrong_bytes",
        "wrong_links",
        "different_alias",
    ),
)
def test_atomic_checkpoint_rejects_unrelated_and_forged_forensic_copies(
    tmp_path: Path, damage: str
) -> None:
    _, copy, facts, bundle, spec, domain, window = _checkpoint(tmp_path, "atomic-spec-file_linked")
    if damage == "extra_file":
        (copy / "unrelated.json").write_bytes(b"{}")
    elif damage == "extra_directory":
        (copy / "unrelated").mkdir()
    elif damage == "missing_plan":
        next(copy.rglob("plan.json")).unlink()
    elif damage == "wrong_bytes":
        (copy / facts.target_path).write_bytes(b"{}")
    else:
        target = next(item for item in facts.files if item.logical_path == facts.target_path)
        changed = target.model_copy(
            update={"link_count": 1} if damage == "wrong_links" else {"inode": target.inode + 1}
        )
        facts = facts.model_copy(
            update={"files": tuple(changed if item == target else item for item in facts.files)}
        )
    before = raw_inventory(copy)
    with pytest.raises(HostedQualificationError):
        verify_atomic_publication_checkpoint(
            copy, facts, bundle, spec, domain=domain, window=window
        )
    assert raw_inventory(copy) == before


@pytest.mark.parametrize("matrix", ("durable_and_corruption", "atomic_only"))
def test_q05_dispatch_never_awards_a_partial_matrix(tmp_path: Path, matrix: str) -> None:
    (tmp_path / "evidence.json").write_bytes(b"{}")
    names = MANAGEMENT_FAULT_WINDOWS if matrix == "durable_and_corruption" else ATOMIC_FAULT_WINDOWS
    case = HostedQualificationCase(
        case_id="Q05",
        roots=tuple(
            HostedQualificationRoot(
                name=f"{name}-{phase}",
                logical_path=f"cases/Q05/{name}/{phase}",
                campaign_hash="a" * 64,
                raw_inventory_path=f"cases/Q05/{name}/{phase}.json",
            )
            for name in names
            for phase in FAULT_SNAPSHOT_PHASES
        ),
        evidence_paths=("evidence.json",),
    )
    result = verify_case(tmp_path, case, sources=SimpleNamespace())
    assert result.verdict == "FAIL"
    assert verify_case(tmp_path, case).verdict == "NOT_EVALUATED"
