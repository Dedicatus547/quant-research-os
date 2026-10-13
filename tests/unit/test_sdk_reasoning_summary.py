"""Summary selection is explicit configuration; fake SDK only, no qualification."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from test_codex_sdk_adapter import _request as _synthetic_request
from test_sdk_campaign_producer import setup as sdk_setup  # noqa: F401

from quantos.application.sdk_producer import build_reservation, model_configuration
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import HarnessExecutionRequest
from quantos.integrations.codex import sdk_host


def test_summary_none_configuration_binding_and_legacy_bytes(sdk_setup):  # noqa: F811
    _service, spec, request, _producer, _harness = sdk_setup
    old_spec = spec.model_dump(mode="json")
    assert "reasoning_summary" not in old_spec["sdk_profile"]
    assert spec.sdk_profile.canonical_bytes() == canonical_json_bytes(old_spec["sdk_profile"])
    old_execution = build_reservation(request, spec).execution_request.model_dump(mode="json")
    assert "reasoning_summary" not in old_execution
    assert HarnessExecutionRequest.model_validate(
        old_execution
    ).canonical_bytes() == canonical_json_bytes(old_execution)
    assert (
        sha256_bytes(model_configuration(spec.sdk_profile))
        == spec.requested_model_configuration_hash
    )

    profile = spec.sdk_profile.model_copy(update={"reasoning_summary": "none"})
    config = model_configuration(profile)
    new_hash = sha256_bytes(config)
    assert new_hash != spec.requested_model_configuration_hash
    assert json.loads(config) == {
        **json.loads(model_configuration(spec.sdk_profile)),
        "reasoning_summary": "none",
    }
    profile = profile.model_copy(update={"requested_model_configuration_hash": new_hash})
    successor = spec.model_copy(
        update={"sdk_profile": profile, "requested_model_configuration_hash": new_hash}
    )
    run_spec = request.business_request.agent_run_spec.model_copy(
        update={"requested_model_configuration_hash": new_hash}
    )
    business = request.business_request.model_copy(update={"agent_run_spec": run_spec})
    rebound = request.model_copy(
        update={
            "hosted_spec_hash": successor.content_hash,
            "sdk_profile_hash": profile.content_hash,
            "business_request": business,
            "input_hashes": tuple(
                sorted(set(successor.frozen_input_hashes) | set(run_spec.input_artifact_hashes))
            ),
        }
    )
    reservation = build_reservation(rebound, successor)
    assert reservation.execution_request.reasoning_summary == "none"
    assert reservation.execution_request.reasoning_effort == "medium"
    assert reservation.execution_request.max_transcript_bytes == 65536
    assert reservation.run_spec.requested_model_configuration_hash == new_hash
    with pytest.raises(ValueError):
        profile.model_validate(
            {**profile.model_dump(mode="python"), "reasoning_summary": "detailed"}
        )


@pytest.mark.parametrize(
    "summary,oversized,cap",
    [
        (None, False, 65536),
        ("none", False, 65536),
        ("none", True, 65536),
        ("none", False, 131072),
        ("none", True, 131072),
    ],
)
def test_host_explicit_summary_preserves_stream_and_cap(monkeypatch, summary, oversized, cap):
    raw = _synthetic_request(Path("/synthetic-cwd")).model_dump(mode="json")
    raw["max_transcript_bytes"] = cap
    request = HarnessExecutionRequest.model_validate(
        {**raw, "model": "synthetic-model", "reasoning_summary": summary}
    )
    observed = {}

    class FakeHandle:
        def stream(self):
            yield SimpleNamespace(
                method="item/reasoning/textDelta",
                payload=SimpleNamespace(
                    params={
                        "delta": "x" * (cap + 1 if oversized else (90000 if cap == 131072 else 8))
                    }
                ),
            )
            yield SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(
                    params={"turn": {"id": "synthetic-turn", "status": "completed"}}
                ),
            )

        def interrupt(self):
            observed["interrupted"] = True

    class FakeThread:
        id = "synthetic-thread"

        def turn(self, _prompt, **kwargs):
            observed["turn_kwargs"] = kwargs
            return FakeHandle()

    class FakeCodex:
        def __init__(self, _config):
            self.metadata = SimpleNamespace(serverInfo=SimpleNamespace(version="0.162.1"))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def account(self, **_kwargs):
            return SimpleNamespace(account=object())

        def thread_start(self, **_kwargs):
            return FakeThread()

    class FakeSummary:
        @staticmethod
        def model_validate(value):
            assert value == "none"
            return ("explicit-reasoning-summary", value)

    codex = ModuleType("openai_codex")
    for name, value in {
        "__version__": "0.162.1",
        "ApprovalMode": SimpleNamespace(deny_all="deny-all"),
        "Sandbox": SimpleNamespace(read_only="read-only"),
        "Codex": FakeCodex,
        "CodexConfig": lambda **kwargs: kwargs,
    }.items():
        setattr(codex, name, value)
    binary = ModuleType("codex_cli_bin")
    binary.bundled_codex_path = lambda: "synthetic-unused-binary"
    generated = ModuleType("openai_codex.generated.v2_all")
    generated.ReasoningEffort = lambda value: value
    generated.ReasoningSummary = FakeSummary
    models = ModuleType("openai_codex.models")
    models.JsonObject = dict
    for name, value in {
        "openai_codex": codex,
        "codex_cli_bin": binary,
        "openai_codex.generated.v2_all": generated,
        "openai_codex.models": models,
    }.items():
        monkeypatch.setitem(sys.modules, name, value)
    monkeypatch.setattr(sdk_host, "version", lambda _name: "0.162.1")
    monkeypatch.setattr(sdk_host, "_sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr(
        sdk_host, "expected_codex_versions", lambda _profile: ("0.162.1", "0.162.1")
    )
    result = sdk_host.execute(request)
    if summary is None:
        assert "summary" not in observed["turn_kwargs"]
    else:
        assert observed["turn_kwargs"]["summary"] == ("explicit-reasoning-summary", "none")
    assert observed["turn_kwargs"]["effort"] == "medium"
    if oversized:
        assert observed["interrupted"] is True
        assert result["error"]["message_hash"] == sha256_bytes(
            b"ValueError: provider transcript exceeds its bound"
        )
    else:
        assert [e["method"] for e in result["provider_events"]] == [
            "item/reasoning/textDelta",
            "turn/completed",
        ]
        assert "error" not in result
