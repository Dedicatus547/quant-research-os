"""Directed offline projection checks; mocks grant no live SDK qualification."""

import json

import pytest
from test_sdk_campaign_producer import _Harness
from test_sdk_campaign_producer import setup as sdk_setup  # noqa: F401
from test_sdk_capture_v3 import _successor

from quantos.application.sdk_producer import build_reservation, model_configuration
from quantos.application.sdk_prompt import bounded_prompt, prompt_projection
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.ledger import ResearchLedgerNodeKind
from quantos.contracts.sdk_producer import SdkCampaignSpec, SdkProducerProfileV4
from quantos.contracts.sdk_prompt import (
    SDK_PROMPT_PROJECTION_HASH,
    SDK_PROMPT_PROJECTION_IDENTIFIER,
)


def successor_v4(spec, request):
    profile = SdkProducerProfileV4.model_validate(
        {
            **spec.sdk_profile.model_dump(mode="python"),
            "schema_version": "sdk-producer-profile/v4",
            "prompt_projection_identifier": SDK_PROMPT_PROJECTION_IDENTIFIER,
            "prompt_projection_hash": SDK_PROMPT_PROJECTION_HASH,
        }
    )
    profile = profile.model_copy(
        update={"requested_model_configuration_hash": sha256_bytes(model_configuration(profile))}
    )
    spec = SdkCampaignSpec.model_validate(
        {
            **spec.model_dump(mode="python"),
            "sdk_profile": profile,
            "requested_model_configuration_hash": profile.requested_model_configuration_hash,
        }
    )
    run_spec = request.business_request.agent_run_spec.model_copy(
        update={"requested_model_configuration_hash": profile.requested_model_configuration_hash}
    )
    business = request.business_request.model_copy(update={"agent_run_spec": run_spec})
    request = request.model_copy(
        update={
            "sdk_profile_hash": profile.content_hash,
            "hosted_spec_hash": spec.content_hash,
            "business_request": business,
            "business_request_hash": business.content_hash,
            "input_hashes": tuple(
                sorted({*spec.frozen_input_hashes, *run_spec.input_artifact_hashes})
            ),
        }
    )
    return spec, request


def test_v4_reservation_response_and_legacy_full_request(sdk_setup, tmp_path):  # noqa: F811
    v3, original, producer, _protocol = _successor(sdk_setup, tmp_path)
    old = build_reservation(original, v3)
    assert old.execution_request.prompt.endswith(original.canonical_bytes().decode())
    spec, request = successor_v4(v3, original)
    reservation = build_reservation(request, spec)
    projection = prompt_projection(request, spec.sdk_profile)
    assert reservation.execution_request.prompt == bounded_prompt(request, spec.sdk_profile)
    assert projection == prompt_projection(request, spec.sdk_profile)
    assert json.loads(projection)["request_hash"] == request.content_hash
    assert json.loads(projection)["business_request"]["candidate_options"] == json.loads(
        request.canonical_bytes()
    )["business_request"]["candidate_options"]
    assert reservation.execution_request.content_hash in reservation.run_spec.input_artifact_hashes
    assert spec.sdk_profile.content_hash in reservation.run_spec.input_artifact_hashes
    assert len(reservation.execution_request.prompt.encode()) <= 24576
    assert reservation.execution_request.max_transcript_bytes == 262144
    assert reservation.execution_request.max_normalized_transcript_bytes == 65536
    assert request.max_response_bytes == 524288
    assert producer.launch(request, spec, harness=_Harness(request, spec.sdk_profile)) == (
        producer.replay(request, spec)
    )
    assert build_reservation(original, v3) == old
    with pytest.raises(ArtifactIntegrityError, match="frozen profile"):
        build_reservation(original, spec)


@pytest.mark.parametrize("field", ["prompt_projection_hash", "prompt_projection_identifier"])
def test_v4_policy_mismatch_rejects(sdk_setup, tmp_path, field):  # noqa: F811
    spec, request, *_ = _successor(sdk_setup, tmp_path)
    spec, request = successor_v4(spec, request)
    values = spec.sdk_profile.model_dump(mode="python")
    values[field] = "0" * 64
    with pytest.raises(ValueError):
        SdkProducerProfileV4.model_validate(values)
    corrupt = spec.sdk_profile.model_copy(update={field: "0" * 64})
    with pytest.raises(ValueError):
        prompt_projection(request, corrupt)


def _content(request, raw, kind=None):
    item = request.business_request.context_pack.items[0]
    updates = {
        "content": raw.decode(),
        "content_bytes": len(raw),
        "object_ref": item.object_ref.model_copy(update={"object_hash": sha256_bytes(raw)}),
    }
    if kind is not None:
        updates["node_kind"] = ResearchLedgerNodeKind(kind)
    item = item.model_copy(update=updates)
    context = request.business_request.context_pack.model_copy(
        update={"items": (item,), "included_content_bytes": len(raw)}
    )
    business = request.business_request.model_copy(update={"context_pack": context})
    return request.model_copy(update={"business_request": business})


def test_v4_secret_unknown_scope_and_original_hash_rejections(sdk_setup, tmp_path):  # noqa: F811
    spec, request, *_ = _successor(sdk_setup, tmp_path)
    spec, request = successor_v4(spec, request)
    for raw, kind in (
        (canonical_json_bytes({"api_key": "offline-sensitive-value"}), None),
        (canonical_json_bytes({"schema_version": "unsupported-report/v9"}), "VALIDATION_REPORT"),
        (canonical_json_bytes({"task": "unknown"}), "OBSERVATION"),
    ):
        with pytest.raises(ValueError):
            prompt_projection(_content(request, raw, kind), spec.sdk_profile)
    item = request.business_request.context_pack.items[0]
    wrong_ref = item.object_ref.model_copy(update={"object_hash": "0" * 64})
    context = request.business_request.context_pack.model_copy(
        update={"items": (item.model_copy(update={"object_ref": wrong_ref}),)}
    )
    business = request.business_request.model_copy(update={"context_pack": context})
    with pytest.raises(ValueError, match="original object binding"):
        prompt_projection(
            request.model_copy(update={"business_request": business}), spec.sdk_profile
        )


def test_v4_bound_counts_utf8_without_truncation(sdk_setup, tmp_path):  # noqa: F811
    spec, request, *_ = _successor(sdk_setup, tmp_path)
    spec, request = successor_v4(spec, request)
    # An ASCII string fitting the byte allowance cannot conceal a multibyte overflow.
    ascii_request = _content(request, canonical_json_bytes({"task": "x" * 7000}))
    assert len(bounded_prompt(ascii_request, spec.sdk_profile).encode()) <= 24576
    utf8_request = _content(request, canonical_json_bytes({"task": "界" * 7000}))
    assert "界" * 7000 in prompt_projection(utf8_request, spec.sdk_profile).decode()
    with pytest.raises(ValueError, match="UTF-8 bound"):
        bounded_prompt(utf8_request, spec.sdk_profile)


def test_v4_loader_and_namespace_reuse_explicit_v3_capture(sdk_setup, tmp_path, monkeypatch):  # noqa: F811
    import test_sdk_capture_v3 as existing

    original_successor = existing._successor

    def v4(values, path):
        spec, request, producer, protocol = original_successor(values, path)
        spec, request = successor_v4(spec, request)
        return spec, request, producer, protocol

    monkeypatch.setattr(existing, "_successor", v4)
    existing.test_v3_namespace_frozen_tuple_and_cli_parse_are_offline(sdk_setup, tmp_path)
    existing.test_v3_loader_projects_only_explicit_frame_delta_from_verified_bundle(
        sdk_setup, tmp_path, monkeypatch, False
    )
