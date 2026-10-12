"""Offline proposal/accounting regressions: no provider, market execution or campaign run."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from quantos.application import discovery_execution as execution
from quantos.application.discovery_admission import (
    build_discovery_batch,
    capability_rejection,
    verify_discovery_batch,
)
from quantos.application.discovery_baselines import baseline_expression_space, generate_baseline
from quantos.application.discovery_comparison import build_discovery_comparison
from quantos.application.discovery_generation import GenerationStore
from quantos.application.discovery_hosted import generation_schema_bytes
from quantos.application.discovery_report import render_discovery_report
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
)
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.discovery import (
    DiscoveryDesign,
    GenerationRequest,
    GenerationReservation,
    GenerationResponse,
)
from quantos.contracts.pit import SafeExpressionNode, SafeQlibExpressionSpec, SafeQlibOperator

FIXTURE = Path(__file__).parents[1] / "fixtures/discovery_regression/design.json"


@pytest.fixture
def design() -> DiscoveryDesign:
    value = json.loads(FIXTURE.read_bytes())
    value.update(
        context_hashes=[sha256_bytes(b'{"fixture":true}')], evaluation_opportunities_per_method=2
    )
    return DiscoveryDesign.model_validate(value)


@pytest.fixture
def durable(tmp_path: Path) -> Path:
    # The production store explicitly rejects /tmp. Under ordinary local pytest,
    # synthetic test storage therefore lives in the ignored workspace artifacts.
    if tmp_path.is_relative_to("/tmp") or tmp_path.is_relative_to("/var/tmp"):
        return Path(__file__).parents[2] / "artifacts/test-authority" / uuid4().hex
    return tmp_path


def requests(design: DiscoveryDesign) -> tuple[GenerationRequest, ...]:
    return tuple(
        GenerationRequest(
            design_hash=design.content_hash,
            method=method,
            max_attempts=2,
            seed=None if method == "LLM" else 17,
            model_identifier="gpt-6.1-sol" if method == "LLM" else None,
            reasoning_effort="medium" if method == "LLM" else None,
            configuration_hash="a" * 64,
            prompt="Synthetic bounded AST regression fixture",
            input_hashes=design.context_hashes,
        )
        for method in ("LLM", "RANDOM", "TEMPLATE")
    )


def frozen_store(design: DiscoveryDesign, root: Path):
    store = GenerationStore(root)
    reqs = requests(design)
    for req in reqs:
        store.save_request(design, req)
        reservation = store.reserve(req)
        text = (
            baseline_expression_space(design)[0].canonical_bytes().decode()
            if req.method == "LLM"
            else generate_baseline(design, req)[0]
        )
        response = store.complete(
            req, reservation, text, producer="OFFLINE_IMPORT" if req.method == "LLM" else "BASELINE"
        )
        assert response.failure_code is None
    return store, store.freeze(design)


def test_seeded_baselines_share_the_admission_grammar(design):
    space = baseline_expression_space(design)
    assert space and len({item.content_hash for item in space}) == len(space)
    assert all(capability_rejection(design, item) is None for item in space)
    for req in requests(design)[1:]:
        first, second = generate_baseline(design, req), generate_baseline(design, req)
        assert first == second and len(first) == req.max_attempts
        assert all(SafeQlibExpressionSpec.model_validate_json(text) in space for text in first)
    with pytest.raises(ValueError, match="supports"):
        generate_baseline(design, requests(design)[0])
    with pytest.raises(ValueError, match="design_hash"):
        generate_baseline(design, requests(design)[1].model_copy(update={"design_hash": "f" * 64}))


@pytest.mark.parametrize(
    "damage,expected",
    [
        ("nodes", "NODE_LIMIT"),
        ("lag", "INPUT_LAG_MISMATCH"),
        ("operator", "OPERATOR_UNSUPPORTED"),
        ("field", "FIELD_PIT_SOURCE_UNSUPPORTED"),
        ("window", "WINDOW_UNSUPPORTED"),
        ("unused", "UNUSED_NODES"),
    ],
)
def test_capability_rejects_unsafe_or_outside_design(design, damage, expected):
    expr = baseline_expression_space(design)[0]
    if damage == "nodes":
        design = design.model_copy(update={"max_nodes": 1})
    elif damage == "lag":
        expr = expr.model_copy(update={"input_lag_trading_days": 1})
    elif damage == "operator":
        design = design.model_copy(update={"allowed_operators": (SafeQlibOperator.FIELD,)})
    elif damage == "field":
        expr = expr.model_copy(
            update={
                "nodes": (expr.nodes[0].model_copy(update={"field_name": "volume"}), expr.nodes[1])
            }
        )
    elif damage == "window":
        expr = expr.model_copy(
            update={"nodes": (expr.nodes[0], expr.nodes[1].model_copy(update={"window": 999}))}
        )
    else:
        expr = expr.model_copy(
            update={
                "nodes": (
                    *expr.nodes,
                    SafeExpressionNode(
                        node_id="unused",
                        operator=SafeQlibOperator.FIELD,
                        field_name="adjusted_close",
                    ),
                )
            }
        )
    assert capability_rejection(design, expr) == expected


def test_batch_retains_failed_unfinished_and_duplicate_denominators(design):
    reqs = requests(design)
    reservations = tuple(
        GenerationReservation(request_hash=r.content_hash, ordinal=i) for r in reqs for i in (1, 2)
    )
    text = baseline_expression_space(design)[0].canonical_bytes().decode()
    responses = (
        GenerationResponse(reservation=reservations[0], text=text, producer="OFFLINE_IMPORT"),
        GenerationResponse(reservation=reservations[1], text=text, producer="OFFLINE_IMPORT"),
        GenerationResponse(reservation=reservations[2], text="bad json", producer="OFFLINE_IMPORT"),
        GenerationResponse(
            reservation=reservations[3],
            text="",
            producer="OFFLINE_IMPORT",
            failure_code="INTERRUPTED",
        ),
    )
    batch = build_discovery_batch(design, reqs, reservations, responses)
    assert len(batch.mappings) == 6 and len(batch.subtasks) == 1
    assert {m.status for m in batch.mappings} == {
        "ADMITTED",
        "DUPLICATE",
        "PARSE_FAILED",
        "FAILED",
        "UNFINISHED",
    }
    verify_discovery_batch(batch)
    with pytest.raises(ValueError):
        build_discovery_batch(design, reqs, (*reservations, reservations[0]), responses)
    with pytest.raises(ValueError):
        build_discovery_batch(design, reqs, reservations, (*responses, responses[0]))
    with pytest.raises(ValueError):
        verify_discovery_batch(batch.model_copy(update={"mappings": batch.mappings[:-1]}))


def test_generation_budget_revision_freeze_and_corruption(design, durable):
    store = GenerationStore(durable / "store")
    reqs = requests(design)
    for r in reqs:
        store.save_request(design, r)
    req = reqs[0]
    first = store.reserve(req)
    response = store.complete(req, first, "malformed", producer="OFFLINE_IMPORT")
    with pytest.raises(ArtifactIntegrityError, match="existing response"):
        store.reserve(req, "b" * 64)
    second = store.reserve(req, response.content_hash)
    rejected = store.reject_capture(req, second, "CAPTURE_PROVENANCE_REJECTED")
    assert rejected.text == "" and rejected.usage_input_units is None
    with pytest.raises(ArtifactIntegrityError, match="exhausted"):
        store.reserve(req)
    batch = store.freeze(design)
    assert len(batch.mappings) == 2 and store.freeze(design) == batch
    store.verify_frozen(batch)
    with pytest.raises(ArtifactIntegrityError, match="frozen"):
        store.reserve(req)
    atomic_write_bytes(store.root / "unexpected.json", b"{}")
    with pytest.raises(ArtifactIntegrityError, match="inventory"):
        store.verify_frozen(batch)


@pytest.mark.parametrize(
    "damage,code",
    [
        ("output", "CAPTURE_OUTPUT_LIMIT"),
        ("provenance", "CAPTURE_PROVENANCE_REJECTED"),
        ("secret", "CAPTURE_SECRET_REJECTED"),
    ],
)
def test_capture_rejection_never_retains_rejected_bytes(design, durable, damage, code):
    store = GenerationStore(durable / "store")
    req = requests(design)[0]
    store.save_request(design, req)
    reservation = store.reserve(req)
    text = (
        "x" * 65537
        if damage == "output"
        else ('{"api_key":"synthetic-prohibited-secret"}' if damage == "secret" else "{}")
    )
    response = store.complete(
        req,
        reservation,
        text,
        producer="SDK_CAPTURE" if damage == "provenance" else "OFFLINE_IMPORT",
    )
    assert response.failure_code == code and response.producer == "CAPTURE_REJECTED"
    raw = (store._directory(req) / "responses/000001.json").read_bytes()
    assert text.encode() not in raw
    assert store.inventory(req)[1] == (response,)


def test_completed_generation_is_immutable(design, durable):
    store = GenerationStore(durable / "store")
    req = requests(design)[0]
    store.save_request(design, req)
    reservation = store.reserve(req)
    first = store.complete(req, reservation, "first", producer="OFFLINE_IMPORT")
    assert store.complete(req, reservation, "first", producer="OFFLINE_IMPORT") == first
    with pytest.raises(ArtifactConflictError, match="immutable target"):
        store.complete(req, reservation, "changed", producer="OFFLINE_IMPORT")
    assert store.inventory(req)[1] == (first,)


def test_generation_paths_and_raw_contract_bytes_fail_closed(design, durable, tmp_path):
    with pytest.raises(ArtifactIntegrityError, match="durable"):
        GenerationStore(Path("/tmp/unsafe-generation"))
    durable.mkdir(parents=True, exist_ok=True)
    (durable / "alias").symlink_to(durable, target_is_directory=True)
    with pytest.raises(ArtifactIntegrityError, match="symbolic"):
        GenerationStore(durable / "alias")
    store = GenerationStore(durable / "store")
    req = requests(design)[0]
    store.save_request(design, req)
    p = store._directory(req) / "request.json"
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ArtifactIntegrityError, match="canonical"):
        store.inventory(req)


def test_offline_inspection_keeps_unavailable_costs_and_no_selection(design, durable):
    store, batch = frozen_store(design, durable / "generation")
    service = execution.DiscoveryExecutionService(
        batch=batch,
        generation_root=store.root,
        snapshot_path=durable / "no-snapshot",
        qlib_view_path=durable / "no-view",
        output_root=durable / "execution",
        workspace=durable,
    )
    assert service.quote() > 0
    # Explicit None prevents a data/adapter inspection, as required for unstarted tasks.
    for task in batch.subtasks:
        state = service.task_state(task.content_hash, inspection=None)
        assert state["status"] == "NOT_STARTED" and state["wall_seconds"] is None
    assert service.batch_state()["wall_seconds"] is None
    fixture_service = SimpleNamespace(
        batch=batch,
        evaluation_bindings=design.bindings,
        evaluation_declaration=None,
        evaluation_identity=service.evaluation_identity,
        max_compute_units=service.max_compute_units,
        evaluation_metadata=service.evaluation_metadata,
        inspect_completed_execution=lambda _: None,
        task_state=lambda key, **kwargs: service.task_state(key, inspection=None),
        batch_state=service.batch_state,
    )
    report = build_discovery_comparison(batch, fixture_service)
    assert len(report["rows"]) == len(batch.mappings)
    assert all(
        row["primary_value"] is None and not row["p14c_selectable"] for row in report["rows"]
    )
    assert all(m["actual_provider_call_count"] is None for m in report["methods"])
    assert "OFFLINE_IMPORT_NO_VERIFIED_LLM_CALL" in render_discovery_report(report)
    assert "unavailable" in render_discovery_report({"rows": [None], "methods": None})
    schema = json.loads(generation_schema_bytes())
    assert set(schema["required"]) == set(schema["properties"])


def test_budget_accounting_with_a_synthetic_execution_port(design, durable, monkeypatch):
    store, batch = frozen_store(design, durable / "generation")
    service = execution.DiscoveryExecutionService(
        batch=batch,
        generation_root=store.root,
        snapshot_path=durable / "no-snapshot",
        qlib_view_path=durable / "no-view",
        output_root=durable / "execution",
        workspace=durable,
    )

    class FixturePort:
        calls = 0

        def verified_completed_execution(self, request):
            return None

        def execute(self, request):
            self.calls += 1
            raise RuntimeError("synthetic execution failure")

    port = FixturePort()
    guard = SimpleNamespace(policy_hash="a" * 64, require_lease=lambda: None, check=lambda: {})
    monkeypatch.setattr(
        service, "_storage_authority", lambda _: (guard, {"lease_prelaunch_hash": "b" * 64})
    )
    monkeypatch.setattr(service, "task_adapter", lambda _: port)
    monkeypatch.setattr(execution, "VerifiedExecutionInputs", lambda *args: object())
    with pytest.raises(RuntimeError, match="synthetic"):
        service.run(expected_new_bytes=1024)
    assert port.calls == 1
    for _ in batch.subtasks[1:]:
        with pytest.raises(RuntimeError):
            service.run(expected_new_bytes=1024)
    service.run(expected_new_bytes=1024)
    assert port.calls == len(batch.subtasks)  # Failed parents are not retried automatically.
    task = batch.subtasks[0].content_hash
    assert service.task_state(task, inspection=None)["status"] == "FAILED"
    for _ in batch.subtasks:
        with pytest.raises(RuntimeError):
            service.run(expected_new_bytes=1024, resume_failed_attempts=True)
    assert port.calls == 2 * len(batch.subtasks) and service._recovery_reservations()
    service.run(expected_new_bytes=1024, resume_failed_attempts=True)
    assert port.calls == 2 * len(batch.subtasks)  # One recovery per subtask, then hard stop.
    assert service.batch_state()["recovery_reserved_compute_units"] > 0
    with pytest.raises(ValueError, match="Boolean"):
        service.run(expected_new_bytes=1024, resume_failed_attempts=1)


def test_readonly_comparison_preserves_pit_rejection_and_unverified_receipts(
    design,
    durable,
    monkeypatch,
):
    store, batch = frozen_store(design, durable / "generation")
    service = execution.DiscoveryExecutionService(
        batch=batch,
        generation_root=store.root,
        snapshot_path=durable / "no-snapshot",
        qlib_view_path=durable / "no-view",
        output_root=durable / "execution",
        workspace=durable,
    )
    inspections = {}
    for task in batch.subtasks:
        request = service.task_request(task.content_hash)
        outcome = AutonomousExecutionResult(
            request_hash=request.content_hash,
            outcome=TrialOutcome.PIT_REJECT,
            execution_requested=False,
            compute_seconds=0,
        )
        inspections[task.content_hash] = execution.DiscoveryExecutionInspection(
            request, outcome, SimpleNamespace(output_root=durable)
        )
    fixture = SimpleNamespace(
        batch=batch,
        evaluation_bindings=design.bindings,
        evaluation_declaration=None,
        evaluation_identity=service.evaluation_identity,
        max_compute_units=service.max_compute_units,
        evaluation_metadata=service.evaluation_metadata,
        batch_state=service.batch_state,
        inspect_completed_execution=lambda key: inspections[key],
        task_state=lambda key, **kwargs: service.task_state(key, inspection=inspections[key]),
    )
    report = build_discovery_comparison(batch, fixture)
    assert all(row["prediction_reason"] == "NO_RESEARCH_RESULT" for row in report["rows"])
    assert all(
        row["execution_outcome"] == "PIT_REJECT" and not row["prediction_analyzable"]
        for row in report["rows"]
    )

    def unavailable(_):
        raise OSError("sensitive diagnostic must not enter a report")

    fixture.inspect_completed_execution = unavailable
    fixture.task_state = unavailable
    fixture.batch_state = lambda: unavailable(None)
    failed = build_discovery_comparison(batch, fixture)
    assert "sensitive diagnostic" not in json.dumps(failed)
    assert all(row["execution_status"] == "UNVERIFIED" for row in failed["rows"])


@pytest.mark.parametrize("budget_exhausted", [False, True])
def test_execution_budget_and_completed_receipt_reuse_do_not_add_trials(
    design,
    durable,
    monkeypatch,
    budget_exhausted,
):
    if budget_exhausted:
        design = design.model_copy(update={"max_compute_units": 1})
    store, batch = frozen_store(design, durable / "generation")
    service = execution.DiscoveryExecutionService(
        batch=batch,
        generation_root=store.root,
        snapshot_path=durable / "no-snapshot",
        qlib_view_path=durable / "no-view",
        output_root=durable / "execution",
        workspace=durable,
    )

    class FixturePort:
        def __init__(self):
            self.calls = 0
            self.receipts = {}

        def verified_completed_execution(self, request):
            return self.receipts.get(request.content_hash)

        def inspect_completed_execution(self, request):
            return self.receipts.get(request.content_hash)

        def execute(self, request):
            self.calls += 1
            value = AutonomousExecutionResult(
                request_hash=request.content_hash,
                outcome=TrialOutcome.PIT_REJECT,
                execution_requested=False,
                compute_seconds=0,
            )
            self.receipts[request.content_hash] = value
            return value

    port = FixturePort()
    guard = SimpleNamespace(policy_hash="a" * 64, require_lease=lambda: None, check=lambda: {})
    monkeypatch.setattr(
        service, "_storage_authority", lambda _: (guard, {"lease_prelaunch_hash": "b" * 64})
    )
    monkeypatch.setattr(service, "task_adapter", lambda _: port)
    monkeypatch.setattr(execution, "VerifiedExecutionInputs", lambda *args: object())
    outcomes = service.run(expected_new_bytes=1024)
    if budget_exhausted:
        assert outcomes == () and port.calls == 0
        assert all(
            service.task_state(t.content_hash, inspection=None)["status"] == "NOT_EXECUTED"
            for t in batch.subtasks
        )
    else:
        assert len(outcomes) == port.calls == len(batch.subtasks)
        first_events = {t.content_hash: service._events(t.content_hash) for t in batch.subtasks}
        assert service.run(expected_new_bytes=1024) == outcomes
        assert port.calls == len(batch.subtasks)
        assert first_events == {
            t.content_hash: service._events(t.content_hash) for t in batch.subtasks
        }
        assert (
            service.inspect_completed_execution(batch.subtasks[0].content_hash).outcome
            == outcomes[0]
        )


def test_malformed_completion_cannot_supply_fake_zero_costs(design, durable, monkeypatch):
    store, batch = frozen_store(design, durable / "generation")
    service = execution.DiscoveryExecutionService(
        batch=batch,
        generation_root=store.root,
        snapshot_path=durable / "no-snapshot",
        qlib_view_path=durable / "no-view",
        output_root=durable / "execution",
        workspace=durable,
    )
    root = service.output_root / "batch-attempts/00000001"
    reservation = {
        "schema_version": "discovery-batch-execution-reservation/v1",
        "batch_hash": batch.content_hash,
        "ordinal": 1,
        "resume_failed_attempts": False,
    }
    atomic_write_bytes(root / "reservation.json", canonical_json_bytes(reservation))
    atomic_write_bytes(
        root / "completion.json",
        canonical_json_bytes(
            {
                "batch_hash": batch.content_hash,
                "reservation_hash": sha256_bytes(canonical_json_bytes(reservation)),
                "status": "SUCCEEDED",
                "wall_seconds": False,
                "cpu_seconds": 0,
            }
        ),
    )
    with pytest.raises(ArtifactIntegrityError, match="measurement"):
        service.batch_state()


@pytest.mark.parametrize(
    "damage",
    [
        "request",
        "reservation",
        "revision",
        "directory",
        "response-keys",
        "baseline",
        "frozen-design",
    ],
)
def test_generation_inventory_rejects_rewritten_authority_and_seed_drift(design, durable, damage):
    store = GenerationStore(durable / "inventory")
    reqs = requests(design)
    for req in reqs:
        store.save_request(design, req)
    req = reqs[1] if damage == "baseline" else reqs[0]
    reserved = store.reserve(req)
    text = generate_baseline(design, req)[0] if req.method != "LLM" else "{}"
    store.complete(
        req, reserved, text, producer="BASELINE" if req.method != "LLM" else "OFFLINE_IMPORT"
    )
    directory = store._directory(req)
    if damage == "request":
        (directory / "request.json").write_bytes(
            req.model_copy(update={"prompt": "changed"}).canonical_bytes()
        )
    elif damage in ("reservation", "revision"):
        value = reserved.model_copy(
            update={"request_hash": "f" * 64}
            if damage == "reservation"
            else {"revision_of": "f" * 64}
        )
        (directory / "reservations/000001.json").write_bytes(value.canonical_bytes())
    elif damage == "directory":
        (directory / "unowned-empty-directory").mkdir()
    elif damage in ("response-keys", "baseline"):
        path = directory / "responses/000001.json"
        value = json.loads(path.read_bytes())
        if damage == "response-keys":
            value["extra"] = "unowned"
        else:
            value["response"]["text"] = "{}"
        path.write_bytes(canonical_json_bytes(value))
    else:
        batch = store.freeze(design)
        with pytest.raises(ArtifactIntegrityError, match="another design"):
            store.freeze(design.model_copy(update={"max_nodes": design.max_nodes + 1}))
        store.verify_frozen(batch)
        return
    with pytest.raises(ArtifactIntegrityError):
        store.inventory(req)


@pytest.mark.parametrize(
    "damage", ["usage-contract", "usage-event", "usage-counter", "transcript", "credential"]
)
def test_secret_guard_accepts_typed_counters_but_rejects_malformed_envelopes(monkeypatch, damage):
    from quantos.application import discovery_generation as generation
    from quantos.application.agent_harness import make_agent_event
    from quantos.contracts.harness import AgentEventKind

    if damage == "usage-contract":
        value = {"schema_version": "agent-usage/v1", "input_tokens": -1}
    elif damage in ("usage-event", "usage-counter"):
        usage = (
            "invalid"
            if damage == "usage-event"
            else {"input_tokens": False, "output_tokens": 0, "cached_input_tokens": 0}
        )
        value = make_agent_event(
            sequence=1,
            kind=AgentEventKind.USAGE,
            provider_event_type="synthetic",
            payload={"usage": usage},
        ).model_dump(mode="json")
    elif damage == "transcript":
        with pytest.raises(ArtifactIntegrityError, match="transcript metadata"):
            generation._safe_envelope({"normalized_transcript": 1})
        return
    else:
        monkeypatch.setenv("TUSHARE_SYNTHETIC_SENTINEL", "synthetic-fixture-marker")
        value = {"fixture": "synthetic-fixture-marker"}
    with pytest.raises(ArtifactIntegrityError):
        generation._safe(value)


def test_unbounded_record_and_unreserved_completion_are_rejected_before_parsing(design, durable):
    from quantos.application import discovery_generation as generation

    atomic_write_bytes(durable / "oversized.json", b" " * (generation._FILE_CAP + 1))
    with pytest.raises(ArtifactIntegrityError, match="exceeds its bound"):
        generation._read(durable, "oversized.json")
    store = GenerationStore(durable / "generation")
    request = requests(design)[0]
    store.save_request(design, request)
    reservation = GenerationReservation(request_hash=request.content_hash, ordinal=1)
    with pytest.raises(ArtifactIntegrityError, match="retained reservation"):
        store.complete(request, reservation, "{}", producer="OFFLINE_IMPORT")
    with pytest.raises(ArtifactIntegrityError, match="retained reservation"):
        store.reject_capture(request, reservation, "CAPTURE_OUTPUT_LIMIT")


def test_offline_import_cannot_claim_runtime_provenance_and_rejection_is_immutable(design, durable):
    store = GenerationStore(durable / "generation")
    request = requests(design)[0]
    store.save_request(design, request)
    reservation = store.reserve(request)
    rejected = store.complete(
        request, reservation, "{}", producer="OFFLINE_IMPORT", agent_run_hash="f" * 64
    )
    assert rejected.failure_code == "CAPTURE_PROVENANCE_REJECTED" and rejected.text == ""
    with pytest.raises(ArtifactIntegrityError, match="already completed"):
        store.reject_capture(request, reservation, "CAPTURE_OUTPUT_LIMIT")
    assert store.inventory(request)[1] == (rejected,)
