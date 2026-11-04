"""Build a source-bound lifecycle catalog entry from an immutable forward snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq

from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hs300_lifecycle import (
    HS300LifecycleDatasetManifest,
    LifecycleFactBundle,
    LifecycleSourceArtifact,
    SecurityLifecycleFact,
    UnsupportedAccountEvent,
)
from quantos.data.qlib_view import verify_qlib_view
from quantos.data.snapshot import verify_snapshot
from quantos.research.hs300_lifecycle_data import build_hs300_lifecycle_panel


def build_forward_catalog(snapshot: Path, view: Path, target: Path) -> dict[str, Any]:
    manifest = verify_snapshot(snapshot)
    qlib = verify_qlib_view(view)
    target.mkdir(parents=True, exist_ok=False)
    instruments = snapshot / "canonical/instruments.parquet"
    rows = cast(Any, pq).read_table(instruments).to_pylist()
    lifecycle = target / "lifecycle"
    atomic_write_bytes(lifecycle / "instruments.parquet", instruments.read_bytes())
    derivation = {
        "schema_version": "hs300-lifecycle-derivation-spec/v1",
        "rules": [{"rule": "canonical-instrument-lifecycle/v1", "source_id": "instruments"}],
    }
    atomic_write_bytes(lifecycle / "derivation.json", canonical_json_bytes(derivation))
    sources = (
        LifecycleSourceArtifact(
            source_id="instruments",
            kind="TUSHARE_PRO",
            logical_path="instruments.parquet",
            sha256=sha256_file(instruments),
            observed_at=manifest.created_at,
        ),
        LifecycleSourceArtifact(
            source_id="derivation",
            kind="DERIVATION_SPEC",
            logical_path="derivation.json",
            sha256=sha256_file(lifecycle / "derivation.json"),
            observed_at=datetime.now(UTC),
        ),
    )
    facts = LifecycleFactBundle(
        coverage_start=manifest.start_date,
        coverage_end=manifest.end_date,
        source_vintage="historical_non_vintage",
        sources=sources,
        securities=tuple(
            SecurityLifecycleFact(
                instrument_id=row["instrument_id"],
                list_date=row["list_date"],
                delist_date=row["delist_date"],
                source_ids=("instruments",),
            )
            for row in rows
        ),
        events=tuple(
            UnsupportedAccountEvent(
                event_id="delist_" + row["instrument_id"][:6],
                instrument_id=row["instrument_id"],
                boundary_date=row["delist_date"],
                event_type="DELISTING",
                source_ids=("instruments",),
            )
            for row in rows
            if row["delist_date"]
        ),
        derivation_source_id="derivation",
    )
    atomic_write_bytes(lifecycle / "facts.json", facts.canonical_bytes())
    panel, proof = build_hs300_lifecycle_panel(
        snapshot,
        view,
        expected_snapshot_hash=manifest.snapshot_hash,
        expected_view_hash=qlib.view_hash,
        lifecycle_path=lifecycle / "facts.json",
        expected_lifecycle_hash=facts.content_hash,
        warmup_start=manifest.start_date,
        end_date=manifest.end_date,
    )
    panel.to_parquet(target / "panel.parquet", index=False)
    proof["panel_sha256"] = sha256_file(target / "panel.parquet")
    atomic_write_bytes(target / "pit.json", canonical_json_bytes(proof))
    sessions = sorted(set(panel.trade_date))
    dataset = HS300LifecycleDatasetManifest(
        dataset_id=manifest.dataset_id,
        kind="market",
        snapshot_hash=manifest.snapshot_hash,
        qlib_view_hash=qlib.view_hash,
        panel_sha256=proof["panel_sha256"],
        pit_evidence_hash=sha256_file(target / "pit.json"),
        start_date=sessions[20],
        end_date=manifest.end_date,
        warmup_start=manifest.start_date,
        market_source="TUSHARE_PRO",
        source_vintage="historical_non_vintage",
        exposure="retrospective_exploration",
        qlib_files={item.logical_path: item.sha256 for item in qlib.files},
        source_files=proof["source_files"],
        snapshot_manifest_sha256=sha256_file(snapshot / "manifest.json"),
        view_manifest_sha256=sha256_file(view / "manifest.json"),
        lifecycle_manifest_hash=facts.content_hash,
        lifecycle_source_hashes={item.source_id: item.sha256 for item in facts.sources},
        native_boundary_policy_hash=facts.policy.content_hash,
    )
    atomic_write_bytes(target / "manifest.json", dataset.canonical_bytes())
    registration = {
        "schema_version": "personal-catalog-registration/v6",
        "manifest_path": str((target / "manifest.json").resolve()),
        "manifest_sha256": sha256_file(target / "manifest.json"),
        "provider_root": str(view.resolve()),
        "panel_path": str((target / "panel.parquet").resolve()),
        "pit_evidence_path": str((target / "pit.json").resolve()),
        "snapshot_path": str(snapshot.resolve()),
        "lifecycle_path": str((lifecycle / "facts.json").resolve()),
        "field_mapping_profile": "canonical-personal-fields/v1",
    }
    atomic_write_bytes(target / "registration.json", canonical_json_bytes(registration))
    return registration
