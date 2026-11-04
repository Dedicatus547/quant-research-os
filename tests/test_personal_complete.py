"""Bounded v7 behavior and Qlib-native continuity; never market research."""

from __future__ import annotations

import os
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from quantos.application.personal_research import PersonalResearchService
from quantos.application.personal_strategy import PersonalStrategyResearch
from quantos.contracts.base import sha256_bytes
from quantos.contracts.personal_strategy import (
    PersonalExecutionPolicy,
    PersonalExpression,
    PersonalResearchScope,
    PersonalStrategy,
    StrategyStudyRequest,
)
from quantos.research.personal_session import NativePersonalSession
from quantos.research.personal_signal import compile_strategy_signal, load_strategy_signal

REPO = Path(__file__).resolve().parents[1]


def expression(window=3, field="adjusted_close"):
    return PersonalExpression.model_validate(
        {
            "expression_id": "momentum",
            "nodes": [
                {"node_id": "price", "operator": "field", "field_name": field},
                {"node_id": "ret", "operator": "return", "inputs": ["price"], "window": window},
            ],
            "output_node_id": "ret",
        }
    )


def strategy(**changes):
    return PersonalStrategy(score=expression(), top_k=2, max_weight=0.45, **changes)


@pytest.fixture(scope="module")
def binding(tmp_path_factory):
    retained = os.environ.get("QUANTOS_COMPLETE_FIXTURE")
    root = Path(retained) if retained else tmp_path_factory.mktemp("native-input")
    return runpy.run_path(str(REPO / "scripts/personal_complete_fixture.py"))["build_fixture"](root)


def request(binding, key="study", **changes):
    data = {
        "schema_version": "personal-study-request/v7",
        "idempotency_key": key,
        "brief": "Synthetic price trend versus reverse ordering; no scientific claim",
        "proposal": {
            "schema_version": "host-session-proposal/v2",
            "session_id": "outer-engineering",
        },
        "dataset_id": binding.manifest.dataset_id,
        "warmup_start": "2024-01-02",
        "start_date": "2024-02-05",
        "end_date": "2024-02-14",
        "candidates": [
            {
                "candidate_id": "price",
                "role": "main",
                "hypothesis": "positive trend",
                "strategy": strategy().model_dump(mode="json"),
            },
            {
                "candidate_id": "reverse",
                "role": "control",
                "hypothesis": "reverse rank control",
                "strategy": strategy(rank_direction="ascending").model_dump(mode="json"),
            },
        ],
        **changes,
    }
    return StrategyStudyRequest.model_validate(data).model_dump(mode="json")


def test_safe_expression_and_policy_boundaries():
    with pytest.raises(ValidationError):
        expression(window=-1)
    with pytest.raises(ValidationError):
        expression(field="future_close")
    with pytest.raises(ValidationError):
        strategy(signal_time="intraday")
    with pytest.raises(ValidationError):
        strategy(target_weights={"SH600001": 0.5})
    from quantos.research.qlib.personal_expression import (
        required_history,
        translate_personal_expression,
    )

    assert required_history(expression()) == 3
    assert "Ref($close,3)" in translate_personal_expression(expression())


def test_namespace_owner_uses_verified_global_lease(tmp_path):
    import fcntl
    import json

    from quantos.application.personal_research import execution_owner_active
    from quantos.contracts.base import canonical_json_bytes

    control = tmp_path / "storage-control"
    run = control / "run-exact"
    run.mkdir(parents=True)
    policy = canonical_json_bytes({"evidence_root": str(tmp_path)})
    digest = sha256_bytes(policy)
    (run / "policy.json").write_bytes(policy)
    (run / "prelaunch.json").write_text(json.dumps({"policy_hash": digest}))
    with (control / "lease.lock").open("w+") as lock:
        lock.write(json.dumps({"run": str(run), "policy_hash": digest}))
        lock.flush()
        fcntl.flock(lock, fcntl.LOCK_EX)
        detail = {
            "pid": 999999999,
            "process_identity": "not-a-host-pid",
            "supervisor_lease": str(run),
            "supervisor_policy_hash": digest,
        }
        assert execution_owner_active(detail)
        fcntl.flock(lock, fcntl.LOCK_UN)
        assert not execution_owner_active(detail)


def test_prepare_early_rejection_and_no_authority(binding, tmp_path):
    app = PersonalResearchService(tmp_path, REPO, catalog={binding.manifest.dataset_id: binding})
    ready = app.prepare(request(binding))
    assert ready["readiness"] == "READY_FOR_AUTHORIZATION"
    assert app.prepare(request(binding))["task_id"] == ready["task_id"]
    with pytest.raises(PermissionError, match="server-side"):
        app.execute(ready["task_id"])
    missing = request(binding, "missing")
    missing["candidates"][0]["strategy"]["score"] = expression(field="amount_cny").model_dump(
        mode="json"
    )
    assert app.prepare(missing)["readiness"] == "READY_FOR_AUTHORIZATION"
    non_session = app.prepare(request(binding, "saturday", start_date="2024-02-03"))
    assert non_session["readiness"] == "BLOCKED"
    with pytest.raises(ValidationError):
        app.prepare({**request(binding, "bad"), "approved": True})
    app.cancel(ready["task_id"])
    assert app.execute(ready["task_id"])["state"] == "CANCELLED"


def test_canonical_profile_signal_preserves_old_identity(binding, tmp_path):
    from dataclasses import replace

    from quantos.contracts.personal_strategy import PersonalSignalArtifactV2
    from quantos.research.personal_signal import dataset_binding_hash

    without_amount_bins = binding.manifest.model_copy(
        update={
            "qlib_files": {
                k: v
                for k, v in binding.manifest.qlib_files.items()
                if not k.endswith("/amount_cny.day.bin")
            }
        }
    )
    canonical = replace(
        binding, manifest=without_amount_bins, field_mapping_profile="canonical-personal-fields/v1"
    )
    assert dataset_binding_hash(binding) == binding.manifest.content_hash
    assert dataset_binding_hash(canonical) != canonical.manifest.content_hash
    spec = strategy().model_copy(update={"score": expression(field="amount_cny")})
    artifact, signal = compile_strategy_signal(
        canonical,
        spec,
        binding.manifest.start_date,
        binding.manifest.end_date,
        tmp_path / "canonical-signal",
        "f" * 64,
    )
    assert isinstance(artifact, PersonalSignalArtifactV2)
    assert artifact.dataset_hash == dataset_binding_hash(canonical)
    loaded_artifact, loaded = load_strategy_signal(
        tmp_path / "canonical-signal", artifact.content_hash
    )
    assert loaded_artifact == artifact
    assert signal.score.notna().any()
    pd.testing.assert_frame_equal(signal, loaded, check_dtype=False)
    assert (
        compile_strategy_signal(
            canonical,
            spec,
            binding.manifest.start_date,
            binding.manifest.end_date,
            tmp_path / "canonical-signal",
            "f" * 64,
        )[0]
        == artifact
    )


def test_new_strategy_market_boundary_before_execution(monkeypatch, tmp_path):
    from datetime import date
    from types import SimpleNamespace

    from quantos.research.personal_native import execute_candidate, require_supported_market_period

    market = SimpleNamespace(
        manifest=SimpleNamespace(kind="market", lifecycle_manifest_hash="a" * 64),
        lifecycle_path=tmp_path / "bound-facts",
    )
    event = SimpleNamespace(
        boundary_date=date(2024, 2, 7), entitlement_window_start=date(2024, 2, 5)
    )
    monkeypatch.setattr(
        "quantos.research.hs300_lifecycle_data.load_lifecycle_facts",
        lambda path, digest: SimpleNamespace(events=[event]),
    )
    require_supported_market_period(market, "2024-02-02")
    # A separately bound fresh-cash lifetime after the completed boundary has
    # no entitlement imported from a prior account.
    require_supported_market_period(market, "2024-02-14", start="2024-02-08")
    with pytest.raises(ValueError, match="UNSUPPORTED_CORPORATE_ACTION"):
        execute_candidate(
            market,
            strategy(),
            PersonalExecutionPolicy(),
            pd.DataFrame(),
            "2024-02-05",
            "2024-02-07",
            "SH000300",
            tmp_path / "must-not-start",
        )
    assert not (tmp_path / "must-not-start").exists()


def test_native_full_vs_segmented_and_publication_recovery(binding, tmp_path):
    import qlib
    from qlib.backtest import get_strategy_executor
    from qlib.backtest.backtest import backtest_loop

    from quantos.research.native_state import encode_native_state
    from quantos.research.personal_native import native_config
    from quantos.research.personal_qlib import _native_order_rows

    spec = strategy(rebalance="weekly_first_session", rank_buffer=1, max_holding_sessions=3)
    # A fixed 1% synthetic capacity yields both partial and zero fills while
    # preserving the original data-health predicates and immutable input cache.
    policy = PersonalExecutionPolicy(volume_participation=0.01)
    artifact, signal = compile_strategy_signal(
        binding,
        spec,
        binding.manifest.warmup_start,
        binding.manifest.end_date,
        tmp_path / "signal",
        "f" * 64,
    )
    _, loaded = load_strategy_signal(tmp_path / "signal", artifact.content_hash)
    pd.testing.assert_frame_equal(signal, loaded, check_dtype=False)
    days = list(pd.bdate_range("2024-02-05", "2024-02-14").date)
    qlib.init(provider_uri=str(binding.provider_root), region="cn", kernels=1)
    config = native_config(binding, spec, policy, signal, str(days[0]), str(days[-1]), "SH000300")
    config["strategy"]["kwargs"]["signal"] = signal
    full_strategy, executor = get_strategy_executor(
        strategy=config["strategy"], executor=config["executor"], **config["backtest"]
    )
    backtest_loop(str(days[0]), str(days[-1]), full_strategy, executor)
    full_account = executor.trade_account
    (tmp_path / "full-account.native.json").write_bytes(encode_native_state(full_account))
    # A separate immutable derived-cache root exercises Qlib's actual provider
    # rebinding while holdings exist. Values are deliberately identical; this is
    # a compatible synthetic view handoff, never claimed as future observation.
    import shutil

    from quantos.application.personal_research import PersonalDatasetBinding
    from quantos.artifacts.store import sha256_file
    from quantos.contracts.base import canonical_json_bytes

    next_root = tmp_path / "compatible-view"
    shutil.copytree(binding.provider_root, next_root / "provider")
    next_snapshot = sha256_bytes(
        canonical_json_bytes(
            {
                "predecessor": binding.manifest.snapshot_hash,
                "case": "synthetic-compatible-view-copy",
            }
        )
    )
    (next_root / "pit.json").write_bytes(
        canonical_json_bytes(
            {
                "kind": "synthetic",
                "snapshot_hash": next_snapshot,
                "panel_sha256": binding.manifest.panel_sha256,
                "origin_manifest": binding.manifest.content_hash,
                "scope": (
                    "Identical verified synthetic values at a distinct view/provider; "
                    "no real forward claim"
                ),
            }
        )
    )
    next_manifest = binding.manifest.model_copy(
        update={
            "dataset_id": "hs300-compatible-view-02",
            "snapshot_hash": next_snapshot,
            "qlib_view_hash": sha256_bytes(
                canonical_json_bytes(
                    {"source_snapshot": next_snapshot, "files": binding.manifest.qlib_files}
                )
            ),
            "pit_evidence_hash": sha256_file(next_root / "pit.json"),
        }
    )
    (next_root / "dataset-manifest.json").write_bytes(next_manifest.canonical_bytes())
    next_binding = PersonalDatasetBinding(
        next_manifest, next_root / "provider", binding.panel_path, next_root / "pit.json"
    )
    session_root = tmp_path / "continuing"
    for index, day in enumerate(days):
        if index == 4:
            binding = next_binding
        # Every day reconstruct a new coordinator/client, including while holding stock.
        session = NativePersonalSession(
            session_root, strategy=spec, policy=policy, runtime_hash="f" * 64
        )
        if index == 2:
            with pytest.raises(InterruptedError):
                session.advance(
                    binding,
                    signal,
                    artifact.content_hash,
                    day,
                    continuous_compatible=True,
                    observation_hash="e" * 64,
                    fault_after_native_export=True,
                )
        else:
            session.advance(
                binding,
                signal,
                artifact.content_hash,
                day,
                continuous_compatible=True,
                observation_hash="e" * 64,
            )
        assert session.status()["completed_sessions"] == index + 1
        assert session.advance(
            binding,
            signal,
            artifact.content_hash,
            day,
            continuous_compatible=True,
            observation_hash="e" * 64,
        )["idempotent_reuse"]
    state = session.native_state()
    continued = state["account"]
    assert any(position.get_stock_list() for position in continued.hist_positions.values())
    # Tolerances frozen before observing differences. Discrete events must be exact.
    pd.testing.assert_frame_equal(
        full_account.get_portfolio_metrics()[0],
        continued.get_portfolio_metrics()[0],
        rtol=1e-12,
        atol=1e-10,
    )
    orders = _native_order_rows(continued.indicator)
    assert ((orders.deal_amount.abs() > 0) & (orders.deal_amount.abs() < orders.amount.abs())).any()
    assert (orders.deal_amount.abs() == 0).any()
    assert full_account.current_position.position == continued.current_position.position
    assert full_account.accum_info.__dict__ == continued.accum_info.__dict__
    assert full_account.init_cash == continued.init_cash == policy.initial_cash_cny
    pd.testing.assert_frame_equal(
        _native_order_rows(full_account.indicator),
        _native_order_rows(continued.indicator),
        rtol=1e-12,
        atol=1e-10,
    )
    assert encode_native_state(continued)  # Complete history is serializable after restart.
    assert len(continued.hist_positions) == len(days)
    assert len(list((tmp_path / "continuing/steps").glob("*/targets.json"))) == len(days)
    assert session.status()["last_execution_date"] == str(days[-1])
    with pytest.raises(ValueError, match="revised"):
        session.advance(
            binding,
            signal,
            artifact.content_hash,
            days[-1],
            continuous_compatible=False,
            observation_hash="e" * 64,
        )


def test_native_intent_without_export_is_unknown_and_never_replayed(tmp_path):
    from quantos.research.personal_session import UnknownNativeStep

    session = NativePersonalSession(
        tmp_path, strategy=strategy(), policy=PersonalExecutionPolicy(), runtime_hash="f" * 64
    )
    step = tmp_path / "steps/2024-02-05"
    step.mkdir(parents=True)
    (step / "started.json").write_text('{"actual":"intent-only-engineering-case"}')
    assert session.status()["state"] == "UNKNOWN"
    with pytest.raises(UnknownNativeStep):
        session.native_state()
    assert not (step / "completed.json").exists()


def test_workflow_two_strategies_successor_budget_and_stop(binding, tmp_path):
    from quantos.application.personal_server_config import (
        CatalogRegistration,
        PersonalScopeRegistration,
        PersonalServerConfigV5,
        make_trusted_service,
    )
    from quantos.artifacts.store import sha256_file

    app = PersonalResearchService(tmp_path, REPO, catalog={binding.manifest.dataset_id: binding})
    first = app.prepare(request(binding))
    approved = b"User-authorized bounded local synthetic engineering; no real research"
    parsed = StrategyStudyRequest.model_validate(request(binding))
    successor_strategy = strategy(rank_buffer=1, max_holding_sessions=2)
    scope = PersonalResearchScope(
        purpose="SYNTHETIC_ENGINEERING",
        dataset_hash=binding.manifest.content_hash,
        policy_hash=parsed.policy.content_hash,
        runtime_hash=first["code_hash"],
        allowed_strategy_hashes=(
            *(c.strategy.content_hash for c in parsed.candidates),
            successor_strategy.content_hash,
        ),
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        max_attempts=3,
        max_native_accounts=4,
        wall_seconds=120,
        growth_bytes=128 * 1024**2,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        approval_evidence_sha256=sha256_bytes(approved),
    )
    # Each attempt uses its own actual matrix supervisor/namespace and observed
    # exit. The test parent must not hold an outer lease around these calls.
    scope_path = tmp_path / "scope.json"
    scope_path.write_bytes(scope.canonical_bytes())
    approval_path = tmp_path / "engineering-approval.txt"
    approval_path.write_bytes(approved)
    policy_path = (
        REPO / "artifacts/hosted-evidence/storage-control/run-1793694490653729098-2/policy.json"
    )
    config = PersonalServerConfigV5(
        product_root=tmp_path,
        repo_root=REPO,
        catalog=(
            CatalogRegistration(
                manifest_path=binding.panel_path.parent / "dataset-manifest.json",
                manifest_sha256=sha256_file(binding.panel_path.parent / "dataset-manifest.json"),
                provider_root=binding.provider_root,
                panel_path=binding.panel_path,
                pit_evidence_path=binding.pit_evidence_path,
            ),
        ),
        research_scope=PersonalScopeRegistration(
            scope_path=scope_path,
            scope_sha256=scope.content_hash,
            approval_evidence_path=approval_path,
            storage_policy_path=policy_path,
            storage_policy_sha256=sha256_file(policy_path),
        ),
    )
    config_path = tmp_path / "server-config.json"
    config_path.write_bytes(config.canonical_bytes())
    app = make_trusted_service(tmp_path, REPO, config_path)
    assert app.execute(first["task_id"])["state"] == "SUCCEEDED"
    result = app.results(first["task_id"])
    assert result["planned_denominator"] == 2
    returns = [r["metrics"]["net_total_return"] for r in result["rows"]]
    assert returns[0] != returns[1]
    assert app.execute(first["task_id"])["idempotent_reuse"]
    followup = request(binding, "successor", parent_task_id=first["task_id"])
    followup["candidates"] = [followup["candidates"][0]]
    followup["candidates"][0]["role"] = "successor"
    followup["candidates"][0]["strategy"] = successor_strategy.model_dump(mode="json")
    second = app.prepare(followup)
    assert second["strategy_hashes"]["price"] != first["strategy_hashes"]["price"]
    assert app.execute(second["task_id"])["state"] == "SUCCEEDED"
    # A new brief and key with identical execution dependencies adopts the original tuple.
    reuse = request(binding, "reuse", parent_task_id=first["task_id"])
    reuse["candidates"] = [reuse["candidates"][0]]
    reuse["brief"] = "Same executable strategy; different explanation"
    third = app.prepare(reuse)
    assert app.execute(third["task_id"])["state"] == "SUCCEEDED"
    assert app.results(third["task_id"])["rows"][0]["run_status"] == "REUSED_ORIGIN"
    assert app.strategy_authority.remaining_limits()["pending"] == []
    assert app.strategy_authority.remaining_limits()["observed_used_wall_seconds"] > 0
    fourth = app.prepare(request(binding, "after-stop"))
    assert (
        app.strategy_authority.stop("Synthetic comparison answers the engineering question")[
            "state"
        ]
        == "STOPPED"
    )
    with pytest.raises(PermissionError):
        app.execute(fourth["task_id"])
    assert app.strategy_authority.remaining_limits()["state"] == "STOPPED"
    assert (
        PersonalStrategyResearch(app).results(app._prepared(first["task_id"]))["validation_verdict"]
        == "NOT_EVALUATED"
    )


def test_real_dispatch_cancel_then_resume_preserves_completed_native_origin(binding, tmp_path):
    import threading
    import time

    from quantos.application.personal_server_config import (
        CatalogRegistration,
        PersonalScopeRegistration,
        PersonalServerConfigV5,
        make_trusted_service,
    )
    from quantos.artifacts.store import sha256_file

    initial = request(binding, "cancel-real")
    for candidate, window in zip(initial["candidates"], (2, 4), strict=True):
        candidate["strategy"]["score"] = expression(window=window).model_dump(mode="json")
    core = PersonalResearchService(tmp_path, REPO, catalog={binding.manifest.dataset_id: binding})
    first = core.prepare(initial)
    parsed = StrategyStudyRequest.model_validate(initial)
    policy_path = (
        REPO / "artifacts/hosted-evidence/storage-control/run-1793694490653729098-2/policy.json"
    )
    registration = CatalogRegistration(
        manifest_path=binding.panel_path.parent / "dataset-manifest.json",
        manifest_sha256=sha256_file(binding.panel_path.parent / "dataset-manifest.json"),
        provider_root=binding.provider_root,
        panel_path=binding.panel_path,
        pit_evidence_path=binding.pit_evidence_path,
    )

    def configured(prepared, ordinal):
        approval = (
            f"User-authorized W0-W7 bounded synthetic engineering attempt {ordinal}; "
            "no market run or old-budget transfer"
        ).encode()
        scope = PersonalResearchScope(
            purpose="SYNTHETIC_ENGINEERING",
            dataset_hash=binding.manifest.content_hash,
            policy_hash=parsed.policy.content_hash,
            runtime_hash=prepared["code_hash"],
            allowed_strategy_hashes=tuple(c.strategy.content_hash for c in parsed.candidates),
            start_date=parsed.start_date,
            end_date=parsed.end_date,
            max_attempts=1,
            max_native_accounts=2,
            wall_seconds=120,
            growth_bytes=128 * 1024**2,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            approval_evidence_sha256=sha256_bytes(approval),
        )
        scope_path = tmp_path / f"scope-{ordinal}.json"
        scope_path.write_bytes(scope.canonical_bytes())
        approval_path = tmp_path / f"approval-{ordinal}.txt"
        approval_path.write_bytes(approval)
        config = PersonalServerConfigV5(
            product_root=tmp_path,
            repo_root=REPO,
            catalog=(registration,),
            research_scope=PersonalScopeRegistration(
                scope_path=scope_path,
                scope_sha256=scope.content_hash,
                approval_evidence_path=approval_path,
                storage_policy_path=policy_path,
                storage_policy_sha256=sha256_file(policy_path),
            ),
        )
        path = tmp_path / f"server-config-{ordinal}.json"
        path.write_bytes(config.canonical_bytes())
        return make_trusted_service(tmp_path, REPO, path)

    app = configured(first, 1)
    returned = {}

    def execute():
        try:
            returned["result"] = app.execute(first["task_id"])
        except Exception as error:
            returned["error"] = error

    thread = threading.Thread(target=execute)
    thread.start()
    target_root = tmp_path / "tasks" / first["task_id"] / "execution/price/native/targets"
    deadline = time.monotonic() + 90
    observed_states = set()
    cancelled = False
    while thread.is_alive() and time.monotonic() < deadline:
        state = app.status(first["task_id"])["state"]
        observed_states.add(state)
        assert state != "UNKNOWN"  # Host status must not mistake a namespace PID for its owner.
        if target_root.exists() and any(target_root.glob("*.json")):
            app.cancel(first["task_id"])
            cancelled = True
            break
        time.sleep(0.005)
    thread.join(timeout=150)
    assert not thread.is_alive() and cancelled, returned
    assert "error" not in returned, returned
    assert "RUNNING" in observed_states
    assert returned["result"]["state"] == "CANCELLED"
    before = app.results(first["task_id"])
    assert [r["run_status"] for r in before["rows"]] == ["SUCCEEDED", "NOT_RUN"]
    assert app.strategy_authority.remaining_limits()["retained_reservation_wall_seconds"] > 0
    assert app.execute(first["task_id"])["idempotent_reuse"]

    successor = {**initial, "idempotency_key": "resume-real", "parent_task_id": first["task_id"]}
    prepared = app.prepare(successor)
    # A separate authorized engineering scope binds this successor. The cancelled
    # scope and its unused reservation remain immutable and cannot be resumed.
    resumed = configured(prepared, 2)
    assert resumed.execute(prepared["task_id"])["state"] == "SUCCEEDED"
    results = resumed.results(prepared["task_id"])
    assert [r["run_status"] for r in results["rows"]] == ["REUSED_ORIGIN", "SUCCEEDED"]
    assert results["rows"][0]["origin"]["receipt_sha256"] == before["rows"][0]["receipt_sha256"]
    assert resumed.status(first["task_id"])["state"] == "CANCELLED"
