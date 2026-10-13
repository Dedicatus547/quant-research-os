"""Independent, explicit prompt projection policy; no runtime dependencies."""

from quantos.contracts.base import canonical_json_bytes, sha256_bytes

SDK_PROMPT_PROJECTION_IDENTIFIER = "sdk-frozen-context-projection/v1"
SDK_PROMPT_PROJECTION_MAX_UTF8_BYTES = 24576
SDK_PROMPT_PREFIX = (
    "Return one JSON object with schema_version sdk-candidate-reference/v1, "
    "candidate_ref copied exactly from a listed candidate_id, rationale and request_stop. "
    "Use only the frozen options and context below. Do not invoke tools. "
    "Do not compute hashes or copy derived proposal fields. "
    "Agent output is a proposal, never evidence. Frozen request projection:\n"
)
SDK_PROMPT_PROJECTION_POLICY = {
    "identifier": SDK_PROMPT_PROJECTION_IDENTIFIER,
    "max_prompt_utf8_bytes": SDK_PROMPT_PROJECTION_MAX_UTF8_BYTES,
    "prefix": SDK_PROMPT_PREFIX,
    "request": (
        "all fields except business_request; add original request_hash and source request schema; "
        "schema_version identifies this projection"
    ),
    "business": (
        "all fields except allowed_proposal_schema_json and agent_run_spec; bind their hashes"
    ),
    "context": "all metadata; each item original metadata and canonical original object hash",
    "EVIDENCE": "complete canonical object, no truncation",
    "CAMPAIGN_TRIAL": "complete campaign-trial/v1 canonical object, no truncation",
    "VALIDATION_REPORT": {
        "schema": "validation-report/v2",
        "retained": (
            "all canonical fields except files, robustness_cases, gates, metrics "
            "and reproducibility"
        ),
        "gates": "all fields except evidence; evidence canonical hash and count",
        "metrics": "metric and value; original metric canonical hash and source artifact sha256",
        "reproducibility": (
            "original comparison hash, passed, max_absolute_error, absolute_tolerance, "
            "relative_tolerance and exact_content_hash renamed exact_content_hash_matches"
        ),
        "robustness_cases": "canonical collection hash and count",
        "files": "canonical collection hash and count",
    },
    "RESEARCH_RESULT": {
        "schema": "research-result-manifest/v1",
        "retained": "all canonical fields except files and source_files",
        "files": "canonical collection hash and count",
        "source_files": "canonical collection hash and count",
    },
    "unknown_scope": "reject unknown node kind, schema or canonical object fields",
    "overflow": "reject; never truncate, replace source or alter predicates",
    "authority": "presentation only; original full verifiers and evidence remain authority",
}
SDK_PROMPT_PROJECTION_POLICY_BYTES = canonical_json_bytes(SDK_PROMPT_PROJECTION_POLICY)
SDK_PROMPT_PROJECTION_HASH = sha256_bytes(SDK_PROMPT_PROJECTION_POLICY_BYTES)
