"""Official MCP Python SDK STDIO entry point for local personal research.

The SDK is an optional tool-environment dependency. Scientific environments
and legacy typed application services do not import it.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from quantos.application.personal_research import PersonalResearchService

# Legacy package initialization imports optional scientific adapters that print
# availability messages. STDIO's stdout belongs exclusively to the official SDK.
with redirect_stdout(sys.stderr):
    from quantos.application.personal_evidence import PersonalEvidenceService, explicit_root


def create_server(
    root: Path,
    repo_root: Path,
    *,
    research_service: PersonalResearchService | None = None,
    server_config: Path | None = None,
) -> FastMCP:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    root, repo_root = explicit_root(root), explicit_root(repo_root)
    if research_service is None:
        from quantos.application.personal_server_config import make_trusted_service

        research_service = make_trusted_service(root, repo_root, server_config)
    evidence = PersonalEvidenceService(root, repo_root)
    from quantos.application.personal_history import PersonalHistoryService

    history = PersonalHistoryService(root, repo_root)
    server = FastMCP(
        "quantos-research",
        instructions=(
            "Local research assistant. Read capabilities and retained history first. "
            "Prepare host-session proposals; execution requires server-side authorization. "
            "Tool arguments cannot grant approval. "
            "Lifecycle data readiness does not prove zero native event exposure; "
            "Cash v5 checks bound rules on actual native orders; merger, delisting or "
            "unknown exposure stop the arm and retain all seven. "
            "Report engineering and scientific status separately. "
            "Announcement conclusions remain unadmitted auxiliary proposals; exact citations "
            "verify text location only, never semantic truth or absence of adverse information. "
            "No data acquisition, paid model calls, broker orders or background jobs are enabled."
        ),
    )
    read = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    def research_capabilities() -> dict[str, Any]:
        """Describe supported research scope and explicit data/execution limitations."""
        inventory = history.search(query="local-data-inventory", limit=1)
        return {
            **research_service.capabilities(),
            "known_data_inventory": history.read("local-data-inventory")["original"]
            if inventory["matched"]
            else None,
            "inventory_admission": "DESCRIPTIVE_ONLY_NOT_AN_EXECUTABLE_DATASET_BINDING",
            "live_data_updated_at": None,
        }

    def research_data_describe(dataset_id: str | None = None) -> dict[str, Any]:
        """Describe server-bound immutable datasets, availability policies and source gaps."""
        return research_service.data_describe(dataset_id)

    def research_history(limit: int = 20, query: str = "") -> dict[str, Any]:
        """Find persisted research tasks across sessions, without mutable latest selection."""
        return {
            **research_service.history(limit=limit),
            "retained_history": history.search(query=query, limit=limit),
        }

    def research_retained_read(record_id: str) -> dict[str, Any]:
        """Read a hash-verified catalogued historical report; never rerun old research."""
        return history.read(record_id)

    def research_prepare(request: dict[str, Any]) -> dict[str, Any]:
        """Prepare a bounded cash v5 proposal; readiness and reuse grant no execution authority."""
        return research_service.prepare(request)

    def research_status(task_id: str) -> dict[str, Any]:
        """Read one explicit persistent task identity."""
        return research_service.status(task_id)

    def research_execute(task_id: str) -> dict[str, Any]:
        """Invoke controlled execution only when the server has valid bound authorization."""
        return research_service.execute(task_id)

    def research_cancel(task_id: str) -> dict[str, Any]:
        """Request cancellation using the persistent core task service."""
        return research_service.cancel(task_id)

    def research_results(task_id: str) -> dict[str, Any]:
        """Read retained results, comparison and honest missing/not-evaluated states."""
        return research_service.results(task_id)

    def research_simulation_prepare(task_id: str) -> dict[str, Any]:
        """Prepare a conditional simulation request; never start live or scheduled work."""
        return research_service.simulation_prepare(task_id)

    def announcement_list(limit: int = 20) -> dict[str, Any]:
        """List explicitly catalogued frozen local material and permission limitations."""
        return evidence.list_evidence(limit)

    def announcement_read(
        evidence_hash: str, start: int = 0, max_chars: int = 8000, as_of: str | None = None
    ) -> dict[str, Any]:
        """Read a bounded frozen span; historical as_of fails when availability is unknown."""
        return evidence.read(evidence_hash, start, max_chars, as_of)

    def announcement_cite(
        evidence_hash: str, start: int, end: int, expected_text: str
    ) -> dict[str, Any]:
        """Construct an exact physical-page citation after matching the frozen text."""
        return evidence.cite(evidence_hash, start, end, expected_text)

    def announcement_propose(
        evidence_hash: str, claim: str, citations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Save unadmitted host-session analysis with exact citations; no semantic qualification."""
        return evidence.propose(evidence_hash, claim, citations)

    def announcement_review(proposal_id: str) -> dict[str, Any]:
        """Recheck proposal/citation integrity; semantic judgment and admission remain pending."""
        return evidence.review(proposal_id)

    def announcement_import_local(intake_manifest: str) -> dict[str, Any]:
        """Import 1-16 retained local raw/text/page maps from a bounded typed intake manifest."""
        return evidence.import_local(intake_manifest)

    server.add_tool(research_capabilities, annotations=read)
    server.add_tool(research_data_describe, annotations=read)
    server.add_tool(research_history, annotations=write)
    server.add_tool(research_retained_read, annotations=read)
    server.add_tool(research_prepare, annotations=write)
    server.add_tool(research_status, annotations=write)
    server.add_tool(research_execute, annotations=write)
    server.add_tool(research_cancel, annotations=write)
    server.add_tool(research_results, annotations=write)
    server.add_tool(research_simulation_prepare, annotations=write)
    server.add_tool(announcement_list, annotations=read)
    server.add_tool(announcement_read, annotations=read)
    server.add_tool(announcement_cite, annotations=read)
    server.add_tool(announcement_propose, annotations=write)
    server.add_tool(announcement_review, annotations=read)
    server.add_tool(announcement_import_local, annotations=write)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", required=True, type=Path, help="Explicit absolute persistent product root"
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        type=Path,
        help="Explicit absolute source/evidence repository root",
    )
    parser.add_argument(
        "--server-config",
        type=Path,
        default=None,
        help="Operator-owned config; default <root>/server-config.json if present",
    )
    args = parser.parse_args(argv)
    server = create_server(args.root, args.repo_root, server_config=args.server_config)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
