"""Bounded successor admission and structural-data continuity regression checks."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from tests.test_personal_scope import lease, setup

from quantos.application.forward_continuity import (
    align_historical_prefix,
    source_observable_factors,
)
from quantos.application.personal_forward_authority import PersonalForwardAuthority
from quantos.contracts.forward import ForwardDatasetAdmission, PersonalForwardScopeV2


def test_successor_budget_survives_restart_and_used_prefix_cannot_be_replaced(
    tmp_path, monkeypatch
):
    old, item, _ = setup(tmp_path, forward=True)
    raw = old.scope.model_dump()
    raw.update(
        schema_version="personal-forward-scope/v2",
        max_dataset_successors=2,
        observation_id="1" * 64,
        shadow_id="2" * 64,
        per_job_wall_seconds=10,
        per_job_growth_bytes=1000,
    )
    scope = PersonalForwardScopeV2.model_validate(raw)
    first = ForwardDatasetAdmission(
        dataset_hash="b" * 64,
        previous_dataset_hash=item.dataset_hash,
        snapshot_hash="1" * 64,
        previous_snapshot_hash="0" * 64,
        arrival_hash="2" * 64,
        end_date=date(2024, 1, 3),
    )
    second = ForwardDatasetAdmission(
        dataset_hash="d" * 64,
        previous_dataset_hash=first.dataset_hash,
        snapshot_hash="3" * 64,
        previous_snapshot_hash=first.snapshot_hash,
        arrival_hash="4" * 64,
        end_date=date(2024, 1, 4),
    )
    approval = b"Synthetic scope boundary fixtures only."

    def authority(entries):
        return PersonalForwardAuthority(
            tmp_path, scope, approval, resource_check=lambda _: None, dataset_admissions=entries
        )

    common = dict(
        strategy_hash=scope.strategy_hash,
        policy_hash=scope.policy_hash,
        runtime_hash=scope.runtime_hash,
        operation="observe",
        kind="synthetic",
    )
    proof = lease(tmp_path, monkeypatch)
    current = authority((first,))
    current.authorize(
        **common, dataset_hash=first.dataset_hash, day=first.end_date, operation_identity="5" * 64
    )
    current.settle(
        "observe", "5" * 64, "EMITTED", wall_seconds=2, growth_bytes=100, exit_reference=proof
    )
    resumed = authority((first, second))
    assert resumed.remaining_limits()["wall_seconds"] == 8
    assert resumed.remaining_limits()["remaining_observations"] == 2
    lease(tmp_path, monkeypatch, "second")
    with pytest.raises(PermissionError, match="different actual session"):
        resumed.authorize(
            **common,
            dataset_hash=second.dataset_hash,
            day=first.end_date,
            operation_identity="6" * 64,
        )
    changed = authority((first.model_copy(update={"arrival_hash": "9" * 64}), second))
    with pytest.raises(PermissionError, match="removed or changed"):
        changed.authorize(
            **common,
            dataset_hash=second.dataset_hash,
            day=second.end_date,
            operation_identity="6" * 64,
        )
    resumed.authorize(
        **common, dataset_hash=second.dataset_hash, day=second.end_date, operation_identity="6" * 64
    )
    assert resumed.reservation("6" * 64)["wall_limit_seconds"] == 8
    with pytest.raises(PermissionError, match="v1"):
        PersonalForwardAuthority(
            tmp_path,
            old.scope,
            approval,
            resource_check=lambda _: None,
            dataset_admissions=(first,),
        )


def test_added_old_rows_must_be_nonmembers_and_missing_factors_need_source_status():
    old = pd.DataFrame({"is_member": [True], "value": [1]}, index=["old"])
    new = pd.DataFrame({"is_member": [True, False], "value": [1, 2]}, index=["old", "new"])
    pd.testing.assert_frame_equal(align_historical_prefix(old, new), old)
    new.loc["new", "is_member"] = True
    with pytest.raises(ValueError, match="previously unobserved member"):
        align_historical_prefix(old, new)
    with pytest.raises(ValueError, match="removed"):
        align_historical_prefix(old, new.loc[["new"]])
    frame = pd.DataFrame(
        {
            "adjustment_factor": [1.0, np.nan],
            "is_listed": [True, False],
            "is_suspended": [False, False],
        }
    )
    assert source_observable_factors(frame)
    frame.loc[1, "is_listed"] = True
    assert not source_observable_factors(frame)
    frame.loc[1, "is_suspended"] = True
    assert source_observable_factors(frame)
    frame.loc[1, "adjustment_factor"] = 0
    assert not source_observable_factors(frame)
