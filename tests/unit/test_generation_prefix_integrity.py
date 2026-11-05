"""Sequential recovery replays retained originals rather than rewritten history."""

import json

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_sequential_reporting import sequential_inputs

from quantos.application.discovery_generation import GenerationStore
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes


@pytest.fixture
def prefix(design, durable):
    requests, policy = sequential_inputs(design)
    store = GenerationStore(durable / "prefix")
    store.save_sequential_policy(policy)
    request = requests[0]
    for registered in requests:
        store.save_request(design, registered)
    first = store.reserve(request)
    response = store.complete(request, first, "unparseable proposal", producer="OFFLINE_IMPORT")
    second = store.reserve(request, response.content_hash)
    return store, request, first, second, policy


def test_prefix_reconstruction_checks_first_response_and_is_idempotent(prefix, design):
    store, request, first, second, policy = prefix
    attempt = store.read_attempt(request, second)
    assert len(attempt.history.entries) == 1
    assert attempt.history.entries[0].reservation_hash == first.content_hash
    store.save_sequential_policy(policy)
    batch = store.freeze(design)
    assert store.freeze(design) == batch
    store.verify_frozen(batch)


@pytest.mark.parametrize(
    "attack", ["array", "noncanonical", "reservation", "changed_attempt", "different_slot"]
)
def test_rewritten_prefix_cannot_be_recovered(prefix, attack):
    store, request, _first, second, _ = prefix
    directory = store.root / "requests" / request.content_hash
    path = directory / "responses/000001.json"
    value = json.loads(path.read_bytes())
    if attack == "array":
        path.write_bytes(b"[]")
    elif attack == "noncanonical":
        path.write_text(json.dumps(value, indent=2))
    elif attack == "reservation":
        value["response"]["reservation"]["ordinal"] = 2
        path.write_bytes(canonical_json_bytes(value))
    elif attack == "changed_attempt":
        path = directory / "reservations/000002.json"
        value = json.loads(path.read_bytes())
        value["history"]["entries"] = []
        path.write_bytes(canonical_json_bytes(value))
    else:
        second = second.model_copy(update={"request_hash": "f" * 64})
    with pytest.raises((ArtifactIntegrityError, ValueError)):
        store.read_attempt(request, second)


def test_policy_cannot_be_retrofitted_or_changed(prefix, design, durable):
    store, request, _, _, policy = prefix
    with pytest.raises(ArtifactIntegrityError, match="immutable"):
        store.save_sequential_policy(policy.model_copy(update={"random_seed": 42}))
    other = GenerationStore(durable / "old")
    other.save_request(design, request)
    with pytest.raises(ArtifactIntegrityError, match="precede"):
        other.save_sequential_policy(policy)


@pytest.mark.parametrize("field", ["max_attempts", "seed"])
def test_request_must_match_frozen_sequential_policy(design, durable, field):
    requests, policy = sequential_inputs(design)
    store = GenerationStore(durable / "store")
    store.save_sequential_policy(policy)
    request = requests[1].model_copy(update={field: 1})
    with pytest.raises(ArtifactIntegrityError, match=r"sequential base|frozen design"):
        store.save_request(design, request)
    assert not (store.root / "requests").exists()
