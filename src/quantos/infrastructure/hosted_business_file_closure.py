"""Exact native file attribution for hosted recovery checkpoints and reports."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from quantos.application.autonomous import AutonomousCampaignOrchestrator
from quantos.application.autonomous_execution import (
    AutonomousExecutionReceipt,
    AutonomousExecutionTrialIndex,
    QuantosResearchExecutionAdapter,
)
from quantos.application.hosted_campaign import hosted_business_operation_id
from quantos.application.hosted_protocol import (
    HostedProtocolService,
    hosted_protocol_operation_id,
)
from quantos.backtest import verify_backtest_artifact
from quantos.contracts.autonomous import AutonomousCandidateProposal, AutonomousExecutionResult
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import CampaignEventType, ResearchCampaignEvent
from quantos.contracts.campaign_selection import CampaignSelectionEvent, CampaignSelectionEventType
from quantos.contracts.hosted import (
    HostedAgentExchange,
    HostedAgentResponse,
    HostedBudgetJournalFact,
    HostedCampaignReport,
    HostedCheckpoint,
    HostedJournalEntry,
    HostedRequestSubmissionCount,
    HostedRequestTerminalReceipt,
    HostedResearchBudgetFact,
    HostedResearchStepIntent,
    HostedSubmissionReceipt,
    strict_json_object,
)
from quantos.contracts.hosted_inputs import HostedFrozenBusinessInputs
from quantos.contracts.hosted_qualification import HostedQualificationFile
from quantos.contracts.ledger import ResearchLedgerEventV2
from quantos.contracts.model_data_split import QlibModelDataSplitAudit
from quantos.contracts.research_result import P14dqNativeLabelExportAudit
from quantos.infrastructure.hosted_business_verification import (
    HostedVerifiedBusiness,
    c11_business_projection_paths,
    principal_business_inventory,
)
from quantos.infrastructure.hosted_store import HostedStoreSnapshot
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    read_relative,
)
from quantos.research.qlib.result import verify_research_result
from quantos.research.qlib.signal import verify_signal_artifact


def _verify_native_protocol_publication(
    state: HostedStoreSnapshot,
    entry: HostedJournalEntry,
    previous_budget: HostedBudgetJournalFact | None,
    accepted_requests: set[str],
    terminal_requests: set[str],
) -> HostedBudgetJournalFact | None:
    """Bind the tuple to native operation identity and exact counter transition."""
    spec = state.spec
    campaign = spec.campaign_hash
    now = entry.recorded_at
    expected: tuple[CanonicalContract, ...]
    budget = previous_budget
    if entry.operation_kind == "REGISTER":
        if previous_budget is not None or entry.sequence != 1 or now != spec.started_at:
            raise HostedQualificationError("native protocol registration chronology differs")
        op = hosted_protocol_operation_id(campaign, "REGISTER", spec.content_hash)
        budget = HostedBudgetJournalFact(
            campaign_hash=campaign,
            hosted_spec_hash=spec.content_hash,
            operation_id=op,
            previous_hash=None,
            used_requests=0,
            used_unique_submissions=0,
            request_submissions=(),
            recorded_at=now,
        )
        expected = (
            spec,
            budget,
            HostedProtocolService.project_exhaustion_receipt(spec, budget, None, now),
        )
    elif entry.operation_kind == "ISSUE" and previous_budget is not None:
        ordinal = previous_budget.used_requests + 1
        request = next((item for item in state.requests if item.transport_ordinal == ordinal), None)
        if request is None or request.issued_at != now:
            raise HostedQualificationError("native protocol issue chronology differs")
        op = hosted_protocol_operation_id(campaign, "ISSUE", ordinal)
        budget = HostedBudgetJournalFact(
            campaign_hash=campaign,
            hosted_spec_hash=spec.content_hash,
            operation_id=op,
            previous_hash=previous_budget.content_hash,
            used_requests=ordinal,
            used_unique_submissions=previous_budget.used_unique_submissions,
            request_submissions=(
                *previous_budget.request_submissions,
                HostedRequestSubmissionCount(transport_ordinal=ordinal, used_submissions=0),
            ),
            recorded_at=now,
        )
        if (
            request.budget_reservation_hash != budget.content_hash
            or request.attempt_identity
            != hosted_protocol_operation_id(campaign, "ATTEMPT", ordinal)
            or request.projection_object_hashes
            != tuple(sorted({request.context_pack_hash, request.proposal_schema_hash}))
        ):
            raise HostedQualificationError("native protocol request reservation/projection differs")
        checkpoint = HostedCheckpoint(
            request_hash=request.content_hash,
            campaign_hash=campaign,
            transport_ordinal=ordinal,
            recorded_at=now,
        )
        expected = (
            budget,
            request,
            checkpoint,
            HostedProtocolService.project_exhaustion_receipt(spec, budget, request, now),
        )
    elif entry.operation_kind == "SUBMIT" and previous_budget is not None:
        receipt = state.artifact(entry.publications[-1].artifact_hash, HostedSubmissionReceipt)
        if receipt.request_hash is None or receipt.outcome == "EXHAUSTED":
            raise HostedQualificationError("native protocol submission has unrelated receipt")
        request = state.request(receipt.request_hash)
        digest = receipt.submission_bytes_hash if receipt.complete else receipt.observed_prefix_hash
        op = hosted_protocol_operation_id(
            campaign, "SUBMIT", (request.content_hash, receipt.complete, digest)
        )
        budget = HostedBudgetJournalFact(
            campaign_hash=campaign,
            hosted_spec_hash=spec.content_hash,
            operation_id=op,
            previous_hash=previous_budget.content_hash,
            used_requests=previous_budget.used_requests,
            used_unique_submissions=previous_budget.used_unique_submissions + 1,
            request_submissions=tuple(
                HostedRequestSubmissionCount(
                    transport_ordinal=item.transport_ordinal,
                    used_submissions=item.used_submissions
                    + (item.transport_ordinal == request.transport_ordinal),
                )
                for item in previous_budget.request_submissions
            ),
            recorded_at=now,
        )
        if (
            receipt.budget_before_hash != previous_budget.content_hash
            or receipt.budget_after_hash != budget.content_hash
            or receipt.recorded_at != now
        ):
            raise HostedQualificationError("native protocol submission budget/time differs")
        if receipt.outcome == "ACCEPTED":
            response = state.artifact(cast(str, receipt.submission_bytes_hash), HostedAgentResponse)
            exchange = HostedAgentExchange(
                request_hash=request.content_hash,
                response_hash=response.content_hash,
                proposal_hash=response.proposal_hash,
                authenticated_principal=receipt.authenticated_principal,
                host_observation_hash=response.host_observation.content_hash,
            )
            if receipt.accepted_exchange_hash != exchange.content_hash:
                raise HostedQualificationError("native protocol accepted exchange differs")
            expected = (budget, response.host_observation, response, exchange, receipt)
            accepted_requests.add(request.content_hash)
        elif (
            request.content_hash not in accepted_requests
            and request.content_hash not in terminal_requests
            and now >= request.expires_at
        ):
            # A first submission at/after TTL publishes its expiration together
            # with the charged rejection. Rebuild the native terminal rather
            # than accepting a producer's extra publication or reason label.
            if receipt.outcome != "REJECTED" or receipt.reason != "REQUEST_EXPIRED":
                raise HostedQualificationError("native first expired submission differs")
            terminal = HostedRequestTerminalReceipt(
                request_hash=request.content_hash,
                campaign_hash=campaign,
                outcome="EXPIRED",
                reason="REQUEST_TTL_ELAPSED",
                authenticated_principal="service",
                recorded_at=now,
            )
            expected = (budget, terminal, receipt)
            terminal_requests.add(request.content_hash)
        else:
            expected = (budget, receipt)
    elif entry.operation_kind == "TERMINATE":
        terminal = state.artifact(entry.publications[0].artifact_hash, HostedRequestTerminalReceipt)
        kind = "EXPIRE" if terminal.outcome == "EXPIRED" else "CANCEL"
        op = hosted_protocol_operation_id(campaign, kind, terminal.request_hash)
        request = state.request(terminal.request_hash)
        accepted = request.content_hash in accepted_requests
        native_outcome = (
            "EXPIRED" if kind == "EXPIRE" else "CANCEL_REJECTED" if accepted else "CANCELLED"
        )
        native_reason = (
            "REQUEST_TTL_ELAPSED"
            if kind == "EXPIRE"
            else "REQUEST_ALREADY_ACCEPTED"
            if accepted
            else "AUTHORIZED_CANCELLATION"
        )
        if (
            terminal.recorded_at != now
            or terminal.outcome not in ("EXPIRED", "CANCELLED", "CANCEL_REJECTED")
            or terminal.outcome != native_outcome
            or terminal.reason != native_reason
            or terminal.business_artifact_hashes != ()
            or (
                kind == "EXPIRE"
                and (
                    now < request.expires_at
                    or accepted
                    or terminal.authenticated_principal != "service"
                )
            )
        ):
            raise HostedQualificationError("native protocol termination differs")
        expected = (terminal,)
        if terminal.outcome != "CANCEL_REJECTED":
            terminal_requests.add(terminal.request_hash)
    else:
        raise HostedQualificationError("native protocol publication is unrelated")
    if entry.operation_id != op or tuple(
        item.canonical_json.encode() for item in entry.publications
    ) != tuple(item.canonical_bytes() for item in expected):
        raise HostedQualificationError("native protocol operation/publication tuple differs")
    return budget


def verify_native_authority_file_closure(
    authority: Path,
    bundle: HostedFrozenBusinessInputs,
    state: HostedStoreSnapshot,
    orchestrator: AutonomousCampaignOrchestrator,
    events: tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...],
    *,
    business: HostedVerifiedBusiness | None = None,
) -> frozenset[str]:
    """Attribute every file to frozen seed or verified native publication/reference.

    This routine runs after semantic protocol/business checks. A file's location,
    producer inventory or valid schema alone never authorizes it.
    """
    campaign = state.spec.campaign_hash
    prefix = f"business/{campaign}"
    execution_prefix = prefix + "/execution"
    actual = {item.logical_path: item for item in raw_inventory(authority).files}
    expected: dict[str, HostedQualificationFile] = {}

    def include(path: str, data: bytes) -> None:
        item = HostedQualificationFile(
            logical_path=path, sha256=sha256_bytes(data), size_bytes=len(data)
        )
        if expected.get(path, item) != item or actual.get(path) != item:
            raise HostedQualificationError("native file reference or published bytes differ")
        expected[path] = item

    def include_hash(path: str, digest: str, size: int) -> None:
        item = HostedQualificationFile(logical_path=path, sha256=digest, size_bytes=size)
        if actual.get(path) != item or expected.get(path, item) != item:
            raise HostedQualificationError("native frozen/file manifest reference differs")
        expected[path] = item

    def include_contract(path: str, contract: CanonicalContract) -> None:
        include(path, contract.canonical_bytes())

    include_contract(f"protocol/specs/{state.spec.content_hash}.json", state.spec)
    shapes = {
        "REGISTER": (
            (
                "hosted-campaign-spec/v1",
                "hosted-budget-journal-fact/v1",
                "hosted-submission-receipt/v1",
            ),
        ),
        "ISSUE": (
            (
                "hosted-budget-journal-fact/v1",
                "hosted-agent-request/v1",
                "hosted-checkpoint/v1",
                "hosted-submission-receipt/v1",
            ),
        ),
        "SUBMIT": (
            (
                "hosted-budget-journal-fact/v1",
                "hosted-observation/v1",
                "hosted-agent-response/v1",
                "hosted-agent-exchange/v1",
                "hosted-submission-receipt/v1",
            ),
            ("hosted-budget-journal-fact/v1", "hosted-submission-receipt/v1"),
            (
                "hosted-budget-journal-fact/v1",
                "hosted-request-terminal-receipt/v1",
                "hosted-submission-receipt/v1",
            ),
        ),
        "TERMINATE": (("hosted-request-terminal-receipt/v1",),),
    }
    protocol_budget = None
    accepted_requests: set[str] = set()
    terminal_requests: set[str] = set()
    for entry in state.journal:
        include_contract(
            f"protocol/campaigns/{campaign}/journal/{entry.sequence:08d}-{entry.content_hash}.json",
            entry,
        )
        if entry.phase != "INTENT":
            continue
        schemas = tuple(
            strict_json_object(publication.canonical_json.encode(), max_bytes=16_777_216).get(
                "schema_version"
            )
            for publication in entry.publications
        )
        if entry.operation_kind == "BUSINESS":
            contracts = tuple(
                state.artifact(
                    publication.artifact_hash,
                    {
                        "hosted-research-budget-fact/v1": HostedResearchBudgetFact,
                        "hosted-research-step-intent/v1": HostedResearchStepIntent,
                        "hosted-request-terminal-receipt/v1": HostedRequestTerminalReceipt,
                        "hosted-campaign-report/v1": HostedCampaignReport,
                    }[cast(str, schema)],
                )
                for publication, schema in zip(entry.publications, schemas, strict=True)
                if schema
                in (
                    "hosted-research-budget-fact/v1",
                    "hosted-research-step-intent/v1",
                    "hosted-request-terminal-receipt/v1",
                    "hosted-campaign-report/v1",
                )
            )
            step = next(
                (item for item in contracts if isinstance(item, HostedResearchStepIntent)), None
            )
            budget = next(
                (item for item in contracts if isinstance(item, HostedResearchBudgetFact)), None
            )
            report = next(
                (item for item in contracts if isinstance(item, HostedCampaignReport)), None
            )
            terminal = next(
                (item for item in contracts if isinstance(item, HostedRequestTerminalReceipt)), None
            )
            if step is not None:
                kind, identity, at = step.phase, step.request_hash, step.event_time
                allowed = (
                    ("hosted-research-budget-fact/v1", "hosted-research-step-intent/v1")
                    if kind == "PREPARED"
                    else ("hosted-research-step-intent/v1",)
                    if kind == "STARTED"
                    else (("autonomous-execution-result/v2",) if step.execution_result_hash else ())
                    + (
                        "campaign-trial/v1",
                        "hosted-research-budget-fact/v1",
                        "hosted-research-step-intent/v1",
                    )
                )
            elif budget is not None and budget.phase in ("INITIAL", "UNCERTAIN"):
                kind = "RESEARCH_INITIAL" if budget.phase == "INITIAL" else "UNCERTAIN"
                identity = (
                    state.spec.content_hash if budget.phase == "INITIAL" else budget.request_hash
                )
                at, allowed = budget.recorded_at, ("hosted-research-budget-fact/v1",)
            elif report is not None:
                kind, identity, at = "FINAL_REPORT", state.spec.content_hash, report.recorded_at
                allowed = ("hosted-campaign-report/v1",)
            elif terminal is not None and terminal.outcome == "STEP_COMPLETED":
                kind, identity, at = "STEP_COMPLETED", terminal.request_hash, terminal.recorded_at
                allowed = ("hosted-request-terminal-receipt/v1",)
            else:
                raise HostedQualificationError("native business publication is unrelated")
            if (
                schemas != allowed
                or entry.recorded_at != at
                or entry.operation_id != hosted_business_operation_id(campaign, kind, identity)
            ):
                raise HostedQualificationError("native business publication shape/identity differs")
        elif schemas not in shapes.get(entry.operation_kind, ()):
            raise HostedQualificationError("native protocol publication shape differs")
        else:
            protocol_budget = _verify_native_protocol_publication(
                state, entry, protocol_budget, accepted_requests, terminal_requests
            )
        for publication in entry.publications:
            include(
                f"protocol/campaigns/{campaign}/objects/{publication.artifact_hash}.json",
                publication.canonical_json.encode(),
            )
    for file in bundle.initial_ledger_files:
        include_hash(f"{prefix}/ledger/{file.logical_path}", file.sha256, file.size_bytes)
    # The production loader materializes the plan already bound by the frozen
    # input bundle and initial event. Component factories may retain it only in
    # that bundle; either way, only these exact referenced bytes are attributed.
    plan_path = f"{prefix}/selection-plans/sha256-{bundle.selection_plan.content_hash}/plan.json"
    if plan_path in actual:
        include_contract(plan_path, bundle.selection_plan)
    ledger_objects: dict[str, CanonicalContract] = {}
    ledger_metadata: dict[str, dict[str, object]] = {}

    def ledger_node(
        contract: CanonicalContract,
        kind: str,
        node_id: str,
        at: object,
        *,
        parents: tuple[str, ...] = (),
        agent: str | None = None,
        verdict: str | None = None,
    ) -> None:
        digest = contract.content_hash
        ledger_objects[digest] = contract
        metadata: dict[str, object] = {
            "node_kind": kind,
            "node_id": node_id,
            "occurred_at": at,
            "authority": "AGENT_PROPOSAL"
            if agent
            else "DETERMINISTIC_VERDICT"
            if verdict
            else "DETERMINISTIC_EVIDENCE",
            "parent_object_hashes": parents,
            "agent_run_hash": agent,
            "verdict_report_hash": verdict,
            "human_review_evidence_hash": None,
        }
        if ledger_metadata.get(digest, metadata) != metadata:
            raise HostedQualificationError("native Ledger object metadata conflicts")
        ledger_metadata[digest] = metadata

    for sequence, event in enumerate(events, 1):
        include_contract(
            f"{prefix}/campaign-events/{sequence:08d}-sha256-{event.content_hash}.json", event
        )
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None:
            ledger_node(
                event.trial,
                "CAMPAIGN_TRIAL",
                f"campaign-trial-{event.content_hash}",
                event.occurred_at,
            )
    for data in state.artifacts.values():
        if (
            strict_json_object(data, max_bytes=16_777_216).get("schema_version")
            != "hosted-research-step-intent/v1"
        ):
            continue
        step = HostedResearchStepIntent.model_validate_json(data)
        if step.phase != "COMPLETED":
            continue
        exchange = state.artifact(step.hosted_exchange_hash, HostedAgentExchange)
        response = state.artifact(exchange.response_hash, HostedAgentResponse)
        try:
            proposal = AutonomousCandidateProposal.model_validate_json(response.proposal_json)
        except ValueError:
            proposal = None
        candidate = next(
            (
                item
                for item in bundle.manifest.candidates
                if item.content_hash == step.candidate_hash
            ),
            None,
        )
        if (
            proposal is not None
            and candidate is not None
            and proposal.campaign_hash == campaign
            and (
                proposal.parameters == candidate.parameters
                and proposal.expression == candidate.expression
                and proposal.candidate_hash == candidate.content_hash
                and proposal.exact_expression_hash == candidate.exact_expression_hash
                and proposal.structural_expression_hash == candidate.structural_expression_hash
                and proposal.canonical_bytes() == response.proposal_json.encode()
            )
        ):
            request = state.request(step.request_hash)
            ledger_node(
                proposal,
                "FACTOR_PROPOSAL",
                f"candidate-proposal-{exchange.content_hash}-{proposal.content_hash}",
                step.event_time,
                parents=tuple(
                    sorted(
                        {
                            item.object_ref.object_hash
                            for item in request.business_request.context_pack.items
                        }
                    )
                ),
                agent=exchange.content_hash,
            )
        if step.execution_request is None:
            continue
        if business is None:
            raise HostedQualificationError("native executed file closure lacks verified report")
        request = step.execution_request
        result = state.artifact(cast(str, step.execution_result_hash), AutonomousExecutionResult)
        execution = cast(QuantosResearchExecutionAdapter, orchestrator.execution_port)
        receipt_path = (
            f"{execution_prefix}/execution-records/identities/{request.execution_identity}.json"
        )
        receipt_data = read_relative(authority, receipt_path)
        receipt = AutonomousExecutionReceipt.model_validate_json(receipt_data)
        include_contract(receipt_path, receipt)
        include_contract(
            f"{execution_prefix}/execution-record-artifacts/sha256-{receipt.content_hash}.json",
            receipt,
        )
        index = AutonomousExecutionTrialIndex(
            campaign_hash=campaign,
            trial_ordinal=request.trial_ordinal,
            execution_identity=request.execution_identity,
            request_hash=request.content_hash,
        )
        include_contract(
            f"{execution_prefix}/trial-identities/{campaign}-{request.trial_ordinal:08d}.json",
            index,
        )
        include_contract(
            f"{execution_prefix}/trial-identity-artifacts/sha256-{index.content_hash}.json", index
        )
        if result.research_result_hash is not None:
            directory = f"{execution_prefix}/research-results/sha256-{result.research_result_hash}"
            manifest = verify_research_result(authority / directory)
            include(
                f"{directory}/manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )
            for file in manifest.files:
                include_hash(f"{directory}/{file.logical_path}", file.sha256, file.size_bytes)
            native = (
                f"{execution_prefix}/executions/{request.execution_identity}/"
                f"qlib-workflow/native-records/sha256-{request.execution_identity}"
            )
            for file in manifest.source_files:
                include_hash(f"{native}/{file.logical_path}", file.sha256, file.size_bytes)
            # The verified receipt already checks this audit's calendar, inputs and
            # native source files. Attribute its exact bytes only through that receipt.
            split_path = f"{native}/model-data-splits.json"
            split = QlibModelDataSplitAudit.model_validate_json(
                read_relative(authority, split_path)
            )
            if (
                split.content_hash not in result.evidence_hashes
                or split.content_hash not in receipt.outcome.evidence_hashes
            ):
                raise HostedQualificationError(
                    "native model split audit lacks its receipt reference"
                )
            include_contract(split_path, split)
            ledger_node(
                manifest,
                "RESEARCH_RESULT",
                f"research-result-{manifest.content_hash}",
                step.event_time,
                parents=(cast(str, step.trial_hash),),
            )
            if execution.p14dq_v2_profile:
                # Native receipt verification already replays this finite-pair audit
                # against the untouched Qlib source, calendar and exported rows.
                matches: list[tuple[str, P14dqNativeLabelExportAudit]] = []
                for digest in result.evidence_hashes:
                    path = f"{execution_prefix}/research-result-audits/sha256-{digest}.json"
                    if path not in actual:
                        continue
                    audit = P14dqNativeLabelExportAudit.model_validate_json(
                        read_relative(authority, path)
                    )
                    if audit.research_result_hash == manifest.content_hash:
                        matches.append((path, audit))
                if len(matches) != 1:
                    raise HostedQualificationError("native DQ audit reference is ambiguous")
                path, audit = matches[0]
                include(path, canonical_json_bytes(audit.model_dump(mode="python")))
        if result.validation_report_hash is not None:
            validation = next(
                report
                for report in business.validation_reports
                if report.content_hash == result.validation_report_hash
            )
            directory = f"{execution_prefix}/validation/sha256-{validation.content_hash}"
            include(
                f"{directory}/report.json",
                canonical_json_bytes(validation.model_dump(mode="python")),
            )
            for file in validation.files:
                include_hash(f"{directory}/{file.logical_path}", file.sha256, file.size_bytes)
            if validation.oos_access_event is not None:
                ref = validation.oos_access_event
                include_hash(
                    f"{execution_prefix}/validation-events/{request.execution_identity}/{ref.logical_path}",
                    ref.sha256,
                    ref.size_bytes,
                )
            ledger_node(
                validation,
                "VALIDATION_REPORT",
                f"validation-report-{validation.content_hash}",
                step.event_time,
                parents=tuple(
                    sorted(
                        {
                            cast(str, step.trial_hash),
                            *(
                                ()
                                if result.research_result_hash is None
                                else (result.research_result_hash,)
                            ),
                        }
                    )
                ),
                verdict=validation.content_hash,
            )
        for digest in result.evidence_hashes:
            failure = execution.verify_execution_failure(digest)
            if failure is not None:
                include_contract(
                    f"{execution_prefix}/execution-failures/sha256-{digest}.json", failure
                )
                ledger_node(
                    failure,
                    "EXPERIMENT",
                    f"execution-failure-{digest}",
                    step.event_time,
                    parents=(cast(str, step.trial_hash),),
                )
    if business is not None:
        for logical in c11_business_projection_paths(authority, business, bundle):
            if "/research-results/" in logical:
                continue
            directory = str(Path(logical).parent)
            if "/signals/" in logical:
                manifest = verify_signal_artifact(authority / directory)
            else:
                manifest = verify_backtest_artifact(authority / directory)
                variant = str(Path(directory).parent.parent)
                signal_directory = f"{variant}/signals/sha256-{manifest.signal_artifact_hash}"
                # Reproduction reuses the baseline signal instead of republishing it.
                if "/reproduction/" not in logical:
                    signal = verify_signal_artifact(authority / signal_directory)
                    include(
                        f"{signal_directory}/manifest.json",
                        canonical_json_bytes(signal.model_dump(mode="python")),
                    )
                    for file in signal.files:
                        include_hash(
                            f"{signal_directory}/{file.logical_path}", file.sha256, file.size_bytes
                        )
            include(logical, canonical_json_bytes(manifest.model_dump(mode="python")))
            for file in manifest.files:
                include_hash(f"{directory}/{file.logical_path}", file.sha256, file.size_bytes)
        if business.selection is not None:
            report = business.selection
            include(
                f"{prefix}/selection-reports/sha256-{report.content_hash}/report.json",
                canonical_json_bytes(report.model_dump(mode="python")),
            )
            selection_prefix = events
            if selection_prefix and (
                (
                    isinstance(selection_prefix[-1], ResearchCampaignEvent)
                    and selection_prefix[-1].event_type is CampaignEventType.CLOSED
                )
                or (
                    isinstance(selection_prefix[-1], CampaignSelectionEvent)
                    and selection_prefix[-1].event_type
                    is CampaignSelectionEventType.SELECTION_FROZEN
                )
            ):
                selection_prefix = selection_prefix[:-1]
            ledger_node(
                report,
                "CAMPAIGN_SELECTION_REPORT",
                f"campaign-selection-{report.content_hash}",
                orchestrator.next_event_time(
                    min(event.occurred_at for event in selection_prefix),
                    selection_prefix,
                    bundle.initial_ledger_snapshot,
                ),
                parents=tuple(
                    sorted(
                        event.trial.content_hash
                        for event in selection_prefix
                        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
                    )
                ),
                verdict=report.content_hash,
            )
        _, runtime = principal_business_inventory(authority, business)
        for file in runtime.files:
            if file.logical_path == "offline-observation.json":
                raise HostedQualificationError(
                    "physical fault fixture has unrelated offline observation"
                )
            expected[file.logical_path] = file
    # The existing native Ledger verifier checks the event chain and object bytes.
    # Attribute only native trial/proposal/result/validation/selection object nodes.
    ledger = orchestrator.current_ledger_snapshot(state.spec.started_at, events)
    orchestrator.require_initial_snapshot_prefix(ledger)
    expected_objects = {*bundle.initial_ledger_snapshot.node_object_hashes, *ledger_objects}
    if set(ledger.node_object_hashes) != expected_objects:
        raise HostedQualificationError("native Ledger has unrelated or missing object nodes")
    added: set[str] = set()
    for path in actual:
        if path in expected or not path.startswith(prefix + "/ledger/events/"):
            continue
        data = read_relative(authority, path)
        event = ResearchLedgerEventV2.model_validate_json(data)
        ref = event.object_ref
        contract = ledger_objects.get(ref.object_hash)
        if (
            contract is None
            or ref.object_hash in added
            or event.ledger_id != bundle.ledger_id
            or ref.source_domain != "quantos-autonomous"
            or ref.campaign_hash != campaign
            or ref.media_type != "application/json"
            or ref.access.value != "CAMPAIGN_INTERNAL"
            or any(
                getattr(event, field) != value
                for field, value in ledger_metadata[ref.object_hash].items()
            )
            or path
            != (
                f"{prefix}/ledger/events/{bundle.ledger_id}/"
                f"{event.sequence:020d}-{event.event_id}.json"
            )
        ):
            raise HostedQualificationError("native Ledger event is unrelated or duplicated")
        added.add(ref.object_hash)
        include_contract(path, event)
        include_contract(
            f"{prefix}/ledger/objects/quantos-autonomous/sha256-{ref.object_hash}.json", contract
        )
    if added != set(ledger_objects) - set(bundle.initial_ledger_snapshot.node_object_hashes):
        raise HostedQualificationError("native Ledger attribution is incomplete")
    if expected != actual:
        raise HostedQualificationError("native authority has an unattributed raw file delta")
    return frozenset(expected)
