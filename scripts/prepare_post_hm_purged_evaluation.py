#!/usr/bin/env python3
"""Declare a successor evaluation and retained stage origins without executing science."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, cast

from quantos.application.autonomous_execution import build_autonomous_execution_bindings
from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import DiscoveryBatch
from quantos.contracts.discovery_adoption import (
    DiscoveryAdoptedVariant,
    DiscoveryEvaluationSourceAdoption,
)
from quantos.contracts.discovery_evaluation import DiscoveryEvaluationDeclaration
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.infrastructure.hosted_storage import configured_guard


def read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 << 20:
        raise ValueError("preparation original is missing or unsafe")
    raw = path.read_bytes()
    parsed: object = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("preparation requires canonical JSON originals")
    result = cast(dict[str, Any], parsed)
    if canonical_json_bytes(result) != raw:
        raise ValueError("preparation requires canonical JSON originals")
    return result


def scientific_symbols(path: Path) -> dict[str, str]:
    """Compare every existing execution symbol, allowing explicit new adoption methods."""
    result: dict[str, str] = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node.name] = ast.dump(node, include_attributes=False)
        elif isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result[f"{node.name}.{method.name}"] = ast.dump(
                        method, include_attributes=False
                    )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[ast.expr] = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            result["assign:" + ast.dump(ast.Tuple(elts=targets, ctx=ast.Load()))] = ast.dump(
                node, include_attributes=False
            )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "capsule",
        "original-capsule",
        "frozen",
        "cutoff",
        "snapshot",
        "view",
        "output-root",
        "inputs-root",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    guard = configured_guard()
    guard.require_lease()
    guard.require_root(args.output_root)
    guard.require_root(args.inputs_root)
    guard.check(64 << 20)
    capsule, original, cutoff = read(args.capsule), read(args.original_capsule), read(args.cutoff)
    workspace, old_workspace = Path(str(capsule["workspace"])), Path(str(original["workspace"]))
    verify_code_provenance(
        workspace,
        expected_commit_hash=str(capsule["actual_commit"]),
        expected_lockfile_hash=str(capsule["lockfile_hash"]),
    )
    verify_code_provenance(
        old_workspace,
        expected_commit_hash=str(original["actual_commit"]),
        expected_lockfile_hash=str(original["lockfile_hash"]),
    )
    batch = DiscoveryBatch.model_validate(read(args.frozen))
    design = batch.design
    if (
        cutoff["batch_hash"] != batch.content_hash
        or cutoff["blocked_source_commit"] != original["actual_commit"]
        or original["actual_commit"] != design.bindings.code_commit_hash
        or capsule["lockfile_hash"] != original["lockfile_hash"]
        or cutoff["old_scheduling_permitted"] is not False
    ):
        raise ValueError("successor preparation differs from retained authority")
    snapshot = DataSnapshotManifest.model_validate(read(args.snapshot / "manifest.json"))
    view = QlibViewManifest.model_validate(read(args.view / "manifest.json"))
    if snapshot.snapshot_hash != design.snapshot_hash or view.view_hash != design.qlib_view_hash:
        raise ValueError("successor dataset metadata differs")
    bindings = build_autonomous_execution_bindings(
        snapshot=snapshot,
        qlib_view=view,
        research_policy=design.research_policy,
        validation_policy=design.validation_policy,
        authoring=design.authoring,
        cost_policy=design.cost_policy,
        backtest_policy=design.backtest_policy,
        code_commit_hash=str(capsule["actual_commit"]),
        lockfile_hash=str(capsule["lockfile_hash"]),
    )
    if bindings.model_dump(
        exclude={"code_commit_hash", "execution_policy_hash"}
    ) != design.bindings.model_dump(exclude={"code_commit_hash", "execution_policy_hash"}):
        raise ValueError("successor changes scientific policies or data")
    old_inventory = read(args.original_capsule.parent / "source-inventory.json")
    new_inventory = read(args.capsule.parent / "source-inventory.json")
    old_files = {item["path"]: item for item in old_inventory["files"]}
    new_files = {item["path"]: item for item in new_inventory["files"]}
    changes = [
        name
        for name in sorted(set(old_files) | set(new_files))
        if old_files.get(name) != new_files.get(name)
    ]
    proofs: list[dict[str, object]] = []
    for name in sorted(old_files):
        if not name.startswith(
            (
                "src/quantos/contracts/",
                "src/quantos/backtest/",
                "src/quantos/validation/",
                "src/quantos/data/",
                "src/quantos/research/qlib/",
            )
        ):
            continue
        if name == "src/quantos/research/qlib/workflow.py":
            continue
        if name not in new_files:
            raise ValueError("successor omits an original scientific dependency")
        if old_files[name] != new_files[name]:
            if name not in {
                "src/quantos/research/qlib/signal.py",
                "src/quantos/backtest/service.py",
            }:
                raise ValueError("successor changes an unapproved mathematical dependency")
            prior, successor = (
                scientific_symbols(old_workspace / name),
                scientific_symbols(workspace / name),
            )
            if any(successor.get(symbol) != value for symbol, value in prior.items()):
                raise ValueError("successor changes an original execution symbol")
            proofs.append(
                {
                    "path": name,
                    "proof": "ALL_ORIGINAL_EXECUTION_SYMBOL_ASTS_IDENTICAL",
                    "symbols_hash": sha256_bytes(canonical_json_bytes(prior)),
                }
            )
        else:
            proofs.append(
                {
                    "path": name,
                    "proof": "EXACT_ORIGINAL_BYTES",
                    "bytes_hash": sha256_file(workspace / name),
                }
            )
    delta = {
        "schema_version": "post-hm-purge-source-delta/v1",
        "original_commit": original["actual_commit"],
        "evaluation_commit": capsule["actual_commit"],
        "original_inventory_hash": sha256_file(
            args.original_capsule.parent / "source-inventory.json"
        ),
        "evaluation_inventory_hash": sha256_file(args.capsule.parent / "source-inventory.json"),
        "changed_paths": changes,
        "preserved_execution_dependencies": proofs,
        "changed_mathematics": "CALENDAR_SESSION_PURGE_OF_MODEL_TRAIN_AND_VALID_ONLY",
        "qualification_transferred": False,
    }
    delta_bytes = canonical_json_bytes(delta)
    atomic_write_bytes(args.inputs_root / "source-delta.json", delta_bytes)
    origins: list[DiscoveryAdoptedVariant] = []
    old_root = Path(str(cutoff["old_execution_root"]))
    for task in batch.subtasks:
        root = old_root / "tasks" / task.content_hash
        if not (root / "request.json").exists():
            continue
        request = read(root / "request.json")
        identity = str(request["execution_identity"])
        for checkpoint_path in sorted(
            root.glob(f"execution-checkpoints/{identity}/*-signal/sha256-*.json")
        ):
            checkpoint = read(checkpoint_path)
            signal_hash = str(checkpoint["outputs"]["signal_hash"])
            stage = str(checkpoint["stage"]).removesuffix("-signal")
            attempt = (
                checkpoint_path.parent
                / str(checkpoint["inputs_hash"])
                / "attempts"
                / f"{int(checkpoint['attempt_ordinal']):08d}"
            )
            if read(attempt / "completion.json")["status"] != "SUCCEEDED":
                raise ValueError("origin signal checkpoint lacks a completed attempt")
            signal_path = (
                root / "executions" / identity / stage / "signals" / f"sha256-{signal_hash}"
            )
            pit_hash = sha256_file(signal_path / "pit-evidence.json")
            backtests = tuple(
                (root / "execution-checkpoints" / identity / stage).glob("sha256-*.json")
            )
            if len(backtests) > 1:
                raise ValueError("ambiguous original variant checkpoints")
            bp = backtests[0] if backtests else None
            backtest_hash = str(read(bp)["outputs"]["backtest_hash"]) if bp else None
            origins.append(
                DiscoveryAdoptedVariant(
                    subtask_hash=task.content_hash,
                    stage=stage,
                    request_path=str(root / "request.json"),
                    request_hash=sha256_file(root / "request.json"),
                    signal_path=str(signal_path),
                    signal_hash=signal_hash,
                    signal_checkpoint_path=str(checkpoint_path),
                    signal_checkpoint_hash=sha256_file(checkpoint_path),
                    pit_path=str(signal_path / "pit-evidence.json"),
                    pit_hash=pit_hash,
                    backtest_path=str(
                        root
                        / "executions"
                        / identity
                        / stage
                        / "backtests"
                        / f"sha256-{backtest_hash}"
                    )
                    if bp
                    else None,
                    backtest_hash=backtest_hash,
                    backtest_checkpoint_path=str(bp) if bp else None,
                    backtest_checkpoint_hash=sha256_file(bp) if bp else None,
                )
            )
    adoption = DiscoveryEvaluationSourceAdoption(
        original_batch_hash=batch.content_hash,
        original_design_hash=design.content_hash,
        original_source_commit=str(original["actual_commit"]),
        evaluation_source_commit=str(capsule["actual_commit"]),
        lockfile_hash=str(capsule["lockfile_hash"]),
        evaluation_execution_policy_hash=bindings.execution_policy_hash,
        original_workspace=str(old_workspace),
        original_capsule_hash=sha256_file(args.original_capsule),
        evaluation_capsule_hash=sha256_file(args.capsule),
        source_delta_record_hash=sha256_bytes(delta_bytes),
        supersession_cutoff_hash=sha256_file(args.cutoff),
        variants=tuple(origins),
    )
    declaration = DiscoveryEvaluationDeclaration(
        original_batch_hash=batch.content_hash,
        original_design_hash=design.content_hash,
        original_generation_source_commit=design.bindings.code_commit_hash,
        bindings=bindings,
        max_compute_units=int(cutoff["successor_max_compute_units"]),
        source_adoption_record_hash=adoption.content_hash,
        exposure_history_append=(
            "Original source03 partial evaluation observed after all fifteen proposal "
            "opportunities were frozen: two terminal execution failures and the third candidate "
            "native predictions "
            "and partial robustness artifacts.",
            "Declared five-session purge was absent from original DatasetH train/valid splits; "
            "forward labels crossed the next segment. Original evaluation stopped with observed "
            "child exit -15 and manager/supervisor exit 1; retained independently completed stages "
            "preserve source03 origins.",
            "Successor evaluation keeps every original candidate, scientific policy and primary "
            "metric; only actual calendar purge, execution provenance and explicit native adoption "
            "are added. No additional generation or sealed confirmation access.",
        ),
    )
    atomic_write_bytes(args.output_root / "source-adoption.json", adoption.canonical_bytes())
    atomic_write_bytes(args.inputs_root / "source-adoption.json", adoption.canonical_bytes())
    atomic_write_bytes(
        args.inputs_root / "evaluation-declaration.json", declaration.canonical_bytes()
    )
    print(
        json.dumps(
            {
                "declaration_hash": declaration.content_hash,
                "adoption_hash": adoption.content_hash,
                "retained_variants": len(origins),
                "compute_limit": declaration.max_compute_units,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
