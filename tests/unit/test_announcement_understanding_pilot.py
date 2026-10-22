"""Targeted offline behavior checks; fixtures confer no extraction qualification."""

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from scripts.announcement_understanding_pilot import (
    Quantity,
    baseline,
    build_request,
    compare,
    import_response,
    load_samples,
    normalize_quantity,
    score,
    validate_response,
)

from quantos.contracts.base import canonical_json_bytes

FIXTURES = Path(__file__).parents[1] / "fixtures/announcement_pilot"


@pytest.fixture
def samples():
    return load_samples(FIXTURES / "samples.json")


def response(sample_id):
    return (FIXTURES / f"{sample_id}-response.json").read_bytes()


def references():
    return json.loads((FIXTURES / "references.json").read_bytes())["references"]


def test_missing_fields_and_refusal_are_retained(samples):
    sample = samples[2]
    malformed = import_response(sample, b"{}", state="CAPTURED", origin="FIXTURE")
    assert malformed["state"] == "FORMAT_FAILED"
    assert malformed["raw_sha256"] is not None
    refused = import_response(
        sample, b'{"refusal":"cannot answer"}', state="REFUSED", origin="FIXTURE"
    )
    assert refused["state"] == "REFUSED" and refused["extraction"] is None


@pytest.mark.parametrize(
    "values,field",
    [
        (("10", "1", "shares"), "cumulative_shares"),
        (("1", "2", "万元"), "cumulative_shares"),
        (("1", "2", "shares"), "cumulative_amount"),
        (("0.5", "0.5", "shares"), "cumulative_shares"),
        (("0.001", "0.001", "CNY"), "cumulative_amount"),
        (("NaN", "1", "CNY"), "cumulative_amount"),
    ],
)
def test_invalid_units_ranges_and_precision(values, field):
    with pytest.raises(ValueError):
        normalize_quantity(
            Quantity(**dict(zip(("lower", "upper", "unit"), values, strict=True))), field
        )


def test_unit_conversion_range_and_explicit_zero(samples):
    value = validate_response(samples[2], response("eval-c"))
    assert normalize_quantity(value.cumulative_shares, "cumulative_shares") == (1000000, 1200000)
    zero = validate_response(samples[3], response("eval-d"))
    assert normalize_quantity(zero.cumulative_amount, "cumulative_amount") == (0, 0)
    assert baseline(samples[0]).cumulative_shares.lower == "100"
    assert baseline(samples[1]).event_present is False


@pytest.mark.parametrize("defect", ["out_of_range", "wrong_hash", "wrong_page", "other_sample"])
def test_citation_and_sample_binding(samples, defect):
    obj = json.loads(response("eval-c"))
    cite = obj["citations"]["issuer"][0]
    if defect == "out_of_range":
        cite["char_end"] = 99999
    elif defect == "wrong_hash":
        cite["cited_text_hash"] = "0" * 64
    elif defect == "wrong_page":
        cite["page"] = 2
    else:
        cite["evidence_hash"] = samples[3].binding.evidence.content_hash
    assert (
        import_response(samples[2], canonical_json_bytes(obj), state="CAPTURED", origin="FIXTURE")[
            "state"
        ]
        == "FORMAT_FAILED"
    )
    with pytest.raises(ValueError, match="cross-sample"):
        validate_response(samples[3], response("eval-c"))


@pytest.mark.parametrize(
    "state", ["REFUSED", "FAILED", "TIMEOUT", "MISSING", "UNKNOWN", "FORMAT_FAILED"]
)
def test_failures_remain_in_denominator(samples, state):
    result = import_response(
        samples[2],
        b"{}" if state == "FORMAT_FAILED" else None,
        state="CAPTURED" if state == "FORMAT_FAILED" else state,
        origin="FIXTURE",
    )
    report = score(samples, [result], references())
    assert report["denominator"] == 4
    assert report["successful_documents"] == 0
    assert report["failure_counts"][state] >= 1
    assert report["target_denominator"] == 2
    assert report["nonnull_quantity_denominators"]["cumulative_shares"] == 2


def test_reference_approval_required_and_request_excludes_labels(samples):
    refs = references()
    refs[0]["approved"] = False
    with pytest.raises(ValueError, match="reference approval"):
        score(samples, [], refs)
    request = build_request(samples[2])
    assert set(request) == {
        "version",
        "sample_id",
        "evidence_hash",
        "extracted_text_hash",
        "text_sha256",
        "text",
        "prompt",
        "response_schema",
        "model_configuration",
        "request_hash",
    }
    assert "SYNTHETIC_FIXTURE_GENERATOR_NOT_HUMAN" not in json.dumps(request)
    assert "evaluation" not in request
    assert request["text"] == samples[2].binding.text


def test_exact_text_does_not_automatically_prove_semantics(samples):
    obj = json.loads(response("eval-c"))
    obj["citations"]["event_present"] = obj["citations"]["issuer"]
    result = import_response(
        samples[2], canonical_json_bytes(obj), state="CAPTURED", origin="FIXTURE"
    )
    assert result["state"] == "CAPTURED"  # location valid, semantics not approved
    report = score(samples, [result], references())
    assert report["rows"][0]["fields"]["event_present"]
    assert not report["rows"][0]["citations"]["event_present"]
    assert not report["rows"][0]["document_success"]


def test_fixture_does_not_become_real_result(samples):
    with pytest.raises(ValueError, match="fixture response"):
        import_response(
            replace(samples[2], source_kind="REAL"),
            response("eval-c"),
            state="CAPTURED",
            origin="FIXTURE",
        )
    refs = references()
    with pytest.raises(ValueError, match="reference approval"):
        score([replace(s, source_kind="REAL") for s in samples], [], refs)


def test_group_leakage_and_duplicate_text_rejected(tmp_path):
    obj = json.loads((FIXTURES / "samples.json").read_bytes())
    obj["samples"][2]["company_group"] = obj["samples"][0]["company_group"]
    path = tmp_path / "samples.json"
    path.write_bytes(canonical_json_bytes(obj))
    with pytest.raises(ValueError, match="cross splits"):
        load_samples(path)
    obj["samples"][2]["company_group"] = "eval-c"
    duplicate = dict(obj["samples"][0], sample_id="different-id")
    obj["samples"].append(duplicate)
    path.write_bytes(canonical_json_bytes(obj))
    with pytest.raises(ValueError, match="duplicate text"):
        load_samples(path)


def test_duplicate_json_keys_rejected(samples):
    result = import_response(
        samples[2], b'{"sample_id":"a","sample_id":"b"}', state="CAPTURED", origin="FIXTURE"
    )
    assert result["state"] == "FORMAT_FAILED"


def test_paired_comparison_keeps_full_split(samples):
    results = [
        import_response(
            s, canonical_json_bytes(baseline(s)), state="CAPTURED", origin="RULE_BASELINE_V1"
        )
        for s in samples
        if s.split == "evaluation"
    ]
    report = compare(samples, results, [], references())
    assert report["paired_denominator"] == 4
    assert report["imported_responses"]["failure_counts"]["MISSING"] == 4
    assert report["document_count_difference"] <= 0


def test_unknown_reference_is_not_a_negative_event_label(samples):
    obj = json.loads(response("eval-f"))
    obj["event_present"], obj["status"] = True, "announced"
    obj["citations"]["event_present"] = obj["citations"]["issuer"]
    obj["citations"]["status"] = obj["citations"]["issuer"]
    result = import_response(
        samples[5], canonical_json_bytes(obj), state="CAPTURED", origin="FIXTURE"
    )
    report = score(samples, [result], references())
    assert report["denominator"] == 4
    assert report["event_labelled_denominator"] == 3
    assert report["unknown_event_denominator"] == 1
    assert report["event_precision"] is None


@pytest.mark.parametrize("scenario", ["unknown", "reuse", "failure"])
def test_existing_sdk_recovery_assertions_in_task_storage(scenario):
    # Reuse existing SDK test assertions and helpers with task-local storage.
    import test_sdk_campaign_producer as old

    from quantos.application.sdk_producer import SdkCampaignProducer, model_configuration
    from quantos.contracts.autonomous import SDK_BOUNDED_FINALIZATION_PROFILE
    from quantos.contracts.base import sha256_bytes
    from quantos.contracts.sdk_producer import SdkCampaignSpec, SdkProducerProfile

    # The producer intentionally rejects /tmp for its authoritative receipts.
    task_path = (
        Path(__file__).resolve().parents[2]
        / "artifacts/announcement-pilot-unit-recovery"
        / uuid4().hex
    )
    task_path.mkdir(parents=True)
    inputs = old._inputs(task_path / "inputs", allow_manual_stop=True)
    cwd = task_path / "empty-cwd"
    cwd.mkdir()
    root = task_path / "sdk-evidence"
    profile = SdkProducerProfile(
        runtime_binary_hash="a" * 64,
        cwd=str(cwd),
        evidence_root=str(root),
        max_launches=3,
        timeout_seconds=30,
        max_input_tokens=1000,
        max_output_tokens=1000,
        max_transcript_bytes=65536,
        max_raw_response_bytes=16384,
        requested_model_configuration_hash="b" * 64,
        skill_hash=inputs.agent_policy.skill_hash,
        instruction_hashes=inputs.agent_policy.instruction_hashes,
    )
    configuration_hash = sha256_bytes(model_configuration(profile))
    profile = profile.model_copy(update={"requested_model_configuration_hash": configuration_hash})
    inputs.agent_policy = inputs.agent_policy.model_copy(
        update={
            "requested_model_configuration_hash": configuration_hash,
            "harness_identifier": "openai-codex-python-sdk",
            "provider_model_identifier": profile.model,
            "model_snapshot_immutable": False,
        }
    )
    inputs.campaign_policy = inputs.campaign_policy.model_copy(
        update={"context_query": "alpha execution_failed"}
    )
    base = old._spec(inputs).model_dump(mode="json")
    base.update(
        schema_version="sdk-campaign-spec/v1",
        profile="sdk-bounded/v1",
        sdk_profile=profile.model_dump(mode="json"),
        selection_finalization_profile_hash=SDK_BOUNDED_FINALIZATION_PROFILE.content_hash,
    )
    spec = SdkCampaignSpec.model_validate(base)
    service = old._service(
        task_path / "business", inputs, spec, selection_profile=SDK_BOUNDED_FINALIZATION_PROFILE
    )
    service.start(spec.content_hash)
    request = service.pending(spec.campaign_hash)
    setup = service, spec, request, SdkCampaignProducer(root), old._Harness(request, profile)
    cases = {
        "unknown": old.test_unknown_launch_never_reissues,
        "reuse": old.test_raw_mapping_submit_replay_and_terminal_feedback,
        "failure": old.test_invalid_semantic_candidate_failure_retains_usage_and_no_reissue,
    }
    cases[scenario](setup)
