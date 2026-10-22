"""Bounded offline synthetic successor rehearsal, reusing the retained dump cache.

No market execution/collection is exposed. A new durable output directory is
required; interrupted or failed directories are never automatically reissued.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from quantos.application.personal_research import PersonalDatasetBinding
from quantos.artifacts.store import atomic_write_bytes, regular_tree_files, sha256_file, verify_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_research import (
    HS300DatasetManifest,
    HS300StudyRequest,
    PersonalCandidate,
    PersonalDatasetManifest,
    PreparedHS300Study,
)
from quantos.research.personal_qlib import PersonalQlibExecutor


def run(root: Path, repo: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    prior = repo / "artifacts/personal-research-product-20261022/run-01/core/synthetic-01/input"
    old = PersonalDatasetManifest.model_validate_json(
        (prior / "dataset-manifest.json").read_bytes()
    )
    if old.kind != "synthetic":
        raise ValueError("only retained synthetic sources are allowed")
    verify_file(prior / "canonical-panel.parquet", old.panel_sha256)
    for logical, digest in old.qlib_files.items():
        verify_file(prior / "provider" / logical, digest)
    provider = root / "provider"
    shutil.copytree(prior / "provider", provider)
    (provider / "features/sh000985").rename(provider / "features/sh000300")
    instrument_file = provider / "instruments/all.txt"
    instrument_file.write_text(instrument_file.read_text().replace("SH000985", "SH000300"))
    panel = pd.read_parquet(prior / "canonical-panel.parquet").rename(
        columns={"is_mainboard": "is_member"}
    )
    panel["qlib_id"] = panel["qlib_id"].replace({"SH000985": "SH000300"})
    panel["amount_cny"] = panel["volume"] * panel["close"]
    panel["is_suspended"] = False
    panel = panel.drop(columns="sector_momentum_5")
    # Non-unit factor exercises Qlib's adjusted-quantity/raw-200-share conversion.
    for field, multiplier in (
        ("open", 2),
        ("high", 2),
        ("low", 2),
        ("close", 2),
        ("factor", 2),
        ("volume", 0.5),
    ):
        path = provider / "features/sh600002" / f"{field}.day.bin"
        values = np.fromfile(path, dtype="<f4")
        values[1:] *= multiplier
        values.tofile(path)
    mask = panel["qlib_id"] == "SH600002"
    panel.loc[mask, "close"] *= 2
    panel.loc[mask, "volume"] /= 2
    panel_path = root / "panel.parquet"
    panel.to_parquet(panel_path, index=False)
    limits = []
    for row in panel.loc[panel["is_member"]].itertuples():
        factor = 2 if row.qlib_id == "SH600002" else 1
        raw_close = row.close / factor
        limits.append(
            {
                "instrument_id": f"{row.qlib_id[2:]}.{row.qlib_id[:2]}",
                "trade_date": row.trade_date,
                "up_limit": raw_close * 1.1,
                "down_limit": raw_close * 0.9,
            }
        )
    source = root / "synthetic-source"
    (source / "canonical").mkdir(parents=True)
    limits_path = source / "canonical/price_limits.parquet"
    pd.DataFrame(limits).to_parquet(limits_path, index=False)
    panel_hash = sha256_file(panel_path)
    synthetic_hash = sha256_bytes(
        canonical_json_bytes({"panel": panel_hash, "parent": old.snapshot_hash})
    )
    view_hash = sha256_bytes(
        canonical_json_bytes({"parent_view": old.qlib_view_hash, "fixture": panel_hash})
    )
    proof = {
        "kind": "synthetic",
        "snapshot_hash": synthetic_hash,
        "qlib_view_hash": view_hash,
        "panel_sha256": panel_hash,
    }
    proof_path = root / "pit-evidence.json"
    atomic_write_bytes(proof_path, canonical_json_bytes(proof))
    manifest = HS300DatasetManifest(
        dataset_id="hs300-native-fixture",
        kind="synthetic",
        snapshot_hash=synthetic_hash,
        qlib_view_hash=view_hash,
        panel_sha256=panel_hash,
        pit_evidence_hash=sha256_file(proof_path),
        start_date=old.start_date,
        end_date=old.end_date,
        warmup_start=date(2024, 1, 2),
        market_source="SYNTHETIC_FIXTURE",
        source_vintage="synthetic",
        exposure="synthetic",
        qlib_files={
            p.relative_to(provider).as_posix(): sha256_file(p) for p in regular_tree_files(provider)
        },
        source_files={"canonical/price_limits.parquet": sha256_file(limits_path)},
        snapshot_manifest_sha256=old.content_hash,
        view_manifest_sha256=old.content_hash,
    )
    candidates = (
        PersonalCandidate(candidate_id="main", role="main", rule="fixed amount trend"),
        PersonalCandidate(candidate_id="classic", role="classic", rule="close/SMA20 trend"),
        *(
            PersonalCandidate(
                candidate_id=f"random-{seed}",
                role="random",
                seed=seed,
                rule="conditional SHA256 rank",
            )
            for seed in (17, 41, 73, 101, 137)
        ),
    )
    prepared = PreparedHS300Study(
        request=HS300StudyRequest(
            idempotency_key="synthetic-hs300",
            brief="bounded engineering only",
            proposal={"session_id": "authorized-synthetic-engineering"},
            dataset_id=manifest.dataset_id,
            start_date=manifest.start_date,
            end_date=manifest.end_date,
            warmup_start=manifest.warmup_start,
        ),
        dataset_manifest=manifest,
        code_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    name: sha256_file(repo / name)
                    for name in (
                        "src/quantos/research/personal_qlib.py",
                        "src/quantos/research/hs300_data.py",
                        "src/quantos/research/hs300_exchange.py",
                        "src/quantos/contracts/personal_research.py",
                        "src/quantos/backtest/strategy.py",
                    )
                }
            )
        ),
        candidates=candidates,
        readiness="READY_FOR_AUTHORIZATION",
        gaps=(),
        rationale="synthetic engineering only",
        comparison_scope="all seven fixed arms",
        limits=("SYNTHETIC_ONLY; NOT_EVALUATED",),
    )
    atomic_write_bytes(root / "prepared.json", prepared.canonical_bytes())
    binding = PersonalDatasetBinding(manifest, provider, panel_path, proof_path, source)
    outcome = PersonalQlibExecutor({manifest.dataset_id: binding})(
        prepared, root / "execution", lambda: False
    )
    atomic_write_bytes(root / "outcome.json", canonical_json_bytes(outcome))
    if outcome["run_status"] != "SUCCEEDED":
        raise RuntimeError("synthetic native execution failed; retain receipts")
    # Native quantities use adjusted shares. The one non-unit source factor is 2.
    for candidate in candidates:
        orders = pd.read_parquet(
            root / "execution" / candidate.candidate_id / "native-orders.parquet"
        )
        filled = orders[orders["deal_amount"].fillna(0).ne(0)]
        factors = np.where(filled["instrument"] == "SH600002", 2.0, 1.0)
        raw_quantities = filled["deal_amount"].abs().to_numpy() * factors
        if not np.allclose(raw_quantities / 200, np.round(raw_quantities / 200), atol=1e-6):
            raise ValueError("native filled raw quantities violate synthetic 200-share scenario")
        if filled.duplicated(["datetime", "instrument"]).any():
            raise ValueError("more than one native fill per stock/session")
    atomic_write_bytes(
        root / "checks.json",
        canonical_json_bytes(
            {
                "engineering_only": True,
                "market_runs": 0,
                "collection_calls": 0,
                "native_arms": 7,
                "raw_200_share_fills": "PASS",
                "one_fill_per_name_session": "PASS",
                "source_factor_scenarios": [1, 2],
                "validation_verdict": "NOT_EVALUATED",
                "parent_synthetic_manifest_hash": old.content_hash,
            }
        ),
    )
    return outcome


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root, Path(__file__).resolve().parents[1]), sort_keys=True))
