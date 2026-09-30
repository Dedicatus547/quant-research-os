"""Existing typed comparison booleans must not be mistaken for digest strings."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from quantos.application.hosted_protocol import _scan_safe
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.validation import ReproducibilityComparison
from quantos.security import SecretArtifactRejected


def _comparison() -> dict[str, object]:
    reference = ArtifactRef(
        kind="research_result",
        sha256="a" * 64,
        size_bytes=1,
        media_type="application/json",
        logical_path="manifest.json",
    )
    return ReproducibilityComparison(
        left=reference,
        right=reference,
        exact_content_hash=True,
        exact_fields_checked=4,
        float_fields_checked=2,
        max_absolute_error=0,
        absolute_tolerance=0,
        relative_tolerance=0,
        passed=True,
        detail="Verified native export hashes agree",
    ).model_dump(mode="json")


def test_scan_valid_comparison_preserves_original_bytes() -> None:
    comparison = _comparison()
    before = copy.deepcopy(comparison)
    _scan_safe({"nested": comparison})
    assert comparison == before


@pytest.mark.parametrize("mutation", ["unknown", "coercion", "credential", "missing"])
def test_comparison_scan_exception_is_strictly_typed(mutation: str) -> None:
    comparison = _comparison()
    if mutation == "unknown":
        comparison["schema_version"] = "unknown-comparison/v1"
    elif mutation == "coercion":
        comparison["exact_content_hash"] = "true"
    elif mutation == "credential":
        comparison["detail"] = "Bearer synthetic-test-canary"
    else:
        comparison.pop("left")
    with pytest.raises((SecretArtifactRejected, ValueError, ValidationError)):
        _scan_safe({"nested": comparison})
