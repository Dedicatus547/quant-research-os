"""Offline wiring/recovery windows; fake SDK/receipts do not qualify a host."""

import pytest
from test_sdk_campaign_producer import _Harness
from test_sdk_campaign_producer import setup as sdk_setup  # noqa: F401

from quantos.application.bounded_runtime import reconcile_only, run_bounded, runtime_summary
from quantos.artifacts.store import ArtifactConflictError, ArtifactIntegrityError


def test_loop_advances_two_candidates_and_receipts_without_duplicate_charge(sdk_setup):  # noqa: F811
    service, spec, _, producer, _ = sdk_setup
    calls = []
    checkpoints = []

    def step():
        pending = service.pending(spec.campaign_hash)
        harness = _Harness(pending, spec.sdk_profile)
        harness.stop = False
        harness.candidate_index = len(calls)
        calls.append(pending.content_hash)
        return producer.step(service, spec.campaign_hash, harness=harness)

    result = run_bounded(
        service, producer, spec, step=step, checkpoint=checkpoints.append, clock_check=lambda: None
    )
    assert result["engineering_state"] in {"COMPLETED", "EXHAUSTED"}
    assert len(calls) == result["launch_intents"] == 2
    assert len(result["execution_result_hashes"]) == 2
    assert result["research_budget"]["used_executions"] == 2
    assert result["qualification"] == "NOT_QUALIFIED"
    assert result["sdk_observed_usage"]["input_tokens"] == 20
    assert result["requests_without_usage_manifest"] == []
    before = result["research_budget"]
    reconcile_only(service, spec)
    after = runtime_summary(service, producer, spec, "AFTER")
    assert after["research_budget"] == before
    assert after["launch_intents"] == 2
    assert checkpoints[-1] == result


def test_unknown_and_no_progress_stop_without_step(sdk_setup):  # noqa: F811
    service, spec, request, producer, harness = sdk_setup
    checkpoints = []
    harness.crash = True
    with pytest.raises(RuntimeError):
        producer.launch(request, spec, harness=harness)

    def forbidden():
        raise AssertionError("UNKNOWN must not dispatch")

    result = run_bounded(
        service,
        producer,
        spec,
        step=forbidden,
        checkpoint=checkpoints.append,
        clock_check=lambda: None,
    )
    assert result["stop_reason"] == "UNKNOWN"
    assert harness.calls == 1
    assert result["research_budget"]["used_executions"] == 0


def test_no_progress_stops_after_one_step(sdk_setup):  # noqa: F811
    service, spec, _, producer, _ = sdk_setup
    calls = []

    def unchanged():
        calls.append(1)
        return service.status(spec.campaign_hash)

    result = run_bounded(
        service, producer, spec, step=unchanged, checkpoint=lambda _: None, clock_check=lambda: None
    )
    assert result["stop_reason"] == "NO_PROGRESS"
    assert calls == [1]


@pytest.mark.parametrize("window", ["accepted", "prepared", "started", "execution_receipt"])
def test_receipt_only_never_starts_fresh_work(sdk_setup, window):  # noqa: F811
    service, spec, request, producer, harness = sdk_setup
    response = producer.launch(request, spec, harness=harness)
    service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer")

    class Interrupted(Exception):
        pass

    if window != "accepted":

        def fault(point):
            if point == window:
                raise Interrupted()

        service._fault_hook = fault
        with pytest.raises(Interrupted):
            service.resume(spec.campaign_hash)
        service._fault_hook = None
    before = service.protocol.store.snapshot(spec.campaign_hash)
    counter = service._registered(spec.campaign_hash).orchestrator.execution_port.root / "calls"
    calls = counter.read_text() if counter.exists() else "0"
    if window in {"accepted", "prepared"}:
        with pytest.raises(ArtifactIntegrityError, match="fresh work"):
            reconcile_only(service, spec)
        assert service.protocol.store.snapshot(spec.campaign_hash).journal == before.journal
    else:
        result = reconcile_only(service, spec)
        assert result.state == ("RECOVERY_REQUIRED" if window == "started" else "EXHAUSTED")
    assert (counter.read_text() if counter.exists() else "0") == calls
    assert harness.calls == 1


def test_deadline_stops_before_any_progress(sdk_setup):  # noqa: F811
    service, spec, _, producer, _ = sdk_setup
    before = service.protocol.store.snapshot(spec.campaign_hash).journal

    def expired():
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        run_bounded(
            service,
            producer,
            spec,
            step=lambda: None,
            checkpoint=lambda _: None,
            clock_check=expired,
        )
    assert service.protocol.store.snapshot(spec.campaign_hash).journal == before


def test_formal_cli_wires_namespace_and_retains_failure_and_fixed_deadline(sdk_setup, monkeypatch):  # noqa: F811
    import argparse
    import json
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from scripts import sdk_campaign as cli
    from scripts import sdk_science_namespace as namespace

    from quantos.infrastructure import hosted_storage

    service, spec, _, producer, _ = sdk_setup
    live = producer.root / "live"
    events = []
    monkeypatch.setattr(
        hosted_storage,
        "configured_guard",
        lambda: SimpleNamespace(
            require_root=lambda _: None,
            require_lease=lambda: None,
        ),
    )
    monkeypatch.setattr(cli, "_service", lambda *_: service)
    monkeypatch.setattr(namespace, "frozen_tuple", lambda args: events.append(args))
    monkeypatch.setattr(cli, "_runtime_preflight", lambda _: None)

    @contextmanager
    def wired(actual_service, args, output):
        assert actual_service is service
        assert args.live_root == live
        events.append("ENTER_NAMESPACE")
        yield
        events.append("EXIT_NAMESPACE")

    monkeypatch.setattr(namespace, "configure_execution_namespace", wired)

    def failed(*args, **kwargs):
        raise RuntimeError("secret value must not appear in retained failure")

    monkeypatch.setattr(producer, "step", failed)
    metadata = live / "metadata"
    args = argparse.Namespace(
        command="run",
        protocol_root=str(live / "protocol"),
        business_lock_root=str(live / "business-locks"),
        evidence_root=str(live / "sdk-evidence"),
        spec=str(metadata / "sdk-campaign-spec.json"),
        spec_sha256=spec.content_hash,
        loader_config=str(metadata / "loader-config.json"),
        loader_config_sha256="a" * 64,
        deadline_utc=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        science_helper_sha256=cli.sha256_bytes(
            (cli.ROOT / "scripts/sdk_science_namespace.py").read_bytes()
        ),
        expected_new_bytes=1024,
    )
    config = SimpleNamespace(provenance_workspace=str(cli.ROOT))
    with pytest.raises(RuntimeError):
        cli._bounded_operation(args, spec, config, producer)
    control = live / "controller" / spec.campaign_hash
    exits = list(control.glob("operation-*-exit.json"))
    assert len(exits) == 1
    failure = json.loads(exits[0].read_bytes())
    assert failure["exit_code"] == 2 and failure["error_class"] == "RuntimeError"
    assert b"secret value" not in exits[0].read_bytes()
    assert events[-1] == "ENTER_NAMESPACE"
    assert list(control.glob("checkpoint-*.json"))
    args.deadline_utc = (datetime.now(UTC) + timedelta(seconds=120)).isoformat()
    with pytest.raises(ArtifactConflictError):
        cli._bounded_operation(args, spec, config, producer)
    assert len(events) == 2  # extending activation refused before namespace or dispatch
