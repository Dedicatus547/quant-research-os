"""Deterministic P14c campaign accounting, selection, and artifact verification."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from struct import unpack
from typing import cast
from uuid import UUID

from pydantic import ValidationError

from quantos.application.campaigns import (
    CampaignChainEvent,
    CampaignGovernanceError,
    ResearchCampaignGovernor,
)
from quantos.application.enumeration import (
    CandidateEnumerationError,
    verify_candidate_enumeration_manifest,
)
from quantos.artifacts.store import (
    ArtifactError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    CampaignEventType,
    CampaignSegment,
    CampaignTrial,
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    TrialOutcome,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    CampaignSelectionEventType,
    CampaignSelectionPlan,
    CampaignSelectionReport,
    CampaignSelectionVerdict,
    CampaignTrialEvidenceBinding,
    CandidateDispositionKind,
    CandidateSelectionDisposition,
    CandidateSelectionScore,
    MultipleTestingPolicySpec,
    SelectionCalendar,
    SelectionPolicySpec,
)
from quantos.contracts.enumeration import (
    CandidateDuplicateKind,
    CandidateEnumerationManifest,
    ResearchCandidateSpec,
    ResearchFactorTemplateSpec,
)
from quantos.contracts.research import (
    ResearchPolicy,
    ResolvedExperimentSpec,
)
from quantos.contracts.research_result import (
    ResearchResultManifest,
    ResearchResultSeriesRow,
)
from quantos.contracts.status import ReasonCode, RunStatus
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view
from quantos.research.qlib.result import verify_research_result
from quantos.research.qlib.universe import QlibResearchError

SELECTION_LIMITATIONS = (
    "CIRCULAR_BLOCK_BOOTSTRAP_APPROXIMATE_STATIONARITY",
    "HOLM_CONTROL_REQUIRES_VALID_CONSTITUENT_P_VALUES",
    "NO_VENDOR_VINTAGE_PIT_CLAIM",
    "UNDECLARED_ADAPTIVE_VALIDATION_REUSE_NOT_PREVENTED",
)


class CampaignSelectionError(RuntimeError):
    """A fail-closed P14c input, execution, publication, or verification error."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _SelectionFailure:
    reason_code: ReasonCode
    message: str


@dataclass(frozen=True)
class _VerifiedResult:
    manifest: ResearchResultManifest
    resolved: ResolvedExperimentSpec
    research_policy: ResearchPolicy
    rank_ic: tuple[ResearchResultSeriesRow, ...]


@dataclass(frozen=True)
class _CandidateLedger:
    candidate: ResearchCandidateSpec
    trial_events: tuple[ResearchCampaignEvent, ...]
    validation_events: tuple[ResearchCampaignEvent, ...]
    disposition: CandidateSelectionDisposition
    result_hash: str | None
    verified_result: _VerifiedResult | None


def _report_from_payload(**values: object) -> CampaignSelectionReport:
    full_payload = {"schema_version": "campaign-selection-report/v1", **values}
    digest = sha256_bytes(canonical_json_bytes(full_payload))
    return CampaignSelectionReport.model_validate({"report_hash": digest, **values})


def _derive_calendar(campaign: ResearchCampaignSpec, view_path: Path) -> SelectionCalendar:
    try:
        view = verify_qlib_view(view_path)
        if (
            view.view_hash != campaign.qlib_view_hash
            or view.source_snapshot_hash != campaign.snapshot_hash
        ):
            raise CampaignSelectionError(
                ReasonCode.SNAPSHOT_HASH_MISMATCH,
                "verified Qlib view differs from the frozen campaign inputs",
            )
        manifest_paths = {item.logical_path for item in view.files}
        if "calendars/day.txt" not in manifest_paths:
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "verified Qlib view does not contain calendars/day.txt",
            )
        raw_dates = (view_path / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
        dates = tuple(date.fromisoformat(line.strip()) for line in raw_dates if line.strip())
    except CampaignSelectionError:
        raise
    except QlibViewBuildError as error:
        raise CampaignSelectionError(error.reason_code, str(error)) from error
    except (OSError, ValueError, UnicodeDecodeError) as error:
        raise CampaignSelectionError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "verified Qlib trading calendar cannot be parsed",
        ) from error
    if not dates or dates != tuple(sorted(set(dates))):
        raise CampaignSelectionError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "Qlib trading calendar must be nonempty, ordered, and unique",
        )
    validation_dates = tuple(
        item for item in dates if campaign.validation.start <= item <= campaign.validation.end
    )
    try:
        return SelectionCalendar(
            qlib_view_hash=view.view_hash,
            start=campaign.validation.start,
            end=campaign.validation.end,
            trading_dates=validation_dates,
        )
    except ValidationError as error:
        raise CampaignSelectionError(
            ReasonCode.SOURCE_INCOMPLETE,
            "validation period has no dates in the verified Qlib calendar",
        ) from error


def _exact_duplicate_hashes(manifest: CandidateEnumerationManifest) -> frozenset[str]:
    hashes: set[str] = set()
    for evidence in manifest.duplicate_evidence:
        if evidence.kind is CandidateDuplicateKind.EXACT:
            hashes.update(evidence.duplicate_candidate_hashes)
    return frozenset(hashes)


class _CounterStream:
    """SHA256 counter stream with unsigned 64-bit rejection sampling."""

    def __init__(self, seed_hash: str, candidate_hash: str) -> None:
        key_material = bytes.fromhex(seed_hash) + bytes.fromhex(candidate_hash)
        self._key = hashlib.sha256(key_material).digest()
        self._counter = 0
        self._words: tuple[int, ...] = ()
        self._position = 0

    def draw_index(self, size: int) -> int:
        if size <= 0:
            raise ValueError("draw size must be positive")
        ceiling = ((1 << 64) // size) * size
        while True:
            if self._position == len(self._words):
                digest = hashlib.sha256(self._key + self._counter.to_bytes(8, "big")).digest()
                self._counter += 1
                self._words = cast(tuple[int, ...], unpack(">QQQQ", digest))
                self._position = 0
            value = self._words[self._position]
            self._position += 1
            if value < ceiling:
                return value % size


def _bootstrap_exceedances(
    oriented_values: tuple[float, ...], policy: MultipleTestingPolicySpec, candidate_hash: str
) -> tuple[float, int]:
    count = len(oriented_values)
    mean = math.fsum(oriented_values) / count
    centered = tuple(value - mean for value in oriented_values)
    stream = _CounterStream(policy.seed, candidate_hash)
    exceedances = 0
    for _ in range(policy.bootstrap_replicates):
        sample: list[float] = []
        while len(sample) < count:
            start = stream.draw_index(count)
            take = min(policy.block_length, count - len(sample))
            sample.extend(centered[(start + offset) % count] for offset in range(take))
        bootstrap_mean = math.fsum(sample) / count
        if bootstrap_mean >= mean:
            exceedances += 1
    return mean, exceedances


def _pvalue_numerator(exceedances: int) -> int:
    return 1 + exceedances


class CampaignSelectionService:
    """Rebuild a P14c verdict only from frozen campaign and Qlib artifacts."""

    def __init__(
        self,
        campaign: ResearchCampaignSpec,
        family: ResearchFamilySpec,
        budget: ResearchBudgetSpec,
        template: ResearchFactorTemplateSpec,
        manifest: CandidateEnumerationManifest,
        multiple_testing_policy: MultipleTestingPolicySpec,
        selection_policy: SelectionPolicySpec,
        qlib_view_path: Path,
        research_results_roots: Iterable[Path] = (),
        *,
        plan: CampaignSelectionPlan | None = None,
    ) -> None:
        self.campaign = campaign
        self.family = family
        self.budget = budget
        self.template = template
        self.manifest = manifest
        self.multiple_testing_policy = multiple_testing_policy
        self.selection_policy = selection_policy
        self.qlib_view_path = qlib_view_path
        self.research_results_roots = tuple(research_results_roots)
        self._input_failure: _SelectionFailure | None = None
        self.calendar: SelectionCalendar | None = None
        try:
            self.calendar = _derive_calendar(campaign, qlib_view_path)
        except CampaignSelectionError as error:
            self._input_failure = _SelectionFailure(error.reason_code, str(error))
        if plan is not None:
            self.plan = plan
        elif self.calendar is not None:
            self.plan = self._make_plan(self.calendar)
        else:
            self.plan = None
        try:
            verify_candidate_enumeration_manifest(family, template, manifest)
        except CandidateEnumerationError as error:
            self._record_failure(error.reason_code, str(error))
        if campaign.family_hash != family.content_hash:
            self._record_failure(
                ReasonCode.ARTIFACT_CORRUPTED, "campaign does not bind the supplied family"
            )
        if campaign.budget_hash != budget.content_hash:
            self._record_failure(
                ReasonCode.ARTIFACT_CORRUPTED, "campaign does not bind the supplied budget"
            )
        if campaign.multiple_testing_policy.value != "PREFROZEN_FINITE_FAMILY":
            self._record_failure(
                ReasonCode.SCHEMA_INVALID,
                "campaign policy is not PREFROZEN_FINITE_FAMILY",
            )
        if selection_policy.multiple_testing_policy_hash != multiple_testing_policy.content_hash:
            self._record_failure(
                ReasonCode.ARTIFACT_CORRUPTED,
                "selection policy does not bind the multiple-testing policy",
            )
        if self.plan is not None:
            expected = self._make_plan(self.calendar) if self.calendar is not None else None
            if expected is not None and expected != self.plan:
                self._record_failure(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "frozen selection plan differs from its supplied inputs",
                )

    def _record_failure(self, reason_code: ReasonCode, message: str) -> None:
        if self._input_failure is None:
            self._input_failure = _SelectionFailure(reason_code, message)

    def _make_plan(self, calendar: SelectionCalendar) -> CampaignSelectionPlan:
        return CampaignSelectionPlan(
            campaign_hash=self.campaign.content_hash,
            family_hash=self.family.content_hash,
            budget_hash=self.budget.content_hash,
            candidate_manifest_hash=self.manifest.content_hash,
            multiple_testing_policy_hash=self.multiple_testing_policy.content_hash,
            selection_policy_hash=self.selection_policy.content_hash,
            validation_calendar_hash=calendar.content_hash,
        )

    def build_plan(self) -> CampaignSelectionPlan:
        if self._input_failure is not None:
            raise CampaignSelectionError(
                self._input_failure.reason_code, self._input_failure.message
            )
        if self.calendar is None:
            failure = self._input_failure
            raise CampaignSelectionError(
                failure.reason_code if failure is not None else ReasonCode.SOURCE_INCOMPLETE,
                failure.message
                if failure is not None
                else "verified validation calendar is missing",
            )
        return self._make_plan(self.calendar)

    def freeze_plan(
        self,
        governor: ResearchCampaignGovernor,
        events: tuple[CampaignChainEvent, ...],
        *,
        event_id: UUID,
        occurred_at: datetime,
        artifact_root: Path,
    ) -> tuple[CampaignSelectionEvent, Path]:
        plan = self.build_plan()
        path = publish_selection_plan(plan, artifact_root)
        event = governor._freeze_verified_plan(  # pyright: ignore[reportPrivateUsage]
            self.campaign,
            self.family,
            self.budget,
            self.manifest,
            events,
            plan,
            event_id=event_id,
            occurred_at=occurred_at,
        )
        return event, path

    def build_report(self, events: tuple[CampaignChainEvent, ...]) -> CampaignSelectionReport:
        if self.plan is None:
            raise CampaignSelectionError(
                ReasonCode.SOURCE_INCOMPLETE,
                "a selection plan must be supplied or derived from a verified Qlib calendar",
            )
        if not events:
            raise CampaignSelectionError(ReasonCode.EVENT_CHAIN_INVALID, "event prefix is empty")

        source_hashes = tuple(event.content_hash for event in events)
        trial_events = tuple(
            event
            for event in events
            if isinstance(event, ResearchCampaignEvent)
            and event.event_type is CampaignEventType.TRIAL_RECORDED
        )
        linked_result_hashes: dict[str, tuple[str, ...]] = {}
        try:
            strict_reason = self._validate_prefix(events)
        except CampaignSelectionError as error:
            strict_reason = _SelectionFailure(error.reason_code, str(error))
        if strict_reason is None:
            try:
                refreshed_calendar = _derive_calendar(self.campaign, self.qlib_view_path)
                if refreshed_calendar != self.calendar:
                    strict_reason = _SelectionFailure(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "Qlib validation calendar changed after plan derivation",
                    )
            except CampaignSelectionError as error:
                strict_reason = _SelectionFailure(error.reason_code, str(error))
        if self._input_failure is not None:
            strict_reason = strict_reason or self._input_failure

        candidates = tuple(sorted(self.manifest.candidates, key=lambda item: item.content_hash))
        events_by_candidate: dict[str, list[ResearchCampaignEvent]] = {
            item.content_hash: [] for item in candidates
        }
        unknown_candidate = False
        for event in trial_events:
            if event.trial is None or event.trial.candidate_hash not in events_by_candidate:
                unknown_candidate = True
                continue
            events_by_candidate[event.trial.candidate_hash].append(event)
        if unknown_candidate:
            strict_reason = strict_reason or _SelectionFailure(
                ReasonCode.ARTIFACT_CORRUPTED,
                "trial event refers to a candidate outside the enumerated manifest",
            )

        candidates_by_hash = {item.content_hash: item for item in candidates}
        verified_results_by_event: dict[str, _VerifiedResult] = {}
        all_result_use: dict[str, set[str]] = {}
        for event in trial_events:
            trial = event.trial
            if trial is None or trial.candidate_hash not in candidates_by_hash:
                continue
            hashes = self._linked_result_hashes(trial)
            linked_result_hashes[event.content_hash] = hashes
            if len(hashes) > 1:
                strict_reason = strict_reason or _SelectionFailure(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "one trial links multiple ResearchResult artifacts",
                )
                continue
            if not hashes:
                continue
            result_hash = hashes[0]
            all_result_use.setdefault(result_hash, set()).add(trial.candidate_hash)
            try:
                verified = self._load_verified_result(result_hash)
                self._validate_result_for_candidate(
                    verified, candidates_by_hash[trial.candidate_hash], trial
                )
                verified_results_by_event[event.content_hash] = verified
            except CampaignSelectionError as error:
                strict_reason = strict_reason or _SelectionFailure(error.reason_code, str(error))

        exact_duplicates = _exact_duplicate_hashes(self.manifest)
        ledgers: list[_CandidateLedger] = []
        dispositions: list[CandidateSelectionDisposition] = []
        budget_exhausted = self._budget_exhausted(trial_events)
        for candidate in candidates:
            candidate_hash = candidate.content_hash
            own_events = tuple(events_by_candidate[candidate_hash])
            validation_events = tuple(
                event
                for event in own_events
                if event.trial is not None and event.trial.segment is CampaignSegment.VALIDATION
            )
            chosen_hash: str | None = None
            verified: _VerifiedResult | None = None
            failure: _SelectionFailure | None = None
            if candidate_hash in exact_duplicates:
                kind = CandidateDispositionKind.EXACT_DUPLICATE
                if len(validation_events) > 1:
                    failure = _SelectionFailure(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "candidate has multiple validation attempts",
                    )
                elif (
                    validation_events
                    and validation_events[0].trial is not None
                    and validation_events[0].trial.outcome is TrialOutcome.PASS
                ):
                    validation = validation_events[0]
                    trial = cast(CampaignTrial, validation.trial)
                    result_hashes = linked_result_hashes.get(validation.content_hash, ())
                    if len(result_hashes) == 1:
                        verified = verified_results_by_event.get(validation.content_hash)
                    else:
                        failure = _SelectionFailure(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "PASS validation trial must link exactly one available ResearchResult",
                        )
            elif len(validation_events) > 1:
                failure = _SelectionFailure(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "candidate has multiple validation attempts",
                )
                kind = CandidateDispositionKind.NONPASS_VALIDATION
            elif not validation_events:
                if not own_events:
                    kind = (
                        CandidateDispositionKind.NOT_RUN_BUDGET
                        if budget_exhausted
                        else CandidateDispositionKind.NOT_RUN_MANUAL_CLOSE
                    )
                else:
                    kind = CandidateDispositionKind.NO_VALIDATION_RESULT
            else:
                validation = validation_events[0]
                trial = validation.trial
                if trial is None:
                    failure = _SelectionFailure(
                        ReasonCode.ARTIFACT_CORRUPTED, "validation event has no trial payload"
                    )
                    kind = CandidateDispositionKind.NO_VALIDATION_RESULT
                elif trial.outcome is not TrialOutcome.PASS:
                    kind = CandidateDispositionKind.NONPASS_VALIDATION
                else:
                    result_hashes = linked_result_hashes.get(validation.content_hash, ())
                    if len(result_hashes) != 1:
                        failure = _SelectionFailure(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "PASS validation trial must link exactly one available ResearchResult",
                        )
                        kind = CandidateDispositionKind.NO_VALIDATION_RESULT
                    else:
                        chosen_hash = result_hashes[0]
                        verified = verified_results_by_event.get(validation.content_hash)
                        kind = CandidateDispositionKind.ELIGIBLE
                        if verified is None:
                            failure = _SelectionFailure(
                                ReasonCode.ARTIFACT_CORRUPTED,
                                "eligible ResearchResult was not verified",
                            )

            if failure is not None and strict_reason is None:
                strict_reason = failure
            disposition = CandidateSelectionDisposition(
                candidate_hash=candidate_hash,
                kind=kind,
                trial_event_hashes=tuple(event.content_hash for event in own_events),
                validation_trial_event_hash=(
                    validation_events[0].content_hash
                    if kind is CandidateDispositionKind.ELIGIBLE and len(validation_events) == 1
                    else None
                ),
                research_result_hash=(
                    chosen_hash if kind is CandidateDispositionKind.ELIGIBLE else None
                ),
            )
            dispositions.append(disposition)
            ledgers.append(
                _CandidateLedger(
                    candidate=candidate,
                    trial_events=own_events,
                    validation_events=validation_events,
                    disposition=disposition,
                    result_hash=chosen_hash,
                    verified_result=verified,
                )
            )

        if any(len(candidate_hashes) > 1 for candidate_hashes in all_result_use.values()):
            strict_reason = strict_reason or _SelectionFailure(
                ReasonCode.ARTIFACT_CORRUPTED,
                "a ResearchResult artifact is reused across candidates",
            )

        trial_bindings = tuple(
            CampaignTrialEvidenceBinding(
                event_hash=event.content_hash,
                trial_hash=cast(CampaignTrial, event.trial).content_hash,
                candidate_hash=cast(CampaignTrial, event.trial).candidate_hash,
                research_result_hash=(
                    linked_result_hashes[event.content_hash][0]
                    if len(linked_result_hashes.get(event.content_hash, ())) == 1
                    else None
                ),
                validation_report_hash=None,
            )
            for event in trial_events
        )
        if len(trial_bindings) != len(trial_events) or len(
            {item.event_hash for item in trial_bindings}
        ) != len(trial_events):
            strict_reason = strict_reason or _SelectionFailure(
                ReasonCode.ARTIFACT_CORRUPTED,
                "trial accounting is incomplete or contains repeated event bindings",
            )

        eligible = [
            item for item in ledgers if item.disposition.kind is CandidateDispositionKind.ELIGIBLE
        ]
        if strict_reason is None and not eligible:
            strict_reason = _SelectionFailure(
                ReasonCode.SOURCE_INCOMPLETE,
                "selection has no eligible validation Rank IC series",
            )

        oriented_series: dict[str, tuple[float, ...]] = {}
        if strict_reason is None:
            try:
                if self.calendar is None:
                    raise CampaignSelectionError(
                        ReasonCode.SOURCE_INCOMPLETE, "verified validation calendar is missing"
                    )
                for ledger in eligible:
                    if ledger.verified_result is None:
                        raise CampaignSelectionError(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "eligible candidate ResearchResult is unavailable",
                        )
                    rows = ledger.verified_result.rank_ic
                    if tuple(item.trade_date for item in rows) != self.calendar.trading_dates:
                        raise CampaignSelectionError(
                            ReasonCode.SOURCE_INCOMPLETE,
                            "Rank IC dates do not exactly match the frozen validation calendar",
                        )
                    values = tuple(float(item.value) for item in rows)
                    if any(not math.isfinite(item) or not -1.0 <= item <= 1.0 for item in values):
                        raise CampaignSelectionError(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "Rank IC series contains a non-finite or out-of-range value",
                        )
                    if len(values) < self.multiple_testing_policy.minimum_sessions:
                        raise CampaignSelectionError(
                            ReasonCode.SOFT_THRESHOLD_NOT_MET,
                            "validation Rank IC series has fewer than 40 sessions",
                        )
                    raw_mean = math.fsum(values) / len(values)
                    if math.fsum((item - raw_mean) ** 2 for item in values) == 0.0:
                        raise CampaignSelectionError(
                            ReasonCode.SOFT_THRESHOLD_NOT_MET,
                            "validation Rank IC series has zero sample variance",
                        )
                    oriented_series[ledger.candidate.content_hash] = (
                        values
                        if self.selection_policy.direction == "POSITIVE"
                        else tuple(-item for item in values)
                    )
            except CampaignSelectionError as error:
                strict_reason = _SelectionFailure(error.reason_code, str(error))

        if strict_reason is not None:
            return self._build_report(
                source_hashes,
                trial_bindings,
                tuple(dispositions),
                (),
                RunStatus.FAILED,
                CampaignSelectionVerdict.NOT_EVALUATED,
                selected=None,
                reason=strict_reason.reason_code,
            )

        scores, adjusted_numerators = self._compute_scores(candidates, eligible, oriented_series)
        winner = self._choose_winner(scores, eligible, adjusted_numerators)
        verdict = (
            CampaignSelectionVerdict.SELECTED
            if winner is not None
            else CampaignSelectionVerdict.NO_SELECTION
        )
        return self._build_report(
            source_hashes,
            trial_bindings,
            tuple(dispositions),
            scores,
            RunStatus.SUCCEEDED,
            verdict,
            selected=winner,
            reason=None,
        )

    def _validate_prefix(self, events: tuple[CampaignChainEvent, ...]) -> _SelectionFailure | None:
        if self.plan is None:
            return _SelectionFailure(ReasonCode.SOURCE_INCOMPLETE, "selection plan is missing")
        try:
            ResearchCampaignGovernor(self.family, self.template, self.manifest).project(
                self.campaign, self.budget, events
            )
        except CampaignGovernanceError as error:
            return _SelectionFailure(error.reason_code, str(error))
        plans = [
            (index, event)
            for index, event in enumerate(events)
            if isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.PLAN_FROZEN
        ]
        if len(plans) != 1:
            return _SelectionFailure(
                ReasonCode.EVENT_CHAIN_INVALID,
                "P14c report requires exactly one frozen selection plan",
            )
        plan_index, plan_event = plans[0]
        if (
            plan_index != 1
            or plan_event.selection_plan_hash != self.plan.content_hash
            or any(
                isinstance(event, CampaignSelectionEvent)
                and event.event_type is not CampaignSelectionEventType.PLAN_FROZEN
                for event in events
            )
            or any(
                isinstance(event, ResearchCampaignEvent)
                and event.event_type in {CampaignEventType.OOS_ACCESSED, CampaignEventType.CLOSED}
                for event in events
            )
        ):
            return _SelectionFailure(
                ReasonCode.EVENT_CHAIN_INVALID,
                "selection report prefix has an invalid plan, OOS, or close event",
            )
        if self._input_failure is not None:
            return self._input_failure
        return None

    def _budget_exhausted(self, trial_events: tuple[ResearchCampaignEvent, ...]) -> bool:
        trials = tuple(cast(CampaignTrial, event.trial) for event in trial_events)
        usage = (
            (len(trials), self.budget.max_trials),
            (len({item.candidate_hash for item in trials}), self.budget.max_distinct_candidates),
            (
                len({item.agent_run_hash for item in trials if item.agent_run_hash is not None}),
                self.budget.max_agent_runs,
            ),
            (sum(item.execution_requested for item in trials), self.budget.max_executions),
            (
                sum(item.segment is CampaignSegment.VALIDATION for item in trials),
                self.budget.max_validation_rounds,
            ),
            (sum(item.compute_seconds for item in trials), self.budget.max_compute_seconds),
        )
        return any(used >= maximum for used, maximum in usage)

    def _result_path(self, result_hash: str) -> Path | None:
        for root in self.research_results_roots:
            path = root / f"sha256-{result_hash}"
            if path.exists() or path.is_symlink():
                return path
        return None

    def _linked_result_hashes(self, trial: CampaignTrial) -> tuple[str, ...]:
        return tuple(
            sorted(
                evidence_hash
                for evidence_hash in trial.evidence_hashes
                if self._result_path(evidence_hash) is not None
            )
        )

    def _load_verified_result(self, result_hash: str) -> _VerifiedResult:
        path = self._result_path(result_hash)
        if path is None:
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "linked ResearchResult artifact is missing",
            )
        try:
            manifest = verify_research_result(path)
            if manifest.artifact_hash != result_hash:
                raise ValueError("ResearchResult hash differs from its evidence binding")
            resolved = ResolvedExperimentSpec.model_validate_json(
                (path / "resolved-experiment.json").read_bytes()
            )
            research_policy = ResearchPolicy.model_validate_json(
                (path / "research-policy.json").read_bytes()
            )
            rows_payload = json.loads((path / "rank-ic-series.json").read_bytes())
            if not isinstance(rows_payload, list):
                raise ValueError("Rank IC payload must be a list")
            rank_ic = tuple(
                ResearchResultSeriesRow.model_validate(item)
                for item in cast(list[object], rows_payload)
            )
        except QlibResearchError as error:
            raise CampaignSelectionError(error.reason_code, str(error)) from error
        except (OSError, ValueError, TypeError, ValidationError) as error:
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED, "ResearchResult bindings cannot be read"
            ) from error
        return _VerifiedResult(manifest, resolved, research_policy, rank_ic)

    def _validate_result_for_candidate(
        self,
        result: _VerifiedResult,
        candidate: ResearchCandidateSpec,
        trial: CampaignTrial,
    ) -> None:
        manifest = result.manifest
        resolved = result.resolved
        if (
            result.research_policy.content_hash != manifest.research_policy_hash
            or resolved.content_hash != manifest.resolved_experiment_hash
            or manifest.snapshot_hash != self.campaign.snapshot_hash
            or manifest.qlib_view_hash != self.campaign.qlib_view_hash
            or resolved.snapshot_hash != self.campaign.snapshot_hash
            or resolved.qlib_view_hash != self.campaign.qlib_view_hash
            or resolved.evaluation_start
            < {
                CampaignSegment.DEVELOPMENT: self.campaign.development,
                CampaignSegment.VALIDATION: self.campaign.validation,
                CampaignSegment.SEALED_CONFIRMATION: self.campaign.sealed_confirmation,
            }[trial.segment].start
            or resolved.evaluation_end
            > {
                CampaignSegment.DEVELOPMENT: self.campaign.development,
                CampaignSegment.VALIDATION: self.campaign.validation,
                CampaignSegment.SEALED_CONFIRMATION: self.campaign.sealed_confirmation,
            }[trial.segment].end
            or resolved.expression.content_hash != manifest.expression_spec_hash
        ):
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "ResearchResult does not bind the campaign trial inputs",
            )
        from quantos.application.enumeration import exact_expression_hash

        if exact_expression_hash(resolved.expression) != candidate.exact_expression_hash:
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "ResearchResult expression differs from its enumerated candidate",
            )
        if trial.candidate_hash != candidate.content_hash:
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "ResearchResult validation trial candidate does not match",
            )

    def _compute_scores(
        self,
        candidates: tuple[ResearchCandidateSpec, ...],
        eligible: list[_CandidateLedger],
        oriented_series: dict[str, tuple[float, ...]],
    ) -> tuple[tuple[CandidateSelectionScore, ...], dict[str, int]]:
        raw_numerators: dict[str, int] = {item.content_hash: 10_000 for item in candidates}
        means: dict[str, float] = {}
        exceedances: dict[str, int] = {}
        for ledger in eligible:
            candidate_hash = ledger.candidate.content_hash
            mean, count = _bootstrap_exceedances(
                oriented_series[candidate_hash], self.multiple_testing_policy, candidate_hash
            )
            means[candidate_hash] = mean
            exceedances[candidate_hash] = count
            raw_numerators[candidate_hash] = _pvalue_numerator(count)

        ordered = sorted(raw_numerators, key=lambda item: (raw_numerators[item], item))
        adjusted_numerators: dict[str, int] = {}
        running_max = 0
        family_size = len(candidates)
        for position, candidate_hash in enumerate(ordered):
            current = min(10_000, (family_size - position) * raw_numerators[candidate_hash])
            running_max = max(running_max, current)
            adjusted_numerators[candidate_hash] = running_max

        scores = tuple(
            CandidateSelectionScore(
                candidate_hash=candidate.content_hash,
                oriented_mean_rank_ic=means[candidate.content_hash],
                raw_p_value=raw_numerators[candidate.content_hash] / 10_000,
                adjusted_p_value=adjusted_numerators[candidate.content_hash] / 10_000,
                observation_count=len(oriented_series[candidate.content_hash]),
                bootstrap_exceedances=exceedances[candidate.content_hash],
            )
            for candidate in sorted(candidates, key=lambda item: item.content_hash)
            if candidate.content_hash in means
        )
        return scores, adjusted_numerators

    @staticmethod
    def _choose_winner(
        scores: tuple[CandidateSelectionScore, ...],
        eligible: list[_CandidateLedger],
        adjusted_numerators: dict[str, int],
    ) -> str | None:
        eligible_hashes = {item.candidate.content_hash for item in eligible}
        significant = [
            item
            for item in scores
            if item.candidate_hash in eligible_hashes
            and adjusted_numerators[item.candidate_hash] * 20 <= 10_000
        ]
        if not significant:
            return None
        winner = min(
            significant,
            key=lambda item: (
                adjusted_numerators[item.candidate_hash],
                -item.oriented_mean_rank_ic,
                item.candidate_hash,
            ),
        )
        return winner.candidate_hash

    def _build_report(
        self,
        source_hashes: tuple[str, ...],
        trial_bindings: tuple[CampaignTrialEvidenceBinding, ...],
        dispositions: tuple[CandidateSelectionDisposition, ...],
        scores: tuple[CandidateSelectionScore, ...],
        run_status: RunStatus,
        verdict: CampaignSelectionVerdict,
        *,
        selected: str | None,
        reason: ReasonCode | None,
    ) -> CampaignSelectionReport:
        if self.plan is None:
            raise CampaignSelectionError(
                ReasonCode.SOURCE_INCOMPLETE,
                "a plan hash is required to produce a selection report",
            )
        calendar_hash = (
            self.calendar.content_hash
            if self.calendar is not None
            else self.plan.validation_calendar_hash
        )
        payload: dict[str, object] = {
            "schema_version": "campaign-selection-report/v1",
            "selection_plan_hash": self.plan.content_hash,
            "campaign_hash": self.campaign.content_hash,
            "family_hash": self.family.content_hash,
            "budget_hash": self.budget.content_hash,
            "candidate_manifest_hash": self.manifest.content_hash,
            "multiple_testing_policy_hash": self.multiple_testing_policy.content_hash,
            "selection_policy_hash": self.selection_policy.content_hash,
            "validation_calendar_hash": calendar_hash,
            "source_event_hashes": source_hashes,
            "trial_bindings": trial_bindings,
            "candidate_dispositions": dispositions,
            "scores": scores,
            "run_status": run_status,
            "verdict": verdict,
            "selected_candidate_hash": selected,
            "reason_code": reason,
            "limitations": SELECTION_LIMITATIONS,
        }
        payload.pop("schema_version")
        return _report_from_payload(**payload)

    def publish_report(
        self,
        events: tuple[CampaignChainEvent, ...],
        output_root: Path,
    ) -> tuple[CampaignSelectionReport, Path]:
        report = self.build_report(events)
        destination = output_root / f"sha256-{report.report_hash}"
        output_root.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = verify_selection_report_artifact(destination)
            if existing != report:
                raise CampaignSelectionError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "existing immutable selection report differs from rebuilt report",
                )
            return existing, destination
        with tempfile.TemporaryDirectory(prefix=".campaign-selection-", dir=output_root) as temp:
            staging = Path(temp) / "selection-report"
            staging.mkdir()
            atomic_write_bytes(
                staging / "report.json", canonical_json_bytes(report.model_dump(mode="python"))
            )
            try:
                publish_directory(staging, destination)
            except ArtifactError:
                if not destination.exists():
                    raise
                existing = verify_selection_report_artifact(destination)
                if existing != report:
                    raise CampaignSelectionError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "selection report publication conflicted with different bytes",
                    ) from None
                return existing, destination
        return report, destination

    def verify_report(
        self,
        path: Path,
        events: tuple[CampaignChainEvent, ...],
    ) -> CampaignSelectionReport:
        stored = verify_selection_report_artifact(path)
        rebuilt = self.build_report(events)
        if canonical_json_bytes(stored.model_dump(mode="python")) != canonical_json_bytes(
            rebuilt.model_dump(mode="python")
        ):
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "selection report differs from recomputed frozen inputs",
            )
        return stored

    def freeze_selection(
        self,
        governor: ResearchCampaignGovernor,
        events: tuple[CampaignChainEvent, ...],
        report_path: Path,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> CampaignSelectionEvent:
        report = self.verify_report(report_path, events)
        return governor._freeze_verified_selection(  # pyright: ignore[reportPrivateUsage]
            self.campaign,
            self.budget,
            events,
            report,
            event_id=event_id,
            occurred_at=occurred_at,
        )

    def access_sealed_confirmation(
        self,
        governor: ResearchCampaignGovernor,
        events: tuple[CampaignChainEvent, ...],
        trial: CampaignTrial,
        report_path: Path,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        """Authorize OOS only after recomputing the report bound by SelectionFrozen."""

        selection_positions = [
            index
            for index, event in enumerate(events)
            if isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.SELECTION_FROZEN
        ]
        if len(selection_positions) != 1:
            raise CampaignSelectionError(
                ReasonCode.OOS_POLICY_VIOLATION,
                "sealed confirmation requires exactly one SelectionFrozen event",
            )
        position = selection_positions[0]
        selection_event = cast(CampaignSelectionEvent, events[position])
        report = self.verify_report(report_path, events[:position])
        if (
            report.verdict is not CampaignSelectionVerdict.SELECTED
            or report.report_hash != selection_event.selection_report_hash
            or report.selected_candidate_hash != selection_event.selected_candidate_hash
            or trial.candidate_hash != report.selected_candidate_hash
        ):
            raise CampaignSelectionError(
                ReasonCode.OOS_POLICY_VIOLATION,
                "sealed trial does not bind the verified selected candidate",
            )
        return governor._access_verified_selection_confirmation(  # pyright: ignore[reportPrivateUsage]
            self.campaign,
            self.budget,
            events,
            trial,
            event_id=event_id,
            occurred_at=occurred_at,
        )


def publish_selection_plan(plan: CampaignSelectionPlan, output_root: Path) -> Path:
    """Publish one hash-addressed plan with an exact-file verifier."""

    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"sha256-{plan.content_hash}"
    if destination.exists():
        stored = verify_selection_plan_artifact(destination)
        if stored != plan:
            raise CampaignSelectionError(
                ReasonCode.ARTIFACT_CORRUPTED, "existing plan artifact has different bytes"
            )
        return destination
    with tempfile.TemporaryDirectory(prefix=".campaign-selection-plan-", dir=output_root) as temp:
        staging = Path(temp) / "selection-plan"
        staging.mkdir()
        atomic_write_bytes(staging / "plan.json", plan.canonical_bytes())
        try:
            publish_directory(staging, destination)
        except ArtifactError:
            if not destination.exists():
                raise
            if verify_selection_plan_artifact(destination) != plan:
                raise CampaignSelectionError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "plan publication conflicted with different bytes",
                ) from None
    return destination


def verify_selection_plan_artifact(path: Path) -> CampaignSelectionPlan:
    try:
        files = regular_tree_files(path)
        if {item.relative_to(path).as_posix() for item in files} != {"plan.json"}:
            raise ValueError("selection plan has an unexpected file set")
        payload = (path / "plan.json").read_bytes()
        plan = CampaignSelectionPlan.model_validate_json(payload)
        if path.name != f"sha256-{plan.content_hash}" or plan.canonical_bytes() != payload:
            raise ValueError("selection plan path or bytes do not match its hash")
    except (OSError, ValueError, ValidationError, ArtifactIntegrityError) as error:
        raise CampaignSelectionError(
            ReasonCode.ARTIFACT_CORRUPTED, "selection plan artifact verification failed"
        ) from error
    return plan


def verify_selection_report_artifact(path: Path) -> CampaignSelectionReport:
    try:
        files = regular_tree_files(path)
        if {item.relative_to(path).as_posix() for item in files} != {"report.json"}:
            raise ValueError("selection report has an unexpected file set")
        payload = (path / "report.json").read_bytes()
        report = CampaignSelectionReport.model_validate_json(payload)
        if (
            path.name != f"sha256-{report.report_hash}"
            or canonical_json_bytes(report.model_dump(mode="python")) != payload
        ):
            raise ValueError("selection report path or bytes do not match its hash")
    except (OSError, ValueError, ValidationError, ArtifactIntegrityError) as error:
        raise CampaignSelectionError(
            ReasonCode.ARTIFACT_CORRUPTED, "selection report artifact verification failed"
        ) from error
    return report
