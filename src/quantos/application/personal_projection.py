"""Bounded display successors; retain the original service integrity path unchanged."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from quantos.contracts.base import canonical_json_bytes, sha256_bytes

if TYPE_CHECKING:
    from quantos.application.personal_research import PersonalResearchService


class PersonalResearchProjection:
    def __init__(self, service: PersonalResearchService) -> None:
        self.service = service

    @staticmethod
    def _page(offset: int, limit: int) -> None:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative; limit must be 1..100")

    def capabilities(self, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        self._page(offset, limit)
        manifests = [binding.manifest for binding in self.service.catalog.values()]
        datasets: list[dict[str, Any]] = []
        for manifest in manifests[offset : offset + limit]:
            data = manifest.model_dump(mode="json")
            datasets.append(
                {
                    "dataset_id": manifest.dataset_id,
                    "content_hash": manifest.content_hash,
                    "start_date": data["start_date"],
                    "end_date": data["end_date"],
                    "warmup_start": data.get("warmup_start"),
                    "source": data.get("market_source", data["kind"]),
                    "source_vintage": data["source_vintage"],
                    "exposure": data["exposure"],
                    "readiness": "REGISTERED_NOT_EXECUTION_AUTHORIZATION",
                }
            )
        next_offset = offset + len(datasets)
        configured = self.service.execution_authorization_configured
        return {
            "schema_version": "personal-research-capability-summary/v1",
            "datasets": datasets,
            "total": len(manifests),
            "next_offset": next_offset if next_offset < len(manifests) else None,
            "readiness": {
                "registered_datasets": len(manifests),
                "blocker_count": len(self.service.data_blockers),
                "execution_authorization_configured": configured,
                "real_market_execution_default": "DENIED",
            },
            "limits": [
                "Historical non-vintage sources grant no vendor-vintage claim",
                "v3 uses vendor-adjusted units, without separate dividend cash/payment claim",
                "Native unsupported/unknown exposure stops the arm; readiness is not zero exposure",
                "Scientific validation NOT_EVALUATED; continuous forward account not qualified",
            ],
            "full_manifest_tool": "research_data_describe",
        }

    @staticmethod
    def _origin(origin: dict[str, Any] | None) -> dict[str, Any] | None:
        if origin is None:
            return None
        return {
            "content_hash": sha256_bytes(canonical_json_bytes(origin)),
            "prepared": origin["prepared"],
            "receipt": origin["receipt"],
            "outcome": origin["outcome"],
            "adoption_scope": origin["adoption_scope"],
        }

    def results(self, task_id: str) -> dict[str, Any]:
        # Full immutable validation is intentional. Display size and verification cost
        # are separate concerns; no alternate verifier or cached PASS is introduced.
        result = self.service.results(task_id)
        if result.get("schema_version") == "personal-strategy-results/v1":
            return self._strategy_results(result)
        metric_keys = (
            "sessions",
            "net_total_return",
            "benchmark_total_return",
            "excess_total_return",
            "max_drawdown",
            "mean_risk_exposure",
            "total_cost_cny",
            "total_turnover",
            "native_order_count",
            "native_filled_order_count",
            "native_unfilled_order_count",
        )
        rows: list[dict[str, Any]] = []
        for row in result["rows"]:
            metrics = row["metrics"]
            rows.append(
                {
                    **{
                        key: row[key]
                        for key in (
                            "candidate_id",
                            "role",
                            "seed",
                            "run_status",
                            "evidence_status",
                            "validation_verdict",
                        )
                    },
                    "metrics": None
                    if metrics is None
                    else {key: metrics.get(key) for key in metric_keys},
                    "origin_reuse": self._origin(row["origin_reuse"]),
                    "native_boundary_status": row.get("native_boundary_status", "NOT_OBSERVED"),
                    "native_rights_observability": row.get(
                        "native_rights_observability", "NOT_OBSERVED"
                    ),
                    "boundary_count": None
                    if row.get("boundary_receipts") is None
                    else len(row["boundary_receipts"]),
                }
            )
        return {
            "schema_version": "personal-research-result-summary/v1",
            **{
                key: result[key]
                for key in (
                    "task_id",
                    "state",
                    "readiness",
                    "validation_verdict",
                    "evidence_kind",
                    "planned_denominator",
                    "succeeded_denominator",
                    "reused_denominator",
                )
            },
            "outcome_hash": result["event"]["detail"].get("outcome_hash"),
            "comparison_sha256": result.get("comparison_sha256"),
            "rows": rows,
            "interpretation": result["interpretation"],
            "limits": [
                "Model returns after fixed trading costs; not actual dividend/tax receipts",
                "Missing or failed full-interval metrics remain null; "
                "partial artifacts are details",
                "Original integrity checks retained; no new scientific qualification",
            ],
            "details_tool": "research_results_boundary_page",
            "full_result_tool": "research_results",
        }

    def _strategy_details(
        self, task_id: str, row: dict[str, Any]
    ) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
        """Resolve original receipt-bound target traces through the full verifier."""
        source_task = task_id
        source = row
        if row["run_status"] == "REUSED_ORIGIN":
            origin = row["origin"]
            source_task = origin["task_id"]
            original = self.service.results(source_task)
            source = next(
                item for item in original["rows"] if item["candidate_id"] == origin["candidate_id"]
            )
        entries = [
            {"file": logical, "sha256": digest}
            for logical, digest in sorted(source.get("files", {}).items())
            if logical.startswith("native/targets/")
            and logical.count("/") == 2
            and logical.endswith(".json")
        ]
        return source_task, source, entries

    def _strategy_results(self, result: dict[str, Any]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        metric_keys = (
            "sessions",
            "net_total_return",
            "benchmark_total_return",
            "excess_total_return",
            "max_drawdown",
            "mean_risk_exposure",
            "actual_exposure",
            "total_cost_cny",
            "total_turnover",
            "order_count",
            "yearly_net_returns",
            "subperiod_net_returns",
        )
        for row in result["rows"]:
            source_task, source, entries = self._strategy_details(result["task_id"], row)
            metrics = row["metrics"]
            rows.append(
                {
                    **{
                        key: row.get(key)
                        for key in (
                            "candidate_id",
                            "role",
                            "hypothesis",
                            "strategy_hash",
                            "run_status",
                            "receipt_sha256",
                            "account_identity",
                            "signal_artifact_hash",
                            "prepared_hash",
                            "policy_hash",
                            "dataset_hash",
                            "engine",
                            "evidence_kind",
                            "error_type",
                        )
                    },
                    "validation_verdict": row.get("validation_verdict", "NOT_EVALUATED"),
                    "metrics": None
                    if metrics is None
                    else {key: metrics.get(key) for key in metric_keys},
                    "origin": row.get("origin"),
                    "detail_source": {
                        "task_id": source_task,
                        "candidate_id": source["candidate_id"],
                        "receipt_sha256": source.get("receipt_sha256"),
                        "account_identity": source.get("account_identity"),
                        "evidence_kind": source.get("evidence_kind"),
                    },
                    "boundary_count": None
                    if source.get("receipt_sha256") is None
                    else len(entries),
                }
            )
        return {
            "schema_version": "personal-research-result-summary/v2",
            "source_schema_version": result["schema_version"],
            **{
                key: result[key]
                for key in (
                    "task_id",
                    "state",
                    "readiness",
                    "validation_verdict",
                    "planned_denominator",
                    "attempted_denominator",
                    "brief_hash",
                    "policy_hash",
                    "dataset_hash",
                    "parent_task_id",
                )
            },
            "succeeded_denominator": sum(row["run_status"] == "SUCCEEDED" for row in rows),
            "reused_denominator": sum(row["run_status"] == "REUSED_ORIGIN" for row in rows),
            "outcome_hash": result["event"]["detail"].get("outcome_hash"),
            "rows": rows,
            "limits": [
                *result["limits"],
                "Missing and failed full-interval metrics remain null; no scientific qualification",
                "Target traces contain generated orders, not fills; "
                "native-order artifacts retain actual fills",
                "Reused native accounts retain their original task, receipt and account identity",
            ],
            "details_kind": "RECEIPT_BOUND_NATIVE_TARGET_TRACES",
            "details_tool": "research_results_boundary_page",
            "detail_read_tool": "research_results_boundary_read",
            "full_result_tool": "research_results",
        }

    def _row(self, task_id: str, candidate_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = self.service.results(task_id)
        for row in result["rows"]:
            if row["candidate_id"] == candidate_id:
                return result, row
        raise ValueError("candidate_id is not in the frozen denominator")

    def boundary_page(
        self, task_id: str, candidate_id: str, offset: int = 0, limit: int = 20
    ) -> dict[str, Any]:
        self._page(offset, limit)
        result, row = self._row(task_id, candidate_id)
        if result.get("schema_version") == "personal-strategy-results/v1":
            source_task, source, entries = self._strategy_details(task_id, row)
            page = entries[offset : offset + limit]
            end = offset + len(page)
            return {
                "schema_version": "personal-research-boundary-page/v2",
                "detail_kind": "NATIVE_TARGET_TRACE",
                "task_id": task_id,
                "candidate_id": candidate_id,
                "run_status": row["run_status"],
                "receipt_sha256": row.get("receipt_sha256"),
                "origin": row.get("origin"),
                "source_task_id": source_task,
                "source_candidate_id": source["candidate_id"],
                "source_receipt_sha256": source.get("receipt_sha256"),
                "observability": "RETAINED" if entries else "NOT_OBSERVED",
                "total": None if source.get("receipt_sha256") is None else len(entries),
                "entries": page,
                "next_offset": end if end < len(entries) else None,
                "read_tool": "research_results_boundary_read",
                "read_hash_parameter": "boundary_sha256",
                "order_semantics": "orders_generated are proposals; "
                "native-orders.parquet retains fills",
            }
        boundaries = row.get("boundary_receipts")
        entries: list[dict[str, Any]] = boundaries or []
        page = [
            {"file": entry["file"], "sha256": entry["sha256"]}
            for entry in entries[offset : offset + limit]
        ]
        end = offset + len(page)
        return {
            "schema_version": "personal-research-boundary-page/v1",
            "task_id": task_id,
            "candidate_id": candidate_id,
            "run_status": row["run_status"],
            "comparison_sha256": result.get("comparison_sha256"),
            "origin_reuse": self._origin(row["origin_reuse"]),
            "observability": "NOT_OBSERVED" if boundaries is None else "RETAINED",
            "total": None if boundaries is None else len(entries),
            "entries": page,
            "next_offset": end if end < len(entries) else None,
            "read_tool": "research_results_boundary_read",
        }

    def boundary_read(
        self,
        task_id: str,
        candidate_id: str,
        boundary_sha256: str,
        start: int = 0,
        max_chars: int = 8000,
    ) -> dict[str, Any]:
        if start < 0 or not 1 <= max_chars <= 32000:
            raise ValueError("start must be nonnegative; max_chars must be 1..32000")
        result, row = self._row(task_id, candidate_id)
        if result.get("schema_version") == "personal-strategy-results/v1":
            source_task, source, boundaries = self._strategy_details(task_id, row)
            ref = next((entry for entry in boundaries if entry["sha256"] == boundary_sha256), None)
            if ref is None:
                raise ValueError("boundary hash is not bound by this candidate receipt")
            directory = (
                self.service.root / "tasks" / source_task / "execution" / source["candidate_id"]
            )
            from quantos.artifacts.store import confined_regular_file

            target_path = confined_regular_file(directory, ref["file"])
            raw = self.service.read_artifact_bytes(target_path.parent, target_path.name)
            if sha256_bytes(raw) != boundary_sha256:
                from quantos.artifacts.store import ArtifactIntegrityError

                raise ArtifactIntegrityError("target trace hash disagrees with receipt")
            content = raw.decode("utf-8")
            end = min(start + max_chars, len(content))
            return {
                "schema_version": "personal-research-boundary-span/v2",
                "detail_kind": "NATIVE_TARGET_TRACE",
                "task_id": task_id,
                "candidate_id": candidate_id,
                "origin": row.get("origin"),
                "source_task_id": source_task,
                "source_candidate_id": source["candidate_id"],
                "source_receipt_sha256": source.get("receipt_sha256"),
                "sha256": boundary_sha256,
                "file": ref["file"],
                "start": start,
                "text": content[start:end],
                "total_chars": len(content),
                "next_start": end if end < len(content) else None,
            }
        boundaries: list[dict[str, Any]] = row.get("boundary_receipts") or []
        ref = next(
            (entry for entry in boundaries if entry["sha256"] == boundary_sha256),
            None,
        )
        if ref is None:
            raise ValueError("boundary hash is not bound by this candidate receipt")
        origin = row["origin_reuse"]
        if origin is None:
            directory = self.service.root / "tasks" / task_id / "execution" / candidate_id
        else:
            from quantos.artifacts.store import confined_regular_file

            directory = confined_regular_file(
                Path(origin["origin_root"]), origin["receipt"]["path"]
            ).parent
        from quantos.artifacts.store import confined_regular_file

        boundary_path = confined_regular_file(directory, ref["file"])
        raw = self.service.read_artifact_bytes(boundary_path.parent, boundary_path.name)
        if sha256_bytes(raw) != boundary_sha256:
            from quantos.artifacts.store import ArtifactIntegrityError

            raise ArtifactIntegrityError("boundary hash disagrees with receipt")
        content = raw.decode("utf-8")
        end = min(start + max_chars, len(content))
        return {
            "schema_version": "personal-research-boundary-span/v1",
            "task_id": task_id,
            "candidate_id": candidate_id,
            "sha256": boundary_sha256,
            "file": ref["file"],
            "start": start,
            "text": content[start:end],
            "total_chars": len(content),
            "next_start": end if end < len(content) else None,
        }
