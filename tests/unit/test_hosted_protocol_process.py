"""Fresh-process protocol recovery; synthetic proposals confer no live qualification."""

from __future__ import annotations

import multiprocessing
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_autonomous_campaign import NOW
from test_hosted_protocol import _fixture

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.hosted import HostedAgentRequest, HostedCampaignSpec
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import raw_inventory, verify_protocol_root


def _process(
    root: str,
    material: str,
    operation: str,
    now: datetime,
    fault: tuple[str, int] | None,
    queue: Any,
    barrier: Any = None,
) -> None:
    """Fixed test-only operations, never reachable through the production channel."""
    path, inputs = Path(root), Path(material)
    spec = HostedCampaignSpec.model_validate_json((inputs / "spec.json").read_bytes())
    request = HostedAgentRequest.model_validate_json((inputs / "request.json").read_bytes())
    hits = 0

    def crash(point: str) -> None:
        nonlocal hits
        if fault is not None and point == fault[0]:
            hits += 1
            if hits == fault[1]:
                os._exit(73)

    service = HostedProtocolService(
        HostedProtocolStore(path, fault_hook=crash),
        clock=lambda: now,
        # Component fixture only. Deployment qualification uses the native loader.
        verify_inputs=lambda _: None,
    )
    if barrier is not None:
        barrier.wait(timeout=120)
    if operation == "register":
        result = service.start(spec.content_hash)
    elif operation == "issue":
        result = service.issue(
            spec.content_hash,
            request.business_request,
            projection_object_hashes=request.projection_object_hashes,
        )
    elif operation in ("submit", "reject"):
        raw = (inputs / "response.json").read_bytes() if operation == "submit" else b"{}"
        result = service.submit(request.content_hash, raw, "process.host")
    elif operation == "cancel":
        result = service.cancel(request.content_hash, "process.host")
    elif operation == "expire":
        result = service.resume(spec.campaign_hash)
    else:
        raise ValueError("unknown fixed test operation")
    lock = (path / "campaigns" / spec.campaign_hash).stat()
    queue.put((os.getpid(), result.canonical_bytes(), (lock.st_dev, lock.st_ino)))


def _run(
    root: Path,
    material: Path,
    operation: str,
    *,
    now: datetime = NOW,
    fault: tuple[str, int] | None = None,
) -> tuple[int, int | None, Any]:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=_process, args=(str(root), str(material), operation, now, fault, queue)
    )
    process.start()
    process.join(120)
    if process.is_alive():
        process.terminate()
        process.join(10)
        pytest.fail("fresh protocol process timed out")
    result = queue.get(timeout=2) if process.exitcode == 0 else None
    assert process.pid is not None
    queue.close()
    queue.join_thread()
    return process.pid, process.exitcode, result


def _material(tmp_path: Path) -> tuple[Path, Path, HostedCampaignSpec, HostedAgentRequest]:
    fixture = _fixture(tmp_path / "fixture")
    material = tmp_path / "test-management-inputs"
    material.mkdir()
    (material / "spec.json").write_bytes(fixture.spec.canonical_bytes())
    (material / "request.json").write_bytes(fixture.request.canonical_bytes())
    (material / "response.json").write_bytes(fixture.response.canonical_bytes())
    root = tmp_path / "authority"
    shutil.copytree(fixture.root, root)
    return root, material, fixture.spec, fixture.request


# Every publication, including registration budgets, request/checkpoint and
# accepted observation/response/exchange/receipt, gets a physical exit window.
_WINDOWS = [
    (operation, point, number)
    for operation, publications in (
        ("register", 3),
        ("issue", 4),
        ("submit", 5),
        ("reject", 2),
        ("cancel", 1),
        ("expire", 1),
    )
    for point, number in (
        ("intent_published", 1),
        *(("artifact_published", index) for index in range(1, publications + 1)),
        ("completion_published", 1),
    )
]


@pytest.mark.parametrize("operation,point,number", _WINDOWS)
def test_each_durable_publication_recovers_after_physical_process_exit(
    tmp_path: Path,
    operation: str,
    point: str,
    number: int,
) -> None:
    root, material, spec, request = _material(tmp_path)
    if operation in ("register", "issue"):
        shutil.rmtree(root)
        store = HostedProtocolStore(root)
        store.register_spec(spec)
        if operation == "issue":
            service = HostedProtocolService(store, clock=lambda: NOW, verify_inputs=lambda _: None)
            service.start(spec.content_hash)
    observed_at = NOW + timedelta(seconds=60) if operation == "expire" else NOW
    crashed_pid, code, _ = _run(root, material, operation, now=observed_at, fault=(point, number))
    assert code == 73
    durable = raw_inventory(root)
    if point != "completion_published":
        with pytest.raises(ArtifactIntegrityError, match="recovery required"):
            HostedProtocolStore(root).snapshot(spec.campaign_hash, recover=False)
        assert raw_inventory(root) == durable  # Read-only inspection cannot finish the INTENT.
    # Accepted/seen bytes must keep the original timestamp even past the TTL.
    recovery_at = observed_at + timedelta(hours=1)
    recovery_operation = "register" if operation == "register" else operation
    recovered_pid, code, first = _run(root, material, recovery_operation, now=recovery_at)
    assert code == 0 and recovered_pid != crashed_pid
    stable = raw_inventory(root)
    next_pid, code, second = _run(root, material, recovery_operation, now=recovery_at)
    assert code == 0 and next_pid not in (crashed_pid, recovered_pid)
    assert first[1:] == second[1:]
    assert raw_inventory(root) == stable
    state = HostedProtocolStore(root).snapshot(spec.campaign_hash, recover=False)
    verify_protocol_root(root, spec.campaign_hash)
    assert all(entry.phase == "COMPLETE" for entry in state.journal[1::2])
    assert len({entry.operation_id for entry in state.journal[::2]}) == len(state.journal) // 2
    assert state.budget.used_requests == (operation != "register")
    assert state.budget.used_unique_submissions == (operation in ("submit", "reject"))
    if operation in ("submit", "reject"):
        charged = [receipt for receipt in state.receipts if receipt.outcome != "EXHAUSTED"]
        assert len(charged) == 1 and charged[0].recorded_at == NOW
        assert charged[0].outcome == ("ACCEPTED" if operation == "submit" else "REJECTED")
        assert (state.accepted_receipt(request.content_hash) is not None) == (operation == "submit")
    elif operation in ("cancel", "expire"):
        assert len(state.terminals) == 1
        assert state.terminals[0].recorded_at == observed_at
        assert state.terminals[0].outcome == ("CANCELLED" if operation == "cancel" else "EXPIRED")
    elif operation == "issue":
        assert state.requests == (request,)


@pytest.mark.parametrize("other", ["submit", "cancel"])
def test_barrier_submit_races_keep_one_acceptance_and_stable_lock_inode(
    tmp_path: Path,
    other: str,
) -> None:
    root, material, spec, request = _material(tmp_path)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    barrier = context.Barrier(3)
    lock = (root / "campaigns" / spec.campaign_hash).stat()
    processes = [
        context.Process(
            target=_process,
            args=(str(root), str(material), operation, NOW, None, queue, barrier),
        )
        for operation in ("submit", other)
    ]
    try:
        for process in processes:
            process.start()
        barrier.wait(timeout=120)
        for process in processes:
            process.join(120)
            assert process.exitcode == 0
        results = [queue.get(timeout=2) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(10)
        queue.close()
        queue.join_thread()
    assert len({result[0] for result in results}) == 2
    assert {result[2] for result in results} == {(lock.st_dev, lock.st_ino)}
    state = HostedProtocolStore(root).snapshot(spec.campaign_hash, recover=False)
    assert state.budget.used_unique_submissions == 1
    charged = [receipt for receipt in state.receipts if receipt.outcome != "EXHAUSTED"]
    assert len(charged) == 1
    if other == "submit":
        assert results[0][1] == results[1][1] and charged[0].outcome == "ACCEPTED"
    else:
        terminal = state.terminals[0]
        assert (charged[0].outcome, terminal.outcome) in (
            ("ACCEPTED", "CANCEL_REJECTED"),
            ("REJECTED", "CANCELLED"),
        )
        assert (state.accepted_receipt(request.content_hash) is not None) == (
            terminal.outcome == "CANCEL_REJECTED"
        )
    before = raw_inventory(root)
    _, code, repeat = _run(root, material, "submit", now=NOW + timedelta(hours=1))
    assert code == 0 and repeat[1] == charged[0].canonical_bytes()
    assert repeat[2] == (lock.st_dev, lock.st_ino)
    assert raw_inventory(root) == before
    verify_protocol_root(root, spec.campaign_hash)


def test_expired_rejected_bytes_are_reused_but_unseen_bytes_are_charged(tmp_path: Path) -> None:
    root, material, spec, request = _material(tmp_path)
    assert _run(root, material, "reject")[1] == 0
    state = HostedProtocolStore(root).snapshot(spec.campaign_hash, recover=False)
    original = next(receipt for receipt in state.receipts if receipt.outcome == "REJECTED")
    assert _run(root, material, "expire", now=NOW + timedelta(seconds=60))[1] == 0
    before = raw_inventory(root)
    _, code, repeat = _run(root, material, "reject", now=NOW + timedelta(hours=1))
    assert code == 0 and repeat[1] == original.canonical_bytes()
    assert raw_inventory(root) == before
    assert _run(root, material, "submit", now=NOW + timedelta(hours=1))[1] == 0
    state = HostedProtocolStore(root).snapshot(spec.campaign_hash, recover=False)
    rejected = [receipt for receipt in state.receipts if receipt.outcome == "REJECTED"]
    assert len(rejected) == 2 and rejected[1].reason == "REQUEST_EXPIRED"
    assert state.budget.used_unique_submissions == 2
    assert state.budget.used_requests == 1
    assert state.accepted_receipt(request.content_hash) is None
    assert len(state.terminals) == 1
    assert all(
        b"campaign-trial" not in data and b"hosted-step-intent" not in data
        for data in state.artifacts.values()
    )
    verify_protocol_root(root, spec.campaign_hash)
