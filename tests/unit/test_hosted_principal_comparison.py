"""Full inventories stay binding when verified principal timestamps are projected."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from test_hosted_campaign import _fixture

from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted_qualification import HostedRawInventory
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    c11_manifest_projection,
    compare_verified_principal_roots,
    raw_inventory,
)


@pytest.mark.parametrize("mutation", [None, "unreferenced", "runtime", "subset", "date_payload"])
def test_principal_projection_retains_raw_runtime_and_reference_boundaries(
    tmp_path: Path, mutation: str | None
) -> None:
    fixture = _fixture(tmp_path / "component")
    snapshot = fixture.inputs.initial_snapshot
    logical = f"ledger/sha256-{snapshot.content_hash}.json"
    roots = [tmp_path / "a", tmp_path / "b"]
    for index, root in enumerate(roots):
        (root / "ledger").mkdir(parents=True)
        value = snapshot.model_copy(
            update={"created_at": snapshot.created_at + timedelta(days=index)}
        )
        (root / logical).write_bytes(canonical_json_bytes(value.model_dump(mode="python")))
        (root / "offline-observation.json").write_bytes(str(index).encode())
    raw = [raw_inventory(root) for root in roots]
    principal = [
        HostedRawInventory(files=tuple(item for item in inv.files if item.logical_path == logical))
        for inv in raw
    ]
    if mutation == "runtime":
        (roots[1] / "offline-observation.json").write_bytes(b"changed after inventory")
    elif mutation == "subset":
        principal[1] = HostedRawInventory(
            files=(principal[1].files[0].model_copy(update={"sha256": "f" * 64}),)
        )
    elif mutation == "date_payload":
        # A nested payload alteration changes the content-addressed identity, so
        # it cannot use a top-level creation date exemption.
        value = snapshot.model_copy(update={"ledger_id": "different-ledger"})
        (roots[1] / logical).write_bytes(canonical_json_bytes(value.model_dump(mode="python")))
        raw[1] = raw_inventory(roots[1])
        principal[1] = HostedRawInventory(
            files=tuple(item for item in raw[1].files if item.logical_path == logical)
        )
    allowed = frozenset() if mutation == "unreferenced" else frozenset({logical})
    if mutation is None:
        result = compare_verified_principal_roots(
            *roots, *raw, *principal, allowed_projection_paths=allowed
        )
        assert len(result) == 1 and result[0].logical_path == logical
        assert result[0].root_a_raw_hash != result[0].root_b_raw_hash
    else:
        with pytest.raises(HostedQualificationError):
            compare_verified_principal_roots(
                *roots, *raw, *principal, allowed_projection_paths=allowed
            )


@pytest.mark.parametrize("path", [None, "snapshot.json", "ledger/sha256-" + "f" * 64 + ".json"])
def test_ledger_projection_requires_self_hash_path(tmp_path: Path, path: str | None) -> None:
    fixture = _fixture(tmp_path / "component")
    data = canonical_json_bytes(fixture.inputs.initial_snapshot.model_dump(mode="python"))
    with pytest.raises(HostedQualificationError, match="path/content"):
        c11_manifest_projection(data, logical_path=path)
