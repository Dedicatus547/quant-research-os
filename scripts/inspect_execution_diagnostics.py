#!/usr/bin/env python3
"""Display hash-pinned retained fields; never execute, recover, or qualify a run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict

_DETAILS = frozenset(
    {
        "UNCLASSIFIED",
        "SIGNAL_PIT_MEMBER_UNMAPPED",
        "SIGNAL_FINITE_WITHOUT_TRADABILITY",
        "WORKFLOW_RECORDER_INTERFACE_MISSING",
        "WORKFLOW_REQUIRED_METRIC_NON_FINITE",
    }
)
_SCHEMAS = {
    "feedback": {"adaptive-feedback/v1"},
    "stage_completion": {
        "discovery-stage-attempt-completion/v1",
        "discovery-stage-attempt-completion/v2",
    },
    "selection_report": {"campaign-selection-report/v1"},
    "closeout": {"adaptive-readonly-closeout/v1"},
}


def _bounded(value: Any, allowed: frozenset[str]) -> str | None:
    return value if type(value) is str and value in allowed else None


def _usage(value: Any) -> dict[str, int | None] | None:
    if not isinstance(value, dict):
        return None
    value = cast(dict[str, Any], value)
    names = ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens")
    return {
        name: value[name] if type(value.get(name)) is int and value[name] >= 0 else None
        for name in names
    }


def inspect(sources: dict[str, tuple[Path, str]]) -> dict[str, Any]:
    """Pin bytes and project fixed fields; source relationships are caller supplied."""
    records: dict[str, Any] = {}
    hashes = {}
    for kind, (path, expected) in sources.items():
        if kind not in _SCHEMAS or path.is_symlink() or not path.is_file():
            raise ValueError("DIAGNOSTIC_INPUT_INVALID")
        with path.open("rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) > 4 * 1024 * 1024 or digest != expected:
            raise ValueError("DIAGNOSTIC_INPUT_INVALID")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("DIAGNOSTIC_INPUT_INVALID")
        record = cast(dict[str, Any], decoded)
        if record.get("schema_version") not in _SCHEMAS[kind]:
            raise ValueError("DIAGNOSTIC_INPUT_INVALID")
        records[kind], hashes[kind] = record, digest
    feedback = records.get("feedback", {})
    completion = records.get("stage_completion", {})
    parent = records.get("selection_report", {})
    captures = records.get("closeout", {}).get("sdk_captures")
    return {
        "schema_version": "execution-diagnostics-inspection/v1",
        "authority": "READ_ONLY_FIELD_PROJECTION_NOT_QUALIFICATION",
        "source_relationships": "CALLER_SUPPLIED_NOT_VERIFIED",
        "source_sha256": hashes,
        "execution_status": _bounded(feedback.get("run_status"), frozenset(RunStatus)),
        "research_verdict": _bounded(feedback.get("verdict"), frozenset(ValidationVerdict)),
        "stage_status": _bounded(
            completion.get("status"), frozenset({"FAILED", "SUCCEEDED", "ADOPTED"})
        ),
        "failure_reason_code": _bounded(
            completion.get("failure_reason_code"), frozenset(ReasonCode)
        ),
        "failure_detail_code": _bounded(completion.get("failure_detail_code"), _DETAILS),
        "parent_selection_reason_code": _bounded(parent.get("reason_code"), frozenset(ReasonCode)),
        "known_usage": [
            _usage(cast(dict[str, Any], item).get("usage"))
            for item in cast(list[Any], captures)
            if isinstance(item, dict)
        ]
        if isinstance(captures, list)
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for kind in _SCHEMAS:
        parser.add_argument(f"--{kind.replace('_', '-')}", nargs=2, metavar=("PATH", "SHA256"))
    args = vars(parser.parse_args())
    sources = {kind: (Path(value[0]), value[1]) for kind, value in args.items() if value}
    try:
        if not sources:
            raise ValueError("DIAGNOSTIC_INPUT_INVALID")
        result = inspect(sources)
    except (OSError, ValueError, TypeError, KeyError):
        print('{"status":"FAILED","failure_detail_code":"DIAGNOSTIC_INPUT_INVALID"}')
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
