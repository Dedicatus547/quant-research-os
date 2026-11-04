"""Cited memory is append-only derived knowledge with enforceable time boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from quantos.application.personal_history import PersonalHistoryService
from quantos.application.personal_memory import (
    MemoryDraft,
    MemoryNotAvailableError,
    PersonalMemoryService,
    json_pointer,
)
from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def setup(tmp_path, *, available="2026-11-03T12:00:00+00:00"):
    source = tmp_path / "result.json"
    raw = canonical_json_bytes({"run_status": "FAILED", "metrics": {"net_return": None}})
    atomic_write_bytes(source, raw)
    root = tmp_path / "product"
    root.mkdir()
    service = PersonalMemoryService(root, tmp_path, clock=lambda: NOW)
    draft = {
        "record_id": "failed-engineering-run",
        "label": "Failed run: metric is unknown",
        "hypothesis": "A changed scoring rule may improve the measured outcome",
        "expectation": "Compare against a control with identical eligibility",
        "universe": "synthetic 3 securities",
        "period": "2024-01-01/2024-01-31",
        "data_scenario": "synthetic; no market or vendor-vintage claim",
        "cost_scenario": "fixed engineering fee scenario",
        "tags": ["synthetic", "failure"],
        "sources": [
            {
                "source_id": "result",
                "path": "result.json",
                "sha256": sha256_bytes(raw),
                "available_at": available,
                "scope": "ORIGINAL_RESULT",
            }
        ],
        "observations": [
            {
                "name": "net return",
                "source_id": "result",
                "pointer": "/metrics/net_return",
                "definition": "Original model net return; null means not evaluated",
            },
            {
                "name": "execution status",
                "source_id": "result",
                "pointer": "/run_status",
                "definition": "Original execution status, independent of qualification",
            },
        ],
        "annotations": [
            {
                "kind": "MODEL_INTERPRETATION",
                "text": "Failure provides no profitability evidence",
                "source_ids": ["result"],
            }
        ],
        "recommendation": "STOP",
        "recommendation_reason": "No execution outcome; retain failure without retrying science",
    }
    return service, draft


def test_facts_null_and_annotations_remain_distinct_and_retries_are_idempotent(tmp_path):
    service, draft = setup(tmp_path)
    first = service.append(draft)
    assert first["reused"] is False
    second = service.append(draft)
    assert second["reused"] is True
    assert first["reference"] == second["reference"]
    history = PersonalHistoryService(service.root, tmp_path)
    read = history.read(draft["record_id"])
    record = read["original"]
    assert record["observations"][0]["value"] is None
    assert record["observations"][1]["value"] == "FAILED"
    assert record["draft"]["annotations"][0]["kind"] == "MODEL_INTERPRETATION"
    assert record["qualification_granted"] is False
    assert record["new_execution"] is False
    assert history.search("identical eligibility", tags=("synthetic",))["matched"] == 1
    assert history.search(tags=("real-market",))["matched"] == 0
    report = service.diagnostic_report(draft["record_id"])
    assert report["observations"][0]["value"] is None
    assert report["qualification_granted"] is False
    assert report["recommendation"] == "STOP"


def test_revision_appends_without_rewriting_predecessor(tmp_path):
    service, draft = setup(tmp_path)
    first = service.append(draft)
    path = tmp_path / first["reference"]["path"]
    before = path.read_bytes()
    changed = {**draft, "recommendation_reason": "New interpretation"}
    with pytest.raises(ValueError, match="immutable"):
        service.append(changed)
    changed["record_id"] = "failed-engineering-run-revision"
    changed["revises_hash"] = first["reference"]["sha256"]
    service.append(changed)
    assert path.read_bytes() == before
    assert service.search()["matched"] == 2
    changed["record_id"] = "unknown-predecessor"
    changed["revises_hash"] = "e" * 64
    with pytest.raises(ValueError, match="predecessor"):
        service.append(changed)


def test_as_of_excludes_new_memory_and_unknown_source_availability(tmp_path):
    service, draft = setup(tmp_path)
    service.append(draft)
    assert service.search(as_of="2026-11-03T23:59:00Z")["records"] == []
    assert service.search(as_of="2026-11-03T23:59:00Z")["total"] == 0
    assert service.search(as_of=NOW.isoformat())["matched"] == 1
    with pytest.raises(MemoryNotAvailableError, match="after as_of"):
        service.read(draft["record_id"], "2026-11-03T23:59:00Z")
    with pytest.raises(ValueError, match="timezone"):
        service.search(as_of="2026-11-04T15:00:00")
    draft["record_id"] = "unknown-availability"
    draft["sources"][0]["available_at"] = None
    service.append(draft)
    assert service.search(as_of=NOW.isoformat())["matched"] == 1
    assert service.search()["matched"] == 2


def test_original_tampering_is_not_hidden_as_a_search_miss(tmp_path):
    service, draft = setup(tmp_path)
    service.append(draft)
    (tmp_path / "result.json").write_text('{"run_status":"SUCCEEDED"}')
    with pytest.raises(ValueError, match="identity"):
        service.read(draft["record_id"])
    with pytest.raises(ValueError, match="identity"):
        service.search("absent query")


def test_even_rehashed_derived_value_must_equal_original(tmp_path):
    service, draft = setup(tmp_path)
    first = service.append(draft)
    path = tmp_path / first["reference"]["path"]
    record = json.loads(path.read_bytes())
    record["observations"][0]["value"] = 0
    raw = canonical_json_bytes(record)
    path.write_bytes(raw)
    catalog_path = service.root / "history-catalog.json"
    catalog = json.loads(catalog_path.read_bytes())
    catalog["records"][0]["sha256"] = sha256_bytes(raw)
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    with pytest.raises(ValueError, match="observations disagree"):
        service.read(draft["record_id"])


def test_legacy_json_reader_and_reference_are_preserved(tmp_path):
    service, draft = setup(tmp_path)
    entry = {
        "record_id": "original",
        "label": "Existing immutable result",
        "path": "result.json",
        "sha256": draft["sources"][0]["sha256"],
        "origin": "old result identity",
    }
    atomic_write_bytes(
        service.root / "history-catalog.json",
        canonical_json_bytes({"schema_version": "personal-history-catalog/v1", "records": [entry]}),
    )
    service.append(draft)
    history = PersonalHistoryService(service.root, tmp_path)
    assert history.read("original")["reference"] == entry
    assert history.read("original")["original"]["run_status"] == "FAILED"
    assert history.search("Existing")["records"] == [entry]
    assert history.search(as_of=NOW.isoformat())["matched"] == 1
    with pytest.raises(ValueError, match="availability is unknown"):
        history.read("original", as_of=NOW.isoformat())


def test_publication_interruption_recovers_record_timestamp(tmp_path, monkeypatch):
    service, draft = setup(tmp_path)
    import quantos.application.personal_memory as memory

    replace = memory.os.replace
    monkeypatch.setattr(
        memory.os,
        "replace",
        lambda *a, **k: (_ for _ in ()).throw(OSError("injected publication interruption")),
    )
    with pytest.raises(OSError, match="publication interruption"):
        service.append(draft)
    records = list((service.root / "history-derived").glob("*.json"))
    assert len(records) == 1
    saved = records[0].read_bytes()
    monkeypatch.setattr(memory.os, "replace", replace)
    restarted = PersonalMemoryService(
        service.root, tmp_path, clock=lambda: datetime(2026, 11, 5, tzinfo=UTC)
    )
    result = restarted.append(draft)
    assert result["record"]["recorded_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert records[0].read_bytes() == saved
    assert restarted.search()["matched"] == 1


@pytest.mark.parametrize("path", ["../result.json", "/result.json", "sealed/result.json"])
def test_traversal_absolute_and_sealed_references_are_rejected(tmp_path, path):
    _, draft = setup(tmp_path)
    draft["sources"][0]["path"] = path
    with pytest.raises(ValueError):
        MemoryDraft.model_validate(draft)


def test_bad_pointer_future_source_and_untrusted_fields_reject(tmp_path):
    service, draft = setup(tmp_path)
    draft["observations"][0]["pointer"] = "/metrics/not_present"
    with pytest.raises(ValueError, match="missing"):
        service.append(draft)
    draft["observations"][0]["pointer"] = "/metrics/net_return"
    draft["sources"][0]["available_at"] = "2026-11-05T12:00:00Z"
    with pytest.raises(ValueError, match="future source"):
        service.append(draft)
    draft["sources"][0]["available_at"] = None
    draft["recorded_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        service.append(draft)
    assert not (service.root / "history-catalog.json").exists()


def test_json_pointer_escapes_and_array_boundaries():
    assert json_pointer({"a/b": [{"~": None}]}, "/a~1b/0/~0") is None
    for pointer in ("/a/01", "/a/-1", "/a/4", "/a/~2"):
        with pytest.raises(ValueError):
            json_pointer({"a": [1]}, pointer)
