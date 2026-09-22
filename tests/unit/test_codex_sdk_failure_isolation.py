from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from openai_codex import client as codex_client

SCRIPT = Path(__file__).parents[2] / "scripts" / "codex_sdk_failure_isolation.py"
SPEC = importlib.util.spec_from_file_location("codex_sdk_failure_isolation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_config: Any = MODULE._config
_classify_matrix: Any = MODULE._classify_matrix
_summarize: Any = MODULE._summarize
_verify_matrix: Any = MODULE.verify_matrix
_verify_raw_matrix: Any = MODULE.verify_raw_matrix
_run_command_exec_probe: Any = MODULE.run_command_exec_probe
PINNED_SDK_VERSION: str = MODULE.PINNED_SDK_VERSION
PINNED_RUNTIME_PACKAGE_VERSION: str = MODULE.PINNED_RUNTIME_PACKAGE_VERSION


def test_diagnostic_variants_are_explicit_and_minimal() -> None:
    assert PINNED_SDK_VERSION == "0.154.0"
    assert "features" not in _config("default")
    assert _config("shell-on-unified-default")["features"] == {"shell_tool": True}
    assert _config("shell-on-unified-off")["features"] == {
        "shell_tool": True,
        "unified_exec": False,
    }
    assert _config("shell-off")["features"] == {"shell_tool": False}


def test_diagnostic_summary_uses_raw_command_events() -> None:
    events = [
        {
            "method": "turn/started",
            "payload": {
                "thread_id": "thread-1",
                "turn": {"status": "inProgress"},
            },
        },
        {
            "method": "item/started",
            "payload": {
                "thread_id": "thread-1",
                "item": {"type": "commandExecution"},
            },
        },
        {
            "method": "turn/completed",
            "payload": {
                "thread_id": "thread-1",
                "turn": {"status": "completed"},
            },
        },
    ]

    result = _summarize(
        events,
        sdk_version="0.154.0",
        runtime_package_version="0.154.0",
        runtime_version="0.154.0 test",
        runtime_binary_hash="a" * 64,
        variant="default",
        config_hash="b" * 64,
    )

    assert result["decision"] == "SHELL_OBSERVED"
    assert result["command_count"] == 1
    assert result["instruction_sources"] is None


def test_raw_wire_fixture_captures_final_sdk_payload() -> None:
    fixture = MODULE._build_raw_wire_fixture("default", expected_sdk_version="0.154.0")
    requests = fixture["requests"]

    assert requests["initialize"]["params"]["clientInfo"] == {
        "name": "codex_python_sdk",
        "title": "Codex Python SDK",
        "version": "0.154.0",
    }
    assert requests["account_read"]["params"] == {"refreshToken": False}
    assert requests["thread_start"]["params"]["model"] == "gpt-5.6-sol"
    turn_params = requests["turn_start"]["params"]
    assert turn_params["approvalPolicy"] == "never"
    assert "model" not in turn_params
    assert turn_params["input"] == [{"type": "text", "text": MODULE.PROMPT}]
    assert turn_params["sandboxPolicy"] == {
        "networkAccess": False,
        "type": "readOnly",
    }


def _raw_provider_events(command: bool = True) -> list[dict[str, object]]:
    events: list[dict[str, object]] = [
        {
            "method": "turn/started",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "inProgress"},
            },
        }
    ]
    if command:
        events.extend(
            [
                {
                    "method": "item/started",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "item": {
                            "id": "command-1",
                            "type": "commandExecution",
                            "status": "inProgress",
                        },
                    },
                },
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "item": {
                            "id": "command-1",
                            "type": "commandExecution",
                            "status": "completed",
                            "exitCode": 0,
                        },
                    },
                },
            ]
        )
    events.append(
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        }
    )
    return events


def test_raw_event_summary_requires_scoped_complete_lifecycle() -> None:
    summary = MODULE._raw_event_summary(
        _raw_provider_events(), thread_id="thread-1", turn_id="turn-1"
    )

    assert summary["command_started_count"] == 1
    assert summary["command_completed_count"] == 1
    assert summary["command_succeeded_count"] == 1
    assert summary["reference_integrity"] is True
    assert summary["lifecycle_integrity"] is True

    mismatched = _raw_provider_events()
    mismatched[1]["params"]["turnId"] = "other-turn"
    invalid = MODULE._raw_event_summary(mismatched, thread_id="thread-1", turn_id="turn-1")
    assert invalid["reference_integrity"] is False
    assert invalid["integrity_error"] == "CROSS_TURN_EVENT"


def test_raw_event_summary_accepts_post_terminal_command_lifecycle() -> None:
    events = _raw_provider_events(command=False)
    command_events = _raw_provider_events(command=True)[1:3]
    events.extend(command_events)

    summary = MODULE._raw_event_summary(events, thread_id="thread-1", turn_id="turn-1")

    assert summary["reference_integrity"] is True
    assert summary["lifecycle_integrity"] is True
    assert summary["command_started_count"] == 1
    assert summary["command_completed_count"] == 1
    assert summary["post_terminal_event_count"] == 2
    assert summary["post_terminal_item_event_count"] == 2
    assert summary["post_terminal_command_event_count"] == 2


def test_raw_turn_drains_notifications_after_terminal() -> None:
    class FakeRawClient:
        def __init__(self) -> None:
            self.messages = iter(
                [
                    {"id": 3, "result": {"turn": {"id": "turn-1"}}},
                    _raw_provider_events(command=False)[-1],
                    *_raw_provider_events(command=True)[1:3],
                ]
            )

        def send(self, _message: dict[str, object]) -> None:
            pass

        def next_message(self, *, deadline: float) -> dict[str, object]:
            del deadline
            try:
                return next(self.messages)
            except StopIteration as error:
                raise TimeoutError("quiet window elapsed") from error

    client = FakeRawClient()
    _response, events, turn_id = MODULE._RawAppServer.turn(
        client,
        {"id": 3},
        expected_thread_id="thread-1",
        deadline=MODULE.time.monotonic() + 1,
    )

    assert turn_id == "turn-1"
    assert [event["method"] for event in events] == [
        "turn/completed",
        "item/started",
        "item/completed",
    ]


def test_raw_artifact_guard_rejects_secret_markers() -> None:
    with pytest.raises(RuntimeError, match="prohibited secret marker"):
        MODULE._safe_artifact_payload("provider event", b'{"access_token":"must-not-be-persisted"}')


def _d07_source_fixture() -> dict[str, bytes]:
    feature_specs = "\n".join(
        f"FeatureSpec {{ id: Feature::{name}, default_enabled: {enabled}, }}"
        for name, enabled in (
            ("CodeModeHost", "true"),
            ("ExecutedToolCallMetadata", "false"),
            ("ShellTool", "true"),
            ("UnifiedExec", "true"),
        )
    )
    values = {
        "codex-rs/models-manager/models.json": json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.6-sol",
                        "tool_mode": "code_mode_only",
                        "use_responses_lite": True,
                        "shell_type": "unified_exec",
                    }
                ]
            }
        ),
        "codex-rs/model-provider-info/src/lib.rs": " ".join(
            (
                'const OPENAI_PROVIDER_NAME: &str = "OpenAI";',
                "pub fn is_openai(&self) -> bool",
                "self.name == OPENAI_PROVIDER_NAME",
            )
        ),
        "codex-rs/core/src/tools/mod.rs": " ".join(
            (
                "model_info.tool_mode.unwrap_or_else(||",
                "Feature::CodeModeOnly",
                "ToolMode::CodeModeOnly",
                "requested_tool_mode == ToolMode::CodeMode",
            )
        ),
        "codex-rs/core/src/tools/spec_plan.rs": " ".join(
            (
                "if is_hidden_by_code_mode_only(turn_context, model_info, &tool_name, exposure)",
                "tool_mode == ToolMode::CodeModeOnly",
                "register_code_mode_executors(turn_context, model_info, &mut registry)",
                "registry.prepend_trusted(Arc::new(CodeModeWaitHandler))",
                "registry.prepend_trusted(Arc::new(execute_handler))",
                "!features.enabled(Feature::ShellTool)",
                "registry.add(ExecCommandHandler::new(options))",
                "registry.add(ExecCommandHandler::one_shot(options))",
            )
        ),
        "codex-rs/core/src/client.rs": " ".join(
            (
                "let (instructions, tools) = if model_info.use_responses_lite",
                "ResponseItem::AdditionalTools",
                "(String::new(), None)",
                "tools,",
                "let is_openai = self.state.provider.info().is_openai();",
                "if !is_openai",
                "item.clear_internal_chat_message_metadata_passthrough();",
            )
        ),
        "codex-rs/core/src/tools/code_mode/mod.rs": (
            "fn submit_nested_tool( handle_tool_call_with_source( ToolCallSource::CodeMode"
        ),
        "codex-rs/features/src/lib.rs": feature_specs,
        "codex-rs/core/tests/suite/code_mode.rs": (
            "code-mode-only must retain code-mode tools "
            "code-mode-only must never expose direct shell tools ev_custom_tool_call( "
            'text(JSON.stringify(await tools.exec_command({ cmd: "printf '
            'code_mode_exec_marker" }))) metadata["executed_tool_calls"] '
            'metadata.get("tool_calls_complete") metadata.get("cell_id")'
        ),
        "codex-rs/app-server/tests/suite/v2/code_mode_host.rs": "code_mode host",
    }
    return {name: value.encode() for name, value in values.items()}


def test_d07_source_characterization_is_mechanical_and_fail_closed() -> None:
    architecture, manifest = MODULE._characterize_d07_source_files(
        _d07_source_fixture(),
        expected_sdk_version="0.154.0",
        parser_sha256="a" * 64,
    )

    assert architecture["tool_mode"] == "code_mode_only"
    assert architecture["use_responses_lite"] is True
    assert architecture["executed_tool_call_metadata_enabled_by_default"] is False
    assert architecture["executed_tool_call_metadata_requires_openai_provider_name"] is True
    assert architecture["non_openai_provider_strips_executed_tool_call_metadata"] is True
    assert architecture["responses_lite"] == {
        "request_tools_expected": "ABSENT_OR_NULL",
        "additional_tools_expected": True,
    }
    assert manifest["release_commit"] == MODULE.D07_RELEASES["0.154.0"]["release_commit"]

    broken = _d07_source_fixture()
    broken["codex-rs/core/src/client.rs"] = b"unknown request construction"
    with pytest.raises(RuntimeError, match="source shape"):
        MODULE._characterize_d07_source_files(
            broken,
            expected_sdk_version="0.154.0",
            parser_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("tools_value", "expected"),
    [
        pytest.param(None, "ABSENT", id="absent"),
        (None, "NULL"),
        ([], "EMPTY"),
        ([{}], "NONEMPTY"),
    ],
)
def test_d07_request_projection_preserves_tools_state(
    tools_value: object, expected: str, request: pytest.FixtureRequest
) -> None:
    payload: dict[str, object] = {
        "model": MODULE.MODEL_IDENTIFIER,
        "input": [
            {
                "type": "additional_tools",
                "tools": [
                    {"name": "wait", "description": "wait"},
                    {"name": "exec", "description": "execute"},
                ],
            }
        ],
    }
    if request.node.callspec.id != "absent":
        payload["tools"] = tools_value
    projection = MODULE._project_d07_request(MODULE.canonical_json_bytes(payload), ordinal=1)

    assert projection["request_tools_state"] == expected
    assert projection["model_visible_tool_names"] == ["exec", "wait"]
    assert projection["exec_visibility"] == "OBSERVED_TRUE"
    assert projection["wait_visibility"] == "OBSERVED_TRUE"


def test_d07_request_projection_rejects_duplicate_tools() -> None:
    payload = {
        "model": MODULE.MODEL_IDENTIFIER,
        "input": [
            {
                "type": "additional_tools",
                "tools": [{"name": "exec"}, {"name": "exec"}],
            }
        ],
    }
    with pytest.raises(RuntimeError, match="duplicated"):
        MODULE._project_d07_request(MODULE.canonical_json_bytes(payload), ordinal=1)


def test_d07_request_projection_flattens_responses_lite_namespaces() -> None:
    payload = {
        "model": MODULE.MODEL_IDENTIFIER,
        "input": [
            {
                "type": "additional_tools",
                "tools": [
                    {
                        "type": "namespace",
                        "name": "functions",
                        "tools": [{"name": "wait"}, {"name": "exec"}],
                    },
                    {
                        "type": "namespace",
                        "name": "collaboration",
                        "tools": [{"name": "spawn_agent"}],
                    },
                ],
            }
        ],
    }
    projection = MODULE._project_d07_request(MODULE.canonical_json_bytes(payload), ordinal=1)

    assert projection["additional_tools_count"] == 2
    assert projection["model_visible_tool_names"] == ["exec", "spawn_agent", "wait"]
    assert projection["exec_visibility"] == "OBSERVED_TRUE"


def test_d07_request_projection_keeps_only_safe_nested_execution_evidence() -> None:
    nested_result = {
        "chunk_id": "chunk-safe",
        "exit_code": 0,
        "output": MODULE.D07_NESTED_EXEC_MARKER,
        "wall_time_seconds": 0.01,
    }
    payload = {
        "model": MODULE.MODEL_IDENTIFIER,
        "input": [
            {
                "type": "custom_tool_call_output",
                "call_id": "d07-exec-call-1",
                "output": [
                    {"type": "input_text", "text": "Script completed"},
                    {"type": "input_text", "text": json.dumps(nested_result)},
                ],
                "internal_chat_message_metadata_passthrough": {
                    "cell_id": "d07-exec-call-1",
                    "executed_tool_calls": [
                        {
                            "name": "exec_command",
                            "arguments": {"cmd": MODULE.D07_NESTED_EXEC_COMMAND},
                        }
                    ],
                    "tool_calls_complete": True,
                },
            }
        ],
    }

    projection = MODULE._project_d07_request(MODULE.canonical_json_bytes(payload), ordinal=2)
    observation = projection["tool_output_observations"][0]

    assert observation["nested_result_present"] is True
    assert observation["nested_output_marker_match"] is True
    assert observation["nested_exit_code_zero"] is True
    assert observation["nested_chunk_id_nonempty"] is True
    assert observation["nested_exec_command_dispatched"] is True
    assert "output_sha256" not in observation
    assert MODULE.D07_NESTED_EXEC_MARKER not in json.dumps(projection)


def test_d07_metadata_variant_is_explicit_in_config() -> None:
    default = MODULE._d07_provider_config(
        "http://127.0.0.1:1234/v1",
        execution_path="/usr/bin:/bin",
        executed_tool_call_metadata=False,
    )
    metadata = MODULE._d07_provider_config(
        "http://127.0.0.1:1234/v1",
        execution_path="/usr/bin:/bin",
        executed_tool_call_metadata=True,
    )

    assert b"executed_tool_call_metadata" not in default
    assert b'name = "QuantOS deterministic loopback"' in default
    assert b"[features]\nexecuted_tool_call_metadata = true\n" in metadata
    assert b'name = "OpenAI"' in metadata


def _d07_surface(
    ordinal: int,
    *,
    exec_visible: bool,
    call_output: bool = False,
    metadata_confirmed: bool = True,
) -> dict[str, object]:
    names = ["exec", "wait"] if exec_visible else ["wait"]
    return {
        "request_ordinal": ordinal,
        "exec_visibility": "OBSERVED_TRUE" if exec_visible else "OBSERVED_FALSE",
        "tool_output_call_ids": ["d07-exec-call-1"] if call_output else [],
        "tool_output_observations": (
            [
                {
                    "call_id": "d07-exec-call-1",
                    "output_classification": "SUCCESS_OR_UNCLASSIFIED",
                    "nested_result_present": True,
                    "nested_output_marker_match": True,
                    "nested_exit_code_zero": True,
                    "nested_chunk_id_nonempty": True,
                    "nested_exec_command_dispatched": metadata_confirmed,
                }
            ]
            if call_output
            else []
        ),
        "model_visible_tool_names": names,
    }


def test_d07_shadow_classification_boundaries() -> None:
    summary = {
        "turn_status": "completed",
        "reference_integrity": True,
        "lifecycle_integrity": True,
    }
    successful_probe = {
        "started_count": 1,
        "completed_count": 1,
        "successful_probe_count": 1,
    }
    assert (
        MODULE._d07_classify_shadow(
            phase="D0.7B1",
            shadow_variant="executed-tool-metadata-on",
            request_surfaces=[
                _d07_surface(1, exec_visible=True),
                _d07_surface(2, exec_visible=True, call_output=True),
            ],
            event_summary=summary,
            command_probe=successful_probe,
            final_message="DONE",
            shadow_error_kind=None,
            terminal_error=None,
        )
        == "CODE_MODE_CHAIN_AVAILABLE"
    )
    assert (
        MODULE._d07_classify_shadow(
            phase="D0.7B1",
            shadow_variant="executed-tool-metadata-on",
            request_surfaces=[
                _d07_surface(1, exec_visible=False),
                _d07_surface(2, exec_visible=False),
            ],
            event_summary=summary,
            command_probe=successful_probe,
            final_message="DONE",
            shadow_error_kind=None,
            terminal_error=None,
        )
        == "MODEL_VISIBLE_CODE_MODE_MISSING"
    )
    assert (
        MODULE._d07_classify_shadow(
            phase="D0.7B1",
            shadow_variant="executed-tool-metadata-on",
            request_surfaces=[
                _d07_surface(1, exec_visible=True),
                _d07_surface(2, exec_visible=True, call_output=True),
            ],
            event_summary=summary,
            command_probe={**successful_probe, "completed_count": 0},
            final_message="DONE",
            shadow_error_kind=None,
            terminal_error=None,
        )
        == "COMMAND_LIFECYCLE_GAP"
    )
    assert (
        MODULE._d07_classify_shadow(
            phase="D0.7B1",
            shadow_variant="executed-tool-metadata-on",
            request_surfaces=[
                _d07_surface(1, exec_visible=True),
                _d07_surface(2, exec_visible=True, call_output=True),
            ],
            event_summary=summary,
            command_probe={**successful_probe, "started_count": 0, "completed_count": 0},
            final_message="DONE",
            shadow_error_kind=None,
            terminal_error=None,
        )
        == "NESTED_COMMAND_EXECUTED_COMMAND_EVENT_NOT_OBSERVED"
    )
    assert (
        MODULE._d07_classify_shadow(
            phase="D0.7B1",
            shadow_variant="executed-tool-metadata-on",
            request_surfaces=[
                _d07_surface(1, exec_visible=True),
                _d07_surface(
                    2,
                    exec_visible=True,
                    call_output=True,
                    metadata_confirmed=False,
                ),
            ],
            event_summary=summary,
            command_probe=successful_probe,
            final_message="DONE",
            shadow_error_kind=None,
            terminal_error=None,
        )
        == "NESTED_EXEC_COMMAND_METADATA_NOT_OBSERVED"
    )


def test_d07_artifact_guard_rejects_broader_secret_markers() -> None:
    for payload in (
        b'{"Authorization":"Bearer redacted"}',
        b'{"cookie":"redacted"}',
        b'{"account_id":"redacted"}',
        b'{"TUSHARE_TOKEN":"redacted"}',
    ):
        with pytest.raises(RuntimeError, match="prohibited secret marker"):
            MODULE._safe_d07_artifact_payload("candidate", payload)


def test_d07_publication_rejects_tampering(tmp_path: Path) -> None:
    destination = MODULE._publish_d07_bundle(
        tmp_path,
        phase="TEST",
        prefix="test",
        files={"result.json": MODULE.canonical_json_bytes({"ok": True})},
    )
    manifest, payloads = MODULE._read_d07_bundle_files(destination)
    assert manifest["phase"] == "TEST"
    assert json.loads(payloads["result.json"])["ok"] is True

    (destination / "result.json").write_bytes(b"{}")
    with pytest.raises(RuntimeError, match="file hash"):
        MODULE._read_d07_bundle_files(destination)


def _matrix_result(
    variant: str, command_count: int, *, version: str = "0.154.0"
) -> dict[str, object]:
    events = _provider_events(command_count)
    return _summarize(
        events,
        sdk_version=version,
        runtime_package_version=version,
        runtime_version=f"{version} test",
        runtime_binary_hash="a" * 64,
        variant=variant,
        config_hash=MODULE.sha256_bytes(MODULE.canonical_json_bytes(_config(variant))),
    )


def _provider_events(command_count: int) -> list[dict[str, object]]:
    events = [
        {
            "method": "turn/started",
            "payload": {
                "thread_id": "thread-1",
                "turn": {"id": "turn-1", "status": "inProgress"},
            },
        }
    ]
    events.extend(
        {
            "method": "item/started",
            "payload": {
                "thread_id": "thread-1",
                "item": {
                    "aggregated_output": "",
                    "command": "/usr/bin/pwd",
                    "exit_code": None,
                    "id": f"command-{index}",
                    "status": "inProgress",
                    "type": "commandExecution",
                },
            },
        }
        for index in range(command_count)
    )
    events.append(
        {
            "method": "turn/completed",
            "payload": {
                "thread_id": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        }
    )
    return events


def test_matrix_classifies_observability_gap() -> None:
    results = [_matrix_result(variant, 0) for variant in MODULE.VARIANTS]

    assert _classify_matrix(results) == "OBSERVABILITY_GAP"


def test_matrix_requires_positive_commands_and_negative_control() -> None:
    results = [
        _matrix_result(variant, 0 if variant == "shell-off" else 1) for variant in MODULE.VARIANTS
    ]
    assert _classify_matrix(results) == "SHELL_SURFACE_AVAILABLE"

    results[-1]["command_count"] = 1
    results[-1]["decision"] = "SHELL_OBSERVED"
    assert _classify_matrix(results) == "NEGATIVE_CONTROL_FAILED"


def test_matrix_publication_verifies_every_child_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_diagnostic(**kwargs: Any) -> tuple[Path, dict[str, object]]:
        variant = kwargs["variant"]
        result = _matrix_result(variant, 0)
        events = _provider_events(0)
        destination = MODULE._publish(
            kwargs["output_root"],
            events=events,
            config=MODULE._config(variant),
            result=result,
            normalized_transcript=MODULE.serialize_agent_events(
                MODULE.normalize_provider_events(events, thread_id="thread-1")
            ),
        )
        return destination, result

    monkeypatch.setattr(MODULE, "run_diagnostic", fake_run_diagnostic)
    matrix_path, matrix = MODULE.run_matrix(
        output_root=tmp_path,
        authentication_home=tmp_path,
        expected_sdk_version="0.154.0",
    )

    assert matrix["classification"] == "OBSERVABILITY_GAP"
    assert _verify_matrix(matrix_path) == matrix

    first_entry = matrix["variants"][0]
    result_path = tmp_path / f"sha256-{first_entry['bundle_hash']}" / "result.json"
    result_path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="file hash"):
        _verify_matrix(matrix_path)


def test_candidate_matrix_verification_does_not_change_frozen_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate_version = "0.155.1"

    def fake_run_diagnostic(**kwargs: Any) -> tuple[Path, dict[str, object]]:
        variant = kwargs["variant"]
        result = _matrix_result(variant, 0, version=candidate_version)
        events = _provider_events(0)
        destination = MODULE._publish(
            kwargs["output_root"],
            events=events,
            config=MODULE._config(variant),
            result=result,
            normalized_transcript=MODULE.serialize_agent_events(
                MODULE.normalize_provider_events(events, thread_id="thread-1")
            ),
        )
        return destination, result

    monkeypatch.setattr(MODULE, "run_diagnostic", fake_run_diagnostic)
    matrix_path, matrix = MODULE.run_matrix(
        output_root=tmp_path,
        authentication_home=tmp_path,
        expected_sdk_version=candidate_version,
    )

    assert matrix["sdk_version"] == candidate_version
    assert _verify_matrix(matrix_path, expected_sdk_version=candidate_version) == matrix
    assert PINNED_SDK_VERSION == "0.154.0"


def test_d05_calls_app_server_command_exec_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload
            self.userAgent = payload.get("userAgent")

        def model_dump(self, **_kwargs: Any) -> dict[str, object]:
            return self.payload

    class FakeClient:
        def __init__(self, config: Any) -> None:
            observed["cwd"] = config.cwd

        def start(self) -> None:
            pass

        def initialize(self) -> FakeResponse:
            return FakeResponse({"userAgent": "quantos_d0_5/0.154.0 test"})

        def request(self, method: str, params: object, **_kwargs: Any) -> FakeResponse:
            observed["method"] = method
            observed["params"] = params
            cwd = observed["cwd"]
            return FakeResponse({"exitCode": 0, "stdout": f"{cwd}\n", "stderr": ""})

        def close(self) -> None:
            pass

    monkeypatch.setattr(codex_client, "CodexClient", FakeClient)
    destination, result = _run_command_exec_probe(
        output_root=tmp_path,
        expected_sdk_version="0.154.0",
    )

    request_lines = (destination / "requests.jsonl").read_bytes().splitlines()
    requests = [json.loads(line) for line in request_lines]
    assert [request["method"] for request in requests] == [
        "initialize",
        "initialized",
        "command/exec",
    ]
    assert observed["method"] == "command/exec"
    assert observed["params"] == requests[2]["params"]
    assert requests[2]["params"]["command"] == ["/usr/bin/pwd"]
    assert requests[2]["params"]["sandboxPolicy"] == {
        "type": "externalSandbox",
        "networkAccess": "restricted",
    }
    assert result["decision"] == "COMMAND_EXEC_AVAILABLE"
    assert result["command_stdout_matches_cwd"] is True
    assert destination.name.startswith("sha256-")
    assert {path.name for path in destination.iterdir()} == {
        "diagnostic-manifest.json",
        "requests.jsonl",
        "responses.jsonl",
        "result.json",
    }
    manifest = json.loads((destination / "diagnostic-manifest.json").read_bytes())
    assert all(
        MODULE._sha256_file(destination / name) == expected_hash
        for name, expected_hash in manifest["files"].items()
    )


def test_matrix_verifier_recomputes_requested_config_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_diagnostic(**kwargs: Any) -> tuple[Path, dict[str, object]]:
        variant = kwargs["variant"]
        result = _matrix_result(variant, 0)
        result["requested_config_hash"] = "f" * 64
        events = _provider_events(0)
        destination = MODULE._publish(
            kwargs["output_root"],
            events=events,
            config=MODULE._config(variant),
            result=result,
            normalized_transcript=MODULE.serialize_agent_events(
                MODULE.normalize_provider_events(events, thread_id="thread-1")
            ),
        )
        return destination, result

    monkeypatch.setattr(MODULE, "run_diagnostic", fake_run_diagnostic)
    matrix_path, _matrix = MODULE.run_matrix(
        output_root=tmp_path,
        authentication_home=tmp_path,
        expected_sdk_version="0.154.0",
    )

    with pytest.raises(RuntimeError, match="requested config binding"):
        _verify_matrix(matrix_path)


def _publish_raw_fixture_bundle(output_root: Path, variant: str) -> tuple[Path, dict[str, object]]:
    version = "0.154.0"
    fixture = MODULE._build_raw_wire_fixture(variant, expected_sdk_version=version)
    requests = fixture["requests"]
    replacements = {
        MODULE.RAW_SENTINELS["binary"]: "/tmp/codex",
        MODULE.RAW_SENTINELS["codex_home"]: "/tmp/codex-home",
        MODULE.RAW_SENTINELS["path_dir"]: "/tmp/codex-path",
        MODULE.RAW_SENTINELS["workspace"]: "/tmp/workspace",
    }

    def resolved(name: str, request_id: int, *, thread: bool = False) -> dict[str, object]:
        values = {
            **replacements,
            MODULE.RAW_SENTINELS["request_id"]: request_id,
        }
        if thread:
            values[MODULE.RAW_SENTINELS["thread_id"]] = "thread-1"
        return MODULE._substitute_sentinels(requests[name], values)

    events = _raw_provider_events(command=False)
    summary = MODULE._raw_event_summary(events, thread_id="thread-1", turn_id="turn-1")
    result = {
        "schema_version": "codex-raw-thread-result/v1",
        "authority": "NON_CANONICAL_DIAGNOSTIC",
        "probe": "D0.6_RAW_THREAD",
        "variant": variant,
        "sdk_version": version,
        "runtime_package_version": version,
        "runtime_version": f"{version} test",
        "runtime_binary_hash": "a" * 64,
        "wire_fixture_hash": MODULE.sha256_bytes(MODULE.canonical_json_bytes(fixture)),
        "model": MODULE.MODEL_IDENTIFIER,
        "reasoning_effort": MODULE.MODEL_REASONING_EFFORT,
        "prompt_hash": MODULE.sha256_bytes(MODULE.PROMPT.encode()),
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        **summary,
        "decision": "SHELL_NOT_OBSERVED",
        "limitations": list(MODULE.RAW_LIMITATIONS),
    }
    environment = {
        "schema_version": "codex-raw-thread-environment/v1",
        "app_server_argv": MODULE._substitute_sentinels(fixture["app_server_argv"], replacements),
        "app_server_environment": MODULE._substitute_sentinels(
            fixture["environment"], replacements
        ),
        "shell_environment_policy": MODULE._config(variant)["shell_environment_policy"],
        "workspace": "/tmp/workspace",
    }
    runtime_identity = {
        "schema_version": "codex-raw-thread-runtime-identity/v1",
        "sdk_distribution": MODULE.CODEX_SDK_DISTRIBUTION,
        "sdk_version": version,
        "runtime_distribution": MODULE.CODEX_RUNTIME_DISTRIBUTION,
        "runtime_package_version": version,
        "runtime_version": f"{version} test",
        "runtime_binary_hash": "a" * 64,
        "protocol_identifier": MODULE.CODEX_PROTOCOL_IDENTIFIER,
    }
    files = {
        "runtime-identity.json": MODULE.canonical_json_bytes(runtime_identity),
        "wire-fixture.json": MODULE.canonical_json_bytes(fixture),
        "effective-environment.json": MODULE.canonical_json_bytes(environment),
        "initialize-request.json": MODULE.canonical_json_bytes(resolved("initialize", 0)),
        "initialize-response.json": MODULE.canonical_json_bytes(
            {"id": 0, "result": {"serverInfo": {"version": f"{version} test"}}}
        ),
        "account-read-request.json": MODULE.canonical_json_bytes(resolved("account_read", 1)),
        "account-read-summary.json": MODULE.canonical_json_bytes({"authenticated": True}),
        "thread-start-request.json": MODULE.canonical_json_bytes(resolved("thread_start", 2)),
        "thread-start-response.json": MODULE.canonical_json_bytes(
            {"id": 2, "result": {"thread": {"id": "thread-1"}}}
        ),
        "turn-start-request.json": MODULE.canonical_json_bytes(
            resolved("turn_start", 3, thread=True)
        ),
        "turn-start-response.json": MODULE.canonical_json_bytes(
            {"id": 3, "result": {"turn": {"id": "turn-1"}}}
        ),
        "provider-events.jsonl": b"".join(
            MODULE.canonical_json_bytes(event) + b"\n" for event in events
        ),
        "stderr-summary.json": MODULE.canonical_json_bytes(
            {"byte_count": 0, "line_count": 0, "sha256": MODULE.sha256_bytes(b"")}
        ),
        "result.json": MODULE.canonical_json_bytes(result),
    }
    return MODULE._publish_raw_bundle(output_root, files), result


def test_raw_matrix_publication_is_offline_verifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_raw_thread_diagnostic(**kwargs: Any) -> tuple[Path, dict[str, object]]:
        return _publish_raw_fixture_bundle(kwargs["output_root"], kwargs["variant"])

    monkeypatch.setattr(MODULE, "run_raw_thread_diagnostic", fake_run_raw_thread_diagnostic)
    matrix_path, matrix = MODULE.run_raw_thread_matrix(
        output_root=tmp_path,
        authentication_home=tmp_path,
        expected_sdk_version="0.154.0",
    )

    assert matrix["classification"] == "RAW_THREAD_OBSERVABILITY_GAP"
    assert _verify_raw_matrix(matrix_path) == matrix

    forged_matrix = {**matrix, "unexpected": True}
    forged_bytes = MODULE.canonical_json_bytes(forged_matrix)
    forged_path = tmp_path / f"raw-matrix-sha256-{MODULE.sha256_bytes(forged_bytes)}"
    forged_path.mkdir()
    (forged_path / "matrix.json").write_bytes(forged_bytes)
    with pytest.raises(RuntimeError, match="matrix identity"):
        _verify_raw_matrix(forged_path)

    first = matrix["variants"][0]
    result_path = tmp_path / f"raw-sha256-{first['bundle_hash']}" / "result.json"
    result_path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="file hash"):
        _verify_raw_matrix(matrix_path)


def test_frozen_version_matches_project_and_lock() -> None:
    root = Path(__file__).parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))

    assert project["project"]["optional-dependencies"]["agent-openai"] == [
        f"openai-codex=={PINNED_SDK_VERSION}"
    ]
    versions = {
        package["name"]: package["version"]
        for package in lock["package"]
        if package["name"] in {"openai-codex", "openai-codex-cli-bin"}
    }
    assert versions == {
        "openai-codex": PINNED_SDK_VERSION,
        "openai-codex-cli-bin": PINNED_RUNTIME_PACKAGE_VERSION,
    }
