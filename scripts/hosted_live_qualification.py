#!/usr/bin/env python3
"""Author fixed P14-DQ hosted inputs; live driving requires the frozen HM-06 manager."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from scripts import p14dq_qualification as p14dq

from quantos.application.provenance import capture_code_provenance
from quantos.artifacts.store import (
    opened_directory,
    read_regular_bytes_at,
    regular_tree_files,
)
from quantos.contracts.autonomous import (
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousAgentRunPolicy,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedAgentResponse,
    HostedBudgetPolicy,
    HostObservation,
    HostReportedUsage,
)
from quantos.contracts.hosted_deployment import HostedLauncherConfiguration
from quantos.contracts.hosted_inputs import (
    HostedCampaignRecipe,
    HostedFrozenBusinessInputs,
    HostedFrozenInputFile,
)
from quantos.contracts.provenance import CodeProvenance
from quantos.infrastructure.hosted_deployment import (
    KnownValueGuard,
    export_projection,
    publish_projection_fact,
)
from quantos.infrastructure.hosted_launcher import (
    EXTRACTION_RULE_BYTES,
    TrustedCodexLauncher,
    TrustedLauncherEvidenceStore,
    register_model_auth_memory,
)
from quantos.infrastructure.hosted_manager import (
    HostedManagedDeployment,
    _memory,
    probe_managed_deployment,
    restricted_client_call,
    stage_hosted_deployment,
    start_managed_service,
    stop_managed_service,
)
from quantos.infrastructure.hosted_storage import storage_checkpoint


def _frozen_file(path: str, data: bytes) -> HostedFrozenInputFile:
    return HostedFrozenInputFile(logical_path=path, sha256=sha256_bytes(data), size_bytes=len(data))


def _hosted_policy_and_objects(
    configuration: HostedLauncherConfiguration,
) -> tuple[AutonomousAgentRunPolicy, dict[str, bytes]]:
    """Bind every pre-deployment policy hash to an actual immutable byte object."""
    objects = {
        "hosted/policy/capability.json": canonical_json_bytes(
            {"profile": "hm-mvp/v1", "host_channel": "authenticated-unix-only"}
        ),
        "hosted/policy/tools.json": canonical_json_bytes({"allowed_tools": []}),
        "hosted/policy/instructions.json": canonical_json_bytes(
            {"instruction": "one final frozen-candidate JSON proposal; no tools"}
        ),
        "hosted/policy/skills.json": canonical_json_bytes({"allowed_skills": []}),
        "hosted/policy/sandbox.json": canonical_json_bytes(
            {"cli_requested_sandbox": "read-only", "host_namespace": "hm-isolated-service/v1"}
        ),
        "hosted/policy/permission.json": canonical_json_bytes(
            {"effective_policy_attested": False, "source": "requested-configuration-only"}
        ),
        "hosted/policy/runtime.json": EXTRACTION_RULE_BYTES,
        "hosted/model-configuration.json": configuration.canonical_bytes(),
    }

    def digest(name: str) -> str:
        return sha256_bytes(objects[name])

    return (
        AutonomousAgentRunPolicy(
            capability_policy_hash=digest("hosted/policy/capability.json"),
            requested_model_configuration_hash=configuration.content_hash,
            tool_schema_hash=digest("hosted/policy/tools.json"),
            instruction_hashes=(digest("hosted/policy/instructions.json"),),
            skill_hash=digest("hosted/policy/skills.json"),
            sandbox_policy_hash=digest("hosted/policy/sandbox.json"),
            permission_policy_hash=digest("hosted/policy/permission.json"),
            runtime_policy_hash=digest("hosted/policy/runtime.json"),
            harness_identifier="host-mediated/v1",
            provider_model_identifier=configuration.model,
            model_snapshot_immutable=False,
        ),
        objects,
    )


def _author_p14dq_business_inputs_testable(
    workspace: Path,
    seed_root: Path,
    *,
    started_at: datetime,
    configuration: HostedLauncherConfiguration,
    code: CodeProvenance,
) -> tuple[HostedFrozenBusinessInputs, dict[str, bytes]]:
    """Build B from verified P14-DQ lineage; injected code is for tests only."""
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("hosted campaign anchor must be timezone-aware")
    workspace = workspace.resolve(strict=True)
    provenance = code
    if not provenance.worktree_clean:
        raise ValueError("hosted code provenance requires a clean checkout")
    inputs = p14dq.verify_external_inputs(
        workspace=workspace,
        snapshot_path=workspace / p14dq.SNAPSHOT_RELATIVE_PATH,
        view_path=workspace / p14dq.VIEW_RELATIVE_PATH,
        release_report_path=workspace / p14dq.UPSTREAM_RELEASE_RELATIVE_PATH,
    )
    policies = p14dq._load_policies(workspace)
    context = p14dq._build_case_context(
        seed_root, inputs, policies, provenance, workspace=workspace
    )
    agent_policy, objects = _hosted_policy_and_objects(configuration)
    for relative in (
        "docs/hosted/hosted-contract-v1.md",
        "docs/hosted/hosted-acceptance-v1.md",
        p14dq.UPSTREAM_RELEASE_RELATIVE_PATH.as_posix(),
        *(path.as_posix() for path in p14dq.POLICY_PATHS.values()),
    ):
        objects[relative] = (workspace / relative).read_bytes()
    seed_files = tuple(
        _frozen_file(path.relative_to(seed_root / "ledger").as_posix(), path.read_bytes())
        for path in regular_tree_files(seed_root / "ledger")
    )
    if not seed_files:
        raise ValueError("P14-DQ seed Ledger has no files")
    recipe = HostedCampaignRecipe(
        hosted_budget=HostedBudgetPolicy(
            max_requests=2,
            max_unique_submissions=4,
            max_submissions_per_request=2,
            max_response_bytes=262144,
            max_proposal_bytes=262144,
            max_request_bytes=1048576,
            request_ttl_seconds=3600,
        ),
        requested_model_configuration_hash=configuration.content_hash,
        contract_hash=sha256_bytes(objects["docs/hosted/hosted-contract-v1.md"]),
        acceptance_hash=sha256_bytes(objects["docs/hosted/hosted-acceptance-v1.md"]),
        started_at=started_at.astimezone(UTC),
    )
    bundle = HostedFrozenBusinessInputs(
        campaign=context.campaign,
        research_budget=context.budget,
        execution_bindings=context.execution_bindings,
        hosted_recipe=recipe,
        family=context.family,
        template=context.template,
        manifest=context.manifest,
        initial_ledger_snapshot=context.initial_ledger,
        initial_events=context.initial_events,
        ledger_id=context.ledger_id,
        search_policy=context.search_policy,
        context_budget=context.context_budget,
        campaign_policy=context.campaign_policy,
        agent_run_policy=agent_policy,
        selection_finalization_profile=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
        multiple_testing_policy=context.selection.multiple_testing_policy,
        selection_policy=context.selection.selection_policy,
        selection_plan=context.selection.build_plan(),
        authoring=context.adapter_args["base_authoring"],
        research_policy=policies.research,
        validation_policy=policies.validation,
        cost_policy=policies.cost,
        backtest_policy=policies.backtest,
        code_provenance=provenance,
        snapshot_directory=p14dq.SNAPSHOT_RELATIVE_PATH.as_posix(),
        qlib_view_directory=p14dq.VIEW_RELATIVE_PATH.as_posix(),
        initial_ledger_directory="seed-ledger",
        initial_ledger_files=seed_files,
        frozen_byte_objects=tuple(
            _frozen_file(path, data) for path, data in sorted(objects.items())
        ),
    )
    return bundle, objects


def author_p14dq_business_inputs(
    workspace: Path,
    seed_root: Path,
    *,
    started_at: datetime,
    configuration: HostedLauncherConfiguration,
) -> tuple[HostedFrozenBusinessInputs, dict[str, bytes]]:
    """Production B authoring from an exact clean checkout; no model or execution call."""
    provenance = capture_code_provenance(workspace)
    return _author_p14dq_business_inputs_testable(
        workspace,
        seed_root,
        started_at=started_at,
        configuration=configuration,
        code=provenance,
    )


def run_live_attempt(
    workspace: Path,
    root: Path,
    *,
    wheel: Path,
    base_python: Path,
    dependency_site: Path,
    codex_binary: Path,
    model_auth_file: Path,
) -> None:
    """Capture actual model output and drive only the restricted installed host CLI.

    The private root is retained on failure. This driver never awards a Q verdict.
    Auth is copied only to memory and the host's private tmpfs; its bytes/hash are
    absent from the exported attempt. No manually authored proposal is accepted.
    """
    if root.exists() or root.is_symlink():
        raise ValueError("live attempt root already exists")
    storage_checkpoint(root, "deployment")
    configuration = HostedLauncherConfiguration(
        model="gpt-6.1-sol",
        output_byte_cap=1_048_576,
        proposal_byte_cap=262144,
        runtime_timeout_seconds=900,
    )
    seed_root = root.parent / f"{root.name}-seed"
    if seed_root.exists() or seed_root.is_symlink():
        raise ValueError("live attempt seed root already exists")
    bundle, objects = author_p14dq_business_inputs(
        workspace, seed_root, started_at=datetime.now(UTC), configuration=configuration
    )
    deployment = stage_hosted_deployment(
        root,
        workspace,
        bundle,
        objects,
        seed_root / "ledger",
        wheel=wheel,
        base_python=base_python,
        dependency_site=dependency_site,
        codex_binary=codex_binary,
        launcher_configuration=configuration,
    )
    drive_live_campaign(deployment, model_auth_file=model_auth_file)


def drive_live_campaign(deployment: HostedManagedDeployment, *, model_auth_file: Path) -> None:
    """Drive an explicit staged deployment using original, directly captured model bytes."""
    root = deployment.root
    bundle = deployment.bundle
    configuration = deployment.launcher_configuration
    guard = KnownValueGuard((deployment.capability,))
    evidence = TrustedLauncherEvidenceStore(root / "evidence", guard=guard)
    auth_fd = None
    process = None
    captures: list[str] = []
    try:
        process = start_managed_service(deployment)
        status = restricted_client_call(deployment, "start")
        evidence.publish_bytes(canonical_json_bytes(status))
        from quantos.infrastructure.hosted_security_verification import verify_deployment_security
        from quantos.infrastructure.hosted_verification import raw_inventory, verify_raw_inventory

        before = raw_inventory(deployment.paths.authority)
        from quantos.infrastructure.hosted_manager import capture_authority_snapshot

        capture_authority_snapshot(deployment, "qualification-cases/Q01/before/authority")
        pending_before = restricted_client_call(deployment, "pending")
        before_wrapper_pid = process.pid
        stop_managed_service(deployment, process)
        process = None
        process = start_managed_service(deployment)
        after_wrapper_pid = process.pid
        queries: list[dict[str, object]] = []
        for _ in range(2):
            pending_after = restricted_client_call(deployment, "pending")
            if pending_after != pending_before:
                raise ValueError("process restart changed pending request bytes")
            queries.append(pending_after)
            queries.append(restricted_client_call(deployment, "status"))
            status = restricted_client_call(deployment, "resume")
            queries.append(status)
        verify_raw_inventory(deployment.paths.authority, before)
        capture_authority_snapshot(deployment, "qualification-cases/Q01/after/authority")
        evidence.publish_bytes(
            canonical_json_bytes(
                {
                    "schema_version": "hosted-manager-suspend-restart/v1",
                    "deployment_profile_hash": deployment.profile.content_hash,
                    "before_inventory": before.model_dump(mode="json"),
                    "after_inventory": raw_inventory(deployment.paths.authority).model_dump(
                        mode="json"
                    ),
                    "pending_before": pending_before,
                    "before_wrapper_pid": before_wrapper_pid,
                    "after_wrapper_pid": after_wrapper_pid,
                    "queries": queries,
                    "qualification_eligibility": "NOT_QUALIFIED",
                }
            )
        )
        probe_managed_deployment(deployment)
        verify_deployment_security(deployment)
        # Actual isolation must pass before acquisition of provider auth/model invocation.
        with opened_directory(model_auth_file.parent) as parent:
            auth_bytes = read_regular_bytes_at(parent, model_auth_file.name, max_bytes=1_048_576)
        auth_fd = _memory(auth_bytes, "hosted-model-auth")
        del auth_bytes
        register_model_auth_memory(auth_fd, guard)
        while status["state"] == "WAITING_FOR_AGENT":
            pending = restricted_client_call(deployment, "pending")
            request = HostedAgentRequest.model_validate(
                restricted_client_call(deployment, "request-export")
            )
            if pending.get("request_hash") != request.content_hash:
                raise ValueError("request export differs from pending identity")
            if request.hosted_spec_hash != deployment.spec.content_hash:
                raise ValueError("restricted host received a different frozen request")
            projection_root = root / "request-projections" / request.content_hash
            context_bytes = request.business_request.context_pack.canonical_bytes()
            schema_bytes = request.business_request.allowed_proposal_schema_json.encode("utf-8")
            projection = export_projection(
                projection_root,
                request,
                {
                    request.context_pack_hash: context_bytes,
                    request.proposal_schema_hash: schema_bytes,
                },
                guard=guard,
            )
            fact = publish_projection_fact(
                request,
                deployment.spec,
                profile=deployment.profile,
                initial_inventory=deployment.initial_projection,
                projection_root=projection_root,
                host_instance=deployment.host_instance,
                publish_bytes=evidence.publish_bytes,
            )
            launcher = TrustedCodexLauncher(
                replace(deployment.paths, projection=projection_root),
                deployment.profile,
                deployment.install,
                configuration,
                evidence,
            )
            os.lseek(auth_fd, 0, os.SEEK_SET)
            record, proposal = launcher.capture(
                request,
                deployment.spec,
                projection,
                deployment.initial_projection,
                projection_fact_hash=fact.content_hash,
                host_instance=deployment.host_instance,
                model_auth_memory_fd=auth_fd,
            )
            captures.append(record.content_hash)
            if proposal is None or record.outcome != "CAPTURED":
                raise ValueError("actual model capture did not yield a valid proposal")
            observation = HostObservation(
                requested_configuration_hash=configuration.content_hash,
                reported_model_identifier=record.actual_model_identifier,
                reported_reasoning_effort=configuration.reasoning_effort,
                reported_usage=HostReportedUsage(
                    unavailable_reason="HOST_INTERNAL_USAGE_UNAVAILABLE"
                ),
                transcript_hash=record.raw_output_hash,
                external_evidence_hashes=(record.content_hash,),
                unavailable_reasons=(
                    "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                    "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                    "HOST_INTERNAL_USAGE_UNAVAILABLE",
                ),
            )
            response = HostedAgentResponse(
                request_hash=request.content_hash,
                campaign_hash=request.campaign_hash,
                transport_ordinal=request.transport_ordinal,
                context_pack_hash=request.context_pack_hash,
                attempt_identity=request.attempt_identity,
                proposal_json=proposal.decode("utf-8"),
                proposal_hash=sha256_bytes(proposal),
                host_observation=observation,
            )
            guard(response.canonical_bytes())
            receipt = restricted_client_call(
                deployment,
                "submit",
                projection_root=projection_root,
                request_hash=request.content_hash,
                response_bytes=response.canonical_bytes(),
            )
            evidence.publish_bytes(canonical_json_bytes(receipt))
            if receipt["outcome"] != "ACCEPTED":
                raise ValueError("captured original proposal was transport rejected")
            status = restricted_client_call(deployment, "resume", projection_root=projection_root)
            evidence.publish_bytes(canonical_json_bytes(status))
        evidence.publish_bytes(
            canonical_json_bytes(
                {
                    "source": "TRUSTED_EXTERNAL_MANAGER",
                    "qualification_eligibility": "NOT_QUALIFIED",
                    "deployment_profile_hash": deployment.profile.content_hash,
                    "hosted_spec_hash": deployment.spec.content_hash,
                    "campaign_hash": bundle.campaign.content_hash,
                    "launcher_record_hashes": captures,
                    "terminal_status": status,
                }
            )
        )
    finally:
        if auth_fd is not None:
            os.close(auth_fd)
        if process is not None:
            stop_managed_service(deployment, process)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--base-python", type=Path, required=True)
    parser.add_argument("--dependency-site", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--model-auth-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        run_live_attempt(
            args.workspace,
            args.root,
            wheel=args.wheel,
            base_python=args.base_python,
            dependency_site=args.dependency_site,
            codex_binary=args.codex_binary,
            model_auth_file=args.model_auth_file,
        )
    except Exception as error:
        # Arbitrary provider/validation exceptions can contain response/auth values.
        # Only the type is public. Failed durable roots and safe source records remain.
        print(
            canonical_json_bytes(
                {
                    "attempt": "FAILED",
                    "error_type": type(error).__name__,
                    "qualification_eligibility": "NOT_QUALIFIED",
                }
            ).decode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
