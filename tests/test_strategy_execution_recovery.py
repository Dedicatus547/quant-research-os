"""Task coordination failures with inert native/signal ports, never a backtest."""

import json
from types import SimpleNamespace

import pytest

from quantos.application.personal_strategy import PersonalStrategyResearch, UnknownNativeStep
from quantos.contracts.personal_strategy import PreparedStrategyStudy, StrategyStudyRequest
from quantos.research import personal_native, personal_signal
from test_personal_complete import request
from test_personal_product_boundaries import core as core


@pytest.fixture
def execution(core, monkeypatch):
    study = StrategyStudyRequest.model_validate(request(core.catalog["fixture"]))
    prepared = PreparedStrategyStudy(
        request=study,
        code_hash="a" * 64,
        dataset_hash="b" * 64,
        strategy_hashes={c.candidate_id: c.strategy.content_hash for c in study.candidates},
        policy_hash=study.policy.content_hash,
        readiness="READY_FOR_AUTHORIZATION",
        gaps=(),
        resolved={},
    )
    events = [SimpleNamespace(state="PREPARED")]
    records = []
    authority = SimpleNamespace(
        scope=SimpleNamespace(wall_seconds=100),
        reserve=lambda *_: "c" * 64,
        record=lambda *args, **kwargs: records.append((args, kwargs)),
    )
    core.strategy_authority = authority
    core._events = lambda _: events
    core._append = lambda task, state, detail: events.append(
        SimpleNamespace(state=state, detail=detail)
    )
    core.status = lambda _: {"state": events[-1].state}
    core.worker_state = lambda _: events[-1].state
    core._cancel_requested = lambda _: events[-1].state == "CANCEL_REQUESTED"
    app = PersonalStrategyResearch(core)
    monkeypatch.setattr(app, "runtime_hash", lambda: prepared.code_hash)
    monkeypatch.setattr(app, "dependencies", lambda: {"synthetic_coordination_only": True})
    calls = []

    def compile(*args, **kwargs):
        directory = args[4]
        directory.mkdir()
        for name in ("manifest.json", "strategy.json", "lineage.json", "signals.parquet"):
            (directory / name).write_bytes(b"inert fixture; never deserialized")
        return SimpleNamespace(content_hash="d" * 64), object()

    def native(*args):
        calls.append(args)
        return {"run_status": "SUCCEEDED", "metrics": {}, "files": {}}

    monkeypatch.setattr(personal_signal, "compile_strategy_signal", compile)
    monkeypatch.setattr(personal_native, "execute_candidate", native)
    return SimpleNamespace(
        app=app,
        core=core,
        prepared=prepared,
        records=records,
        calls=calls,
        events=events,
        root=core.root / "tasks" / prepared.content_hash / "execution",
    )


@pytest.mark.parametrize(
    "failure", ["signal", "native", "existing", "unknown", "cancel", "record", "timeout"]
)
def test_coordination_preserves_failure_and_never_reissues_native_step(
    execution, monkeypatch, failure
):
    f = execution

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic port failure")

    if failure == "signal":
        monkeypatch.setattr(personal_signal, "compile_strategy_signal", fail)
    elif failure == "native":
        monkeypatch.setattr(personal_native, "execute_candidate", fail)
    elif failure == "existing":
        (f.root / "price").mkdir(parents=True)
    elif failure in {"unknown", "cancel"}:

        def stopped(*args):
            f.events.append(
                SimpleNamespace(state="UNKNOWN" if failure == "unknown" else "CANCEL_REQUESTED")
            )
            return {"run_status": "SUCCEEDED", "metrics": {}, "files": {}}

        monkeypatch.setattr(personal_native, "execute_candidate", stopped)
    elif failure == "timeout":
        f.core.strategy_authority.scope.wall_seconds = -1
    else:

        def record(*args, **kwargs):
            f.records.append((args, kwargs))
            if len(f.records) == 1:
                raise OSError("synthetic scope writer interruption")

        f.core.strategy_authority.record = record
    result = f.app.execute(f.prepared)
    expected = (
        "UNKNOWN" if failure == "unknown" else "CANCELLED" if failure == "cancel" else "FAILED"
    )
    assert result["state"] == expected
    if failure in {"existing", "record", "timeout"}:
        detail = json.loads((f.root / "coordination-failure.json").read_bytes())
        assert (
            detail["error_type"]
            == {
                "existing": UnknownNativeStep.__name__,
                "record": "OSError",
                "timeout": "TimeoutError",
            }[failure]
        )
    else:
        outcome = json.loads((f.root / "outcome.json").read_bytes())
        assert outcome["run_status"] == expected
        assert outcome["validation_verdict"] == "NOT_EVALUATED"
        assert len(outcome["receipts"]) == (1 if failure in {"unknown", "cancel"} else 2)
    before = len(f.calls)
    assert f.app.execute(f.prepared)["idempotent_reuse"]
    assert len(f.calls) == before
    assert f.records[-1][0][1] == expected


@pytest.mark.parametrize("failure", ["readiness", "runtime", "authority", "identity"])
def test_preexecution_checks_do_not_start_candidate(execution, monkeypatch, failure):
    f = execution
    if failure == "readiness":
        f.prepared = f.prepared.model_copy(update={"readiness": "BLOCKED"})
    elif failure == "runtime":
        monkeypatch.setattr(f.app, "runtime_hash", lambda: "e" * 64)
    elif failure == "authority":
        f.core.strategy_authority = None
    else:
        from quantos.application import personal_research

        monkeypatch.setattr(personal_research, "_process_identity", lambda _: None)
    with pytest.raises((PermissionError, RuntimeError)):
        f.app.execute(f.prepared)
    assert not f.calls and not f.root.exists()


@pytest.mark.parametrize("state", ["PREPARED", "FAILED"])
def test_dispatcher_receives_only_prepared_task(execution, state):
    f = execution
    f.events[-1].state = state
    dispatched = []
    f.core.strategy_dispatcher = lambda *args: dispatched.append(args) or {"state": "DISPATCHED"}
    result = f.app.execute(f.prepared)
    assert result["state"] == ("DISPATCHED" if state == "PREPARED" else "FAILED")
    assert len(dispatched) == (state == "PREPARED")
    assert not f.calls
