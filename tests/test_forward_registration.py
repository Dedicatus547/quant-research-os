"""Registration must bind the original source assessment and contiguous calendar."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from quantos.application.forward_registration import (
    verify_arrival_assessment,
    verify_dataset_admissions,
)
from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.forward import ForwardDatasetAdmission, PersonalForwardScopeV2
from quantos.contracts.personal_strategy import PersonalForwardScope


@pytest.fixture
def chain(tmp_path):
    calendar = tmp_path / "calendars/day.txt"
    calendar.parent.mkdir()
    calendar.write_text("2024-01-02\n2024-01-03\n2024-01-04\n2024-01-05\n")

    def binding(name, digest, day):
        manifest = SimpleNamespace(
            dataset_id=name,
            content_hash=digest,
            snapshot_hash=digest,
            end_date=day,
            kind="synthetic",
            source_vintage="synthetic",
            warmup_start=date(2024, 1, 2),
            qlib_files={"calendars/day.txt": sha256_file(calendar)},
        )
        return SimpleNamespace(
            manifest=manifest, provider_root=tmp_path, field_mapping_profile="native-bins/v1"
        )

    old = binding("initial", "a" * 64, date(2024, 1, 2))
    new = binding("next", "b" * 64, date(2024, 1, 4))
    arrival = SimpleNamespace(content_hash="c" * 64, previous_snapshot_hash="a" * 64)
    scope = PersonalForwardScopeV2(
        purpose="SYNTHETIC_ENGINEERING",
        strategy_hash="d" * 64,
        policy_hash="e" * 64,
        runtime_hash="f" * 64,
        allowed_dataset_hashes=("a" * 64,),
        start_date=date(2024, 1, 4),
        end_date=date(2024, 1, 5),
        max_observations=2,
        max_native_steps=2,
        wall_seconds=10,
        growth_bytes=1000,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        approval_evidence_sha256="0" * 64,
        max_dataset_successors=2,
        initial_bridge_sessions=2,
        observation_id="1" * 64,
        shadow_id="2" * 64,
        per_job_wall_seconds=10,
        per_job_growth_bytes=1000,
    )
    admission = ForwardDatasetAdmission(
        dataset_hash="b" * 64,
        previous_dataset_hash="a" * 64,
        snapshot_hash="b" * 64,
        previous_snapshot_hash="a" * 64,
        arrival_hash="c" * 64,
        end_date=date(2024, 1, 4),
    )
    return scope, admission, {"initial": old, "next": new}, {"next": arrival}


def test_initial_bridge_is_explicit_and_v1_cannot_inherit_successors(chain):
    scope, admission, catalog, arrivals = chain
    verify_dataset_admissions(scope, (admission,), catalog, arrivals)
    with pytest.raises(PermissionError, match="chain differs"):
        verify_dataset_admissions(
            scope.model_copy(update={"initial_bridge_sessions": 1}), (admission,), catalog, arrivals
        )
    legacy = PersonalForwardScope.model_validate(
        {
            **{
                key: value
                for key, value in scope.model_dump().items()
                if key in PersonalForwardScope.model_fields
            },
            "schema_version": "personal-forward-scope/v1",
        }
    )
    with pytest.raises(PermissionError, match="v2 scope"):
        verify_dataset_admissions(legacy, (admission,), catalog, arrivals)


@pytest.mark.parametrize(
    "field", ["previous_dataset_hash", "previous_snapshot_hash", "snapshot_hash", "arrival_hash"]
)
def test_admission_cannot_change_bound_predecessor_or_arrival(chain, field):
    scope, admission, catalog, arrivals = chain
    with pytest.raises(PermissionError, match="chain differs"):
        verify_dataset_admissions(
            scope, (admission.model_copy(update={field: "9" * 64}),), catalog, arrivals
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "market"),
        ("source_vintage", "historical_non_vintage"),
        ("warmup_start", date(2024, 1, 3)),
        ("end_date", date(2024, 1, 5)),
    ],
)
def test_successor_cannot_change_source_domain_or_calendar_bounds(chain, field, value):
    scope, admission, catalog, arrivals = chain
    setattr(catalog["next"].manifest, field, value)
    with pytest.raises(PermissionError, match="chain differs"):
        verify_dataset_admissions(scope, (admission,), catalog, arrivals)


def test_arrival_recomputes_source_assessment_and_rejects_supplied_pass(tmp_path, monkeypatch):
    assessment = {
        "snapshot_end_date": "2024-01-05",
        "fresh_account_start": "2024-01-08",
        "status": "SUPPORTED_IN_DECLARED_SOURCE_SCOPE",
        "source_max_received_at": "2024-01-05T10:00:00+00:00",
    }
    monkeypatch.setattr(
        "quantos.data.forward_action_coverage.assess_actions", lambda root, inputs: assessment
    )
    arrival = SimpleNamespace(
        assessment_hash=sha256_bytes(canonical_json_bytes(assessment)),
        assessment_end_date=date(2024, 1, 5),
        fresh_account_start=date(2024, 1, 8),
        corporate_actions=assessment["status"],
        source_visible_at=datetime(2024, 1, 5, 10, tzinfo=UTC),
    )
    binding = SimpleNamespace(
        manifest=SimpleNamespace(
            snapshot_hash="a" * 64,
            end_date=date(2024, 1, 5),
            source_files={"canonical/index_membership.parquet": "b" * 64},
        )
    )
    evidence = {
        "schema_version": "forward-arrival-evidence/v2",
        "snapshot_hash": "a" * 64,
        "inputs": {"membership": {"sha256": "b" * 64}},
        "assessment": dict(assessment),
    }
    verify_arrival_assessment(arrival, evidence, tmp_path, binding)
    assessment["status"] = "UNSUPPORTED_OR_UNKNOWN"
    with pytest.raises(PermissionError, match="retained sources"):
        verify_arrival_assessment(arrival, evidence, tmp_path, binding)
