"""Synthetic snapshot-arrival boundaries; the fixture compiler is not a research run."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pydantic import ValidationError

from quantos.application.personal_observation import PersonalObservationService, SnapshotArrival
from quantos.application.personal_research import PersonalDatasetBinding
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_research import HS300DatasetManifest
from quantos.contracts.personal_strategy import PersonalSignalArtifact, PersonalStrategy
from quantos.contracts.signal import SignalRow
from quantos.research.qlib.personal_expression import (
    expression_dependencies,
    translate_personal_expression,
)
from quantos.research.qlib.signal import signal_content_hash, write_signal_table

ZONE = ZoneInfo("Asia/Shanghai")
DAYS = (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5))
RUNTIME = "f" * 64


def at(day, hour=23, minute=59):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


def strategy(field="adjusted_close"):
    return PersonalStrategy.model_validate(
        {
            "score": {
                "expression_id": "observation-fixture",
                "nodes": [{"node_id": "price", "operator": "field", "field_name": field}],
                "output_node_id": "price",
            },
            "top_k": 1,
        }
    )


def dataset(
    root,
    name,
    through,
    *,
    previous=None,
    received=None,
    revise=False,
    unknown=False,
    future=False,
    missing_factor=False,
    missing_close=False,
    unknown_status=False,
):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "calendars").mkdir()
    calendar = directory / "calendars/day.txt"
    calendar.write_text("\n".join(day.isoformat() for day in DAYS) + "\n")
    # These small inventory sentinels test mapping admission. The injected
    # compiler emits Arrow directly and never calls Qlib on these bytes.
    inventory = {"calendars/day.txt": sha256_file(calendar)}
    feature_root = directory / "features/sh600001"
    feature_root.mkdir(parents=True)
    for feature in ("close", "volume"):
        path = feature_root / (feature + ".day.bin")
        path.write_bytes(b"fixture inventory sentinel; not a Qlib cache")
        inventory[f"features/sh600001/{feature}.day.bin"] = sha256_file(path)
    frame = pd.DataFrame(
        [
            {
                "trade_date": day,
                "qlib_id": "SH600001",
                "close": 10.0 + i,
                "volume": 1000.0,
                "amount_cny": 1_000_000.0,
                "adjustment_factor": 1.0,
                "is_member": True,
                "is_st": False,
                "is_suspended": False,
                "available_at": at(day, 16),
            }
            for i, day in enumerate(DAYS[: through + 1])
        ]
    )
    if revise:
        frame.loc[0, "close"] = 20.0
        frame.loc[0, "adjustment_factor"] = 2.0
    if future:
        frame.loc[1, "available_at"] = at(DAYS[2], 16)
    if missing_factor:
        frame = frame.drop(columns="adjustment_factor")
    if missing_close:
        frame.loc[1, "close"] = float("nan")
    if unknown_status:
        frame["is_st"] = frame["is_st"].astype("boolean")
        frame.loc[1, "is_st"] = None
    panel = directory / "panel.parquet"
    frame.to_parquet(panel, index=False)
    pit = directory / "pit.json"
    pit.write_bytes(b"fixture PIT identity")
    manifest = HS300DatasetManifest(
        dataset_id=name,
        kind="synthetic",
        snapshot_hash=sha256_bytes((name + "-snapshot").encode()),
        qlib_view_hash=sha256_bytes((name + "-view").encode()),
        panel_sha256=sha256_file(panel),
        pit_evidence_hash=sha256_file(pit),
        warmup_start=DAYS[0],
        start_date=DAYS[1],
        end_date=DAYS[-1],
        market_source="SYNTHETIC_FIXTURE",
        source_vintage="synthetic",
        exposure="synthetic",
        qlib_files=inventory,
        snapshot_manifest_sha256="a" * 64,
        view_manifest_sha256="b" * 64,
    )
    arrival = SnapshotArrival(
        acquired_at=at(DAYS[through], 17),
        source_visible_at=at(DAYS[through], 16),
        received_at=received or at(DAYS[through], 18),
        evidence_sha256="c" * 64,
        previous_snapshot_hash=previous,
        corporate_actions="UNSUPPORTED_OR_UNKNOWN" if unknown else "KNOWN_NONE_IN_SCOPE",
    )
    return PersonalDatasetBinding(manifest, directory, panel, pit), arrival


class FixtureCompiler:
    """Emit existing Arrow SignalArtifact layout; no strategy computation or account."""

    def __init__(self, root, *, score=2.0, error=False):
        self.root, self.score, self.error = root, score, error
        self.calls = []

    def __call__(self, binding, spec, day, publication_time):
        self.calls.append(
            (binding.manifest.snapshot_hash, spec.content_hash, day, publication_time)
        )
        if self.error:
            raise RuntimeError("private exception message must not be retained")
        destination = (
            self.root / binding.manifest.snapshot_hash / spec.content_hash / day.isoformat()
        )
        destination.mkdir(parents=True)
        signal = SignalRow(
            instrument_id="600001.SH",
            signal_time=at(day),
            decision_time=at(day),
            available_at=at(day, 16),
            score=self.score,
            score_valid=self.score is not None,
            tradable=True,
        )
        write_signal_table((signal,), destination / "signals.parquet")
        expressions = [
            e for e in (spec.score, spec.eligibility, spec.market_condition) if e is not None
        ]
        translations = [translate_personal_expression(e) for e in expressions]
        translation_hash = sha256_bytes(canonical_json_bytes(translations))
        lineage = canonical_json_bytes(
            {
                "schema_version": "personal-signal-lineage/v1",
                "strategy_hash": spec.content_hash,
                "dataset_hash": binding.manifest.content_hash,
                "panel_sha256": binding.manifest.panel_sha256,
                "pit_evidence_hash": binding.manifest.pit_evidence_hash,
                "translation_hash": translation_hash,
                "expressions": [e.model_dump(mode="json") for e in expressions],
                "dependencies": [expression_dependencies(e) for e in expressions],
                "benchmark": "SH000300",
                "rule": "backward dependency availability; "
                "input lag once; native execution lag once",
            }
        )
        atomic_write_bytes(destination / "lineage.json", lineage)
        atomic_write_bytes(destination / "strategy.json", spec.canonical_bytes())
        manifest = binding.manifest
        artifact = PersonalSignalArtifact(
            strategy_hash=spec.content_hash,
            dataset_hash=manifest.content_hash,
            snapshot_hash=manifest.snapshot_hash,
            qlib_view_hash=manifest.qlib_view_hash,
            panel_sha256=manifest.panel_sha256,
            pit_evidence_hash=manifest.pit_evidence_hash,
            runtime_hash=RUNTIME,
            expression_translation_hash=translation_hash,
            transform_lineage_hash=sha256_bytes(lineage),
            signal_content_hash=signal_content_hash((signal,)),
            signals_parquet_sha256=sha256_file(destination / "signals.parquet"),
            start_date=day,
            end_date=day,
            row_count=1,
            source_vintage="synthetic",
        )
        atomic_write_bytes(destination / "manifest.json", artifact.canonical_bytes())
        return {"directory": str(destination), "artifact_hash": artifact.content_hash}


def setup(
    tmp_path,
    *,
    authorized=True,
    score=2.0,
    error=False,
    late=False,
    revision=False,
    unknown=False,
    future=False,
    missing_factor=False,
    missing_close=False,
    unknown_status=False,
):
    one, meta_one = dataset(
        tmp_path,
        "one",
        1,
        future=future,
        missing_close=missing_close,
        unknown_status=unknown_status,
    )
    two, meta_two = dataset(
        tmp_path,
        "two",
        2,
        previous=one.manifest.snapshot_hash,
        received=at(DAYS[3], 10) if late else None,
        missing_factor=missing_factor,
    )
    three, meta_three = dataset(
        tmp_path, "three", 3, previous=two.manifest.snapshot_hash, revise=revision, unknown=unknown
    )
    compiler = FixtureCompiler(tmp_path / "compiled", score=score, error=error)
    app = PersonalObservationService(
        tmp_path / "observations",
        {b.manifest.dataset_id: b for b in (one, two, three)},
        compiler,
        metadata={"one": meta_one, "two": meta_two, "three": meta_three},
        compiler_runtime_hash=RUNTIME,
        authorizer=(lambda context: "synthetic observation only") if authorized else None,
    )
    request = {
        "idempotency_key": "arrival-fixture",
        "dataset_id": "one",
        "strategy": strategy().model_dump(mode="json"),
        "planned_dates": list(DAYS[1:]),
    }
    return app, compiler, request


def test_normal_arrivals_publish_artifacts_and_snapshots_link_across_restart(tmp_path):
    app, compiler, request = setup(tmp_path)
    plan = app.prepare(request)
    identity = plan["observation_id"]
    assert plan["scope"] == "ENGINEERING_REPLAY"
    assert app.prepare(request) == plan
    first = app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    second = app.observe(identity, DAYS[2], "two", at(DAYS[2]))
    assert first["status"] == second["status"] == "EMITTED"
    assert second["previous_record_hash"] == first["record_hash"]
    assert second["continuous_compatible"] is True
    assert first["signal"]["finite_score_count"] == 1
    assert first["signal_published_at"] is not None
    assert datetime.fromisoformat(first["recorded_at"]).year >= 2026
    assert first["after_the_fact"] is False
    assert len(compiler.calls) == 2
    restarted = PersonalObservationService(
        app.root, app.catalog, compiler, metadata=app.metadata, compiler_runtime_hash=RUNTIME
    )
    assert restarted.observe(identity, DAYS[2], "two", at(DAYS[2])) == second
    assert len(compiler.calls) == 2
    page = restarted.status(identity, limit=1)
    assert page["record_count"] == 2 and page["next_offset"] == 1
    assert restarted.status(identity, offset=1)["records"] == [second]
    assert len(canonical_json_bytes(page)) < 8000


def test_missing_then_late_recomputation_appends_without_replacing_original(tmp_path):
    app, compiler, request = setup(tmp_path, late=True)
    identity = app.prepare(request)["observation_id"]
    first = app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    missing = app.observe(identity, DAYS[2], "one", at(DAYS[2]))
    assert missing["status"] == "MISSING" and missing["signal"] is None
    late = app.observe(identity, DAYS[2], "two", at(DAYS[3]), recompute=True)
    assert late["status"] == "EMITTED"
    assert late["after_the_fact"] is True
    assert late["reason"] == "AFTER_THE_FACT_RECOMPUTATION"
    assert late["revises_record_hash"] == missing["record_hash"]
    assert app.status(identity)["records"] == [first, missing, late]
    assert len(compiler.calls) == 2
    assert app.observe(identity, DAYS[2], "two", at(DAYS[3]), recompute=True) == late
    assert len(compiler.calls) == 2


def test_revised_adjustment_units_are_separate_and_incompatible_with_continuity(tmp_path):
    app, _, request = setup(tmp_path, revision=True)
    identity = app.prepare(request)["observation_id"]
    first = app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    second = app.observe(identity, DAYS[2], "two", at(DAYS[2]))
    revised = app.observe(identity, DAYS[3], "three", at(DAYS[3]))
    assert revised["status"] == "EMITTED"
    assert revised["continuous_compatible"] is False
    assert revised["after_the_fact"] is True
    assert "HISTORICAL_UNITS_OR_PRICE_REVISED:adjustment_factor" in revised["continuity_reasons"]
    assert app.status(identity)["records"][:2] == [first, second]
    later = app.observe(identity, DAYS[2], "three", at(DAYS[3]), recompute=True)
    assert later["continuous_compatible"] is False
    assert "PREVIOUS_CHAIN_INCOMPATIBLE" in later["continuity_reasons"]


def test_missing_factor_stops_account_adoption_without_inventing_conversion(tmp_path):
    app, _, request = setup(tmp_path, missing_factor=True)
    identity = app.prepare(request)["observation_id"]
    app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    record = app.observe(identity, DAYS[2], "two", at(DAYS[2]))
    assert record["status"] == "EMITTED"
    assert record["continuous_compatible"] is False
    assert "UNIT_COMPARISON_FIELDS_MISSING" in record["continuity_reasons"]


def test_unknown_company_actions_stop_and_do_not_generate_signals(tmp_path):
    app, compiler, request = setup(tmp_path, unknown=True)
    identity = app.prepare(request)["observation_id"]
    app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    app.observe(identity, DAYS[2], "two", at(DAYS[2]))
    stopped = app.observe(identity, DAYS[3], "three", at(DAYS[3]))
    assert stopped["status"] == "STOPPED"
    assert stopped["actual_exit"] == "NOT_STARTED"
    assert len(compiler.calls) == 2
    assert app.status(identity)["state"] == "STOPPED"
    with pytest.raises(ValueError, match="stopped"):
        app.observe(identity, DAYS[2], "three", at(DAYS[3]), recompute=True)


def test_no_authority_from_arguments_and_no_cross_day_reissue(tmp_path):
    app, compiler, request = setup(tmp_path, authorized=False)
    with pytest.raises(ValidationError):
        app.prepare({**request, "approved": True})
    identity = app.prepare(request)["observation_id"]
    with pytest.raises(PermissionError, match="server-side"):
        app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    assert not compiler.calls
    assert app.status(identity)["record_count"] == 0
    assert app.snapshot_prepare("one")["acquisition_calls"] == 0
    with pytest.raises(ValueError, match="registered"):
        app.snapshot_prepare("../../outside")


def test_metadata_and_runtime_gaps_are_explicit_and_strategy_versions_are_distinct(tmp_path):
    app, compiler, request = setup(tmp_path)
    blocked = PersonalObservationService(app.root / "blocked", app.catalog, compiler)
    plan = blocked.prepare(request)
    assert plan["readiness"] == "BLOCKED"
    assert set(plan["gaps"]) == {
        "SNAPSHOT_ARRIVAL_METADATA_REQUIRED",
        "COMPILER_RUNTIME_IDENTITY_REQUIRED",
    }
    with pytest.raises(PermissionError, match="blocked"):
        blocked.observe(plan["observation_id"], DAYS[1], "one", at(DAYS[1]))
    first = app.prepare(request)
    changed = {**request, "strategy": strategy("adjusted_volume").model_dump(mode="json")}
    with pytest.raises(ValueError, match="idempotency"):
        app.prepare(changed)
    new = app.prepare({**changed, "idempotency_key": "new-strategy-version"})
    assert first["observation_id"] != new["observation_id"]
    assert first["strategy_hash"] != new["strategy_hash"]


def test_calendar_timing_and_missing_day_order_reject_before_compilation(tmp_path):
    app, compiler, request = setup(tmp_path)
    with pytest.raises(ValueError, match="actual sessions"):
        app.prepare({**request, "planned_dates": ["2024-01-06"]})
    identity = app.prepare(request)["observation_id"]
    with pytest.raises(ValueError, match="preceding"):
        app.observe(identity, DAYS[2], "two", at(DAYS[2]))
    with pytest.raises(ValueError, match="requires an original"):
        app.observe(identity, DAYS[1], "one", at(DAYS[1]), recompute=True)
    with pytest.raises(ValueError, match="cutoff"):
        app.observe(identity, DAYS[1], "one", at(DAYS[1]) - timedelta(minutes=1))
    with pytest.raises(ValueError, match="future"):
        app.observe(identity, DAYS[1], "one", datetime.now(UTC) + timedelta(days=1))
    with pytest.raises(ValueError, match="planned"):
        app.observe(identity, date(2024, 1, 6), "one", at(DAYS[3]))
    assert not compiler.calls


def test_source_future_availability_never_enters_old_signal(tmp_path):
    app, compiler, request = setup(tmp_path, future=True)
    identity = app.prepare(request)["observation_id"]
    missing = app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    assert missing["status"] == "MISSING" and missing["reason"] == "PIT_FUTURE_INPUT_EXCLUDED"
    assert not compiler.calls


def test_delayed_publication_cannot_be_labelled_as_an_on_time_signal(tmp_path):
    app, _, request = setup(tmp_path)
    identity = app.prepare(request)["observation_id"]
    record = app.observe(identity, DAYS[1], "one", at(DAYS[3]))
    assert record["status"] == "EMITTED"
    assert record["after_the_fact"] is True
    assert record["next_execution_session"] == DAYS[2].isoformat()
    assert app.plan(identity)["request"]["strategy"] == request["strategy"]
    assert app.record(identity, record["record_hash"]) == record
    assert app.input_manifest(record["input_hash"])["snapshot_hash"] == record["snapshot_hash"]
    with pytest.raises(ValueError, match="not in"):
        app.record(identity, "0" * 64)


@pytest.mark.parametrize(
    "problem,expected", [("missing_close", "MISSING"), ("unknown_status", "STOPPED")]
)
def test_missing_prices_or_unknown_status_never_become_an_ineligible_zero(
    tmp_path, problem, expected
):
    app, compiler, request = setup(tmp_path, **{problem: True})
    identity = app.prepare(request)["observation_id"]
    record = app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    assert record["status"] == expected and record["signal"] is None
    assert not compiler.calls


def test_unsupported_field_mapping_is_blocked_during_preparation(tmp_path):
    app, compiler, request = setup(tmp_path)
    plan = app.prepare({**request, "strategy": strategy("amount_cny").model_dump(mode="json")})
    assert plan["readiness"] == "BLOCKED"
    assert any("QLIB_REQUIRED_FIELDS_UNMAPPED" in gap for gap in plan["gaps"])
    assert not compiler.calls


def test_abstention_and_compiler_failure_preserve_real_in_process_outcome(tmp_path):
    app, _, request = setup(tmp_path / "abstain", score=None)
    identity = app.prepare(request)["observation_id"]
    record = app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    assert record["status"] == "ABSTAIN"
    assert record["signal"]["finite_score_count"] == 0
    failed, compiler, payload = setup(tmp_path / "failed", error=True)
    identity = failed.prepare(payload)["observation_id"]
    record = failed.observe(identity, DAYS[1], "one", at(DAYS[1]))
    assert record["status"] == "FAILED" and record["actual_exit"] == "IN_PROCESS_EXCEPTION"
    assert "private" not in json.dumps(record)
    assert failed.observe(identity, DAYS[1], "one", at(DAYS[1])) == record
    assert len(compiler.calls) == 1


def test_post_compile_pre_publish_crash_recovers_completion_without_recompiling(
    tmp_path, monkeypatch
):
    app, compiler, request = setup(tmp_path)
    identity = app.prepare(request)["observation_id"]
    original = app._finish

    def interrupted(*args):
        raise RuntimeError("synthetic crash after durable completion before publication")

    monkeypatch.setattr(app, "_finish", interrupted)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    assert len(compiler.calls) == 1
    monkeypatch.setattr(app, "_finish", original)
    attempt = next((app.root / "observations" / identity / "attempts").iterdir())
    record = app.recover(identity, attempt.name)
    assert record["status"] == "EMITTED"
    assert app.recover(identity, attempt.name) == record
    assert len(compiler.calls) == 1
    assert app.status(identity)["record_count"] == 1


def test_intent_without_completion_stays_unknown_and_is_never_blindly_reissued(tmp_path):
    app, compiler, request = setup(tmp_path)
    identity = app.prepare(request)["observation_id"]
    operation = {
        "observation_id": identity,
        "day": DAYS[1].isoformat(),
        "dataset_id": "one",
        "recompute": False,
    }
    digest = sha256_bytes(canonical_json_bytes(operation))
    root = app.root / "observations" / identity / "attempts" / digest
    root.mkdir(parents=True)
    atomic_write_bytes(
        root / "intent.json", canonical_json_bytes({**operation, "attempt_hash": digest})
    )
    assert app.observe(identity, DAYS[1], "one", at(DAYS[1]))["status"] == "UNKNOWN"
    assert app.recover(identity, digest)["status"] == "UNKNOWN"
    assert app.status(identity)["unknown_attempts"] == [digest]
    assert not compiler.calls


@pytest.mark.parametrize("attack", ["plan", "input", "record", "artifact"])
def test_plan_input_chain_and_artifact_tampering_are_rejected(tmp_path, attack):
    app, _, request = setup(tmp_path)
    identity = app.prepare(request)["observation_id"]
    record = app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    root = app.root / "observations" / identity
    targets = {
        "plan": root / "plan.json",
        "input": app.root / "inputs" / (record["input_hash"] + ".json"),
        "record": next((root / "records").iterdir()),
        "artifact": Path(record["signal"]["directory"]) / "signals.parquet",
    }
    targets[attack].write_bytes(b"{}")
    with pytest.raises((ArtifactIntegrityError, ValueError, KeyError)):
        app.observe(identity, DAYS[1], "one", at(DAYS[1]))


def test_stop_is_durable_idempotent_and_output_limits_are_bounded(tmp_path):
    app, compiler, request = setup(tmp_path)
    identity = app.prepare(request)["observation_id"]
    stopped = app.stop(identity, "Finite observation ended")
    assert app.stop(identity) == stopped
    assert app.status(identity)["state"] == "STOPPED"
    with pytest.raises(ValueError, match="stopped"):
        app.observe(identity, DAYS[1], "one", at(DAYS[1]))
    for offset, limit in ((-1, 1), (0, 0), (0, 101)):
        with pytest.raises(ValueError, match="limit"):
            app.status(identity, offset, limit)
    assert not compiler.calls


def test_arrival_metadata_requires_aware_and_ordered_times():
    with pytest.raises(ValueError, match="timezone"):
        SnapshotArrival(
            acquired_at=datetime(2024, 1, 3),
            source_visible_at=at(DAYS[1], 16),
            received_at=at(DAYS[1], 18),
            evidence_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="receipt"):
        SnapshotArrival(
            acquired_at=at(DAYS[2], 16),
            source_visible_at=at(DAYS[1], 16),
            received_at=at(DAYS[1], 18),
            evidence_sha256="a" * 64,
        )
