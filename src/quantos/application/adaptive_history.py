"""Bounded historical field projection; source identity is distinct from interpretation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from quantos.application.adaptive_store import read
from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.base import canonical_json_bytes

# Deliberately limited to exposed originals used by this successor, not arbitrary documents.
_FIELDS = {
    "validation-report/v2": (
        r"/(run_status|verdict|snapshot_hash|qlib_view_hash|research_policy_hash|validation_policy_hash)",
        r"/gates/[0-9]+/(gate_id|verdict|reason_code|reason)",
        r"/metrics/[0-9]+/(metric|value|detail)",
        r"/robustness_cases/[0-9]+/(case_id|kind|description|observation_count)",
        r"/robustness_cases/[0-9]+/metrics/[0-9]+/(metric|value|detail)",
    ),
    "b2-common-day-report/v1": (
        r"/(combination_minus_best_constituent|missing_constituent_semantics|llm_minus_best_baseline|quality_increment|limitation)",
        r"/constituent_controls_same_common_days/long_return_std",
    ),
    "adaptive-first-live-closeout/v1": (
        r"/(status|sdk_decisions|new_candidates|scientific_executions|qualification|remaining_allowance)",
    ),
    "adaptive-decision/v1": (r"/(action|hypothesis|rationale)",),
    "campaign-selection-report/v1": (r"/(run_status|verdict|reason_code)",),
    "hosted-campaign-report/v1": (r"/(state|research_run_status|research_verdict|reason)",),
}


def verify_pins(recipe: dict[str, Any]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for pin in recipe["source_pins"]:
        path = Path(pin["path"])
        if not path.is_absolute() or path.is_symlink():
            raise ArtifactIntegrityError("historical pin requires an absolute regular path")
        name = str(path.resolve())
        if name in pins or sha256_file(path) != pin["sha256"]:
            raise ArtifactIntegrityError("historical pin duplicate or identity differs")
        pins[name] = pin["sha256"]
    for path in recipe["batches"]:
        if str(Path(path).resolve()) not in pins:
            raise ArtifactIntegrityError("historical batch lacks verified source pin")
    if not set(recipe["context_source_hashes"]) <= set(pins.values()):
        raise ArtifactIntegrityError("context citation lacks verified source pin")
    return pins


def project_history(recipe: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """v1 remains readable; v2 replaces free factual context with exact field assertions."""
    pins = verify_pins(recipe)
    if recipe["schema_version"] == "adaptive-local-package-recipe/v1":
        return recipe["context"], {"mode": "LEGACY_FREE_TEXT_PIN_CLOSURE_ONLY"}
    if recipe["schema_version"] != "adaptive-local-package-recipe/v2" or "context" in recipe:
        raise ArtifactIntegrityError("explicit successor recipe required; no free factual context")
    facts = recipe["historical_facts"]
    if not 1 <= len(facts) <= 48:
        raise ArtifactIntegrityError("historical fact count outside bound")
    projected: list[dict[str, Any]] = []
    local: list[dict[str, Any]] = []
    loaded: dict[str, Any] = {}
    seen: set[tuple[str, str]] = set()
    cited = {pins[str(Path(p).resolve())] for p in recipe["batches"]}
    for fact in facts:
        if set(fact) != {"source_path", "source_sha256", "pointer", "value"}:
            raise ArtifactIntegrityError("historical fact fields differ")
        path, digest, pointer = (
            str(Path(fact["source_path"]).resolve()),
            fact["source_sha256"],
            fact["pointer"],
        )
        if pins.get(path) != digest or (digest, pointer) in seen:
            raise ArtifactIntegrityError("fact source unpinned, replaced or duplicate")
        seen.add((digest, pointer))
        if path not in loaded:
            loaded[path] = json.loads(read(Path(path)))
        source = loaded[path]
        schema = source.get("schema_version")
        if not any(re.fullmatch(p, pointer) for p in _FIELDS.get(schema, ())):
            raise ArtifactIntegrityError("historical field outside exposed whitelist")
        value: Any = source
        try:
            for part in pointer.split("/")[1:]:
                value = (
                    cast(list[Any], value)[int(part)] if isinstance(value, list) else value[part]
                )
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise ArtifactIntegrityError("historical field missing") from error
        if isinstance(value, (dict, list)) or canonical_json_bytes(value) != canonical_json_bytes(
            fact["value"]
        ):
            raise ArtifactIntegrityError("historical field value/type differs")
        # Null, failed execution and scientific verdict are retained verbatim.
        projected.append({"source": digest, "schema": schema, "field": pointer, "value": value})
        local.append({**fact, "source_path": path, "schema": schema})
        cited.add(digest)
    if sorted(cited) != sorted(recipe["context_source_hashes"]):
        raise ArtifactIntegrityError("citation inventory differs from facts and historical batches")
    framing = recipe["task_framing_inference"]
    if not isinstance(framing, str) or not 1 <= len(framing) <= 2400:
        raise ArtifactIntegrityError("bounded explicitly labelled task interpretation required")
    context = canonical_json_bytes(
        {"historical_fields": projected, "task_framing_inference_not_evidence": framing}
    ).decode()
    if len(context) > 8000:
        raise ArtifactIntegrityError("historical projection exceeds context bound")
    return context, {"mode": "VERIFIED_FIELDS_V2", "facts": local, "context": context}
