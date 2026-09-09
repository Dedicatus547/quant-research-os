#!/usr/bin/env python3
"""Serve one verified P13 Evidence object through a two-tool stdio MCP surface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from quantos.application import EvidenceBinding, EvidenceMcpError, EvidenceMcpService
from quantos.application.evidence_mcp import evidence_mcp_tools
from quantos.artifacts.store import confined_regular_file
from quantos.contracts import canonical_json_bytes
from quantos.evidence.publisher import verify_evidence_store


def _write(message: dict[str, object]) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(message) + b"\n")
    sys.stdout.buffer.flush()


def _load_binding(store_path: Path, store_hash: str, evidence_hash: str) -> EvidenceBinding:
    manifest = verify_evidence_store(store_path)
    if manifest.store_hash != store_hash:
        raise ValueError("Evidence Store hash does not match the frozen P13 invocation")
    matches = [item for item in manifest.items if item.evidence.content_hash == evidence_hash]
    if len(matches) != 1:
        raise ValueError("frozen P13 evidence is absent or ambiguous")
    item = matches[0]
    if item.extracted_text is None or item.text_ref is None:
        raise ValueError("frozen P13 evidence has no extracted text")
    text = confined_regular_file(store_path, item.text_ref.logical_path).read_text(encoding="utf-8")
    return EvidenceBinding(evidence=item.evidence, extracted_text=item.extracted_text, text=text)


def _tool_result(payload: object) -> dict[str, object]:
    if not hasattr(payload, "canonical_payload"):
        raise TypeError("Evidence MCP result is not canonical")
    result = payload.canonical_payload()
    return {
        "content": [{"type": "text", "text": canonical_json_bytes(result).decode("utf-8")}],
        "structuredContent": result,
        "isError": False,
    }


def _response(
    request: dict[str, Any], service: EvidenceMcpService
) -> dict[str, object] | None:
    request_id = request.get("id")
    if request_id is None:
        return None
    method = request.get("method")
    if method == "initialize":
        requested = request.get("params", {}).get("protocolVersion", "2025-06-18")
        result: dict[str, object] = {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "quantos-p13-evidence", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": list(evidence_mcp_tools())}
    elif method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("arguments"), dict):
            return _error(request_id, -32602, "invalid tool arguments")
        tool_name = params.get("name")
        capability = {"evidence_get": "evidence.get", "evidence_cite": "evidence.cite"}.get(
            tool_name
        )
        if capability is None:
            return _error(request_id, -32601, "tool is not allowlisted")
        try:
            payload = service.call(capability, canonical_json_bytes(params["arguments"]))
        except EvidenceMcpError as error:
            return _error(request_id, -32602, f"{error.reason_code.value}: {error}")
        result = _tool_result(payload)
    else:
        return _error(request_id, -32601, "method not found")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("store_path", type=Path)
    parser.add_argument("store_hash")
    parser.add_argument("evidence_hash")
    args = parser.parse_args()
    binding = _load_binding(args.store_path, args.store_hash, args.evidence_hash)
    service = EvidenceMcpService({binding.evidence.content_hash: binding})
    for line in sys.stdin.buffer:
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                continue
            response = _response(value, service)
            if response is not None:
                _write(response)
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
