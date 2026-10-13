"""Offline successor reader and managed capture boundaries; no launcher or science."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import post_hm_discovery as management
from scripts import run_post_hm_generation as managed
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_hosted_launcher import _configuration

from quantos.application.discovery_generation import GenerationStore
from quantos.application.discovery_prediction import _research_policy
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import (
    CompositionGenerationPolicy,
    DiscoveryCompositionDesign,
    GenerationRequest,
)
from quantos.contracts.discovery_prediction import PredictionFileSource
from quantos.contracts.pit import SafeQlibOperator


@pytest.fixture
def composition(design):
    value = design.model_dump(mode="python")
    for key in (
        "schema_version",
        "profile_id",
        "candidate_grammar",
        "allowed_windows",
        "max_nodes",
    ):
        value.pop(key)
    value.update(
        evaluation_opportunities_per_method=3,
        allowed_operators=tuple(
            sorted(
                (
                    SafeQlibOperator.FIELD,
                    SafeQlibOperator.RETURN,
                    SafeQlibOperator.ROLLING_MEAN,
                    SafeQlibOperator.ROLLING_STD,
                    SafeQlibOperator.DIVIDE,
                    SafeQlibOperator.MULTIPLY,
                ),
                key=str,
            )
        ),
    )
    return DiscoveryCompositionDesign.model_validate(value)


def test_management_and_prediction_preserve_successor_original(composition, durable):
    path = durable / "design.json"
    atomic_write_bytes(path, composition.canonical_bytes())
    assert management._read_design(path) == composition
    reference = PredictionFileSource(path=str(path.absolute()), sha256=composition.content_hash)
    assert _research_policy(reference) == composition.research_policy
    wrapper = canonical_json_bytes(
        {
            "schema_version": "discovery-sequential-batch/v2",
            "batch": {
                "schema_version": "discovery-batch/v1",
                "design": composition.model_dump(mode="python"),
            },
        }
    )
    wrapper_path = durable / "batch.json"
    atomic_write_bytes(wrapper_path, wrapper)
    assert (
        _research_policy(
            PredictionFileSource(path=str(wrapper_path.absolute()), sha256=sha256_bytes(wrapper))
        )
        == composition.research_policy
    )
    atomic_write_bytes(
        durable / "spaced.json", json.dumps(composition.model_dump(mode="json")).encode()
    )
    with pytest.raises(ValueError, match="canonical"):
        management._read_design(durable / "spaced.json")
    value = composition.model_dump(mode="python")
    value["schema_version"] = "discovery-design/v999"
    atomic_write_bytes(durable / "unknown.json", canonical_json_bytes(value))
    with pytest.raises(ValueError):
        management._read_design(durable / "unknown.json")


@pytest.fixture
def prepared_composition(composition, durable):
    configuration = _configuration(model="gpt-6.1-sol", reasoning_effort="high")
    requests = tuple(
        GenerationRequest(
            design_hash=composition.content_hash,
            method=method,
            max_attempts=3,
            seed=None if method == "LLM" else 1729,
            model_identifier="gpt-6.1-sol" if method == "LLM" else None,
            reasoning_effort="high" if method == "LLM" else None,
            configuration_hash=configuration.content_hash if method == "LLM" else "a" * 64,
            prompt="Synthetic composition source-bound fixture",
            input_hashes=composition.context_hashes,
        )
        for method in ("LLM", "RANDOM", "TEMPLATE")
    )
    policy = CompositionGenerationPolicy(
        design_hash=composition.content_hash,
        request_hashes=tuple(item.content_hash for item in requests),
    )
    store = GenerationStore(durable / "generation")
    store.save_sequential_policy(policy)
    for request in requests:
        store.save_request(composition, request)
    context = b'{"fixture":true}'
    originals = {
        "design.json": composition.canonical_bytes(),
        "llm-request.json": requests[0].canonical_bytes(),
        "llm-configuration.json": configuration.canonical_bytes(),
        "sequential-policy.json": policy.canonical_bytes(),
        f"contexts/sha256-{sha256_bytes(context)}.json": context,
    }
    preparation = {
        "schema_version": "discovery-input-preparation/v3",
        "design_hash": composition.content_hash,
        "files": {
            name: {"bytes_hash": sha256_bytes(data), "size_bytes": len(data)}
            for name, data in originals.items()
        },
    }
    return store, preparation, originals, durable


def _publish_preparation(preparation, originals, root: Path) -> Path:
    data = canonical_json_bytes(preparation)
    directory = root / f"sha256-{sha256_bytes(data)}"
    for name, original in {**originals, "preparation.json": data}.items():
        atomic_write_bytes(directory / name, original)
    return directory


def test_managed_capture_reads_new_budget_and_rejects_legacy_container(prepared_composition):
    store, preparation, originals, root = prepared_composition
    loaded = managed._inputs(_publish_preparation(preparation, originals, root), store)
    assert loaded.request.max_attempts == 3
    assert isinstance(loaded.policy, CompositionGenerationPolicy)
    assert not store.inventory(loaded.request)[0]
    preparation["schema_version"] = "discovery-input-preparation/v2"
    with pytest.raises(ArtifactIntegrityError, match="version"):
        managed._inputs(_publish_preparation(preparation, originals, root), store)
