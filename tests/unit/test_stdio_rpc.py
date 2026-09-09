import json
from io import BytesIO
from pathlib import Path

from quantos.application import (
    ProposalMcpService,
    ResearchMcpService,
    StdioJsonRpcAdapter,
    build_json_rpc_tool_schema,
    serve_stdio,
)
from quantos.contracts import ReasonCode
from quantos.registry import RegistryService


def _adapter(tmp_path: Path, *, max_request_bytes: int = 262_144) -> StdioJsonRpcAdapter:
    return StdioJsonRpcAdapter(
        proposals=ProposalMcpService(tmp_path / "proposals"),
        research=ResearchMcpService(
            tmp_path / "research",
            datasets={},
            proposal_chains={},
            registry=RegistryService(tmp_path / "registry"),
        ),
        max_request_bytes=max_request_bytes,
    )


def test_stdio_json_rpc_dispatches_only_typed_allowlisted_methods(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "registry.search",
        "params": {"schema_version": "registry-search-request/v1", "limit": 5},
    }

    response = json.loads(adapter.handle_line(json.dumps(request).encode()))

    assert response["id"] == 1
    assert response["result"]["hits"] == []
    assert adapter.transcript.entries[0].succeeded
    assert adapter.transcript.tool_schema_hash == adapter.tool_schema.content_hash
    assert len(build_json_rpc_tool_schema().tools) == 11


def test_stdio_json_rpc_denies_shell_paths_malformed_and_oversized_payloads(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path, max_request_bytes=512)
    requests = (
        b'{"jsonrpc":"2.0","id":1,"method":"shell","params":{}}',
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "dataset.describe",
                "params": {
                    "schema_version": "dataset-lookup-request/v1",
                    "snapshot_hash": "1" * 64,
                    "qlib_view_hash": "2" * 64,
                    "path": "/etc/passwd",
                },
            }
        ).encode(),
        b"not-json",
        b"{" + b"x" * 512 + b"}",
    )
    responses = [json.loads(adapter.handle_line(item)) for item in requests]

    assert [item["error"]["data"]["reason_code"] for item in responses] == [
        ReasonCode.CAPABILITY_DENIED.value,
        ReasonCode.SCHEMA_INVALID.value,
        ReasonCode.SCHEMA_INVALID.value,
        ReasonCode.RESOURCE_BUDGET_EXCEEDED.value,
    ]
    assert all("/etc/passwd" not in json.dumps(item) for item in responses)
    assert [item.sequence for item in adapter.transcript.entries] == [1, 2, 3, 4]
    assert all(not item.succeeded for item in adapter.transcript.entries)


def test_stdio_json_rpc_transcript_contains_hashes_not_request_payload(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    line = b'{"jsonrpc":"2.0","id":"x","method":"shell","params":{"token":"secret"}}'

    adapter.handle_line(line)
    encoded = adapter.transcript.canonical_bytes()

    assert b"secret" not in encoded
    assert b"token" not in encoded
    assert adapter.transcript.entries[0].request_hash


def test_stdio_loop_frames_one_response_per_request_until_eof(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    valid = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "registry.search",
            "params": {"schema_version": "registry-search-request/v1"},
        }
    ).encode()
    denied = b'{"jsonrpc":"2.0","id":2,"method":"shell","params":{}}'
    source = BytesIO(valid + b"\n" + denied + b"\n")
    destination = BytesIO()

    serve_stdio(adapter, source, destination)

    responses = [json.loads(line) for line in destination.getvalue().splitlines()]
    assert len(responses) == 2
    assert "result" in responses[0]
    assert responses[1]["error"]["data"]["reason_code"] == ReasonCode.CAPABILITY_DENIED
