"""Synthetic scheduler recovery checks; no market calls or native account runs."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from quantos.application import forward_campaign as campaign
from quantos.artifacts.store import ArtifactIntegrityError


@pytest.fixture
def scheduled(tmp_path, monkeypatch):
    approval = tmp_path / "approval.json"
    campaign.write_new(approval, {"purpose": "SYNTHETIC_ENGINEERING"})
    source = tmp_path / "source.py"
    source.write_text("# frozen synthetic dependency\n")
    plan = {
        "root": str(tmp_path),
        "repo_root": str(tmp_path),
        "source_hashes": {"source.py": campaign.sha256_file(source)},
        "approval": campaign.reference(approval),
        "signal_dates": ["2024-01-04"],
        "execution_dates": ["2024-01-05"],
        "acquisition_dates": ["2024-01-04", "2024-01-05"],
        "initial_wall_charge_seconds": 0,
        "arms": [
            {"name": name, "observation_id": name + "-observation"} for name in ("main", "control")
        ],
    }
    now = [datetime(2024, 1, 5, 0, 1, tzinfo=campaign.SHANGHAI)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0].astimezone(tz)

    monkeypatch.setattr(campaign, "datetime", Clock)
    path = tmp_path / "plan.json"

    def freeze():
        path.write_bytes(campaign.canonical_json_bytes(plan))
        return path, campaign.sha256_file(path)

    return SimpleNamespace(root=tmp_path, plan=plan, now=now, freeze=freeze)


def test_scheduler_rejects_changed_dependency_before_any_job(scheduled):
    args = scheduled.freeze()
    (scheduled.root / "source.py").write_text("# changed\n")
    with pytest.raises(ArtifactIntegrityError, match="artifact hash mismatch"):
        campaign.run(*args, "observe")
    assert not (scheduled.root / "scheduled-jobs").exists()


@pytest.mark.parametrize(
    "instant,phase,state",
    [
        ("2024-01-03T23:00:00+08:00", "acquire", "NO_SCHEDULED_SESSION"),
        ("2024-01-04T22:29:00+08:00", "acquire", "NOT_DUE"),
        ("2024-01-06T00:01:00+08:00", "observe", "NO_SCHEDULED_SESSION"),
    ],
)
def test_finite_dates_and_early_acquisition_have_no_job(scheduled, instant, phase, state):
    scheduled.now[0] = datetime.fromisoformat(instant)
    assert campaign.run(*scheduled.freeze(), phase)["state"] == state
    assert not (scheduled.root / "scheduled-jobs").exists()


@pytest.mark.parametrize("prior", ["unfinished", "budget", "stop"])
def test_scheduler_refuses_unknown_exit_exhausted_budget_and_stop(scheduled, prior):
    if prior == "stop":
        campaign.write_new(scheduled.root / "campaign-stop.json", {"state": "STOPPED"})
        message = "campaign stopped"
    else:
        job = scheduled.root / "scheduled-jobs" / "prior-acquire"
        job.mkdir(parents=True)
        if prior == "budget":
            campaign.write_new(job / "result.json", {"wall_seconds": 172000})
            message = "wall budget"
        else:
            campaign.write_new(job / "intent.json", {"state": "STARTED"})
            message = "prior scheduler exit"
    with pytest.raises(PermissionError, match=message):
        campaign.run(*scheduled.freeze(), "observe")
    assert not (scheduled.root / "scheduled-jobs" / "2024-01-04-observe").exists()


def synthetic_products(scheduled, monkeypatch, *, fail_control=False):
    acquired = scheduled.root / "acquired.json"
    campaign.write_new(acquired, {"catalog": {}})
    monkeypatch.setattr(
        campaign,
        "registry",
        lambda *_: {"acquisition_result": campaign.reference(acquired)},
    )
    monkeypatch.setattr(
        campaign, "binding", lambda _: SimpleNamespace(manifest=SimpleNamespace(dataset_id="synth"))
    )
    calls = []

    def core(_plan, _state, arm):
        def observe(**kwargs):
            calls.append((arm["name"], kwargs))
            if fail_control and arm["name"] == "control":
                raise RuntimeError("synthetic interruption after first arm")
            return {"status": "EMITTED", "after_the_fact": False, "record_hash": arm["name"]}

        return SimpleNamespace(observe=observe)

    monkeypatch.setattr(campaign, "core_for", core)
    return calls


def test_completed_observations_are_idempotent_and_keep_actual_session(scheduled, monkeypatch):
    calls = synthetic_products(scheduled, monkeypatch)
    args = scheduled.freeze()
    result = campaign.run(*args, "observe")
    assert result["state"] == "COMPLETED"
    assert result["day"] == "2024-01-04"
    assert [arm for arm, _ in calls] == ["main", "control"]
    assert all(args["day"] == "2024-01-04" and args["dataset_id"] == "synth" for _, args in calls)
    root = scheduled.root / "scheduled-jobs" / "2024-01-04-observe"
    original = (root / "result.json").read_bytes()
    replay = campaign.run(*args, "observe")
    assert replay["arms"] == result["arms"]
    assert len(calls) == 2
    assert (root / "result.json").read_bytes() == original


def test_partial_failure_retains_first_arm_and_prevents_reissue(scheduled, monkeypatch):
    calls = synthetic_products(scheduled, monkeypatch, fail_control=True)
    args = scheduled.freeze()
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        campaign.run(*args, "observe")
    root = scheduled.root / "scheduled-jobs" / "2024-01-04-observe"
    first = (root / "main.json").read_bytes()
    failure = json.loads((root / "failure.json").read_bytes())
    assert failure["state"] == "STOPPED"
    assert failure["wall_seconds"] >= 0
    assert str(root / "main.json") in failure["partial_results"]
    assert not (root / "result.json").exists()
    assert not (root / "control.json").exists()
    with pytest.raises(PermissionError, match="campaign stopped"):
        campaign.run(*args, "observe")
    assert len(calls) == 2
    assert (root / "main.json").read_bytes() == first


def test_unknown_current_job_cannot_be_replayed(scheduled):
    job = scheduled.root / "scheduled-jobs" / "2024-01-04-observe"
    job.mkdir(parents=True)
    campaign.write_new(job / "intent.json", {"state": "STARTED"})
    with pytest.raises(PermissionError, match="unfinished scheduled job"):
        campaign.run(*scheduled.freeze(), "observe")
    assert not (job / "failure.json").exists()
