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
from quantos.contracts.hs300_lifecycle import (
    HS300LifecycleDatasetManifest,
    HS300LifecycleStudyRequest,
    PreparedHS300LifecycleStudy,
)
from quantos.contracts.personal_research import (
    HS300DatasetManifest,
    HS300StudyRequest,
    PersonalCandidate,
    PersonalDatasetManifest,
    PersonalStudyRequest,
    PersonalStudyRequestV2,
    PersonalTaskEvent,
    PreparedHS300Study,
    PreparedStudy,
)


@dataclass(frozen=True)
class PersonalDatasetBinding:
    """Trusted catalog binding: no filesystem paths are accepted through tool requests."""

    manifest: PersonalDatasetManifest | HS300DatasetManifest | HS300LifecycleDatasetManifest
    provider_root: Path
    panel_path: Path
    pit_evidence_path: Path | None = None
    snapshot_path: Path | None = None
    lifecycle_path: Path | None = None


Prepared = PreparedStudy | PreparedHS300Study | PreparedHS300LifecycleStudy
Authorizer = Callable[[Prepared], str | None]
Executor = Callable[[Prepared, Path, Callable[[], bool]], dict[str, Any]]


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
        data_blockers: tuple[str, ...] = (),
        execution_authorizer: Authorizer | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.root = root.absolute()
        self.repo_root = repo_root.absolute()
        self.catalog = dict(catalog or {})
        self.data_blockers = data_blockers
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

    def _code_hash(self, *, hs300: bool = False, lifecycle: bool = False) -> str:
        manifest = self.dependency_manifest()
        if hs300:
            sources = cast(dict[str, str], manifest["sources"])
            for name in (
                "src/quantos/research/hs300_data.py",
                "src/quantos/application/personal_server_config.py",
                "src/quantos/application/hs300_worker.py",
                "src/quantos/infrastructure/hosted_storage.py",
                "src/quantos/infrastructure/hosted_deployment.py",
                "src/quantos/infrastructure/hosted_regression_runtime.py",
                "src/quantos/research/hs300_exchange.py",
                "scripts/run_hs300_study.py",
            ):
                sources[name] = sha256_bytes((self.repo_root / name).read_bytes())
            import sys
            from importlib.metadata import distribution

            native = distribution("pyqlib")
            for name in (
                "qlib/backtest/report.py",
                "qlib/backtest/high_performance_ds.py",
                "qlib/backtest/utils.py",
                "qlib/strategy/base.py",
            ):
                sources[name] = sha256_bytes(Path(str(native.locate_file(name))).read_bytes())

            for executable in ("/usr/bin/bwrap", "/usr/bin/timeout", sys.executable):
                sources["executable:" + executable] = sha256_bytes(Path(executable).read_bytes())
        if lifecycle:
            sources = cast(dict[str, str], manifest["sources"])
            for name in (
                "src/quantos/contracts/hs300_lifecycle.py",
                "src/quantos/research/hs300_lifecycle_data.py",
                "src/quantos/research/hs300_native_boundary.py",
                "src/quantos/data/lifecycle_sources.py",
            ):
                sources[name] = sha256_bytes((self.repo_root / name).read_bytes())
            from importlib.metadata import distribution, version

            native = distribution("pyqlib")
            name = "qlib/backtest/decision.py"
            sources[name] = sha256_bytes(Path(str(native.locate_file(name))).read_bytes())
            cast(dict[str, str], manifest["environment"])["pypdf"] = version("pypdf")
        return sha256_bytes(canonical_json_bytes(manifest))

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": "personal-research-capabilities/v1",
            "proposal_origin": "host-session-proposal/v2",
            "retained_proposal_origins": ["host-session-proposal/v1"],
            "authenticated_model_identity": False,
            "profile": "hs300-daily-trend-tushare-lifecycle/v1",
            "retained_profiles": ["hs300-daily-trend-tushare/v1", "daily-mainboard-trend/v1"],
            "lifecycle_policy": {
                "static_readiness": "verified source/date/coverage, never presumed zero exposure",
                "native_event_boundary": "hard stop exposed arm; retain all seven candidates",
                "unknown_event_state": "hard stop; never infer zero exposure",
                "cash_settlement_accounting": "native unsupported events are not synthesized",
            },
            "tools": [
                "capabilities",
                "history",
                "data_describe",
                "prepare",
                "status",
                "execute",
                "cancel",
                "results",
                "simulation_prepare",
            ],
            "datasets": [b.manifest.model_dump(mode="json") for b in self.catalog.values()],
            "data_blockers": self.data_blockers,
            "execution_authorization_configured": self._authorizer is not None,
            "execution_mode": "synchronous_single_worker_no_automatic_unknown_retry",
            "real_market_execution_default": "DENIED",
            "announcements": "auxiliary_analysis_only_not_historical_trading_features",
            "simulation": "prepare_only_native_account_continuation_not_qualified",
        }

    def data_describe(self, dataset_id: str | None = None) -> dict[str, Any]:
        """Describe only trusted catalog entries, never admit client-supplied paths."""
        if dataset_id is not None and dataset_id not in self.catalog:
            raise ValueError("dataset_id is not registered by this server")
        bindings = (
            [self.catalog[dataset_id]] if dataset_id is not None else list(self.catalog.values())
        )
        return {
            "schema_version": "personal-data-description/v2",
            "datasets": [binding.manifest.model_dump(mode="json") for binding in bindings],
            "data_blockers": self.data_blockers,
            "admission": "SERVER_BOUND_IMMUTABLE_MANIFESTS_ONLY",
            "market_source": "Tushare Pro; snapshot acquisition only; all research offline",
            "membership": (
                "conservative historical intervals, not official exact daily effective dates"
            ),
            "lifecycle": {
                "structural_classification": "not a predictive stock-selection signal",
                "source_policy": "immutable actual source hashes; no retrospective vintage claim",
                "execution_boundary": "native account exposure checked at event boundaries",
                "zero_exposure": "only an observed native boundary result, never a pre-run fact",
                "unsupported_or_unknown_exposure": "stop arm; retain all seven candidates",
            },
            "vendor_vintage_claim": False,
            "company_information": {
                "source": "Tushare actual returned entitled fields only",
                "announcement_entitlement": "UNKNOWN",
                "historical_feature_admission": "NOT_ADMITTED",
                "external_pdf_download": "DISABLED",
                "old_local_materials": "retained auxiliary evidence; not relabelled Tushare",
            },
        }

    def _prepare_hs300(
        self, request: Mapping[str, object], *, lifecycle: bool = False
    ) -> dict[str, Any]:
        request_type = HS300LifecycleStudyRequest if lifecycle else HS300StudyRequest
        proposed = request_type.model_validate(dict(request))
        binding = self.catalog.get(proposed.dataset_id or "")
        manifest = binding.manifest if binding else None
        gaps: list[str] = []
        manifest_type = HS300LifecycleDatasetManifest if lifecycle else HS300DatasetManifest
        if manifest is not None and type(manifest) is not manifest_type:
            raise ValueError("HS300 request and immutable dataset successor versions disagree")
        if manifest is None:
            gaps.append("No server-bound immutable HS300/Tushare dataset for this request")
            gaps.extend(self.data_blockers)
        else:
            from quantos.research.hs300_data import verify_hs300_binding
            from quantos.research.hs300_lifecycle_data import verify_hs300_lifecycle_binding

            assert binding is not None
            try:
                if lifecycle:
                    verify_hs300_lifecycle_binding(binding)
                else:
                    verify_hs300_binding(binding)
            except (ValueError, OSError, ArtifactIntegrityError) as error:
                gaps.append("HS300 binding verification failed: " + type(error).__name__)
            if proposed.warmup_start != manifest.warmup_start:
                gaps.append("Requested warmup differs from the immutable dataset warmup")
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
                    "As-of historical HS300, benchmark close>SMA20, complete stock history, "
                    "non-ST and unsuspended; adjusted close>SMA20, positive 5-session return, "
                    "amount_cny/prior-5-session-mean>=1.2; "
                    "rank momentum descending/code ascending. "
                    "Daily top10, 0.09 target each, next actual session open; remove when "
                    "ineligible/displaced, no fixed holding ceiling; native fills only."
                ),
            ),
            PersonalCandidate(
                candidate_id="classic",
                role="classic",
                rule=(
                    "Same historical HS300, benchmark regime, costs, schedule and targets; "
                    "adjusted close>SMA20, rank close/SMA20-1; no amount or positive5 screen."
                ),
            ),
            *(
                PersonalCandidate(
                    candidate_id=f"random-{seed}",
                    role="random",
                    seed=seed,
                    rule=(
                        "Same main eligibility, schedule, weights, fees and exit rule; "
                        "SHA256(seed,signal_date,instrument) rank. "
                        "Conditional selection comparator; "
                        "realized holdings/exits/exposure differ; "
                        "no significance claim from five seeds."
                    ),
                )
                for seed in (17, 41, 73, 101, 137)
            ),
        )
        prepared_type = PreparedHS300LifecycleStudy if lifecycle else PreparedHS300Study
        prepared = prepared_type.model_validate(
            dict(
                request=proposed,
                dataset_manifest=manifest,
                code_hash=self._code_hash(hs300=True, lifecycle=lifecycle),
                candidates=candidates,
                readiness="BLOCKED" if gaps else "READY_FOR_AUTHORIZATION",
                gaps=tuple(gaps),
                rationale=(
                    "Explicit daily HS300/Tushare successor: "
                    "price trend and turnover amount confirmation; "
                    "all index boards included under conservative "
                    "historical membership availability. "
                    "No THS or mainboard intersection. Company information is auxiliary only."
                ),
                comparison_scope=(
                    "1 main + 1 classic + seeds 17/41/73/101/137; no training/retry/revision"
                ),
                limits=(
                    "Retrospective exploration; scientific NOT_EVALUATED",
                    (
                        "Historical non-vintage; monthly membership "
                        "is not an exact official daily event"
                    ),
                    "Fixed all-in fee scenario, not reconstructed historical taxes/broker slippage",
                    "Uniform 200-share research lot; native limits/liquidity; scenario fills",
                    "Native ST blocks buys and sells; an existing ST holding can remain blocked",
                    (
                        "Native target-order prechecks can block both directions on either daily "
                        "limit, including the prior signal-session check"
                    ),
                    (
                        "Full-session execution-day volume caps open-price fills retrospectively; "
                        "no opening-auction liquidity guarantee"
                    ),
                    "Announcement entitlement UNKNOWN; titles/links cannot prove no adverse news",
                    "No collection, external PDF, research SDK, broker or forward execution",
                ),
            )
        )
        if lifecycle:
            prepared = prepared.model_copy(
                update={
                    "rationale": prepared.rationale
                    + (
                        " Lifecycle facts are structural classifications, not predictive features. "
                        "Verified source coverage permits preparation; "
                        "native event exposure remains "
                        "unobserved until execution. "
                        "Exposed/unknown unsupported events stop that arm."
                    ),
                    "limits": (
                        *prepared.limits,
                        "No pre-run zero-exposure claim; native boundary observation required",
                        "Unsupported or unknown native lifecycle exposure hard-stops the arm",
                        "Stopped/failed arms and all seven candidates remain in the denominator",
                        "No custom settlement, delisting liquidation or account reconstruction",
                    ),
                }
            )
        return self._persist_prepared(prepared)

    def prepare(self, request: Mapping[str, object]) -> dict[str, Any]:
        from quantos.security.artifact_secrets import validate_secret_free

        validate_secret_free(dict(request), file_name="personal-study-request.json")
        if request.get("schema_version") == "personal-study-request/v4":
            return self._prepare_hs300(request, lifecycle=True)
        if request.get("schema_version") == "personal-study-request/v3":
            return self._prepare_hs300(request)
        request_type = (
            PersonalStudyRequest
            if request.get("schema_version") == "personal-study-request/v1"
            else PersonalStudyRequestV2
        )
        proposed = request_type.model_validate(dict(request))
        binding = self.catalog.get(proposed.dataset_id or "")
        gaps: list[str] = []
        manifest = binding.manifest if binding else None
        if manifest is not None and not isinstance(manifest, PersonalDatasetManifest):
            raise ValueError("HS300 datasets require personal-study-request/v3")
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
        return self._persist_prepared(prepared)

    def _persist_prepared(self, prepared: Prepared) -> dict[str, Any]:
        proposed = prepared.request
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

    def _prepared(self, task_id: str) -> Prepared:
        import json

        task_id = _identity(task_id)
        raw = self._read(self.root / "tasks" / task_id, "prepared.json")
        schema = json.loads(raw).get("schema_version")
        contract = (
            PreparedHS300LifecycleStudy
            if schema == "personal-study-prepared/v3"
            else PreparedHS300Study
            if schema == "personal-study-prepared/v2"
            else PreparedStudy
        )
        item = contract.model_validate_json(raw)
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
                if prepared.code_hash != self._code_hash(
                    hs300=isinstance(prepared, (PreparedHS300Study, PreparedHS300LifecycleStudy)),
                    lifecycle=isinstance(prepared, PreparedHS300LifecycleStudy),
                ):
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

    def worker_state(self, task_id: str) -> str:
        """Read the verified ledger without reconciling a host PID in a child namespace.

        The parent service alone owns liveness reconciliation and state writes.
        A supervised PID namespace cannot observe the parent's host process ID.
        """
        self._prepared(task_id)
        return self._events(task_id)[-1].state

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
        comparison: dict[str, Any] | None = None
        comparison_hash: str | None = None
        if outcome_hash is not None:
            from quantos.artifacts.store import verify_file

            outcome_bytes = self._read(execution, "outcome.json")
            if sha256_bytes(outcome_bytes) != outcome_hash:
                raise ArtifactIntegrityError("terminal outcome hash disagrees")
            outcome = json.loads(outcome_bytes)
            if outcome.get("prepared_hash") != prepared.content_hash:
                raise ArtifactIntegrityError("outcome prepared identity disagrees")
            if isinstance(prepared, (PreparedHS300Study, PreparedHS300LifecycleStudy)):
                comparison_hash = outcome.get("comparison_sha256")
                if comparison_hash is not None:
                    raw_comparison = self._read(execution, "comparison.json")
                    if sha256_bytes(raw_comparison) != comparison_hash:
                        raise ArtifactIntegrityError("comparison hash disagrees with outcome")
                    comparison = json.loads(raw_comparison)
                    assert comparison is not None
                    if (
                        comparison.get("prepared_hash") != prepared.content_hash
                        or comparison.get("planned_denominator") != len(prepared.candidates)
                        or [row.get("candidate_id") for row in comparison.get("rows", [])]
                        != [candidate.candidate_id for candidate in prepared.candidates]
                    ):
                        raise ArtifactIntegrityError("comparison identity or denominator disagrees")
                elif outcome.get("run_status") == "SUCCEEDED":
                    raise ArtifactIntegrityError("HS300 success has no immutable comparison")
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
                **(
                    {
                        "native_boundary_status": outcomes.get(c.candidate_id, {}).get(
                            "native_boundary_status", "NOT_OBSERVED"
                        ),
                        "boundary_receipts": outcomes.get(c.candidate_id, {}).get(
                            "boundary_receipts"
                        ),
                        "native_rights_observability": outcomes.get(c.candidate_id, {}).get(
                            "native_rights_observability", "NOT_OBSERVED"
                        ),
                        "partial_native_artifacts": outcomes.get(c.candidate_id, {}).get(
                            "partial_native_artifacts"
                        ),
                    }
                    if isinstance(prepared, PreparedHS300LifecycleStudy)
                    else {}
                ),
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
            **(
                {"comparison": comparison, "comparison_sha256": comparison_hash}
                if isinstance(prepared, (PreparedHS300Study, PreparedHS300LifecycleStudy))
                else {}
            ),
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
