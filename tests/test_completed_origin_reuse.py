"""Synthetic completed-origin evidence, independently joined before any deserialization."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hs300_cash import ClassicOriginReuse
from quantos.contracts.hs300_lifecycle import LifecycleFactBundle
from quantos.research import hs300_cash_runtime as runtime
from test_hs300_cash_runtime import observation
from test_personal_lifecycle_service import _request, _setup
from test_signal_origin_guards import COMPILERS, REPO, projected_predecessor
from test_signal_origin_guards import origin as origin


@pytest.fixture
def completed(origin, monkeypatch):
    root = origin.root
    service, _, _, manifest = _setup(root, monkeypatch)
    original = service._prepared(service.prepare(_request())["task_id"])
    source = origin.put("facts/source.json", b'{"synthetic":true}')
    facts = LifecycleFactBundle(
        coverage_start=manifest.warmup_start,
        coverage_end=manifest.end_date,
        source_vintage="synthetic",
        sources=(
            {
                "source_id": "fixture",
                "kind": "SYNTHETIC_FIXTURE",
                "logical_path": "source.json",
                "sha256": source.sha256,
                "observed_at": datetime(2024, 1, 1, tzinfo=UTC),
            },
        ),
        securities=(
            {
                "instrument_id": "600001.SH",
                "list_date": date(2000, 1, 1),
                "source_ids": ["fixture"],
            },
        ),
        events=(
            {
                "event_id": "merger",
                "instrument_id": "600001.SH",
                "event_type": "MERGER_EXCHANGE",
                "boundary_date": date(2024, 2, 5),
                "source_ids": ["fixture"],
            },
        ),
    )
    facts_ref = origin.put("facts/lifecycle.json", facts.canonical_bytes())
    original = original.model_copy(
        update={
            "dataset_manifest": manifest.model_copy(
                update={
                    "lifecycle_manifest_hash": facts.content_hash,
                    "lifecycle_source_hashes": {"fixture": source.sha256},
                    "native_boundary_policy_hash": facts.policy.content_hash,
                }
            )
        }
    )
    executor = origin.put("originals/" + COMPILERS[2], projected_predecessor())
    origin.refs[COMPILERS[2]] = executor
    origin.dependencies["sources"][COMPILERS[2]] = executor.sha256
    for name in (
        "src/quantos/backtest/strategy.py",
        "src/quantos/research/hs300_exchange.py",
        "src/quantos/research/hs300_native_boundary.py",
        "src/quantos/research/qlib/workflow.py",
    ):
        origin.dependencies["sources"][name] = sha256_file(REPO / name)
    spec, old_dep = origin.bind()
    old = original.model_copy(update={"code_hash": old_dep.code_hash})
    prepared_ref = origin.put("prepared.json", old.canonical_bytes())
    signals = {
        c.candidate_id: origin.put(
            "signals/" + c.candidate_id + ".pkl",
            ("opaque synthetic signal " + c.candidate_id).encode(),
        )
        for c in old.candidates
    }
    checkpoint = {
        "task_id": old.content_hash,
        "code_hash": old.code_hash,
        "panel_sha256": old.dataset_manifest.panel_sha256,
        "rows": [
            {"candidate_id": name, "signal_sha256": ref.sha256} for name, ref in signals.items()
        ],
    }
    spec = spec.model_copy(
        update={
            "prepared": prepared_ref,
            "checkpoint": origin.put("checkpoint.json", canonical_json_bytes(checkpoint)),
            "signal_files": signals,
            "panel_sha256": old.dataset_manifest.panel_sha256,
            "compiler_dependency_hashes": runtime.signal_compiler_dependency_hashes(),
        }
    )
    successor = SimpleNamespace(
        dataset_manifest=old.dataset_manifest,
        request=old.request,
        candidates=old.candidates,
        signal_reuse=spec,
    )
    observed = observation(
        session=date(2024, 2, 5),
        ever_held_or_filled=(),
        native_source_hashes=runtime.native_boundary_runtime_identity(),
    )
    boundary = {
        "observation": observed.model_dump(mode="json"),
        "lifecycle_manifest_hash": facts.content_hash,
        "events": {e.event_id: e.content_hash for e in facts.events},
        "decisions": [
            runtime.evaluate_native_boundary(e, observed, facts.policy).model_dump(mode="json")
            for e in facts.events
        ],
    }
    boundary_ref = origin.put("classic/boundary.json", canonical_json_bytes(boundary))
    receipt = {
        "prepared_hash": old.content_hash,
        "candidate_id": "classic",
        "run_status": "SUCCEEDED",
        "qlib_version": "0.9.7",
        "native_boundary_status": "CLEARED_ZERO_EXPOSURE",
        "signal_sha256": signals["classic"].sha256,
        "files": {"boundary.json": boundary_ref.sha256},
        "boundary_receipts": [{"file": "boundary.json", "sha256": boundary_ref.sha256}],
    }

    def seal():
        ref = origin.put("classic/receipt.json", canonical_json_bytes(receipt))
        outcome = origin.put(
            "outcome.json",
            canonical_json_bytes(
                {
                    "prepared_hash": old.content_hash,
                    "receipts": [
                        {
                            "candidate_id": "classic",
                            "receipt_hash": ref.sha256,
                            "run_status": "SUCCEEDED",
                        }
                    ],
                }
            ),
        )
        return ClassicOriginReuse(
            origin_root=str(root),
            prepared=prepared_ref,
            receipt=ref,
            outcome=outcome,
            dependencies=(spec.dependency_manifest,),
            source_refs=(facts_ref,),
        )

    return SimpleNamespace(
        origin=origin,
        successor=successor,
        old=old,
        spec=spec,
        checkpoint=checkpoint,
        receipt=receipt,
        boundary=boundary,
        seal=seal,
    )


def test_completed_origin_verifies_all_seven_signals_and_native_boundary_original(completed):
    f = completed
    signals = runtime.verify_reused_signal_bindings(f.successor, f.spec)
    assert set(signals) == {c.candidate_id for c in f.old.candidates}
    assert all(raw.startswith(b"opaque synthetic signal") for raw in signals.values())
    reuse = f.seal()
    before = (f.origin.root / reuse.receipt.path).read_bytes()
    assert runtime.verify_classic_origin(f.successor, reuse) == f.receipt
    assert (f.origin.root / reuse.receipt.path).read_bytes() == before


@pytest.mark.parametrize(
    "attack", ["panel", "compiler", "task", "code", "checkpoint_panel", "inventory", "signal"]
)
def test_signal_reuse_requires_independent_checkpoint_and_complete_denominator(completed, attack):
    f = completed
    spec = f.spec
    if attack == "panel":
        spec = spec.model_copy(update={"panel_sha256": "e" * 64})
    elif attack == "compiler":
        spec = spec.model_copy(update={"compiler_dependency_hashes": {}})
    else:
        if attack in {"task", "code", "checkpoint_panel"}:
            key = {"task": "task_id", "code": "code_hash", "checkpoint_panel": "panel_sha256"}[
                attack
            ]
            f.checkpoint[key] = "e" * 64
        elif attack == "inventory":
            f.checkpoint["rows"].pop()
        else:
            f.checkpoint["rows"][0]["signal_sha256"] = "e" * 64
        spec = spec.model_copy(
            update={
                "checkpoint": f.origin.put("checkpoint.json", canonical_json_bytes(f.checkpoint))
            }
        )
    with pytest.raises(ValueError, match=r"(dependency changed|checkpoint|inventory differs)"):
        runtime.verify_reused_signal_bindings(f.successor, spec)


@pytest.mark.parametrize(
    "attack",
    [
        "prepared_hash",
        "candidate_id",
        "run_status",
        "qlib_version",
        "native_boundary_status",
        "signal_sha256",
        "signal_scope",
        "boundaries",
        "exports",
        "facts",
        "dependencies",
    ],
)
def test_completed_receipt_cannot_substitute_status_inputs_exports_or_sources(completed, attack):
    f = completed
    if attack in f.receipt:
        f.receipt[attack] = "changed"
    elif attack == "signal_scope":
        f.successor.signal_reuse = None
    elif attack == "boundaries":
        f.receipt["boundary_receipts"] = []
    elif attack == "exports":
        (f.origin.root / "classic/boundary.json").write_bytes(b"changed")
    reuse = f.seal()
    if attack == "facts":
        reuse = reuse.model_copy(update={"source_refs": (reuse.outcome,)})
    elif attack == "dependencies":
        reuse = reuse.model_copy(update={"dependencies": (reuse.outcome,)})
    with pytest.raises(ValueError, match=r"(unproven|signal|boundary|export|lifecycle|dependency)"):
        runtime.verify_classic_origin(f.successor, reuse)


@pytest.mark.parametrize("attack", ["events", "decisions", "facts", "runtime", "binding"])
def test_boundary_status_is_recomputed_from_observed_native_inputs(completed, attack):
    f = completed
    if attack == "events":
        f.boundary["events"] = {}
    elif attack == "decisions":
        f.boundary["decisions"] = []
    elif attack == "facts":
        f.boundary["lifecycle_manifest_hash"] = "e" * 64
    elif attack == "runtime":
        f.boundary["observation"]["native_source_hashes"] = {}
    ref = f.origin.put("classic/boundary.json", canonical_json_bytes(f.boundary))
    f.receipt["files"]["boundary.json"] = ref.sha256
    f.receipt["boundary_receipts"][0]["sha256"] = "e" * 64 if attack == "binding" else ref.sha256
    with pytest.raises(ValueError, match="boundary"):
        runtime.verify_classic_origin(f.successor, f.seal())
