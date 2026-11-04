"""Complete personal product tool registrations on the existing official MCP server."""

from __future__ import annotations

from typing import Any

from quantos.application.personal_product import personal_product


def register_product_tools(server: Any, core: Any, read: Any, write: Any) -> None:
    product = personal_product(core)

    def research_strategy_capabilities(include_schema: bool = False) -> dict[str, Any]:
        """Bounded executable DSL, portfolio/holding rules, clocks and permission state."""
        return {
            **product.research.capabilities(include_schema),
            "forward_runtime_hash": product.runtime_hash,
        }

    def research_scope_status() -> dict[str, Any]:
        """Read trusted attempt/native-step budgets; proposals cannot grant authority."""
        return product.scope_status()

    def research_scope_stop(kind: str, reason: str) -> dict[str, Any]:
        """End a configured research or forward scope with an explicit STOP reason."""
        return product.stop(kind, reason)

    def research_reconcile(task_id: str) -> dict[str, Any]:
        """Reverify completed artifacts and process state without replaying UNKNOWN work."""
        return product.reconcile(task_id)

    def research_memory_record(draft: dict[str, Any]) -> dict[str, Any]:
        """Append cited JSON facts and separately labelled model annotations; no qualification."""
        return product.memory.append(draft)

    def research_diagnostic_read(record_id: str, as_of: str | None = None) -> dict[str, Any]:
        """Read defined observations, counterevidence, limits and recommendations with sources."""
        return product.memory.diagnostic_report(record_id, as_of)

    def research_feedback_record(
        task_id: str, interpretation: str, recommendation: str, reason: str
    ) -> dict[str, Any]:
        """Form cited feedback from verified v7 receipts and labelled model interpretation."""
        return product.feedback(task_id, interpretation, recommendation, reason)

    def research_snapshot_prepare(dataset_id: str) -> dict[str, Any]:
        """Inspect offline registered snapshot/view, source arrival and continuity requirements."""
        return product.observations.snapshot_prepare(dataset_id)

    def research_observation_prepare(request: dict[str, Any]) -> dict[str, Any]:
        """Freeze strategy, policy and finite signal dates over server-bound snapshots."""
        return product.observations.prepare(request)

    def research_observation_observe(
        observation_id: str, day: str, dataset_id: str, observed_at: str, recompute: bool = False
    ) -> dict[str, Any]:
        """Publish a signal/abstention/missing/STOP record under trusted finite authority."""
        return product.observe(
            observation_id=observation_id,
            day=day,
            dataset_id=dataset_id,
            observed_at=observed_at,
            recompute=recompute,
        )

    def research_observation_status(
        observation_id: str, offset: int = 0, limit: int = 20
    ) -> dict[str, Any]:
        """Read bounded observation records and unresolved attempts across clients."""
        return product.observations.status(observation_id, offset, limit)

    def research_observation_recover(observation_id: str, attempt_hash: str) -> dict[str, Any]:
        """Publish a retained completion; incomplete UNKNOWN attempts are not recompiled."""
        return product.observations.recover(observation_id, attempt_hash)

    def research_observation_stop(observation_id: str, reason: str) -> dict[str, Any]:
        """Stop a frozen observation stream and retain its history."""
        return product.observations.stop(observation_id, reason)

    def research_shadow_prepare(
        observation_id: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        """Prepare a fresh-cash Qlib native account bound to a frozen observation stream."""
        return product.shadow.prepare(observation_id, start_date, end_date)

    def research_shadow_advance(
        shadow_id: str, execution_date: str, observation_record_hash: str, execution_dataset_id: str
    ) -> dict[str, Any]:
        """Advance one native session from frozen prior signal plus explicit execution snapshot."""
        return product.advance_shadow(
            shadow_id=shadow_id,
            execution_date=execution_date,
            observation_record_hash=observation_record_hash,
            execution_dataset_id=execution_dataset_id,
        )

    def research_shadow_status(shadow_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        """Read complete native checkpoint identity/clock and account scope across restarts."""
        return product.shadow.status(shadow_id, offset, limit)

    def research_shadow_stop(shadow_id: str, reason: str) -> dict[str, Any]:
        """Stop native account advances without changing prior positions, trades or reports."""
        return product.shadow.stop(shadow_id, reason)

    for function in (
        research_strategy_capabilities,
        research_scope_status,
        research_diagnostic_read,
        research_snapshot_prepare,
        research_observation_status,
    ):
        server.add_tool(function, annotations=read)
    for function in (
        research_scope_stop,
        research_reconcile,
        research_memory_record,
        research_feedback_record,
        research_observation_prepare,
        research_observation_observe,
        research_observation_recover,
        research_observation_stop,
        research_shadow_prepare,
        research_shadow_advance,
        research_shadow_status,
        research_shadow_stop,
    ):
        server.add_tool(function, annotations=write)
