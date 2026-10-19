"""Retained field inspection is read only and does not expose arbitrary strings."""

import hashlib
import json

import pytest
from scripts.inspect_execution_diagnostics import inspect


def test_inspection_preserves_failure_missing_fields_and_known_usage(tmp_path):
    values = {
        "feedback": {
            "schema_version": "adaptive-feedback/v1",
            "run_status": "FAILED",
            "verdict": "NOT_EVALUATED",
        },
        "stage_completion": {
            "schema_version": "discovery-stage-attempt-completion/v2",
            "status": "FAILED",
            "failure_reason_code": "QLIB_EXECUTION_FAILED",
            "failure_detail_code": "WORKFLOW_REQUIRED_METRIC_NON_FINITE",
            "exception": "synthetic-private-text",
        },
        "selection_report": {
            "schema_version": "campaign-selection-report/v1",
            "reason_code": "SOURCE_INCOMPLETE",
        },
        "closeout": {
            "schema_version": "adaptive-readonly-closeout/v1",
            "sdk_captures": [
                {"usage": {"input_tokens": 120, "output_tokens": 30, "private": "secret"}},
                {"usage": None},
            ],
        },
    }
    sources = {}
    for kind, value in values.items():
        path = tmp_path / f"{kind}.json"
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        sources[kind] = (path, hashlib.sha256(raw).hexdigest())
    before = {path: path.read_bytes() for path, _ in sources.values()}
    result = inspect(sources)
    assert result["execution_status"] == "FAILED"
    assert result["research_verdict"] == "NOT_EVALUATED"
    assert result["failure_detail_code"] == "WORKFLOW_REQUIRED_METRIC_NON_FINITE"
    assert result["parent_selection_reason_code"] == "SOURCE_INCOMPLETE"
    assert result["known_usage"] == [
        {
            "input_tokens": 120,
            "output_tokens": 30,
            "cached_input_tokens": None,
            "total_tokens": None,
        },
        None,
    ]
    assert "private" not in json.dumps(result)
    assert {path: path.read_bytes() for path in before} == before
    assert set(tmp_path.iterdir()) == set(before)

    # Historical v1 stage completions lack diagnostic fields; do not invent them.
    path, _ = sources["stage_completion"]
    raw = json.dumps(
        {"schema_version": "discovery-stage-attempt-completion/v1", "status": "FAILED"}
    ).encode()
    path.write_bytes(raw)
    old = inspect({"stage_completion": (path, hashlib.sha256(raw).hexdigest())})
    assert old["stage_status"] == "FAILED"
    assert old["execution_status"] is None
    assert old["research_verdict"] is None
    assert old["failure_detail_code"] is None
    assert old["known_usage"] is None


def test_inspection_rejects_replaced_original(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"schema_version":"adaptive-feedback/v1"}')
    with pytest.raises(ValueError, match="DIAGNOSTIC_INPUT_INVALID"):
        inspect({"feedback": (path, "a" * 64)})
