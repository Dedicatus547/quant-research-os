"""Minimal stdio MCP server used only by the frozen P10 capability spike."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DATASET_HASH = "a" * 64
SKILL_NONCE = "P10_SKILL_20260907"


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _tool() -> dict[str, Any]:
    path = Path(__file__).with_name("mcp_tool.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _result(request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    if request_id is None:
        return None
    method = request.get("method")
    if method == "initialize":
        requested = request.get("params", {}).get("protocolVersion", "2025-06-18")
        result: dict[str, Any] = {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "quantos-p10-probe", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [_tool()]}
    elif method == "tools/call":
        params = request.get("params", {})
        arguments = params.get("arguments", {})
        if params.get("name") != "dataset_describe" or arguments != {
            "dataset_hash": DATASET_HASH,
            "skill_nonce": SKILL_NONCE,
        }:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "frozen tool arguments do not match"},
            }
        payload = {
            "dataset_hash": DATASET_HASH,
            "fields": ["adjusted_close", "membership", "tradable"],
            "fixture_kind": "SYNTHETIC",
            "row_count": 3,
        }
        result = {
            "content": [{"type": "text", "text": json.dumps(payload, separators=(",", ":"))}],
            "structuredContent": payload,
            "isError": False,
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = _result(request)
            if response is not None:
                _write(response)
        except (AttributeError, json.JSONDecodeError, TypeError):
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
