#!/usr/bin/env python3
"""Publish a durable synthetic successor fixture, never canonical research preparation."""

from __future__ import annotations

import argparse
from pathlib import Path

from quantos.application.discovery_baselines import (
    baseline_expression_space,
    generate_sequential_baseline,
)
from quantos.application.discovery_execution import quote_discovery_workload
from quantos.application.discovery_generation import GenerationStore
from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import (
    CompositionGenerationPolicy,
    DiscoveryCompositionDesign,
    GenerationRequest,
    SequentialDiscoveryBatch,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = (
        Path(__file__).resolve().parents[1] / "tests/fixtures/discovery_composition/design.json"
    )
    original = source.read_bytes()
    design = DiscoveryCompositionDesign.model_validate_json(original)
    store = GenerationStore(args.output / "generation")
    requests = tuple(
        GenerationRequest(
            design_hash=design.content_hash,
            method=method,
            max_attempts=design.evaluation_opportunities_per_method,
            seed=None if method == "LLM" else 1729,
            model_identifier="gpt-6.1-sol" if method == "LLM" else None,
            reasoning_effort="medium" if method == "LLM" else None,
            configuration_hash=sha256_bytes(
                canonical_json_bytes({"kind": "OFFLINE_SYNTHETIC", "method": method})
            ),
            prompt=(
                "Offline source-bound synthetic composition example; "
                "no actual model call or market execution."
            ),
            input_hashes=design.context_hashes,
        )
        for method in ("LLM", "RANDOM", "TEMPLATE")
    )
    policy = CompositionGenerationPolicy(
        design_hash=design.content_hash,
        request_hashes=(
            requests[0].content_hash,
            requests[1].content_hash,
            requests[2].content_hash,
        ),
    )
    store.save_sequential_policy(policy)
    example = baseline_expression_space(design)[0]
    for request in requests:
        store.save_request(design, request)
        texts = (
            (example.canonical_bytes().decode(),)
            if request.method == "LLM"
            else generate_sequential_baseline(design, request, policy)
        )
        for text in texts:
            reservation = store.reserve(request)
            store.complete(
                request,
                reservation,
                text,
                producer="OFFLINE_IMPORT" if request.method == "LLM" else "BASELINE",
            )
    batch = store.freeze(design)
    if not isinstance(batch, SequentialDiscoveryBatch):
        raise ValueError("composition example requires its sequential policy")
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(args.output / "example-expression.json", example.canonical_bytes())
    atomic_write_bytes(
        args.output / "source-binding.json",
        canonical_json_bytes(
            {
                "schema_version": "discovery-composition-offline-example/v1",
                "origin": "SYNTHETIC_FIXTURE_NOT_RESEARCH_PREPARATION",
                "fixture_path": str(source.relative_to(Path(__file__).resolve().parents[1])),
                "fixture_bytes_hash": sha256_bytes(original),
                "design_hash": design.content_hash,
                "policy_hash": policy.content_hash,
                "sequential_batch_hash": batch.content_hash,
                "proposal_hash": example.content_hash,
                "actual_model_calls": 0,
                "scientific_executions": 0,
                "quoted_unique_workload_units": quote_discovery_workload(batch.batch),
                "code_binding": "HISTORICAL_FIXTURE_IDENTITY_NOT_CURRENT_DIRTY_HEAD",
                "unreserved_llm_opportunities": 2,
                "limitations": [
                    "Offline imports do not prove model provenance or qualification.",
                    "Input hashes are inherited fixture references; no market inputs were opened.",
                ],
            }
        ),
    )
    print(f"Saved synthetic source-bound example: {args.output}")


if __name__ == "__main__":
    main()
