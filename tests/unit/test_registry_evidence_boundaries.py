"""Public registry admission and chain recovery refuse inconsistent retained evidence."""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_registry_service import NOW, _publish_report

from quantos.artifacts.store import StoredEvent, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.events import EventType, ImmutableEvent
from quantos.contracts.validation import ValidationReport
from quantos.registry import service as registry
from quantos.validation.service import ValidationError, verify_validation_report


def event(number, previous=None, **changes):
    value = ImmutableEvent.model_validate(
        {
            "event_id": UUID(int=number),
            "aggregate_id": "strategy",
            "event_type": EventType.STRATEGY_CREATED,
            "occurred_at": NOW + timedelta(seconds=number),
            "payload": {"version": number, "strategy_spec_hash": "a" * 64},
            "previous_event_hash": previous,
            **changes,
        }
    )
    return StoredEvent(event=value, event_hash=value.content_hash)


@pytest.mark.parametrize(
    "attack,message",
    [
        ("duplicate", "duplicate event hash"),
        ("heads", "one chain head"),
        ("missing", "predecessor is missing"),
        ("fork", "contains a fork"),
        ("clock", "time moved backwards"),
        ("aggregate", "identifier mismatch"),
    ],
)
def test_registry_chain_rejects_forks_missing_parents_and_reordered_time(attack, message):
    first = event(1)
    second = event(2, first.event_hash)
    assert registry._ordered_chain([second, first], aggregate_id="strategy") == [first, second]
    assert registry._ordered_chain([], aggregate_id="strategy") == []
    if attack == "duplicate":
        values = [first, first]
    elif attack == "heads":
        values = [first, event(2)]
    elif attack == "missing":
        values = [first, event(2, "f" * 64)]
    elif attack == "fork":
        values = [first, second, event(3, first.event_hash)]
    elif attack == "clock":
        values = [first, event(2, first.event_hash, occurred_at=NOW)]
    else:
        values = [first, event(2, first.event_hash, aggregate_id="other")]
    with pytest.raises(registry.RegistryError, match=message):
        registry._ordered_chain(values, aggregate_id="strategy")


def revise(path, **changes):
    report = ValidationReport.model_validate_json((path / "report.json").read_bytes())
    updated = ValidationReport.create(**{**report.model_dump(exclude={"report_hash"}), **changes})
    destination = path.with_name("sha256-" + updated.report_hash)
    path.rename(destination)
    (destination / "report.json").write_bytes(canonical_json_bytes(updated.model_dump()))
    return destination


@pytest.mark.parametrize(
    "attack,message",
    [
        ("directory", "directory does not match"),
        ("extra", "file set"),
        ("missing", "file set"),
        ("noncanonical", "not canonical"),
        ("contract", "cannot be loaded"),
        ("binding", "bindings are inconsistent"),
    ],
)
def test_validation_report_rechecks_inventory_and_bound_contracts(tmp_path, attack, message):
    path, _ = _publish_report(tmp_path, experiment_id="evidence-boundary")
    assert verify_validation_report(path).experiment_id == "evidence-boundary"
    if attack == "directory":
        renamed = path.with_name("wrong")
        path.rename(renamed)
        path = renamed
    elif attack == "extra":
        (path / "unlisted.json").write_text("{}")
    elif attack == "missing":
        (path / "runtime-fingerprint.json").unlink()
    elif attack == "noncanonical":
        (path / "report.json").write_bytes((path / "report.json").read_bytes() + b"\n")
    elif attack == "binding":
        path = revise(path, research_policy_hash="e" * 64)
    else:
        (path / "authoring-spec.json").write_text("{}")
        report = ValidationReport.model_validate_json((path / "report.json").read_bytes())
        files = tuple(
            item.model_copy(
                update={
                    "sha256": sha256_file(path / item.logical_path),
                    "size_bytes": (path / item.logical_path).stat().st_size,
                }
            )
            for item in report.files
        )
        path = revise(path, files=files)
    with pytest.raises(ValidationError, match=message):
        verify_validation_report(path)


@pytest.mark.parametrize("kind", ["snapshot", "qlib_view", "signal"])
@pytest.mark.parametrize("provided", [False, True])
def test_registry_requires_explicit_paths_exactly_when_report_binds_them(tmp_path, kind, provided):
    path, _ = _publish_report(tmp_path, experiment_id="evidence-boundary")
    if not provided:
        field = {
            "snapshot": "snapshot_hash",
            "qlib_view": "qlib_view_hash",
            "signal": "signal_artifact_hash",
        }[kind]
        path = revise(path, **{field: "a" * 64})
    service = registry.RegistryService(tmp_path / "registry")
    kwargs = {kind + "_path": tmp_path / "unknown"} if provided else {}
    with pytest.raises(
        registry.RegistryError, match=r"(requires its explicit|supplied for a report without)"
    ):
        service.register_experiment(path, **kwargs)
    assert not service.list_experiments()


@pytest.mark.parametrize("kind", ["snapshot", "qlib_view"])
def test_registry_rejects_valid_but_differently_bound_dataset(tmp_path, monkeypatch, kind):
    path, _ = _publish_report(tmp_path, experiment_id="evidence-boundary")
    field = "snapshot_hash" if kind == "snapshot" else "qlib_view_hash"
    path = revise(path, **{field: "a" * 64})
    name = "verify_snapshot" if kind == "snapshot" else "verify_qlib_view"
    monkeypatch.setattr(
        registry,
        name,
        lambda _: SimpleNamespace(
            snapshot_hash="b" * 64, view_hash="b" * 64, source_snapshot_hash="b" * 64
        ),
    )
    service = registry.RegistryService(tmp_path / "registry")
    with pytest.raises(registry.RegistryError, match="does not match"):
        service.register_experiment(path, **{kind + "_path": tmp_path})
    assert not service.list_experiments()


@pytest.mark.parametrize("attack", ["json", "path", "canonical"])
def test_stored_event_bytes_and_envelope_location_are_both_authority(tmp_path, attack):
    stored = event(1)
    path = tmp_path / "strategy" / (str(stored.event.event_id) + ".json")
    path.parent.mkdir()
    path.write_bytes(canonical_json_bytes(stored.model_dump()))
    assert registry._read_stored_event(path) == stored
    if attack == "json":
        path.write_text(json.dumps({"schema_version": "unknown"}))
    elif attack == "path":
        changed = path.with_name("wrong.json")
        path.rename(changed)
        path = changed
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(registry.RegistryError, match="registry event"):
        registry._read_stored_event(path)
