"""Operator reports preserve unknowns and do not run acquisition or accounts."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from scripts import forward_report as report


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    root = tmp_path / "campaign"
    root.mkdir()
    plan = {
        "root": str(root),
        "repo_root": str(tmp_path),
        "source_hashes": {},
        "approval": {},
        "initial_date": "2026-11-03",
        "initial_registry": {},
        "acquisition_dates": ["2026-11-05", "2026-11-06"],
        "signal_dates": ["2026-11-05"],
        "initial_wall_charge_seconds": 100,
        "global_wall_seconds": 1000,
        "complete_growth_bytes": 10000,
        "source_scope": "synthetic scope",
        "scientific_status": "NOT_EVALUATED",
        "arms": [{"name": "main", "observation_id": "observation", "shadow_id": "shadow"}],
    }
    state = {"acquisition_result": {"path": "acquired"}, "configs": {"main": {"path": "config"}}}
    actual_read_ref = report.read_ref

    def read(ref):
        if ref.get("path") == "plan":
            return plan
        if ref.get("path") == "acquired":
            return {"assessment": {"status": "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"}}
        if not ref:
            return {}
        return actual_read_ref(ref)

    monkeypatch.setattr(report, "read_ref", read)
    monkeypatch.setattr(report, "registry", lambda *_: state)
    observation = {
        "state": "ACTIVE",
        "record_count": 0,
        "records": [],
        "next_offset": None,
        "unknown_attempts": [],
    }
    shadow = {
        "state": "ACTIVE",
        "native": {"completed_sessions": 0, "last_execution_date": None, "checkpoint_hash": None},
        "native_cash_cny": None,
        "native_latest_report": None,
        "holdings_count": 0,
    }
    scope = {"state": "OPEN", "remaining_limits": {"pending": []}}
    # No acquire/observe/advance/recovery methods exist on this read-only port.
    product = SimpleNamespace(
        observations=SimpleNamespace(status=lambda *a, **k: observation),
        shadow=SimpleNamespace(status=lambda *a: shadow),
        scope_status=lambda: {"forward": scope},
    )
    monkeypatch.setattr(report, "core_for", lambda *_: product)
    monkeypatch.setattr(report, "shadow_status", lambda *_: shadow)
    return SimpleNamespace(
        root=root, plan=plan, observation=observation, shadow=shadow, scope=scope, product=product
    )


def test_waiting_and_due_use_real_scheduled_clock(campaign):
    early = datetime.fromisoformat("2026-11-05T22:29:00+08:00")
    rows = report.scheduled_rows(campaign.plan, early)
    assert all(r["state"] == "WAITING" for r in rows)
    due = datetime.fromisoformat("2026-11-06T00:01:00+08:00")
    rows = report.scheduled_rows(campaign.plan, due)
    assert [r["state"] for r in rows] == ["DUE_WITHOUT_RECORD", "DUE_WITHOUT_RECORD", "WAITING"]
    assert rows[1]["day"] == "2026-11-05" and rows[1]["phase"] == "observe"
    with pytest.raises(ValueError, match="timezone"):
        report.scheduled_rows(campaign.plan, datetime(2026, 11, 5))


@pytest.mark.parametrize(
    "kind,expected",
    [("intent", "IN_PROGRESS_OR_UNKNOWN"), ("result", "COMPLETED"), ("failure", "STOPPED")],
)
def test_scheduler_retains_terminal_and_unknown_evidence(campaign, kind, expected):
    job = campaign.root / "scheduled-jobs/2026-11-05-acquire"
    job.mkdir(parents=True)
    value = {"day": "2026-11-05", "phase": "acquire", "state": "COMPLETED", "wall_seconds": 5}
    (job / f"{kind}.json").write_text(json.dumps(value))
    row = report.scheduled_rows(campaign.plan, datetime.fromisoformat("2026-11-05T23:00:00+08:00"))[
        0
    ]
    assert row["state"] == expected and len(row["evidence"]) == 1
    if kind == "intent":
        assert row["wall_seconds"] is None
    else:
        assert row["wall_seconds"] == 5


def test_wrong_job_identity_cannot_be_displayed_as_success(campaign):
    job = campaign.root / "scheduled-jobs/2026-11-05-acquire"
    job.mkdir(parents=True)
    (job / "result.json").write_text(json.dumps({"day": "2026-11-04", "phase": "acquire"}))
    with pytest.raises(ValueError, match="different job"):
        report.scheduled_rows(campaign.plan, datetime.now(report.UTC))


def test_report_keeps_unstarted_account_null_and_does_not_execute(campaign):
    from pathlib import Path

    value = report.collect(Path("plan"), "synthetic")
    arm = value["arms"][0]
    assert arm["completed_sessions"] == 0
    assert arm["native_cash_cny"] is None and arm["native_latest_report"] is None
    assert value["budget"]["current_complete_growth_bytes"] is None
    text = report.markdown(value)
    assert "未产生/未知" in text and "NOT_EVALUATED" in text


def test_unknown_native_status_is_not_zero_completed_sessions(campaign):
    from pathlib import Path

    campaign.shadow["state"] = "UNKNOWN"
    campaign.shadow["native"]["completed_sessions"] = None
    value = report.collect(Path("plan"), "synthetic")
    assert value["state"] == "ATTENTION_REQUIRED"
    assert value["arms"][0]["completed_sessions"] is None


def test_pending_scheduler_does_not_invent_remaining_budget(campaign):
    from pathlib import Path

    job = campaign.root / "scheduled-jobs/2026-11-05-acquire"
    job.mkdir(parents=True)
    (job / "intent.json").write_text(json.dumps({"day": "2026-11-05", "phase": "acquire"}))
    value = report.collect(Path("plan"), "synthetic")
    assert value["budget"]["remaining_wall_seconds"] is None


def test_registry_gap_is_not_silently_skipped(campaign):
    from pathlib import Path

    directory = campaign.root / "registry"
    directory.mkdir()
    (directory / "2026-11-06.json").write_text("{}")
    with pytest.raises(ValueError, match="registry has a gap"):
        report.collect(Path("plan"), "synthetic")


def test_paged_observation_change_requires_a_fresh_report(campaign):
    from pathlib import Path

    first = {**campaign.observation, "next_offset": 100, "record_count": 101}
    second = {**campaign.observation, "record_count": 102}
    campaign.product.observations.status = lambda *a, **k: second if "offset" in k else first
    with pytest.raises(RuntimeError, match="changed during report"):
        report.collect(Path("plan"), "synthetic")


def test_read_only_native_does_not_initialize_or_publish_recovery(tmp_path):
    from quantos.artifacts.store import ArtifactIntegrityError

    strategy = SimpleNamespace(content_hash="strategy")
    policy = SimpleNamespace(content_hash="policy")
    kwargs = {
        "strategy": strategy,
        "policy": policy,
        "runtime_hash": "runtime",
        "benchmark": "benchmark",
    }
    missing = tmp_path / "missing"
    with pytest.raises(ArtifactIntegrityError):
        report.ReadOnlySession(missing, **kwargs)
    assert not missing.exists()
    root = tmp_path / "native"
    root.mkdir()
    session = {
        "schema_version": "personal-native-session/v1",
        "strategy_hash": "strategy",
        "policy_hash": "policy",
        "runtime_hash": "runtime",
        "benchmark": "benchmark",
    }
    (root / "session.json").write_text(json.dumps(session))
    step = root / "steps/2026-11-06"
    step.mkdir(parents=True)
    (step / "executed.json").write_text("{}")
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    reader = report.ReadOnlySession(root, **kwargs)
    assert reader.status()["state"] == "UNKNOWN"
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_shadow_before_first_step_does_not_create_native_session(tmp_path):
    service = SimpleNamespace(
        root=tmp_path, runtime_hash="runtime", _plan=lambda _: {"runtime_hash": "runtime"}
    )
    value = report.shadow_status(SimpleNamespace(shadow=service), "synthetic")
    assert value["state"] == "NOT_STARTED" and value["native_cash_cny"] is None
    assert not list(tmp_path.iterdir())


def test_completed_native_report_reuses_codec_and_preserves_originals(tmp_path):
    from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
    from quantos.contracts.base import canonical_json_bytes
    from quantos.research.native_state import encode_native_state
    from test_native_state import native_account
    from test_personal_shadow import setup_shadow

    # Existing synthetic native Account transport fixture, not a market run.
    fixture = setup_shadow(tmp_path)
    identity = fixture.account["shadow_id"]
    session = fixture.service._session(identity, fixture.account["plan"])
    account, _ = native_account()
    step = session.root / "steps/2024-02-01"
    step.mkdir(parents=True)
    state = step / "state.native.json"
    state.write_bytes(encode_native_state({"account": account}))
    completed = {
        "session": session.identity,
        "execution_date": "2024-02-01",
        "previous_checkpoint_hash": None,
        "files": {"state.native.json": sha256_file(state)},
    }
    (step / "completed.json").write_bytes(canonical_json_bytes(completed))
    before = {str(p): p.read_bytes() for p in session.root.rglob("*") if p.is_file()}
    result = report.shadow_status(SimpleNamespace(shadow=fixture.service), identity)
    assert result["native"]["completed_sessions"] == 1
    assert result["native_cash_cny"] == account.get_cash() == 599.5
    assert result["native_latest_report"]["account"] == 999.5
    assert result["holdings_count"] == 1
    assert before == {str(p): p.read_bytes() for p in session.root.rglob("*") if p.is_file()}
    state.write_bytes(state.read_bytes() + b"altered")
    with pytest.raises(ArtifactIntegrityError):
        report.shadow_status(SimpleNamespace(shadow=fixture.service), identity)
