"""Deterministic SDK presentation over immutable full requests, never evidence."""

from typing import cast

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import CampaignTrial
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.research_result import (
    ResearchResultArtifactFile,
    ResearchResultManifest,
    ResearchResultMetric,
    ResearchResultSourceFile,
)
from quantos.contracts.sdk_producer import SdkAgentRequest, SdkProducerProfileV4
from quantos.contracts.sdk_prompt import (
    SDK_PROMPT_PREFIX,
    SDK_PROMPT_PROJECTION_HASH,
    SDK_PROMPT_PROJECTION_IDENTIFIER,
    SDK_PROMPT_PROJECTION_MAX_UTF8_BYTES,
)
from quantos.contracts.validation import (
    GateResult,
    ReproducibilityComparison,
    RobustnessCaseResult,
    ValidationArtifactFile,
    ValidationMetric,
    ValidationReport,
)


def _canonical_fields(value: dict[str, object], cls: type[CanonicalContract]) -> None:
    expected = set(cls.model_fields) - set(cls.hash_exclude_fields)
    if set(value) != expected or value.get("schema_version") != cls.model_fields[
        "schema_version"
    ].default:
        raise ValueError("SDK projection canonical object scope differs")


def _typed(value: object, cls: type[CanonicalContract]) -> None:
    if cls.model_validate(value).canonical_bytes() != canonical_json_bytes(value):
        raise ValueError("SDK projection canonical scalar scope differs")


def _bind_collection(value: dict[str, object], key: str) -> None:
    collection = value.pop(key)
    if not isinstance(collection, list):
        raise ValueError("SDK projection collection shape differs")
    value[key + "_hash"] = sha256_bytes(canonical_json_bytes(collection))
    value[key + "_count"] = len(collection)


def prompt_projection(request: SdkAgentRequest, profile: SdkProducerProfileV4) -> bytes:
    """Original hashes identify omitted detail; missing/unknown fields fail closed."""
    profile = SdkProducerProfileV4.model_validate(profile.model_dump(mode="python"))
    from quantos.application.hosted_protocol import scan_protocol_artifact

    if request.sdk_profile_hash != profile.content_hash:
        raise ValueError("SDK projection request/profile differs")
    projected = request.canonical_payload()
    scan_protocol_artifact(projected)
    business = cast(dict[str, object], projected["business_request"])
    context = cast(dict[str, object], business["context_pack"])
    for item in cast(list[dict[str, object]], context["items"]):
        raw = cast(str, item.pop("content")).encode("utf-8")
        content = strict_json_object(raw, max_bytes=request.max_request_bytes)
        ref = cast(dict[str, object], item["object_ref"])
        if sha256_bytes(raw) != ref["object_hash"] or len(raw) != item["content_bytes"]:
            raise ValueError("SDK projection original object binding differs")
        kind = item["node_kind"]
        if kind == "CAMPAIGN_TRIAL":
            _canonical_fields(content, CampaignTrial)
            _typed(content, CampaignTrial)
        elif kind == "VALIDATION_REPORT":
            _canonical_fields(content, ValidationReport)
            for key, cls in (
                ("robustness_cases", RobustnessCaseResult),
                ("files", ValidationArtifactFile),
            ):
                for nested in cast(list[object], content[key]):
                    _typed(nested, cls)
            if content["reproducibility"] is not None:
                _typed(content["reproducibility"], ReproducibilityComparison)
                comparison = cast(dict[str, object], content["reproducibility"])
                content["reproducibility"] = {
                    "original_comparison_hash": sha256_bytes(canonical_json_bytes(comparison)),
                    "exact_content_hash_matches": comparison["exact_content_hash"],
                    **{
                        key: comparison[key]
                        for key in (
                            "passed",
                            "max_absolute_error",
                            "absolute_tolerance",
                            "relative_tolerance",
                        )
                    },
                }
            for gate in cast(list[dict[str, object]], content["gates"]):
                _canonical_fields(gate, GateResult)
                _typed(gate, GateResult)
                _bind_collection(gate, "evidence")
            metrics = []
            for metric in cast(list[dict[str, object]], content["metrics"]):
                _canonical_fields(metric, ValidationMetric)
                _typed(metric, ValidationMetric)
                metrics.append(
                    {
                        "metric": metric["metric"],
                        "value": metric["value"],
                        "original_metric_hash": sha256_bytes(canonical_json_bytes(metric)),
                        "source_sha256": cast(dict[str, object], metric["source"])["sha256"],
                    }
                )
            content["metrics"] = metrics
            _bind_collection(content, "robustness_cases")
            _bind_collection(content, "files")
        elif kind == "RESEARCH_RESULT":
            _canonical_fields(content, ResearchResultManifest)
            for key, cls in (
                ("metrics", ResearchResultMetric),
                ("files", ResearchResultArtifactFile),
                ("source_files", ResearchResultSourceFile),
            ):
                for nested in cast(list[object], content[key]):
                    _typed(nested, cls)
            _bind_collection(content, "files")
            _bind_collection(content, "source_files")
        elif kind != "EVIDENCE":
            raise ValueError("SDK projection node kind outside policy scope")
        item["original_object_hash"] = ref["object_hash"]
        item["presentation"] = content
    for key in ("agent_run_spec", "allowed_proposal_schema_json"):
        original = business.pop(key)
        business[key + "_hash"] = sha256_bytes(
            original.encode("utf-8")
            if isinstance(original, str)
            else canonical_json_bytes(original)
        )
    projected.update(
        request_hash=request.content_hash,
        schema_version=SDK_PROMPT_PROJECTION_IDENTIFIER,
        source_request_schema_version=request.schema_version,
        prompt_projection_identifier=SDK_PROMPT_PROJECTION_IDENTIFIER,
        prompt_projection_hash=SDK_PROMPT_PROJECTION_HASH,
        presentation_authority="PROPOSAL_CONTEXT_ONLY; ORIGINAL_FULL_EVIDENCE_IS_AUTHORITY",
    )
    # Presentation is a separate schema, never a full hosted request or evidence.
    scan_protocol_artifact({"projection": projected})
    return canonical_json_bytes(projected)


def bounded_prompt(request: SdkAgentRequest, profile: SdkProducerProfileV4) -> str:
    prompt = SDK_PROMPT_PREFIX + prompt_projection(request, profile).decode("utf-8")
    if len(prompt.encode("utf-8")) > SDK_PROMPT_PROJECTION_MAX_UTF8_BYTES:
        raise ValueError("SDK projected prompt exceeds explicit UTF-8 bound")
    return prompt
