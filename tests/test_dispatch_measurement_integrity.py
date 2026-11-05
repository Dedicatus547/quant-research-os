"""Retained supervisor measurement integrity without a real worker launch."""

import json
from types import SimpleNamespace

import pytest

from quantos.application.personal_dispatch import PersonalResourceDispatcher, _write
from quantos.artifacts.store import ArtifactIntegrityError


@pytest.fixture
def measurement(tmp_path):
    client = object.__new__(PersonalResourceDispatcher)
    owned, attempt, run = (tmp_path / name for name in ("owned", "attempt", "supervisor"))
    for directory in (owned, attempt, run):
        directory.mkdir()
    path = owned / "retained"
    path.write_bytes(b"1234")
    client._owned_roots = lambda _: [owned]
    baseline = client._sizes([owned])
    start = {"command_hash": "a" * 64, "owned_roots": [str(owned)], "baseline": baseline}
    returned = {"command_hash": "a" * 64, "wall_seconds": 0.25}
    _write(attempt, "measurement-start.json", start)
    _write(attempt, "supervisor-returned.json", returned)
    return SimpleNamespace(
        client=client, owned=owned, attempt=attempt, run=run, start=start, returned=returned
    )


def usage(f):
    return f.client._usage({}, f.attempt, f.run, "a" * 64, "b" * 64)


def test_growth_counts_positive_retained_deltas_without_deletion_credit(measurement):
    f = measurement
    (f.owned / "retained").unlink()
    (f.owned / "new").write_bytes(b"123456")
    result = usage(f)
    assert result["growth_bytes"] == 6 and result["wall_seconds"] == 0.25
    assert usage(f) == result


@pytest.mark.parametrize(
    "attack",
    [
        "baseline_command",
        "roots",
        "shape",
        "negative",
        "boolean",
        "return_command",
        "return_bool",
        "return_negative",
        "return_null",
    ],
)
def test_untrusted_measurement_cannot_refund_a_reserved_budget(measurement, attack):
    f = measurement
    if attack == "baseline_command":
        f.start["command_hash"] = "f" * 64
    elif attack == "roots":
        f.start["owned_roots"] = []
    elif attack == "shape":
        f.start["baseline"] = []
    elif attack in {"negative", "boolean"}:
        f.start["baseline"] = {"file": -1 if attack == "negative" else True}
    elif attack == "return_command":
        f.returned["command_hash"] = "f" * 64
    elif attack == "return_bool":
        f.returned["wall_seconds"] = True
    elif attack == "return_negative":
        f.returned["wall_seconds"] = -1
    else:
        f.returned["wall_seconds"] = None
    # Deliberate corruption simulates originals changing before first reconciliation.
    (f.attempt / "measurement-start.json").write_text(
        json.dumps(f.start, sort_keys=True, separators=(",", ":"))
    )
    (f.attempt / "supervisor-returned.json").write_text(
        json.dumps(f.returned, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(ArtifactIntegrityError):
        usage(f)
    assert not (f.attempt / "resource-usage.json").exists()


@pytest.mark.parametrize(
    "attack", ["command_hash", "supervisor_run", "exit_sha256", "baseline", "return"]
)
def test_reused_usage_must_still_bind_its_original_measurements(measurement, attack):
    f = measurement
    record = usage(f)
    if attack in {"baseline", "return"}:
        name = "measurement-start.json" if attack == "baseline" else "supervisor-returned.json"
        (f.attempt / name).write_bytes(b"changed")
    else:
        record[attack] = "f" * 64
        (f.attempt / "resource-usage.json").write_text(
            json.dumps(record, sort_keys=True, separators=(",", ":"))
        )
    with pytest.raises(ArtifactIntegrityError):
        usage(f)
