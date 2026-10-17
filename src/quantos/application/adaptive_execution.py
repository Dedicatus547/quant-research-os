"""Freeze singleton children and compose the existing Qlib/PIT/Validation port."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from quantos.application.adaptive_store import read
from quantos.application.autonomous_execution import (
    QuantosResearchExecutionAdapter,
    VerifiedExecutionInputs,
    quote_autonomous_workload,
)
from quantos.application.discovery_admission import freeze_singleton
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.adaptive import AdaptiveChild, AdaptiveDecision, AdaptiveResearchSpec
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import (
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
    autonomous_execution_identity,
)
from quantos.contracts.base import sha256_bytes
from quantos.contracts.campaign import (
    CampaignStoppingRule,
    MultipleTestingPolicy,
    ResearchBudgetSpec,
    ResearchCampaignSpec,
)
from quantos.contracts.discovery import DiscoveryCompositionDesign
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.contracts.research import ExperimentAuthoringSpec


def quote_expression(spec: AdaptiveResearchSpec, expression: SafeQlibExpressionSpec) -> int:
    authoring = ExperimentAuthoringSpec.model_validate(
        {
            **spec.design.authoring.model_dump(mode="python"),
            "expression": expression.model_dump(mode="python"),
        }
    )
    window = (
        next((n.node_id for n in expression.nodes if n.window is not None), None)
        if isinstance(spec.design, DiscoveryCompositionDesign)
        else None
    )
    return quote_autonomous_workload(
        authoring, spec.design.validation_policy, window_node_id=window
    )


def freeze_child(
    spec: AdaptiveResearchSpec, decision: AdaptiveDecision, capture_hash: str, ordinal: int
) -> AdaptiveChild:
    if decision.expression is None or decision.action != "PROPOSE":
        raise ValueError("only a proposed expression can freeze a child")
    task = freeze_singleton(spec.design, decision.expression)
    quote = quote_expression(spec, task.manifest.candidates[0].expression)
    budget = ResearchBudgetSpec(
        budget_id=f"{spec.task_id}-{ordinal}",
        max_trials=1,
        max_distinct_candidates=1,
        max_agent_runs=1,
        max_executions=1,
        max_validation_rounds=1,
        max_compute_seconds=quote,
    )
    design = spec.design
    campaign = ResearchCampaignSpec(
        campaign_id=f"{spec.task_id}-{ordinal}",
        research_question=design.research_question,
        family_hash=task.family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=tuple(
            sorted(
                {
                    spec.content_hash,
                    decision.content_hash,
                    capture_hash,
                    *spec.context_source_hashes,
                }
            )
        ),
        ledger_snapshot_hash=design.ledger_snapshot_hash,
        snapshot_hash=design.snapshot_hash,
        qlib_view_hash=design.qlib_view_hash,
        development=design.research_policy.validation,
        validation=design.research_policy.test,
        sealed_confirmation=design.sealed_confirmation,
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    candidate = task.manifest.candidates[0]
    bindings = design.bindings
    identity = autonomous_execution_identity(
        campaign_hash=campaign.content_hash,
        family_hash=task.family.content_hash,
        budget_hash=budget.content_hash,
        candidate_manifest_hash=task.manifest.content_hash,
        candidate=candidate,
        snapshot_hash=design.snapshot_hash,
        qlib_view_hash=design.qlib_view_hash,
        segment=CampaignSegment.VALIDATION,
        segment_start=design.research_policy.test.start,
        segment_end=design.research_policy.test.end,
        trial_ordinal=1,
        bindings=bindings,
    )
    request = AutonomousExecutionRequest(
        **bindings.model_dump(mode="python", exclude={"schema_version"}),
        idempotency_key=identity,
        execution_identity=identity,
        trial_ordinal=1,
        campaign_hash=campaign.content_hash,
        family_hash=task.family.content_hash,
        budget_hash=budget.content_hash,
        candidate_manifest_hash=task.manifest.content_hash,
        candidate=candidate,
        candidate_exact_expression_hash=candidate.exact_expression_hash,
        candidate_structural_expression_hash=candidate.structural_expression_hash,
        snapshot_hash=design.snapshot_hash,
        qlib_view_hash=design.qlib_view_hash,
        segment=CampaignSegment.VALIDATION,
        segment_start=design.research_policy.test.start,
        segment_end=design.research_policy.test.end,
        agent_run_hash=capture_hash,
        remaining_executions=1,
        remaining_validation_rounds=1,
        remaining_compute_seconds=quote,
    )
    return AdaptiveChild(
        task_hash=spec.content_hash,
        decision_hash=decision.content_hash,
        capture_hash=capture_hash,
        ordinal=ordinal,
        quote_units=quote,
        subtask=task,
        campaign=campaign,
        budget=budget,
        request=request,
    )


class AdaptiveExecutionPort:
    def __init__(
        self,
        spec: AdaptiveResearchSpec,
        dispatch: Callable[
            [AdaptiveChild, QuantosResearchExecutionAdapter], AutonomousExecutionResult
        ]
        | None = None,
    ) -> None:
        self.spec, self.dispatch = spec, dispatch
        self.inputs: VerifiedExecutionInputs | None = None
        self.adapters: dict[str, QuantosResearchExecutionAdapter] = {}

    def verify_inputs(self) -> None:
        """Verify frozen data once per operation, before spending a new SDK call."""
        if self.inputs is None:
            self.inputs = VerifiedExecutionInputs(
                Path(self.spec.snapshot_path), Path(self.spec.qlib_view_path)
            )

    def adapter(self, child: AdaptiveChild) -> QuantosResearchExecutionAdapter:
        if child.task_hash != self.spec.content_hash:
            raise ValueError("child belongs to another parent")
        if child.content_hash not in self.adapters:
            self.verify_inputs()
            d, t = self.spec.design, child.subtask
            self.adapters[child.content_hash] = QuantosResearchExecutionAdapter(
                campaign=child.campaign,
                family=t.family,
                budget=child.budget,
                template=t.template,
                manifest=t.manifest,
                snapshot_path=Path(self.spec.snapshot_path),
                qlib_view_path=Path(self.spec.qlib_view_path),
                base_authoring=d.authoring,
                research_policy=d.research_policy,
                validation_policy=d.validation_policy,
                cost_policy=d.cost_policy,
                backtest_policy=d.backtest_policy,
                bindings=d.bindings,
                output_root=Path(self.spec.output_root)
                / "children"
                / child.content_hash
                / "execution",
                workspace=Path(self.spec.workspace),
                discovery_stage_recovery=True,
                retain_completed_outcome=True,
                discovery_profile=d.profile_id,
                _verified_inputs=self.inputs,
            )
        return self.adapters[child.content_hash]

    def execute(self, child: AdaptiveChild) -> AutonomousExecutionResult:
        if self.dispatch is None:
            raise ValueError("science requires explicit offline namespace dispatcher")
        return self.dispatch(child, self.adapter(child))

    def reconcile(self, child: AdaptiveChild) -> AutonomousExecutionResult | None:
        # This path cannot call execute(), even when a receipt is absent.
        return self.adapter(child).reconcile_completed_outcome(child.request)

    def process_exit(self, child: AdaptiveChild) -> dict[str, Any] | None:
        path = (
            Path(self.spec.output_root)
            / "children"
            / child.content_hash
            / "job"
            / "process-exit.json"
        )
        if not path.exists():
            return None
        data = read(path)
        record = json.loads(data)
        if (record.get("task_hash"), record.get("child_hash"), record.get("request_hash")) != (
            self.spec.content_hash,
            child.content_hash,
            child.request.content_hash,
        ):
            raise ArtifactIntegrityError("scientific exit belongs to another child")
        return {"exit_code": record["exit_code"], "evidence_hash": sha256_bytes(data)}
