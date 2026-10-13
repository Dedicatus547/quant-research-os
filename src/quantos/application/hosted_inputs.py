"""Fixed production bootstrap for pre-registered immutable hosted research inputs."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from quantos.application.autonomous import AutonomousCampaignOrchestrator
from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.campaign_selection import (
    CampaignSelectionService,
    verify_selection_plan_artifact,
)
from quantos.application.campaigns import ResearchCampaignGovernor
from quantos.application.hosted_campaign import (
    HostedCampaignApplicationService,
    HostedCampaignInputs,
)
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.application.ledger import ResearchLedgerService
from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    opened_directory,
    read_regular_bytes_at,
    regular_tree_files,
)
from quantos.contracts.autonomous import AutonomousAgentRequest, AutonomousAgentResponse
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import HostedCampaignSpec, parse_hosted_contract
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    HostedFrozenInputFile,
    derive_hosted_campaign_spec,
)
from quantos.contracts.p14dq_qualification import (
    P14DQ_CANDIDATE_HASHES,
    P14DQ_CANDIDATE_MANIFEST_HASH,
    P14DQ_FAMILY_HASH,
    P14DQ_TEMPLATE_HASH,
    P14DQ_UPSTREAM_RELEASE_REPORT_HASH,
)
from quantos.contracts.sdk_producer import (
    SdkCampaignSpec,
    SdkHostedBudgetPolicyV3,
    SdkProducerProfileV3,
)
from quantos.data import verify_qlib_view, verify_snapshot

_BUNDLE_CAP = 4_194_304


def build_hosted_execution_adapter(
    bundle: HostedFrozenBusinessInputs,
    *,
    input_root: Path,
    runtime_root: Path,
    provenance_workspace: Path,
    sdk_spec: SdkCampaignSpec | None = None,
) -> QuantosResearchExecutionAdapter:
    """Construct the existing adapter for execution or read-only offline inspection."""
    return QuantosResearchExecutionAdapter(
        campaign=bundle.campaign,
        family=bundle.family,
        budget=bundle.research_budget,
        template=bundle.template,
        manifest=bundle.manifest,
        snapshot_path=input_root / bundle.snapshot_directory,
        qlib_view_path=input_root / bundle.qlib_view_directory,
        base_authoring=bundle.authoring,
        research_policy=bundle.research_policy,
        validation_policy=bundle.validation_policy,
        cost_policy=bundle.cost_policy,
        backtest_policy=bundle.backtest_policy,
        bindings=bundle.execution_bindings,
        output_root=runtime_root / "execution",
        workspace=provenance_workspace,
        canonical_validation=True,
        p14dq_v2_profile=True,
        sdk_campaign_spec=sdk_spec,
    )


class HostedProposalOnlyDriver:
    def run(self, request: AutonomousAgentRequest) -> AutonomousAgentResponse:
        raise ArtifactIntegrityError("hosted proposals must enter through persisted protocol bytes")


def _read_file(root: Path, relative: str, *, max_bytes: int) -> bytes:
    """Resolve every input component below a pinned service-owned directory."""
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ArtifactIntegrityError("invalid frozen input relative path")
    descriptors: list[int] = []
    with opened_directory(root) as root_fd:
        parent = root_fd
        try:
            for part in parts[:-1]:
                parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(parent)
            return read_regular_bytes_at(parent, parts[-1], max_bytes=max_bytes)
        except OSError as error:
            raise ArtifactIntegrityError("frozen input path is unavailable or unsafe") from error
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)


def _verify_file(root: Path, item: HostedFrozenInputFile) -> bytes:
    data = _read_file(root, item.logical_path, max_bytes=item.size_bytes)
    if len(data) != item.size_bytes or sha256_bytes(data) != item.sha256:
        raise ArtifactIntegrityError("frozen input file bytes differ from inventory")
    return data


def _publish_seed_file(ledger_root: Path, item: HostedFrozenInputFile, data: bytes) -> None:
    """Materialize frozen seed bytes without rewriting existing directory facts."""
    if len(data) != item.size_bytes or sha256_bytes(data) != item.sha256:
        raise ArtifactIntegrityError("seed ledger bytes differ from frozen input")
    destination = ledger_root / item.logical_path
    with opened_directory(destination.parent, create=True) as descriptor:
        atomic_write_bytes_at(descriptor, destination.name, data)


def _verify_bundle(
    config: HostedBusinessLoaderConfiguration,
    bundle: HostedFrozenBusinessInputs,
    *,
    sdk: bool = False,
) -> None:
    root = Path(config.input_root)
    data = _read_file(root, f"sha256-{config.business_inputs_hash}.json", max_bytes=_BUNDLE_CAP)
    if data != bundle.canonical_bytes() or sha256_bytes(data) != config.business_inputs_hash:
        raise ArtifactIntegrityError("business input bundle changed after registration")
    for item in bundle.frozen_byte_objects:
        _verify_file(root, item)
    required_bytes = {
        bundle.hosted_recipe.contract_hash,
        bundle.hosted_recipe.acceptance_hash,
        bundle.hosted_recipe.requested_model_configuration_hash,
        P14DQ_UPSTREAM_RELEASE_REPORT_HASH,
    }
    if not required_bytes.issubset({item.sha256 for item in bundle.frozen_byte_objects}):
        raise ArtifactIntegrityError(
            "contract, upstream release or model configuration bytes are missing"
        )
    if (
        bundle.family.content_hash != P14DQ_FAMILY_HASH
        or bundle.template.content_hash != P14DQ_TEMPLATE_HASH
        or bundle.manifest.content_hash != P14DQ_CANDIDATE_MANIFEST_HASH
        or tuple(candidate.content_hash for candidate in bundle.manifest.candidates)
        != P14DQ_CANDIDATE_HASHES
    ):
        raise ArtifactIntegrityError(
            "production hosted input escaped the fixed two-candidate family"
        )
    if (
        bundle.agent_run_policy.harness_identifier
        != ("openai-codex-python-sdk" if sdk else "host-mediated/v1")
        or bundle.agent_run_policy.model_snapshot_immutable
    ):
        raise ArtifactIntegrityError(
            "production hosted request policy claims old or immutable runtime"
        )
    snapshot_path = root / bundle.snapshot_directory
    view_path = root / bundle.qlib_view_directory
    # These existing bottom-up verifiers inspect immutable Parquet and derived
    # Qlib cache inventories. No acquisition, model call or Qlib execution occurs.
    snapshot = verify_snapshot(snapshot_path)
    view = verify_qlib_view(view_path)
    if (
        snapshot.snapshot_hash != bundle.campaign.snapshot_hash
        or view.view_hash != bundle.campaign.qlib_view_hash
        or view.source_snapshot_hash != snapshot.snapshot_hash
        or snapshot.dataset_id != bundle.execution_bindings.dataset_id
        or view.qlib_version != bundle.execution_bindings.qlib_version
        or bundle.campaign.feature_artifact_hashes
    ):
        raise ArtifactIntegrityError(
            "frozen snapshot/view bindings differ or unsupported features exist"
        )
    seed_root = root / bundle.initial_ledger_directory
    actual_paths = tuple(
        sorted(path.relative_to(seed_root).as_posix() for path in regular_tree_files(seed_root))
    )
    if actual_paths != tuple(item.logical_path for item in bundle.initial_ledger_files):
        raise ArtifactIntegrityError("frozen seed Ledger inventory changed")
    for item in bundle.initial_ledger_files:
        _verify_file(seed_root, item)
    seed = ResearchLedgerService(seed_root).verify(
        bundle.ledger_id,
        created_at=bundle.initial_ledger_snapshot.created_at,
    )
    if seed.canonical_bytes() != bundle.initial_ledger_snapshot.canonical_bytes():
        raise ArtifactIntegrityError("frozen seed Ledger differs from initial campaign snapshot")
    verify_code_provenance(
        Path(config.provenance_workspace),
        expected_commit_hash=bundle.code_provenance.commit_hash,
        expected_lockfile_hash=bundle.code_provenance.lockfile_hash,
    )


def load_hosted_campaign_application(
    config: HostedBusinessLoaderConfiguration,
    protocol: HostedProtocolService,
    business_lock_root: Path,
    *,
    deployment_profile_hash: str,
    fault_hook: Callable[[str], None] | None = None,
    sdk_spec: SdkCampaignSpec | None = None,
) -> HostedCampaignApplicationService:
    """Load one frozen MVP registration from management-owned configuration.

    The service wheel imports this fixed function. Paths are read-only management
    configuration; no host operation accepts a path, factory name, code or hook.
    The protocol's verify_inputs callback must call the returned application's
    verify_registered_inputs (a construction-time holder may resolve the cycle).
    """
    root = Path(config.input_root)
    encoded = _read_file(root, f"sha256-{config.business_inputs_hash}.json", max_bytes=_BUNDLE_CAP)
    if sha256_bytes(encoded) != config.business_inputs_hash:
        raise ArtifactIntegrityError("frozen business input bundle hash differs")
    bundle = parse_hosted_contract(encoded, HostedFrozenBusinessInputs, max_bytes=_BUNDLE_CAP)
    _verify_bundle(config, bundle, sdk=sdk_spec is not None)
    spec = derive_hosted_campaign_spec(bundle, deployment_profile_hash=deployment_profile_hash)
    if sdk_spec is not None:
        sdk_spec = SdkCampaignSpec.model_validate(sdk_spec.model_dump(mode="python"))
        expected = spec.model_dump(mode="json")
        if isinstance(sdk_spec.sdk_profile, SdkProducerProfileV3):
            expected["hosted_budget"] = SdkHostedBudgetPolicyV3.model_validate(
                {
                    **spec.hosted_budget.model_dump(mode="json"),
                    "schema_version": "sdk-hosted-budget-policy/v3",
                    "max_response_bytes": 524288,
                }
            ).model_dump(mode="json")
        actual = sdk_spec.model_dump(mode="json")
        for name in ("schema_version", "profile", "sdk_profile"):
            expected.pop(name, None)
            actual.pop(name, None)
        if actual != expected:
            raise ArtifactIntegrityError("SDK successor spec differs from verified business inputs")
        spec = sdk_spec
    runtime = Path(config.business_root) / bundle.campaign.content_hash
    seed_root = root / bundle.initial_ledger_directory
    ledger_root = runtime / "ledger"
    for item in bundle.initial_ledger_files:
        _publish_seed_file(ledger_root, item, _verify_file(seed_root, item))
    ledger = ResearchLedgerService(ledger_root)
    execution = build_hosted_execution_adapter(
        bundle,
        input_root=root,
        runtime_root=runtime,
        provenance_workspace=Path(config.provenance_workspace),
        sdk_spec=sdk_spec,
    )
    selection = CampaignSelectionService(
        bundle.campaign,
        bundle.family,
        bundle.research_budget,
        bundle.template,
        bundle.manifest,
        bundle.multiple_testing_policy,
        bundle.selection_policy,
        root / bundle.qlib_view_directory,
        (execution.research_results_root,),
        plan=bundle.selection_plan,
    )
    if selection.build_plan() != bundle.selection_plan:
        raise ArtifactIntegrityError("frozen selection plan does not match verified inputs")
    governor = ResearchCampaignGovernor(bundle.family, bundle.template, bundle.manifest)
    activation, frozen_plan_event = bundle.initial_events
    rebuilt_event, rebuilt_path = selection.freeze_plan(
        governor,
        (activation,),
        event_id=frozen_plan_event.event_id,
        occurred_at=frozen_plan_event.occurred_at,
        artifact_root=runtime / "selection-plans",
    )
    if (
        rebuilt_event != frozen_plan_event
        or verify_selection_plan_artifact(rebuilt_path) != bundle.selection_plan
    ):
        raise ArtifactIntegrityError("initial selection event or plan differs from frozen inputs")
    orchestrator = AutonomousCampaignOrchestrator(
        campaign=bundle.campaign,
        family=bundle.family,
        budget=bundle.research_budget,
        template=bundle.template,
        manifest=bundle.manifest,
        initial_ledger_snapshot=bundle.initial_ledger_snapshot,
        ledger_service=ledger,
        ledger_id=bundle.ledger_id,
        search_policy=bundle.search_policy,
        context_budget=bundle.context_budget,
        campaign_policy=bundle.campaign_policy,
        agent_run_policy=bundle.agent_run_policy,
        agent_driver=HostedProposalOnlyDriver(),
        execution_port=execution,
        exchange_root=runtime / "legacy-exchanges-unused",
        event_root=runtime / "campaign-events",
        selection_service=selection,
        selection_artifact_root=runtime / "selection-reports",
        autonomous_report_root=runtime / "legacy-loop-reports-unused",
        execution_bindings=bundle.execution_bindings,
        selection_finalization_profile=bundle.selection_finalization_profile,
    )
    service = HostedCampaignApplicationService(
        protocol, business_lock_root=business_lock_root, fault_hook=fault_hook
    )

    frozen_spec = spec

    def reverify(spec: HostedCampaignSpec) -> None:
        if spec != frozen_spec:
            raise ArtifactIntegrityError(
                "registered hosted spec differs from frozen business bundle"
            )
        _verify_bundle(config, bundle, sdk=sdk_spec is not None)

    service.register_inputs(
        spec, HostedCampaignInputs(orchestrator, bundle.initial_events, reverify)
    )
    service.verify_registered_inputs(spec)
    return service
