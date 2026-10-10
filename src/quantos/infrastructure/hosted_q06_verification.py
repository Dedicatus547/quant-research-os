"""Complete Q06 gate: original lifecycle and independently frozen budget matrix."""

from __future__ import annotations

from pathlib import Path

from quantos.contracts.hosted_qualification import HostedQualificationCase
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES
from quantos.infrastructure.hosted_budget_verification import (
    BUDGET_SNAPSHOT_PHASES,
    verify_q06_budget_subset,
)
from quantos.infrastructure.hosted_lifecycle_cases import (
    HOSTED_LIFECYCLE_CASES,
    LIFECYCLE_SNAPSHOT_PHASES,
)
from quantos.infrastructure.hosted_lifecycle_verification import verify_q06_lifecycle_subset
from quantos.infrastructure.hosted_negative_origin import require
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources


def verify_q06(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """No subset or inferred budget variant can award the full scenario gate."""
    lifecycle = {
        f"{name}-{phase}" for name in HOSTED_LIFECYCLE_CASES for phase in LIFECYCLE_SNAPSHOT_PHASES
    }
    budget = {f"{name}-{phase}" for name in HOSTED_BUDGET_CASES for phase in BUDGET_SNAPSHOT_PHASES}
    require(case.case_id == "Q06", "Q06 case identity differs")
    require(
        {root.name for root in case.roots} == lifecycle | budget,
        "Q06 complete original lifecycle and budget matrices absent",
    )
    checked: set[str] = set()
    checked.update(
        verify_q06_lifecycle_subset(
            bundle,
            case.model_copy(
                update={
                    "roots": tuple(root for root in case.roots if root.name in lifecycle),
                }
            ),
            sources,
        )
    )
    checked.update(
        verify_q06_budget_subset(
            bundle,
            case.model_copy(
                update={
                    "roots": tuple(root for root in case.roots if root.name in budget),
                }
            ),
            sources,
        )
    )
    return tuple(sorted(checked))
