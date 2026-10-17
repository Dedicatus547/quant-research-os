"""Offline regression for retained metadata failure; no provider or scientific work."""

import copy
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_codex_sdk_adapter import _request, _response
from test_sdk_campaign_producer import setup as sdk_setup  # noqa: F401

from quantos.application.agent_harness import HarnessExecutionResult, capture_from_agent_events
from quantos.application.bounded_runtime import runtime_summary
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import HarnessErrorKind
from quantos.integrations.codex import event_normalizer as frozen
from quantos.integrations.codex import notification_projection as projection
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter


def _events():
    events = json.loads(_response())["provider_events"]
    events.insert(
        1,
        {
            "method": projection.METHOD,
            "payload": {
                "thread_id": "thread-test",
                "turn_id": "turn-test",
                "metadata": {"prompt": {"outputs": [{"is_blocked": False}]}},
            },
        },
    )
    events[-2]["payload"].update(thread_id="thread-test", turn_id="turn-test")
    return events


def test_retained_failure_original_projects_without_republishing(record_property):
    source = os.environ.get("QUANTOS_BOUNDED_RETAINED_PROVIDER")
    if source is None:
        pytest.skip("Explicit retained-original path required; never acquire a new capture")
    raw = Path(source).read_bytes()
    expected_hash = "49f37974be26ff83b7a5b47f7b6db934f8b60d57fab1e04659e6d788bf829852"
    assert sha256_bytes(raw) == expected_hash
    events = projection.provider_events(raw)
    thread_id = events[0]["payload"]["thread_id"]
    with pytest.raises(frozen.CodexEventNormalizationError, match="turn/moderationMetadata"):
        frozen.normalize_provider_events(events, thread_id=thread_id)
    capture = capture_from_agent_events(
        projection.normalize_provider_events(events, thread_id=thread_id), max_bytes=65536
    )
    final = next(e["payload"]["turn"] for e in events if e["method"] == "turn/completed")
    assert capture.agent_messages == (final["items"][0]["text"],)
    assert capture.turn_completed and not capture.turn_failed
    assert capture.usage == {"input_tokens": 19738, "output_tokens": 117, "cached_input_tokens": 0}
    assert projection.observe_usage(events)["usage"] == {
        "input_count": 19738,
        "output_count": 117,
        "cached_input_count": 0,
    }
    assert Path(source).read_bytes() == raw
    record_property("origin_provider_sha256", expected_hash)
    record_property("offline_projection_only", True)


def test_plain_stream_keeps_frozen_v2_bytes_and_metadata_binds_successor():
    events = _events()
    plain = [event for event in events if event["method"] != projection.METHOD]
    expected = frozen.normalize_provider_events(plain, thread_id="thread-test")
    assert projection.normalize_provider_events(plain, thread_id="thread-test") == expected
    base_hash = sha256_bytes(Path(frozen.__file__).read_bytes())
    assert projection.source_hash(plain) == base_hash
    assert projection.source_hash(events) != base_hash
    assert projection.normalize_provider_events(events, thread_id="thread-test") == expected


@pytest.mark.parametrize(
    "defect",
    [
        "thread",
        "turn",
        "extra",
        "metadata_type",
        "blocked",
        "block_flag_type",
        "before_start",
        "after_terminal",
        "overlap",
        "terminal_turn",
        "turn_thread",
        "unknown_method",
        "unknown_item",
    ],
)
def test_metadata_and_unknown_events_fail_closed(defect):
    events = _events()
    body = events[1]["payload"]
    if defect in {"thread", "turn"}:
        body[defect + "_id"] = "unrelated"
    elif defect == "extra":
        body["unexpected"] = True
    elif defect == "metadata_type":
        body["metadata"] = []
    elif defect in {"blocked", "block_flag_type"}:
        body["metadata"]["prompt"]["outputs"][0]["is_blocked"] = (
            True if defect == "blocked" else "false"
        )
    elif defect == "before_start":
        events.insert(0, events.pop(1))
    elif defect == "after_terminal":
        events.append(events.pop(1))
    elif defect == "overlap":
        events.insert(1, copy.deepcopy(events[0]))
    elif defect == "terminal_turn":
        events[-1]["payload"]["turn"]["id"] = "unrelated"
    elif defect == "turn_thread":
        events[0]["payload"]["thread_id"] = "unrelated"
    elif defect == "unknown_method":
        events.insert(2, {"method": "future/unknown", "payload": {}})
    else:
        events.insert(2, {"method": "item/completed", "payload": {"item": {"type": "future"}}})
    with pytest.raises(frozen.CodexEventNormalizationError):
        projection.normalize_provider_events(events, thread_id="thread-test")


@pytest.mark.parametrize(
    "defect", ["missing", "bool", "negative", "float", "thread", "turn", "two_turns"]
)
def test_unavailable_and_unattributable_usage_is_not_zero(defect):
    events = _events()
    snapshot = events[-2]["payload"]
    if defect == "missing":
        events.pop(-2)
    elif defect in {"bool", "negative", "float"}:
        snapshot["token_usage"]["last"]["input_tokens"] = {
            "bool": True,
            "negative": -1,
            "float": 1.5,
        }[defect]
    elif defect in {"thread", "turn"}:
        snapshot[defect + "_id"] = "unrelated"
    else:
        events.insert(1, copy.deepcopy(events[0]))
    observed = projection.observe_usage(events)
    assert observed["usage"] is None
    assert observed["status"] == (
        "UNAVAILABLE" if defect == "missing" else "INVALID_OR_UNATTRIBUTABLE"
    )


def test_usage_snapshots_are_not_added_and_explicit_zero_is_observed():
    events = _events()
    earlier = copy.deepcopy(events[-2])
    earlier["payload"]["token_usage"]["last"]["input_tokens"] = 1
    events.insert(-2, earlier)
    assert projection.observe_usage(events)["usage"]["input_count"] == 10
    assert projection.observe_usage(events)["notifications"] == 2
    events[-2]["payload"]["token_usage"]["last"] = dict.fromkeys(projection.USAGE_KEYS, 0)
    assert projection.observe_usage(events)["status"] == "OBSERVED"
    assert projection.observe_usage(events)["usage"]["input_count"] == 0


@pytest.mark.parametrize(
    "mode", ["success", "frozen_default", "nonzero", "timeout", "unobserved_exit"]
)
def test_fake_host_process_exit_is_independent_of_provider_turn(tmp_path, monkeypatch, mode):
    body = json.loads(_response())
    body["provider_events"] = _events()

    class FakeProcess:
        returncode = 4 if mode == "nonzero" else None if mode == "unobserved_exit" else 0
        pid = 123

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, payload, timeout):
            if mode in {"timeout", "unobserved_exit"}:
                self.returncode = None
                raise subprocess.TimeoutExpired("fake-sdk-host", timeout)
            return canonical_json_bytes(body), b""

    def terminate(process):
        if mode != "unobserved_exit":
            process.returncode = -9

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(CodexSdkAdapter, "_terminate_process_group", staticmethod(terminate))
    adapter = CodexSdkAdapter(
        authentication_home=tmp_path, metadata_projection=mode != "frozen_default"
    )
    result = adapter.execute(_request(tmp_path))
    exit_record = result.attempts[-1].qualification_observations["host_process_exit"]
    expected = {
        "success": 0,
        "frozen_default": 0,
        "nonzero": 4,
        "timeout": -9,
        "unobserved_exit": None,
    }[mode]
    assert exit_record["spawned"] is True
    assert exit_record["return_code"] == expected
    assert exit_record["wait_observed"] is (expected is not None)
    assert (result.terminal_error is None) is (mode == "success")


def _failed_launch(setup_values, monkeypatch, *, unsafe=False):
    service, spec, request, producer, harness = setup_values
    original_execute = harness.execute

    def execute(execution_request):
        result = original_execute(execution_request)
        events = list(projection.provider_events(result.provider_transcript))
        events[-2]["payload"].update(thread_id="thread-sdk", turn_id="turn-sdk")
        if unsafe:
            monkeypatch.setenv("P10_FORBIDDEN_SECRET", "synthetic-capture-parent-marker")
            events[1]["payload"]["item"]["text"] = "synthetic-capture-parent-marker"
        return HarnessExecutionResult(
            attempts=(
                replace(
                    CodexSdkAdapter._failed_result(
                        HarnessErrorKind.PROTOCOL_UNSUPPORTED,
                        ValueError("offline normalization fault"),
                        runtime=result.runtime,
                        provider_transcript=b"".join(
                            canonical_json_bytes(e) + b"\n" for e in events
                        ),
                    ),
                    qualification_observations={
                        "host_process_exit": {
                            "schema_version": "sdk-host-process-exit/v1",
                            "spawned": True,
                            "wait_observed": True,
                            "return_code": 0,
                        }
                    },
                ),
            )
        )

    monkeypatch.setattr(harness, "execute", execute)
    with pytest.raises(ArtifactIntegrityError):
        producer.launch(request, spec, harness=harness)
    root = producer.root / request.campaign_hash / request.content_hash
    return service, spec, request, producer, harness, root


def test_failed_normalization_keeps_nonzero_provider_usage_and_actual_exit(sdk_setup, monkeypatch):  # noqa: F811
    service, spec, request, producer, harness, root = _failed_launch(sdk_setup, monkeypatch)
    summary = runtime_summary(service, producer, spec, "FAILED")
    assert summary["sdk_observed_usage"]["input_tokens"] == 0
    observation = summary["sdk_provider_observations"][0]
    assert observation["provider_usage"]["usage"]["input_count"] == 10
    assert observation["process_exit"]["return_code"] == 0
    assert summary["producer_state"] == "FAILED"
    assert summary["research_budget"]["used_executions"] == 0
    with pytest.raises(ArtifactIntegrityError, match="reissue forbidden"):
        producer.launch(request, spec, harness=harness)
    assert harness.calls == 1
    assert (
        json.loads((root / "sdk-observation.json").read_bytes())["usage_observation"]["status"]
        == "OBSERVED"
    )


@pytest.mark.parametrize(
    "target",
    [
        "sdk-observation.json",
        "capture-fact.json",
        "provider-transcript.jsonl",
        "sdk-process-exit.json",
    ],
)
def test_observation_original_tamper_is_rejected(sdk_setup, monkeypatch, target):  # noqa: F811
    service, spec, _, producer, _, root = _failed_launch(sdk_setup, monkeypatch)
    # Corrupt only this isolated synthetic case, never the retained real campaign.
    path = root / target
    if target == "capture-fact.json":
        fact = json.loads(path.read_bytes())
        fact["sdk_observation_hash"] = "0" * 64
        path.write_bytes(canonical_json_bytes(fact))
    else:
        path.write_bytes(path.read_bytes().rstrip() + b" \n")
    with pytest.raises(ArtifactIntegrityError):
        runtime_summary(service, producer, spec, "TAMPERED")


def test_capture_secret_rejection_still_retains_actual_process_exit(sdk_setup, monkeypatch):  # noqa: F811
    service, spec, _, producer, _, root = _failed_launch(sdk_setup, monkeypatch, unsafe=True)
    assert not (root / "provider-transcript.jsonl").exists()
    assert not (root / "agent-run-manifest.json").exists()
    assert json.loads((root / "sdk-process-exit.json").read_bytes())["return_code"] == 0
    summary = runtime_summary(service, producer, spec, "FAILED")
    assert summary["sdk_provider_observations"][0]["provider_usage"]["usage"] is None
    for path in root.iterdir():
        if path.is_file():
            assert b"synthetic-capture-parent-marker" not in path.read_bytes()


def test_bounded_producer_publishes_and_replays_projected_synthetic_response(
    sdk_setup,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    from quantos.application import sdk_producer

    service, spec, request, producer, harness = sdk_setup
    execution = harness.execute(sdk_producer.build_reservation(request, spec).execution_request)
    events = list(projection.provider_events(execution.provider_transcript))
    events.insert(
        1,
        {
            "method": projection.METHOD,
            "payload": {"thread_id": "thread-sdk", "turn_id": "turn-sdk", "metadata": {}},
        },
    )
    events[-2]["payload"].update(thread_id="thread-sdk", turn_id="turn-sdk")
    body = {
        "provider_events": events,
        "thread_id": "thread-sdk",
        "runtime_package_version": "0.162.1",
        "runtime_version": "0.162.1 offline-test",
        "runtime_binary_hash": spec.sdk_profile.runtime_binary_hash,
        "sdk_version": "0.162.1",
    }

    class FakeProcess:
        returncode = 0
        pid = 123

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, payload, timeout):
            return canonical_json_bytes(body), b""

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    adapter = CodexSdkAdapter(authentication_home=tmp_path, metadata_projection=True)
    response = producer.launch(request, spec, harness=adapter)
    assert response.manifest.normalizer_hash == projection.source_hash(events)
    assert response.manifest.normalizer_hash != sha256_bytes(Path(frozen.__file__).read_bytes())
    assert response.manifest.aggregate_usage.input_tokens == 10
    assert producer.replay(request, spec) == response
    assert (
        runtime_summary(service, producer, spec, "SYNTHETIC")["research_budget"]["used_executions"]
        == 0
    )
