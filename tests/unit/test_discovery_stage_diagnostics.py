"""Exercise stage bookkeeping with synthetic callbacks, without scientific execution."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from quantos.application.autonomous_execution import (
    DiscoveryExecutionStageCheckpoint,
    QuantosResearchExecutionAdapter,
)
from quantos.contracts.autonomous import AutonomousExecutionRequest
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.status import ReasonCode
from quantos.research.qlib import QlibResearchError

_MAPPING_MESSAGE = "PIT member is absent from the Qlib view mapping"
_PRIVATE_TEXT = "synthetic-private-instrument-and-exception-context"
_TRADABILITY_MESSAGE = f"finite signal lacks tradability evidence for {_PRIVATE_TEXT}"
_OUTPUTS = {"signal_hash": "c" * 64}


@pytest.fixture
def stage_runner(tmp_path: Path):
    # Bypass scientific input verification and runtime capture deliberately: only
    # _discovery_stage's bookkeeping is under test, never the production pipeline.
    adapter = object.__new__(QuantosResearchExecutionAdapter)
    adapter.output_root = tmp_path
    adapter._discovery_runtime_hash = "a" * 64
    request = cast(
        AutonomousExecutionRequest,
        SimpleNamespace(content_hash="b" * 64, execution_identity="d" * 64),
    )

    def run(build, *, stage="baseline-signal", verify=lambda outputs: outputs, recover=None):
        return adapter._discovery_stage(request, stage, {}, build, verify, recover)

    return run


def _never_called(*args):
    pytest.fail("checkpoint reuse/adoption unexpectedly invoked a build or recovery callback")


def _completion_paths(root: Path) -> list[Path]:
    return sorted(root.rglob("completion.json"))


@pytest.mark.parametrize(
    ("stage", "error", "reason", "detail"),
    [
        pytest.param(
            "baseline-signal",
            QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, _MAPPING_MESSAGE),
            "SOURCE_INCOMPLETE",
            "SIGNAL_PIT_MEMBER_UNMAPPED",
            id="unmapped-member",
        ),
        pytest.param(
            "baseline-signal",
            QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, _TRADABILITY_MESSAGE),
            "SOURCE_INCOMPLETE",
            "SIGNAL_FINITE_WITHOUT_TRADABILITY",
            id="missing-tradability",
        ),
        pytest.param(
            "cost-2-signal",
            QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, _TRADABILITY_MESSAGE),
            "SOURCE_INCOMPLETE",
            "SIGNAL_FINITE_WITHOUT_TRADABILITY",
            id="variant-signal",
        ),
        pytest.param(
            "baseline-pit",
            QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, _MAPPING_MESSAGE),
            "SOURCE_INCOMPLETE",
            "UNCLASSIFIED",
            id="different-stage",
        ),
        pytest.param(
            "baseline-signal",
            QlibResearchError(ReasonCode.LOOK_AHEAD, _TRADABILITY_MESSAGE),
            "LOOK_AHEAD",
            "UNCLASSIFIED",
            id="different-reason",
        ),
        pytest.param(
            "baseline-signal",
            QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, _PRIVATE_TEXT),
            "SOURCE_INCOMPLETE",
            "UNCLASSIFIED",
            id="unknown-message",
        ),
        pytest.param(
            "baseline-signal",
            QlibResearchError(cast(ReasonCode, "SOURCE_INCOMPLETE"), _MAPPING_MESSAGE),
            None,
            "UNCLASSIFIED",
            id="string-is-not-enum-identity",
        ),
        pytest.param(
            "baseline-signal",
            QlibResearchError(cast(ReasonCode, _PRIVATE_TEXT), _TRADABILITY_MESSAGE),
            None,
            "UNCLASSIFIED",
            id="untrusted-reason",
        ),
        pytest.param(
            "baseline-signal",
            QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, cast(str, {"private": _PRIVATE_TEXT})),
            "SOURCE_INCOMPLETE",
            "UNCLASSIFIED",
            id="non-string-message",
        ),
        pytest.param(
            "baseline-signal",
            RuntimeError(_TRADABILITY_MESSAGE),
            None,
            "UNCLASSIFIED",
            id="non-qlib-error",
        ),
        pytest.param(
            "baseline-signal",
            KeyboardInterrupt(_PRIVATE_TEXT),
            None,
            "UNCLASSIFIED",
            id="interrupt",
        ),
        pytest.param(
            "baseline-signal",
            SystemExit(_PRIVATE_TEXT),
            None,
            "UNCLASSIFIED",
            id="exit",
        ),
    ],
)
def test_failed_stage_records_only_bounded_diagnostics_and_reraises(
    tmp_path, stage_runner, stage, error, reason, detail
):
    cause = RuntimeError(_PRIVATE_TEXT)

    def fail():
        raise error from cause

    with pytest.raises(type(error)) as raised:
        stage_runner(fail, stage=stage, verify=_never_called)
    assert raised.value is error
    assert raised.value.__cause__ is cause
    [path] = _completion_paths(tmp_path)
    encoded = path.read_bytes()
    record = json.loads(encoded)
    reservation = json.loads(path.with_name("reservation.json").read_bytes())
    assert encoded == canonical_json_bytes(record)
    assert record == {
        "schema_version": "discovery-stage-attempt-completion/v2",
        "inputs_hash": reservation["inputs_hash"],
        "status": "FAILED",
        "failure_code": "STAGE_EXCEPTION",
        "failure_reason_code": reason,
        "failure_detail_code": detail,
        "wall_seconds": record["wall_seconds"],
        "cpu_seconds": record["cpu_seconds"],
    }
    assert record["wall_seconds"] >= 0
    assert record["cpu_seconds"] >= 0
    assert _PRIVATE_TEXT.encode() not in encoded
    assert not list(tmp_path.rglob("sha256-*.json"))


@pytest.mark.parametrize("failure_site", ["verify", "recover"])
def test_callback_failure_is_recorded_without_publishing_checkpoint(
    tmp_path, stage_runner, failure_site
):
    error = QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, _TRADABILITY_MESSAGE)

    def fail(*args):
        raise error

    if failure_site == "recover":
        with pytest.raises(QlibResearchError):
            stage_runner(fail)
    prior = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    with pytest.raises(QlibResearchError) as raised:
        if failure_site == "verify":
            stage_runner(lambda: _OUTPUTS, verify=fail)
        else:
            stage_runner(_never_called, recover=fail, verify=_never_called)
    assert raised.value is error
    assert all(path.read_bytes() == encoded for path, encoded in prior.items())
    record = json.loads(_completion_paths(tmp_path)[-1].read_bytes())
    assert record["status"] == "FAILED"
    assert record["failure_detail_code"] == "SIGNAL_FINITE_WITHOUT_TRADABILITY"
    assert not list(tmp_path.rglob("sha256-*.json"))


@pytest.mark.parametrize("legacy_failure", [False, True])
@pytest.mark.parametrize("adopt", [False, True])
def test_retry_preserves_failure_and_success_remains_reusable_v1(
    tmp_path, stage_runner, legacy_failure, adopt
):
    def fail():
        raise QlibResearchError(ReasonCode.SOURCE_INCOMPLETE, _TRADABILITY_MESSAGE)

    with pytest.raises(QlibResearchError):
        stage_runner(fail)
    [failed_path] = _completion_paths(tmp_path)
    if legacy_failure:
        # Construct a historical v1 fixture only inside this test's scratch tree.
        legacy = json.loads(failed_path.read_bytes())
        legacy["schema_version"] = "discovery-stage-attempt-completion/v1"
        del legacy["failure_reason_code"], legacy["failure_detail_code"]
        failed_path.write_bytes(canonical_json_bytes(legacy))
    prior = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    result = stage_runner(
        _never_called if adopt else lambda: _OUTPUTS,
        recover=lambda: _OUTPUTS if adopt else None,
    )
    assert result == _OUTPUTS
    assert all(path.read_bytes() == encoded for path, encoded in prior.items())
    failed, succeeded = _completion_paths(tmp_path)
    assert failed == failed_path
    assert succeeded.parent.name == "00000002"
    record = json.loads(succeeded.read_bytes())
    [checkpoint_path] = tmp_path.rglob("sha256-*.json")
    checkpoint = DiscoveryExecutionStageCheckpoint.model_validate_json(checkpoint_path.read_bytes())
    assert checkpoint.attempt_ordinal == 2
    assert checkpoint.outputs == _OUTPUTS
    assert checkpoint.content_hash == record["checkpoint_hash"]
    assert checkpoint.reservation_hash == sha256_bytes(
        succeeded.with_name("reservation.json").read_bytes()
    )
    assert record["schema_version"] == "discovery-stage-attempt-completion/v1"
    assert record["status"] == ("ADOPTED" if adopt else "SUCCEEDED")
    assert record["process_exit"] is None
    assert "failure_reason_code" not in record
    assert "failure_detail_code" not in record
    for timing in ("wall_seconds", "cpu_seconds"):
        assert record[timing] is None if adopt else record[timing] >= 0
    prior = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    verified = []

    def verify(outputs):
        verified.append(outputs)
        return "verified-original"

    assert stage_runner(_never_called, verify=verify, recover=_never_called) == "verified-original"
    assert verified == [_OUTPUTS]
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == prior
