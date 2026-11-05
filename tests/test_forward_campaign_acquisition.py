"""Successor registry chains and two-arm advances without live collection or accounts."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from quantos.application import forward_campaign as campaign
from test_forward_campaign import scheduled as scheduled


@pytest.fixture
def registered(scheduled, monkeypatch):
    f = scheduled
    f.plan["initial_date"] = "2024-01-03"
    f.calls = []
    f.native_failure = False
    f.action_status = "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"
    initial = {
        "day": "2024-01-03",
        "snapshot_hash": "a" * 64,
        "catalog": {"snapshot_hash": "a" * 64, "dataset_hash": "b" * 64},
    }
    initial_path = f.root / "initial-result.json"
    campaign.write_new(initial_path, initial)
    configs = {}
    for arm in f.plan["arms"]:
        arm["product_root"] = str(f.root / "products" / arm["name"])
        arm["shadow_id"] = arm["name"] + "-shadow"
        path = f.root / (arm["name"] + "-config.json")
        campaign.write_new(
            path,
            {
                "catalog": [initial["catalog"]],
                "snapshot_arrivals": [],
                "forward_dataset_admissions": [],
            },
        )
        configs[arm["name"]] = campaign.reference(path)
    prior = {
        "day": "2024-01-03",
        "previous_registry": None,
        "acquisition_result": campaign.reference(initial_path),
        "configs": configs,
    }
    # A runtime successor legitimately retains its initial registry elsewhere.
    registry = f.root / "migration/initial-registry.json"
    campaign.write_new(registry, prior)
    f.plan["initial_registry"] = campaign.reference(registry)

    def binding(value):
        return SimpleNamespace(
            field_mapping_profile="native-bins/v1",
            manifest=SimpleNamespace(
                content_hash=value["dataset_hash"],
                snapshot_hash=value["snapshot_hash"],
                dataset_id="synthetic",
            ),
        )

    def arrival(root, result, previous_hash):
        path = root / (result["day"] + "-arrival.json")
        campaign.write_new(path, {"previous_snapshot_hash": previous_hash})
        return {"metadata_path": str(path)}

    def service(product_root, repo_root, config_path):
        assert repo_root == f.root and config_path.is_file()
        name = product_root.name

        def advance(**kwargs):
            f.calls.append((name, kwargs))
            return {
                "native_receipt": {
                    "run_status": "FAILED"
                    if f.native_failure and name == "control"
                    else "SUCCEEDED"
                }
            }

        return SimpleNamespace(advance_shadow=advance, scope_status=lambda: {"state": "OPEN"})

    def acquire(plan, path, previous, day):
        assert json.loads(previous.read_bytes())["day"] < day
        ordinal = plan["acquisition_dates"].index(day) + 3
        result = {
            "day": day,
            "snapshot_hash": str(ordinal) * 64,
            "catalog": {"dataset_hash": str(ordinal + 1) * 64, "snapshot_hash": str(ordinal) * 64},
            "assessment": {"status": f.action_status},
        }
        campaign.write_new(f.root / "days" / day / "acquisition-result.json", result)

    monkeypatch.setattr(campaign, "binding", binding)
    monkeypatch.setattr(campaign, "arrival_registration", arrival)
    monkeypatch.setattr(campaign, "make_trusted_service", service)
    monkeypatch.setattr(campaign, "personal_product", lambda value: value)
    monkeypatch.setattr(campaign, "acquire_job", acquire)
    return f


def first_acquisition(f):
    f.now[0] = datetime.fromisoformat("2024-01-04T22:30:00+08:00")
    return campaign.run(*f.freeze(), "acquire")


def test_successor_uses_explicit_initial_registry_then_preserves_the_chain(registered):
    f = registered
    assert first_acquisition(f)["arms"] == {}
    state = campaign.registry(f.plan, "2024-01-04")
    assert state["previous_registry"] == f.plan["initial_registry"]
    for ref in state["configs"].values():
        config = campaign.read_ref(ref)
        assert len(config["catalog"]) == 2 and len(config["forward_dataset_admissions"]) == 1
    before = (f.root / "registry/2024-01-04.json").read_bytes()
    assert first_acquisition(f)["state"] == "COMPLETED"
    assert (f.root / "registry/2024-01-04.json").read_bytes() == before
    assert f.calls == []


@pytest.mark.parametrize("failure", [False, True])
def test_two_arm_advance_uses_prior_signal_and_retains_partial_failure(registered, failure):
    f = registered
    first_acquisition(f)
    campaign.write_new(
        f.root / "scheduled-jobs/2024-01-04-observe/result.json",
        {
            "wall_seconds": 1,
            "arms": {name: {"record_hash": name + "-record"} for name in ("main", "control")},
        },
    )
    f.now[0] = datetime.fromisoformat("2024-01-05T22:30:00+08:00")
    f.native_failure = failure
    if failure:
        with pytest.raises(RuntimeError, match="native advance"):
            campaign.run(*f.freeze(), "acquire")
        assert (f.root / "campaign-stop.json").exists()
        assert (f.root / "scheduled-jobs/2024-01-05-acquire/main.json").exists()
        assert not (f.root / "scheduled-jobs/2024-01-05-acquire/result.json").exists()
    else:
        result = campaign.run(*f.freeze(), "acquire")
        assert set(result["arms"]) == {"main", "control"}
        assert campaign.registry(f.plan, "2024-01-05")["previous_registry"] == campaign.reference(
            f.root / "registry/2024-01-04.json"
        )
    assert [name for name, _ in f.calls] == ["main", "control"]
    assert f.calls[0][1]["observation_record_hash"] == "main-record"
    assert f.calls[0][1]["execution_date"] == "2024-01-05"


def test_unknown_action_is_retained_but_never_advances_an_account(registered):
    f = registered
    f.action_status = "UNSUPPORTED_OR_UNKNOWN"
    with pytest.raises(PermissionError, match="action evidence"):
        first_acquisition(f)
    assert (f.root / "days/2024-01-04/acquisition-result.json").exists()
    assert (f.root / "campaign-stop.json").exists()
    assert not f.calls


def test_preflight_does_not_consume_or_acquire_and_registry_fork_rejects(registered):
    f = registered
    result = campaign.run(*f.freeze(), "preflight")
    assert result["state"] == "READY" and result["future_observations_performed"] == 0
    assert not (f.root / "days").exists() and not f.calls
    first_acquisition(f)
    path = f.root / "registry/2024-01-04.json"
    state = json.loads(path.read_bytes())
    state["previous_registry"]["sha256"] = "f" * 64
    path.write_bytes(campaign.canonical_json_bytes(state))
    with pytest.raises(PermissionError, match="registry chain"):
        campaign.registry(f.plan, "2024-01-04")
