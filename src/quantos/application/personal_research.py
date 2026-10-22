"""Persistent local personal-research facade; authorization stays in trusted server code."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_research import (
    PersonalCandidate,
    PersonalDatasetManifest,
    PersonalStudyRequest,
    PersonalStudyRequestV2,
    PersonalTaskEvent,
    PreparedStudy,
)


@dataclass(frozen=True)
class PersonalDatasetBinding:
    """Trusted catalog binding: no filesystem paths are accepted through tool requests."""

    manifest: PersonalDatasetManifest
    provider_root: Path
    panel_path: Path
    pit_evidence_path: Path | None = None


Authorizer = Callable[[PreparedStudy], str | None]
Executor = Callable[[PreparedStudy, Path, Callable[[], bool]], dict[str, Any]]


def _identity(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("task_id must be a SHA-256 identifier")
    return value


def _process_identity(pid: int) -> str | None:
    try:
        # Linux start ticks and boot id prevent pid reuse from claiming ownership.
        ticks = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"{boot}:{pid}:{ticks}"
    except (OSError, IndexError):
        return None


class PersonalResearchService:
    """Thin offline compiler, hash-chained task ledger and one-worker dispatcher.

    Execution is synchronous. A live caller owns it; interrupted work becomes UNKNOWN,
    never automatically reissued. Completed per-candidate receipts remain readable.
    """

    def __init__(
        self,
        root: Path,
        repo_root: Path,
        *,
        catalog: Mapping[str, PersonalDatasetBinding] | None = None,
        execution_authorizer: Authorizer | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.root = root.absolute()
        self.repo_root = repo_root.absolute()
        self.catalog = dict(catalog or {})
        for key, binding in self.catalog.items():
            if key != binding.manifest.dataset_id:
                raise ValueError("dataset catalog identity disagrees")
        self._authorizer = execution_authorizer
        self._executor = executor
        with opened_directory(self.root, create=True):
            pass

    def _write(self, directory: Path, name: str, value: object) -> None:
        with opened_directory(directory, create=True) as fd:
            atomic_write_bytes_at(fd, name, canonical_json_bytes(value))

    def _read(self, directory: Path, name: str) -> bytes:
        with opened_directory(directory) as fd:
            return read_regular_bytes_at(fd, name, max_bytes=4 * 1024 * 1024)

    def dependency_manifest(self) -> dict[str, object]:
        files = (
            "src/quantos/contracts/personal_research.py",
            "src/quantos/application/personal_research.py",
            "src/quantos/research/personal_qlib.py",
            "src/quantos/backtest/strategy.py",
            "src/quantos/research/qlib/workflow.py",
            "src/quantos/artifacts/store.py",
            "src/quantos/contracts/base.py",
            "src/quantos/security/artifact_secrets.py",
        )
        import sys
        from importlib.metadata import distribution, version

        dependencies = {name: sha256_bytes((self.repo_root / name).read_bytes()) for name in files}
        dependencies["uv.lock"] = sha256_bytes((self.repo_root / "uv.lock").read_bytes())
        native = distribution("pyqlib")
        for name in (
            "qlib/backtest/__init__.py",
            "qlib/backtest/backtest.py",
            "qlib/backtest/executor.py",
            "qlib/backtest/exchange.py",
            "qlib/backtest/position.py",
            "qlib/backtest/account.py",
            "qlib/backtest/signal.py",
            "qlib/contrib/strategy/signal_strategy.py",
            "qlib/contrib/strategy/order_generator.py",
            "qlib/workflow/record_temp.py",
        ):
            dependencies[name] = sha256_bytes(Path(str(native.locate_file(name))).read_bytes())
        environment = {
            name: version(name)
            for name in ("pyqlib", "numpy", "pandas", "pyarrow", "pydantic", "mlflow")
        }
        return {"sources": dependencies, "environment": environment, "python": sys.version}

    def _code_hash(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.dependency_manifest()))

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": "personal-research-capabilities/v1",
            "proposal_origin": "host-session-proposal/v2",
            "retained_proposal_origins": ["host-session-proposal/v1"],
            "authenticated_model_identity": False,
            "profile": "daily-mainboard-trend/v1",
            "tools": [
                "capabilities",
                "history",
                "prepare",
                "status",
                "execute",
                "cancel",
                "results",
                "simulation_prepare",
            ],
            "datasets": [b.manifest.model_dump(mode="json") for b in self.catalog.values()],
            "execution_authorization_configured": self._authorizer is not None,
            "execution_mode": "synchronous_single_worker_no_automatic_unknown_retry",
            "real_market_execution_default": "DENIED",
            "announcements": "auxiliary_analysis_only_not_historical_trading_features",
            "simulation": "prepare_only_native_account_continuation_not_qualified",
        }

    def prepare(self, request: Mapping[str, object]) -> dict[str, Any]:
        from quantos.security.artifact_secrets import validate_secret_free

        validate_secret_free(dict(request), file_name="personal-study-request.json")
        request_type = (
            PersonalStudyRequest
            if request.get("schema_version") == "personal-study-request/v1"
            else PersonalStudyRequestV2
        )
        proposed = request_type.model_validate(dict(request))
        binding = self.catalog.get(proposed.dataset_id or "")
        gaps: list[str] = []
        manifest = binding.manifest if binding else None
        if manifest is None:
            gaps.append(
                "No server-bound immutable dataset for the requested full-mainboard/THS scope"
            )
        else:
            if manifest.kind == "market":
                gaps.append(
                    "Real-market successor PIT and date-specific fee adapter is not yet qualified"
                )
            if not manifest.all_mainboard_pit:
                gaps.append(
                    "PIT full-mainboard membership is missing; index constituents cannot substitute"
                )
            if not manifest.ths_historical_membership:
                gaps.append(
                    "THS historical sector membership and availability evidence are missing"
                )
            if not manifest.tradability_verified:
                gaps.append("Date-specific ST, suspension, limit and factor evidence is missing")
            if proposed.benchmark not in manifest.benchmarks:
                gaps.append("Requested benchmark is not bound to the immutable dataset")
            if proposed.start_date is None:
                proposed = proposed.model_copy(
                    update={"start_date": manifest.start_date, "end_date": manifest.end_date}
                )
            assert proposed.start_date is not None and proposed.end_date is not None
            if proposed.start_date < manifest.start_date or proposed.end_date > manifest.end_date:
                gaps.append("Requested evaluation dates exceed the bound data coverage")
        if proposed.end_date is not None and proposed.end_date > date.today():
            gaps.append("Future evaluation dates cannot be backtested")
        candidates = (
            PersonalCandidate(
                candidate_id="main",
                role="main",
                rule=(
                    "After close: PIT non-ST mainboard; close>SMA20, positive 5-session momentum, "
                    "volume/prior-SMA5>=1.2, positive THS sector 5-session "
                    "momentum and market close>SMA20; "
                    "rank by stock momentum + 0.25*sector momentum. Daily "
                    "top-K equal target weights; "
                    "next open rebalance, exit when ineligible or displaced; "
                    "no fixed holding ceiling."
                ),
            ),
            PersonalCandidate(
                candidate_id="classic",
                role="classic",
                rule=(
                    "Same basic PIT universe, market regime, account and costs; close>SMA20, "
                    "rank by close/SMA20-1; daily top-K next-open target replacement."
                ),
            ),
            *(
                PersonalCandidate(
                    candidate_id=f"random-{seed}",
                    role="random",
                    seed=seed,
                    rule=(
                        "Keep main strategy eligibility, schedule, weights, "
                        "exits and fees; replace ranking "
                        "with SHA256(seed,signal_date,instrument). Exit rules"
                        " match; individual holding dates differ. "
                        "This tests stock selection conditional "
                        "on the main eligibility screen, not whole-system superiority."
                    ),
                )
                for seed in (17, 41, 73, 101, 137)
            ),
        )
        prepared = PreparedStudy(
            request=proposed,
            dataset_manifest=manifest,
            code_hash=self._code_hash(),
            candidates=candidates,
            readiness="BLOCKED" if gaps else "READY_FOR_AUTHORIZATION",
            gaps=tuple(gaps),
            rationale=(
                "A finite daily trend proposal matches after-close research "
                "and next-session entry. "
                "20-session trend, 5-session momentum and volume confirmation"
                " are fixed before results; "
                "THS membership remains a required source. The maximum stock weight is applied "
                "before the global risk_degree; target investment cap is risk_degree * "
                "min(1,top_k*max_weight), with residual cash retained. "
                "Intraday rebound/late-volume heuristics "
                "are not reproducible from daily bars. Company announcements "
                "are auxiliary proposals."
            ),
            comparison_scope=(
                "1 main + 1 classic + all 5 fixed seeds; no adaptive retry or revision"
            ),
            limits=(
                "NOT_EVALUATED: no successor scientific qualification policy has been approved",
                "Historical source availability does not prove vendor-vintage PIT",
                (
                    "Fees are fixed scenario assumptions; historical fee-regime "
                    "changes require split packages"
                ),
                "Qlib target-weight limit precheck can conservatively block both trade directions",
                (
                    "No intraday execution, broker connection, automatic "
                    "collection or scheduled worker"
                ),
            ),
        )
        task_id = prepared.content_hash
        with exclusive_directory_lock(self.root):
            index_dir = self.root / "idempotency"
            name = f"{proposed.idempotency_key}.json"
            try:
                import json

                previous = json.loads(self._read(index_dir, name))
            except (FileNotFoundError, ArtifactIntegrityError):
                previous = None
                # An existing unsafe index must fail closed, not be treated as absent.
                if (index_dir / name).exists() or (index_dir / name).is_symlink():
                    raise
            receipt = {"task_id": task_id, "request_hash": proposed.content_hash}
            if previous is not None and previous != receipt:
                raise ValueError("idempotency key is already bound to another prepared study")
            task_dir = self.root / "tasks" / task_id
            self._write(task_dir, "prepared.json", prepared)
            if not (task_dir / "events" / "000001.json").exists():
                self._append(task_id, "PREPARED", {"readiness": prepared.readiness})
            self._write(index_dir, name, receipt)
        return {"task_id": task_id, **prepared.model_dump(mode="json")}

    def _prepared(self, task_id: str) -> PreparedStudy:
        task_id = _identity(task_id)
        item = PreparedStudy.model_validate_json(
            self._read(self.root / "tasks" / task_id, "prepared.json")
        )
        if item.content_hash != task_id:
            raise ArtifactIntegrityError("prepared task hash disagrees")
        return item

    def _events(self, task_id: str) -> list[PersonalTaskEvent]:
        directory = self.root / "tasks" / _identity(task_id) / "events"
        with opened_directory(directory):
            names = sorted(
                item.name for item in directory.iterdir() if not item.name.startswith(".publish-")
            )
        previous: str | None = None
        events: list[PersonalTaskEvent] = []
        for sequence, name in enumerate(names, 1):
            if name != f"{sequence:06d}.json":
                raise ArtifactIntegrityError("task ledger has an unexpected event or sequence gap")
            event = PersonalTaskEvent.model_validate_json(self._read(directory, name))
            if (
                event.task_id != task_id
                or event.sequence != sequence
                or event.previous_event_hash != previous
            ):
                raise ArtifactIntegrityError("task event hash chain disagrees")
            previous = event.content_hash
            events.append(event)
        if not events:
            raise ArtifactIntegrityError("task ledger is empty")
        return events

    def _append(
        self,
        task_id: str,
        state: Literal[
            "PREPARED", "RUNNING", "CANCEL_REQUESTED", "CANCELLED", "SUCCEEDED", "FAILED", "UNKNOWN"
        ],
        detail: dict[str, object],
    ) -> None:
        directory = self.root / "tasks" / task_id / "events"
        events = self._events(task_id) if directory.exists() else []
        event = PersonalTaskEvent(
            task_id=task_id,
            sequence=len(events) + 1,
            previous_event_hash=events[-1].content_hash if events else None,
            state=state,
            at=datetime.now(UTC),
            detail=detail,
        )
        self._write(directory, f"{event.sequence:06d}.json", event)

    def status(self, task_id: str) -> dict[str, Any]:
        prepared = self._prepared(task_id)
        with exclusive_directory_lock(self.root):
            events = self._events(task_id)
            last = events[-1]
            if last.state in {"RUNNING", "CANCEL_REQUESTED"}:
                owner = next(e for e in reversed(events) if e.state == "RUNNING")
                if (
                    _process_identity(int(cast(Any, owner.detail["pid"])))
                    != owner.detail["process_identity"]
                ):
                    self._append(
                        task_id,
                        "UNKNOWN",
                        {
                            "reason": (
                                "Owner process exited without a durable terminal receipt; "
                                "never auto-reissue"
                            ),
                            "validation_verdict": "NOT_EVALUATED",
                        },
                    )
                    events = self._events(task_id)
                    last = events[-1]
        return {
            "task_id": task_id,
            "state": last.state,
            "readiness": prepared.readiness,
            "validation_verdict": "NOT_EVALUATED",
            "event": last.model_dump(mode="json"),
            "event_hashes": [event.content_hash for event in events],
        }

    def history(self, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("history limit must be 1..100")
        directory = self.root / "tasks"
        if not directory.exists():
            return {"tasks": [], "total": 0}
        with opened_directory(directory):
            ids = sorted(p.name for p in directory.iterdir())
        entries: list[dict[str, Any]] = []
        for task_id in ids:
            prepared = self._prepared(task_id)
            entries.append(
                {
                    **self.status(task_id),
                    "brief": prepared.request.brief,
                    "dataset_id": prepared.request.dataset_id,
                }
            )
        entries.sort(key=lambda item: (item["event"]["at"], item["task_id"]), reverse=True)
        return {"tasks": entries[:limit], "total": len(ids)}

    def execute(self, task_id: str) -> dict[str, Any]:
        prepared = self._prepared(task_id)
        # Worker lock and task authority locks are separate: cancellation remains responsive.
        with exclusive_directory_lock(self.root / "worker"):
            with exclusive_directory_lock(self.root):
                last = self._events(task_id)[-1]
                if last.state != "PREPARED":
                    return {
                        "task_id": task_id,
                        "state": last.state,
                        "validation_verdict": "NOT_EVALUATED",
                        "idempotent_reuse": True,
                    }
                if prepared.readiness != "READY_FOR_AUTHORIZATION":
                    self._append(task_id, "PREPARED", {"execution_denied": "blocked_inputs"})
                    raise PermissionError("study is blocked: " + "; ".join(prepared.gaps))
                if prepared.code_hash != self._code_hash():
                    self._append(task_id, "PREPARED", {"execution_denied": "changed_dependencies"})
                    raise PermissionError(
                        "execution dependencies changed; prepare a successor package"
                    )
                receipt = self._authorizer(prepared) if self._authorizer else None
                if not isinstance(receipt, str) or not receipt.strip():
                    self._append(
                        task_id, "PREPARED", {"execution_denied": "no_server_authorization"}
                    )
                    raise PermissionError(
                        "no trusted server-side authorization bound to this prepared study"
                    )
                process_identity = _process_identity(os.getpid())
                if process_identity is None:
                    raise RuntimeError("cannot establish local execution process identity")
                self._append(
                    task_id,
                    "RUNNING",
                    {
                        "pid": os.getpid(),
                        "process_identity": process_identity,
                        "authorization_receipt_hash": sha256_bytes(receipt.encode()),
                    },
                )
            output_root = self.root / "tasks" / task_id / "execution"
            with opened_directory(output_root, create=True):
                pass
            try:
                executor = self._executor
                if executor is None:
                    from quantos.research.personal_qlib import PersonalQlibExecutor

                    executor = PersonalQlibExecutor(self.catalog)
                outcome = executor(prepared, output_root, lambda: self._cancel_requested(task_id))
                # Canonicalization rejects NaN/Infinity instead of silently zero filling.
                canonical_json_bytes(outcome)
                if outcome.get("prepared_hash") != prepared.content_hash:
                    raise ArtifactIntegrityError("executor outcome is not bound to prepared study")
                entries = outcome.get("receipts", [])
                if outcome.get("run_status") == "SUCCEEDED" and (
                    len(entries) != len(prepared.candidates)
                    or any(entry.get("run_status") != "SUCCEEDED" for entry in entries)
                ):
                    raise ArtifactIntegrityError("successful outcome omits predeclared candidates")
                with exclusive_directory_lock(self.root):
                    self._write(output_root, "outcome.json", outcome)
                    cancelled = self._cancel_requested(task_id)
                    state = (
                        "CANCELLED"
                        if cancelled
                        else ("SUCCEEDED" if outcome.get("run_status") == "SUCCEEDED" else "FAILED")
                    )
                    self._append(
                        task_id,
                        state,
                        {
                            "outcome_hash": sha256_bytes(canonical_json_bytes(outcome)),
                            "validation_verdict": "NOT_EVALUATED",
                        },
                    )
            except Exception as error:
                with exclusive_directory_lock(self.root):
                    self._append(
                        task_id,
                        "FAILED",
                        {
                            "reason": getattr(error, "reason_code", "execution_error"),
                            "error_type": type(error).__name__,
                            "validation_verdict": "NOT_EVALUATED",
                        },
                    )
                # Never persist arbitrary exception messages or local secrets.
            return self.status(task_id)

    def _cancel_requested(self, task_id: str) -> bool:
        return self._events(task_id)[-1].state == "CANCEL_REQUESTED"

    def cancel(self, task_id: str) -> dict[str, Any]:
        self._prepared(task_id)
        with exclusive_directory_lock(self.root):
            last = self._events(task_id)[-1]
            if last.state == "PREPARED":
                self._append(task_id, "CANCELLED", {"reason": "cancelled_before_execution"})
            elif last.state == "RUNNING":
                self._append(
                    task_id,
                    "CANCEL_REQUESTED",
                    {"reason": "cooperative_stop_at_next_candidate_boundary_no_forced_kill"},
                )
        return self.status(task_id)

    def results(self, task_id: str) -> dict[str, Any]:
        import json

        prepared = self._prepared(task_id)
        current = self.status(task_id)
        execution = self.root / "tasks" / task_id / "execution"
        outcomes: dict[str, Any] = {}
        terminal = self._events(task_id)[-1]
        outcome_hash = terminal.detail.get("outcome_hash")
        committed_receipts: dict[str, str] | None = None
        if outcome_hash is not None:
            from quantos.artifacts.store import verify_file

            outcome_bytes = self._read(execution, "outcome.json")
            if sha256_bytes(outcome_bytes) != outcome_hash:
                raise ArtifactIntegrityError("terminal outcome hash disagrees")
            outcome = json.loads(outcome_bytes)
            if outcome.get("prepared_hash") != prepared.content_hash:
                raise ArtifactIntegrityError("outcome prepared identity disagrees")
            committed_receipts = {}
            for entry in outcome.get("receipts", []):
                candidate_id = entry["candidate_id"]
                if candidate_id in committed_receipts or candidate_id not in {
                    candidate.candidate_id for candidate in prepared.candidates
                }:
                    raise ArtifactIntegrityError("outcome receipt denominator disagrees")
                committed_receipts[candidate_id] = entry["receipt_hash"]
        elif terminal.state == "SUCCEEDED":
            raise ArtifactIntegrityError("success has no committed immutable outcome")
        for candidate in prepared.candidates:
            directory = execution / candidate.candidate_id
            if not directory.exists():
                if committed_receipts is not None and candidate.candidate_id in committed_receipts:
                    raise ArtifactIntegrityError("committed candidate receipt is missing")
                continue
            try:
                receipt_bytes = self._read(directory, "receipt.json")
                if committed_receipts is not None and committed_receipts.get(
                    candidate.candidate_id
                ) != sha256_bytes(receipt_bytes):
                    raise ArtifactIntegrityError(
                        "candidate receipt does not match committed outcome"
                    )
                item = json.loads(receipt_bytes)
            except (FileNotFoundError, ArtifactIntegrityError):
                if (
                    (
                        committed_receipts is not None
                        and candidate.candidate_id in committed_receipts
                    )
                    or (directory / "receipt.json").exists()
                    or (directory / "receipt.json").is_symlink()
                ):
                    raise
                continue
            if (
                item.get("candidate_id") != candidate.candidate_id
                or item.get("prepared_hash") != prepared.content_hash
            ):
                raise ArtifactIntegrityError("candidate receipt identity disagrees")
            from quantos.artifacts.store import confined_regular_file, verify_file

            for logical, digest in item.get("files", {}).items():
                verify_file(confined_regular_file(directory, logical), digest)
            outcomes[candidate.candidate_id] = item
        rows = [
            {
                "candidate_id": c.candidate_id,
                "role": c.role,
                "seed": c.seed,
                "run_status": outcomes.get(c.candidate_id, {}).get("run_status", "NOT_RUN"),
                "metrics": outcomes.get(c.candidate_id, {}).get("metrics"),
                "evidence_status": "VERIFIED_COMMITTED"
                if committed_receipts is not None and c.candidate_id in committed_receipts
                else ("UNCOMMITTED_RECEIPT" if c.candidate_id in outcomes else "MISSING"),
                "validation_verdict": "NOT_EVALUATED",
            }
            for c in prepared.candidates
        ]
        return {
            **current,
            "evidence_kind": prepared.dataset_manifest.kind
            if prepared.dataset_manifest
            else "none",
            "planned_denominator": len(rows),
            "succeeded_denominator": sum(row["run_status"] == "SUCCEEDED" for row in rows),
            "rows": rows,
            "comparison_scope": prepared.comparison_scope,
            "interpretation": (
                "Missing/failed results are absent, never zero; all predeclared candidates retained"
            ),
            "limits": list(prepared.limits),
        }

    def simulation_prepare(self, task_id: str) -> dict[str, Any]:
        prepared = self._prepared(task_id)
        return {
            "task_id": task_id,
            "strategy_hash": prepared.request.profile.content_hash,
            "state": "NOT_STARTED",
            "mode": "conditional_native_qlib_simulation",
            "gaps": [
                "Separate finite forward-data acquisition/execution authorization required",
                (
                    "Qlib 0.9.7 account=dict seeds holdings but first-day return "
                    "uses init_cash, not total NAV"
                ),
                (
                    "Executor.reset_common_infra resets Account report; complete "
                    "Account continuation is not qualified"
                ),
                (
                    "Native Qlib Position checkpoint/resume across newly arriving"
                    " immutable views is not qualified"
                ),
            ],
            "native_artifacts": (
                "Completed historical engineering runs export Qlib positions; "
                "replay is not forward simulation"
            ),
            "authorization_inherited": False,
        }
