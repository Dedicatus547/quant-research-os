"""Observation-to-account adapter guards; mock cases do not prove native accounting."""

from __future__ import annotations

import io
import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantos.application.personal_observation import PersonalObservationService, SnapshotArrival
from quantos.application.personal_research import PersonalDatasetBinding
from quantos.application.personal_shadow import PersonalShadowService
from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_research import HS300DatasetManifest
from quantos.contracts.personal_strategy import PersonalSignalArtifact, PersonalStrategy
from quantos.contracts.signal import SignalRow
from quantos.research.personal_signal import _lineage, compile_strategy_signal, load_strategy_signal
from quantos.research.qlib.personal_expression import translate_personal_expression
from quantos.research.qlib.signal import signal_content_hash, write_signal_table
from test_personal_observation import DAYS, RUNTIME, at, dataset, strategy

REPO = Path(__file__).resolve().parents[1]


class BoundFixtureCompiler:
    """Trusted unit-test compiler: publish a bound Arrow fixture, never an account."""

    def __init__(self, root, score=2.0):
        self.root, self.score = root, score
        self.calls = []

    def __call__(self, binding, spec, day, publication):
        self.calls.append((binding.manifest.dataset_id, day))
        directory = self.root / binding.manifest.snapshot_hash / spec.content_hash / str(day)
        if (directory / "manifest.json").exists():
            artifact = PersonalSignalArtifact.model_validate_json(
                (directory / "manifest.json").read_bytes()
            )
            load_strategy_signal(directory, artifact.content_hash)
            return {"directory": str(directory), "artifact_hash": artifact.content_hash}
        directory.mkdir(parents=True)
        rows = (
            SignalRow(
                instrument_id="600001.SH",
                signal_time=at(day),
                decision_time=at(day),
                available_at=at(day, 16),
                score=self.score,
                score_valid=self.score is not None,
                tradable=True,
            ),
        )
        temporary = io.BytesIO()
        write_signal_table(rows, temporary)
        atomic_write_bytes(directory / "signals.parquet", temporary.getvalue())
        translations = [translate_personal_expression(spec.score)]
        lineage = _lineage(binding, spec, translations, "SH000300")
        atomic_write_bytes(directory / "lineage.json", canonical_json_bytes(lineage))
        atomic_write_bytes(directory / "strategy.json", spec.canonical_bytes())
        manifest = binding.manifest
        artifact = PersonalSignalArtifact(
            strategy_hash=spec.content_hash,
            dataset_hash=manifest.content_hash,
            snapshot_hash=manifest.snapshot_hash,
            qlib_view_hash=manifest.qlib_view_hash,
            panel_sha256=manifest.panel_sha256,
            pit_evidence_hash=manifest.pit_evidence_hash,
            runtime_hash=RUNTIME,
            expression_translation_hash=lineage["translation_hash"],
            transform_lineage_hash=sha256_bytes(canonical_json_bytes(lineage)),
            signal_content_hash=signal_content_hash(rows),
            signals_parquet_sha256=sha256_file(directory / "signals.parquet"),
            start_date=day,
            end_date=day,
            row_count=1,
            source_vintage="synthetic",
        )
        atomic_write_bytes(directory / "manifest.json", artifact.canonical_bytes())
        return {"directory": str(directory), "artifact_hash": artifact.content_hash}


@pytest.fixture
def mock_native(monkeypatch):
    """Count dispatch only; actual native session semantics are tested separately."""
    import quantos.application.personal_shadow as shadow

    state = {}
    calls = []

    class Session:
        def __init__(self, root, **kwargs):
            self.root = str(root)
            state.setdefault(self.root, {})

        def status(self):
            steps = state[self.root]
            return {
                "completed_sessions": len(steps),
                "last_execution_date": max(steps) if steps else None,
                "state": "ACTIVE",
            }

        def native_state(self):
            # These guard-only cases deliberately have no native Account.
            return None

        def advance(self, binding, signal, signal_hash, day, **kwargs):
            calls.append({"day": day, "binding": binding, "signal": signal, "kwargs": kwargs})
            steps = state[self.root]
            if str(day) in steps:
                return {**steps[str(day)], "idempotent_reuse": True}
            receipt = {
                "execution_date": str(day),
                "signal_hash": signal_hash,
                "dataset_hash": binding.manifest.content_hash,
                "run_status": "SUCCEEDED",
                "validation_verdict": "NOT_EVALUATED",
            }
            steps[str(day)] = receipt
            return receipt

    monkeypatch.setattr(shadow, "NativePersonalSession", Session)
    return SimpleNamespace(calls=calls, state=state)


def setup_shadow(tmp_path, *, score=2.0, authorize=True, changes=None):
    one, meta_one = dataset(tmp_path, "one", 1)
    two, meta_two = dataset(tmp_path, "two", 2, previous=one.manifest.snapshot_hash)
    three, meta_three = dataset(tmp_path, "three", 3, previous=two.manifest.snapshot_hash)
    bindings = {item.manifest.dataset_id: item for item in (one, two, three)}
    metadata = {"one": meta_one, "two": meta_two, "three": meta_three}
    if changes:
        bindings, metadata = changes(bindings, metadata)
    compiler = BoundFixtureCompiler(tmp_path / "signals", score)
    observations = PersonalObservationService(
        tmp_path / "product",
        bindings,
        compiler,
        metadata=metadata,
        authorizer=lambda context: "synthetic-observation-scope",
        compiler_runtime_hash=RUNTIME,
    )
    plan = observations.prepare(
        {
            "idempotency_key": "shadow-fixture",
            "dataset_id": "one",
            "strategy": strategy().model_dump(mode="json"),
            "planned_dates": list(DAYS[1:]),
        }
    )
    approvals = []

    def authorizer(*args):
        approvals.append(args)
        return "synthetic-account-scope"

    service = PersonalShadowService(
        tmp_path / "product",
        observations,
        runtime_hash=RUNTIME,
        authorizer=authorizer if authorize else None,
    )
    account = service.prepare(plan["observation_id"], str(DAYS[2]), str(DAYS[3]))
    return SimpleNamespace(
        observations=observations,
        plan=plan,
        service=service,
        account=account,
        approvals=approvals,
        compiler=compiler,
    )


def first_record(fixture):
    return fixture.observations.observe(fixture.plan["observation_id"], DAYS[1], "one", at(DAYS[1]))


def advance(fixture, record, day=DAYS[2], dataset_id="two"):
    return fixture.service.advance(
        fixture.account["shadow_id"], str(day), record["record_hash"], dataset_id
    )


def test_observed_artifact_dispatch_duplicate_and_stop_are_explicit(tmp_path, mock_native):
    fixture = setup_shadow(tmp_path)
    record = first_record(fixture)
    assert record["status"] == "EMITTED" and record["after_the_fact"] is False
    input_manifest = fixture.observations.input_manifest(record["input_hash"])
    assert input_manifest["dataset_id"] == "one"
    result = advance(fixture, record)
    assert result["native_receipt"]["run_status"] == "SUCCEEDED"
    assert mock_native.calls[0]["kwargs"]["continuous_compatible"] is True
    assert mock_native.calls[0]["kwargs"]["observation_hash"] == record["record_hash"]
    assert mock_native.calls[0]["signal"].index.get_level_values("datetime").max().date() == DAYS[1]
    assert fixture.approvals[0][1] == "shadow_advance"
    assert advance(fixture, record)["native_receipt"]["idempotent_reuse"] is True
    status = fixture.service.status(fixture.account["shadow_id"])
    assert status["native"]["completed_sessions"] == 1
    assert fixture.service.stop(fixture.account["shadow_id"], "operator stop")["state"] == "STOPPED"
    before = len(mock_native.calls)
    with pytest.raises(PermissionError, match="stopped"):
        advance(fixture, record)
    assert len(mock_native.calls) == before


def test_default_deny_after_fact_missing_and_non_next_session_never_dispatch(tmp_path, mock_native):
    fixture = setup_shadow(tmp_path, authorize=False)
    record = first_record(fixture)
    with pytest.raises(PermissionError, match="authorization"):
        advance(fixture, record)
    assert not mock_native.calls
    fixture.service.authorizer = lambda *args: "synthetic-account-scope"
    with pytest.raises(ValueError, match="next actual session"):
        advance(fixture, record, day=DAYS[3], dataset_id="three")
    recomputed = fixture.observations.observe(
        fixture.plan["observation_id"], DAYS[1], "one", at(DAYS[2]), recompute=True
    )
    assert recomputed["after_the_fact"] is True
    with pytest.raises(PermissionError, match="contemporaneous"):
        advance(fixture, recomputed)
    missing = fixture.observations.observe(
        fixture.plan["observation_id"], DAYS[2], "one", at(DAYS[2])
    )
    assert missing["status"] == "MISSING"
    with pytest.raises(PermissionError, match="contemporaneous"):
        advance(fixture, missing, day=DAYS[3], dataset_id="three")
    assert not mock_native.calls


def test_account_first_day_cannot_be_skipped(tmp_path, mock_native):
    fixture = setup_shadow(tmp_path)
    first_record(fixture)
    later = fixture.observations.observe(
        fixture.plan["observation_id"], DAYS[2], "two", at(DAYS[2])
    )
    with pytest.raises(ValueError, match="first native execution"):
        advance(fixture, later, day=DAYS[3], dataset_id="three")
    assert not mock_native.calls


def test_abstain_is_a_real_cash_target_input_not_a_missing_signal(tmp_path, mock_native):
    fixture = setup_shadow(tmp_path, score=None)
    record = first_record(fixture)
    assert record["status"] == "ABSTAIN"
    advance(fixture, record)
    assert len(mock_native.calls) == 1
    assert mock_native.calls[0]["signal"].score.isna().all()


def modified_panel(binding, transform):
    frame = pd.read_parquet(binding.panel_path)
    transform(frame)
    path = binding.panel_path.with_name("modified-panel.parquet")
    frame.to_parquet(path, index=False)
    manifest = binding.manifest.model_copy(update={"panel_sha256": sha256_file(path)})
    return PersonalDatasetBinding(manifest, binding.provider_root, path, binding.pit_evidence_path)


@pytest.mark.parametrize(
    "problem",
    [
        "missing_factor",
        "unknown_factor",
        "negative_factor",
        "wrong_predecessor",
        "history_listing",
        "history_calendar",
        "unknown_action",
        "historical_price",
    ],
)
def test_revisions_unknown_units_and_unbound_execution_snapshots_stop_before_dispatch(
    tmp_path, mock_native, problem
):
    def changes(bindings, metadata):
        if problem in {"missing_factor", "unknown_factor", "negative_factor"}:
            for name in ("one", "two"):

                def update(frame):
                    if problem == "missing_factor":
                        frame.drop(columns="adjustment_factor", inplace=True)
                    else:
                        frame["adjustment_factor"] = np.nan if problem == "unknown_factor" else -1.0

                bindings[name] = modified_panel(bindings[name], update)
        elif problem == "wrong_predecessor":
            metadata["two"] = metadata["two"].model_copy(
                update={"previous_snapshot_hash": "e" * 64}
            )
        elif problem == "history_listing":
            bindings["one"] = modified_panel(
                bindings["one"], lambda f: f.__setitem__("is_listed", True)
            )
            bindings["two"] = modified_panel(
                bindings["two"], lambda f: f.__setitem__("is_listed", False)
            )
        elif problem == "history_calendar":
            binding = bindings["two"]
            path = binding.provider_root / "calendars/day.txt"
            path.write_text("\n".join(str(day) for day in DAYS[1:]) + "\n")
            manifest = binding.manifest.model_copy(
                update={
                    "qlib_files": {
                        **binding.manifest.qlib_files,
                        "calendars/day.txt": sha256_file(path),
                    }
                }
            )
            bindings["two"] = PersonalDatasetBinding(
                manifest, binding.provider_root, binding.panel_path, binding.pit_evidence_path
            )
        elif problem == "unknown_action":
            metadata["two"] = metadata["two"].model_copy(
                update={"corporate_actions": "UNSUPPORTED_OR_UNKNOWN"}
            )
        elif problem == "historical_price":

            def revise(frame):
                frame.loc[frame.trade_date == DAYS[0], "close"] += 1.0

            bindings["two"] = modified_panel(bindings["two"], revise)
        return bindings, metadata

    fixture = setup_shadow(tmp_path, changes=changes)
    record = first_record(fixture)
    assert record["status"] == "EMITTED"
    with pytest.raises((PermissionError, ValueError)):
        advance(fixture, record)
    assert not mock_native.calls


def test_account_scope_and_record_identity_cannot_be_substituted(tmp_path, mock_native):
    fixture = setup_shadow(tmp_path)
    record = first_record(fixture)
    with pytest.raises(ValueError, match="preceding signal day"):
        fixture.service.prepare(fixture.plan["observation_id"], str(DAYS[0]), str(DAYS[3]))
    with pytest.raises(ValueError, match="reversed"):
        fixture.service.prepare(fixture.plan["observation_id"], str(DAYS[3]), str(DAYS[2]))
    with pytest.raises(PermissionError, match="outside frozen account scope"):
        advance(fixture, record, day=DAYS[1], dataset_id="one")
    with pytest.raises(ValueError, match="not in this observation"):
        fixture.service.advance(fixture.account["shadow_id"], str(DAYS[2]), "d" * 64, "two")
    assert not mock_native.calls


@pytest.mark.skipif(
    not os.environ.get("QUANTOS_SHADOW_NATIVE_FIXTURE"),
    reason="explicit retained native fixture and shared resource lease required",
)
def test_observation_signalartifact_to_real_native_step_reuses_retained_fixture(
    tmp_path, monkeypatch
):
    """One real synthetic native step; no dump and no claim of true future observation."""
    root = Path(os.environ["QUANTOS_SHADOW_NATIVE_FIXTURE"])
    assert root.is_absolute()
    assert json.loads((root / "dump-exit.json").read_bytes())["actual_exit_code"] == 0
    assert json.loads((root / "health-exit.json").read_bytes())["actual_exit_code"] == 0
    manifest = HS300DatasetManifest.model_validate_json(
        (root / "dataset-manifest.json").read_bytes()
    )
    assert manifest.kind == "synthetic"
    binding = PersonalDatasetBinding(
        manifest,
        root / "provider",
        root / "panel.parquet",
        root / "pit.json",
        field_mapping_profile="canonical-personal-fields/v1",
    )
    signal_day = date(2024, 2, 2)
    execution_day = date(2024, 2, 5)
    spec = PersonalStrategy.model_validate(
        {
            **strategy().model_dump(mode="json"),
            "score": {
                "expression_id": "forward-history-regression",
                "nodes": [
                    {"node_id": "close", "operator": "field", "field_name": "amount_cny"},
                    {"node_id": "return3", "operator": "return", "inputs": ["close"], "window": 3},
                ],
                "output_node_id": "return3",
            },
        }
    )
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(binding.provider_root), region="cn", kernels=1)
    original_features = D.features
    query_ends = []

    def bounded_features(*args, **kwargs):
        end = kwargs.get("end_time", args[3] if len(args) > 3 else None)
        assert end is not None
        assert pd.Timestamp(end).date() <= execution_day
        query_ends.append(str(end))
        return original_features(*args, **kwargs)

    monkeypatch.setattr(D, "features", bounded_features)

    def compiler(actual, proposal, day, publication):
        artifact, _ = compile_strategy_signal(
            actual, proposal, day, day, tmp_path / "real-signal", RUNTIME
        )
        return {"directory": str(tmp_path / "real-signal"), "artifact_hash": artifact.content_hash}

    metadata = SnapshotArrival(
        acquired_at=at(signal_day, 17),
        source_visible_at=at(signal_day, 16),
        received_at=at(signal_day, 18),
        evidence_sha256="c" * 64,
        corporate_actions="KNOWN_NONE_IN_SCOPE",
    )
    observations = PersonalObservationService(
        tmp_path / "product",
        {manifest.dataset_id: binding},
        compiler,
        metadata={manifest.dataset_id: metadata},
        authorizer=lambda context: "synthetic-observation-scope",
        compiler_runtime_hash=RUNTIME,
    )
    plan = observations.prepare(
        {
            "idempotency_key": "native-observation",
            "dataset_id": manifest.dataset_id,
            "strategy": spec.model_dump(mode="json"),
            "planned_dates": [signal_day],
        }
    )
    assert plan["readiness"] == "READY_FOR_AUTHORIZATION"
    record = observations.observe(
        plan["observation_id"], signal_day, manifest.dataset_id, at(signal_day)
    )
    assert record["status"] == "EMITTED"
    assert record["scope"] == "ENGINEERING_REPLAY" and record["after_the_fact"] is False
    service = PersonalShadowService(
        tmp_path / "product",
        observations,
        runtime_hash=RUNTIME,
        authorizer=lambda *args: "synthetic-native-scope",
    )
    account = service.prepare(plan["observation_id"], str(execution_day), str(execution_day))
    result = service.advance(
        account["shadow_id"], str(execution_day), record["record_hash"], manifest.dataset_id
    )
    assert result["native_receipt"]["run_status"] == "SUCCEEDED"
    status = service.status(account["shadow_id"])
    assert status["native"]["completed_sessions"] == 1
    assert status["native_cash_cny"] is not None
    assert status["native_latest_report"] is not None
    assert status["holdings_count"] >= len(status["holdings"])
    assert query_ends
    assert (
        service.advance(
            account["shadow_id"], str(execution_day), record["record_hash"], manifest.dataset_id
        )["native_receipt"]["idempotent_reuse"]
        is True
    )
    directory = (
        tmp_path
        / "product/shadow-accounts"
        / account["shadow_id"]
        / "native/steps"
        / str(execution_day)
    )
    assert {
        "state.native.json",
        "decision.native.json",
        "fills.native.json",
        "targets.json",
        "completed.json",
    } <= {p.name for p in directory.iterdir()}
