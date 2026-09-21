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
