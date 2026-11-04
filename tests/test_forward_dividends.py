"""Bounded membership inventory and immutable reuse, with a synthetic provider."""

import json
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantos.data.tushare import forward_dividends as dividends


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot"
    (snapshot / "canonical").mkdir(parents=True)
    pq.write_table(
        pa.table({"instrument_id": ["600001.SH", "600002.SH", "600001.SH"]}),
        snapshot / "canonical/index_membership.parquet",
    )
    monkeypatch.setenv("TUSHARE_TOKEN", "synthetic-dividend-credential")
    monkeypatch.setattr(
        dividends, "verify_snapshot", lambda _: SimpleNamespace(snapshot_hash="a" * 64)
    )
    monkeypatch.setattr(dividends.time, "sleep", lambda _: None)
    # No network requests occur; limiter behavior has its own acquisition tests.
    monkeypatch.setattr(
        dividends, "Limiter", lambda *_args, **_kwargs: SimpleNamespace(try_acquire=lambda _: True)
    )
    calls = []
    failure = [None]

    class Client:
        def query(self, endpoint, *, fields, **params):
            calls.append((endpoint, params))
            if failure[0]:
                raise RuntimeError(failure[0])
            return pd.DataFrame(columns=fields.split(","))

    monkeypatch.setattr(
        dividends, "TushareSnapshotSource", lambda _: SimpleNamespace(client=Client())
    )
    return SimpleNamespace(snapshot=snapshot, root=tmp_path, calls=calls, failure=failure)


def test_inventory_deduplicates_members_and_reuses_verified_original_chain(inventory):
    original = inventory.root / "original"
    first = dividends.acquire(original, inventory.snapshot, "a" * 64)
    assert first["expected_securities"] == first["completed_securities"] == 2
    assert first["request_attempts"] == len(inventory.calls) == 2
    assert first["coverage_granted"] is False
    originals = {
        p.relative_to(original): p.read_bytes() for p in original.rglob("*") if p.is_file()
    }
    second_root = inventory.root / "second"
    second = dividends.acquire(second_root, inventory.snapshot, "a" * 64, original)
    third = dividends.acquire(inventory.root / "third", inventory.snapshot, "a" * 64, second_root)
    assert second["request_attempts"] == third["request_attempts"] == 0
    assert len(inventory.calls) == 2
    assert all(row["status"] == "ACQUIRED_NOT_ADMITTED" for row in third["results"])
    assert all(row["reused_from"].startswith(str(original)) for row in third["results"])
    assert originals == {
        p.relative_to(original): p.read_bytes() for p in original.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "message,reason", [("permission denied", "PERMISSION_DENIED"), ("rate limit", "RATE_LIMITED")]
)
def test_provider_denial_stops_inventory_without_claiming_full_coverage(inventory, message, reason):
    inventory.failure[0] = message
    result = dividends.acquire(inventory.root / "denied", inventory.snapshot, "a" * 64)
    assert result["completed_securities"] == result["request_attempts"] == 1
    assert result["expected_securities"] == 2
    assert result["results"][0]["reason"] == reason
    assert not result["coverage_granted"]


@pytest.mark.parametrize("mode", ["hash", "credential", "empty", "oversized"])
def test_inventory_rejects_unbound_or_unbounded_input_before_provider(inventory, monkeypatch, mode):
    digest = "b" * 64 if mode == "hash" else "a" * 64
    if mode == "credential":
        monkeypatch.delenv("TUSHARE_TOKEN")
    if mode in {"empty", "oversized"}:
        codes = [] if mode == "empty" else [f"{i:06d}.SH" for i in range(351)]
        pq.write_table(
            pa.table({"instrument_id": pa.array(codes, type=pa.string())}),
            inventory.snapshot / "canonical/index_membership.parquet",
        )
    output = inventory.root / "rejected"
    with pytest.raises(ValueError):
        dividends.acquire(output, inventory.snapshot, digest)
    assert not output.exists()
    assert inventory.calls == []


def test_failed_original_is_retained_as_failure_and_missing_raw_response_rejects(inventory):
    original = inventory.root / "original"
    failed = original / "600001.SH"
    failed.mkdir(parents=True)
    receipt = {
        "status": "FAILED",
        "reason": "SHARED_RESPONSE_VALIDATION_FAILED",
        "request_attempts": 1,
    }
    (failed / "exit.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="failed provider response unavailable"):
        dividends.acquire(inventory.root / "missing", inventory.snapshot, "a" * 64, original)
    (failed / "provider-response.json").write_text('{"synthetic":"rejected raw response"}')
    result = dividends.acquire(inventory.root / "retained", inventory.snapshot, "a" * 64, original)
    assert result["results"][0]["status"] == "FAILED"
    assert result["results"][0]["request_attempts"] == 0
    assert result["results"][0]["retained_failure_from"] == str(failed)
    assert json.loads((failed / "exit.json").read_bytes()) == receipt
    assert result["request_attempts"] == len(inventory.calls) == 1


def test_reuse_cannot_follow_an_origin_outside_campaign(inventory):
    original = inventory.root / "original"
    dividends.acquire(original, inventory.snapshot, "a" * 64)
    path = original / "600001.SH/exit.json"
    data = json.loads(path.read_bytes())
    data["reused_from"] = str(inventory.root.parent / "outside-campaign")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="outside campaign"):
        dividends.acquire(inventory.root / "rejected", inventory.snapshot, "a" * 64, original)
    assert len(inventory.calls) == 2
