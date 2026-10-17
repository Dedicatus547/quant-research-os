"""Exact exposed historical facts, never market computation or model calls."""

from copy import deepcopy

import pytest

from quantos.application.adaptive_history import project_history
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes


@pytest.fixture
def recipe(tmp_path):
    values = [
        {"schema_version": "b2-common-day-report/v1", "combination_minus_best_constituent": None},
        {
            "schema_version": "campaign-selection-report/v1",
            "run_status": "FAILED",
            "verdict": "NOT_EVALUATED",
        },
        {"schema_version": "discovery-sequential-batch/v2", "batch": {}},
    ]
    pins = []
    for index, value in enumerate(values):
        path = tmp_path / f"source-{index}.json"
        raw = canonical_json_bytes(value)
        path.write_bytes(raw)
        pins.append({"path": str(path), "sha256": sha256_bytes(raw)})
    return {
        "schema_version": "adaptive-local-package-recipe/v2",
        "source_pins": pins,
        "batches": [pins[2]["path"]],
        "context_source_hashes": sorted(p["sha256"] for p in pins),
        "task_framing_inference": "Missing comparison may justify STOP; interpretation only.",
        "historical_facts": [
            {
                "source_path": pins[0]["path"],
                "source_sha256": pins[0]["sha256"],
                "pointer": "/combination_minus_best_constituent",
                "value": None,
            },
            {
                "source_path": pins[1]["path"],
                "source_sha256": pins[1]["sha256"],
                "pointer": "/run_status",
                "value": "FAILED",
            },
            {
                "source_path": pins[1]["path"],
                "source_sha256": pins[1]["sha256"],
                "pointer": "/verdict",
                "value": "NOT_EVALUATED",
            },
        ],
    }


def test_projection_preserves_null_failure_and_actual_context(recipe):
    import json

    context, proof = project_history(recipe)
    assert [f["value"] for f in json.loads(context)["historical_fields"]] == [
        None,
        "FAILED",
        "NOT_EVALUATED",
    ]
    assert proof["context"] == context
    assert "task_framing_inference_not_evidence" in json.loads(context)


@pytest.mark.parametrize(
    "mutation",
    [
        "null_zero",
        "failed_success",
        "unpin_batch",
        "unpin_citation",
        "replace_source",
        "private_field",
        "free_context",
        "duplicate",
        "metric_change",
    ],
)
def test_projection_rejects_false_or_unclosed_history(recipe, mutation):
    value = deepcopy(recipe)
    if mutation == "null_zero":
        value["historical_facts"][0]["value"] = 0
    elif mutation == "failed_success":
        value["historical_facts"][1]["value"] = "SUCCEEDED"
    elif mutation == "unpin_batch":
        value["source_pins"].pop()
    elif mutation == "unpin_citation":
        value["context_source_hashes"].append("f" * 64)
    elif mutation == "replace_source":
        value["historical_facts"][0]["source_path"] = value["source_pins"][1]["path"]
    elif mutation == "private_field":
        value["historical_facts"][0]["pointer"] = "/sealed_confirmation"
    elif mutation == "free_context":
        value["context"] = "Unverified facts."
    elif mutation == "duplicate":
        value["historical_facts"].append(value["historical_facts"][0])
    else:
        value["historical_facts"][0]["value"] = 1.234
    with pytest.raises(ArtifactIntegrityError):
        project_history(value)


def test_typed_numbers_are_not_coerced(recipe):
    from pathlib import Path

    p = Path(recipe["source_pins"][0]["path"])
    raw = canonical_json_bytes(
        {"schema_version": "b2-common-day-report/v1", "combination_minus_best_constituent": 1}
    )
    p.write_bytes(raw)
    digest = sha256_bytes(raw)
    recipe["context_source_hashes"].remove(recipe["source_pins"][0]["sha256"])
    recipe["context_source_hashes"].append(digest)
    recipe["source_pins"][0]["sha256"] = digest
    recipe["historical_facts"][0].update(source_sha256=digest, value=True)
    with pytest.raises(ArtifactIntegrityError):
        project_history(recipe)
