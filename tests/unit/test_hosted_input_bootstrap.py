"""Native frozen-input bootstrap on synthetic immutable Parquet/ledger fixtures.

Only fixed production family and upstream identities are substituted for this
component. Real byte, snapshot/view, plan, ledger and provenance checks remain;
this synthetic campaign cannot grant production or hosted qualification.
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest

from quantos.application import hosted_inputs as loader
from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.application.provenance import capture_code_provenance
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, regular_tree_files
from quantos.contracts.autonomous import AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import HostedBudgetPolicy
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedCampaignRecipe,
    HostedFrozenBusinessInputs,
    HostedFrozenInputFile,
)
from quantos.contracts.hosted_qualification import HOSTED_ACCEPTANCE_SHA256, HOSTED_CONTRACT_SHA256
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import raw_inventory


def _inputs(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integration"))
    fixtures = importlib.import_module("test_autonomous_execution_e2e")
    dates = fixtures._synthetic_fixture(root / "fixture")
    snapshot_source = fixtures._fixture_hash_directory(fixtures.E2E_SNAPSHOT_FIXTURE_ROOT)[0]
    view_source = fixtures._fixture_hash_directory(fixtures.E2E_VIEW_FIXTURE_ROOT)[0]
    snapshot_path, view_path = (
        root / "snapshot" / snapshot_source.name,
        root / "view" / view_source.name,
    )
    shutil.copytree(snapshot_source, snapshot_path)
    shutil.copytree(view_source, view_path)
    snapshot, view = verify_snapshot(snapshot_path), verify_qlib_view(view_path)
    values = fixtures._contracts(
        root,
        dates,
        snapshot,
        snapshot_path,
        snapshot.snapshot_hash,
        view,
        view.view_hash,
        view_path,
        soft_reject=True,
    )
    (
        ledger_id,
        initial_ledger,
        _ledger,
        campaign,
        family,
        budget,
        template,
        manifest,
        search_policy,
        context_budget,
        campaign_policy,
        agent_policy,
        selection,
        initial_events,
        arguments,
        *_rest,
    ) = values
    objects = {
        f"policies/{name}.json": arguments[name].canonical_bytes()
        for name in ("research_policy", "validation_policy", "cost_policy", "backtest_policy")
    }
    repository = Path(__file__).parents[2]
    objects["contract.md"] = (repository / "docs/hosted/hosted-contract-v1.md").read_bytes()
    objects["acceptance.md"] = (repository / "docs/hosted/hosted-acceptance-v1.md").read_bytes()
    assert sha256_bytes(objects["contract.md"]) == HOSTED_CONTRACT_SHA256
    assert sha256_bytes(objects["acceptance.md"]) == HOSTED_ACCEPTANCE_SHA256
    objects["model.json"] = b'{"synthetic_model_configuration":true}'
    objects["upstream.json"] = b'{"synthetic_upstream":true}'
    agent_policy = agent_policy.model_copy(
        update={
            "requested_model_configuration_hash": sha256_bytes(objects["model.json"]),
            "harness_identifier": "host-mediated/v1",
            "model_snapshot_immutable": False,
        }
    )
    for path, data in objects.items():
        atomic_write_bytes(root / path, data)
    seed_files = tuple(
        HostedFrozenInputFile(
            logical_path=path.relative_to(root / "ledger").as_posix(),
            sha256=sha256_bytes(path.read_bytes()),
            size_bytes=path.stat().st_size,
        )
        for path in regular_tree_files(root / "ledger")
    )
    bundle = HostedFrozenBusinessInputs(
        campaign=campaign,
        research_budget=budget,
        execution_bindings=arguments["bindings"],
        hosted_recipe=HostedCampaignRecipe(
            hosted_budget=HostedBudgetPolicy(
                max_requests=2,
                max_unique_submissions=4,
                max_submissions_per_request=2,
                max_response_bytes=262144,
                max_proposal_bytes=262144,
                max_request_bytes=1048576,
                request_ttl_seconds=3600,
            ),
            requested_model_configuration_hash=agent_policy.requested_model_configuration_hash,
            contract_hash=HOSTED_CONTRACT_SHA256,
            acceptance_hash=HOSTED_ACCEPTANCE_SHA256,
            started_at=fixtures.NOW,
        ),
        family=family,
        template=template,
        manifest=manifest,
        initial_ledger_snapshot=initial_ledger,
        initial_events=initial_events,
        ledger_id=ledger_id,
        search_policy=search_policy,
        context_budget=context_budget,
        campaign_policy=campaign_policy,
        agent_run_policy=agent_policy,
        selection_finalization_profile=AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE,
        multiple_testing_policy=selection.multiple_testing_policy,
        selection_policy=selection.selection_policy,
        selection_plan=selection.plan,
        authoring=arguments["base_authoring"],
        research_policy=arguments["research_policy"],
        validation_policy=arguments["validation_policy"],
        cost_policy=arguments["cost_policy"],
        backtest_policy=arguments["backtest_policy"],
        code_provenance=capture_code_provenance(root / "provenance"),
        snapshot_directory=snapshot_path.relative_to(root).as_posix(),
        qlib_view_directory=view_path.relative_to(root).as_posix(),
        initial_ledger_directory="ledger",
        initial_ledger_files=seed_files,
        frozen_byte_objects=tuple(
            HostedFrozenInputFile(
                logical_path=path, sha256=sha256_bytes(data), size_bytes=len(data)
            )
            for path, data in sorted(objects.items())
        ),
    )
    monkeypatch.setattr(
        loader, "P14DQ_UPSTREAM_RELEASE_REPORT_HASH", sha256_bytes(objects["upstream.json"])
    )
    return bundle, arguments


def _configuration(root, runtime, bundle):
    atomic_write_bytes(root / f"sha256-{bundle.content_hash}.json", bundle.canonical_bytes())
    return HostedBusinessLoaderConfiguration(
        business_inputs_hash=bundle.content_hash,
        input_root=str(root),
        business_root=str(runtime),
        provenance_workspace=str(root / "provenance"),
    )


def test_native_loader_reverifies_immutable_seed_plan_and_source_before_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, adapter_arguments = _inputs(tmp_path / "inputs", monkeypatch)
    # The production adapter correctly rejects this synthetic family under its
    # P14-DQ profile. Use the existing synthetic adapter configuration only for
    # loader composition; neither adapter nor Workflow executes in this test.
    monkeypatch.setattr(
        loader,
        "build_hosted_execution_adapter",
        lambda *_args, **kwargs: QuantosResearchExecutionAdapter(
            **{**adapter_arguments, "output_root": kwargs["runtime_root"] / "execution"}
        ),
    )
    config = _configuration(tmp_path / "inputs", tmp_path / "runtime", bundle)
    # The real production family gate must reject this synthetic input first.
    with pytest.raises(ArtifactIntegrityError, match="fixed two-candidate family"):
        loader._verify_bundle(config, bundle)
    for name, value in (
        ("P14DQ_FAMILY_HASH", bundle.family.content_hash),
        ("P14DQ_TEMPLATE_HASH", bundle.template.content_hash),
        ("P14DQ_CANDIDATE_MANIFEST_HASH", bundle.manifest.content_hash),
        ("P14DQ_CANDIDATE_HASHES", tuple(x.content_hash for x in bundle.manifest.candidates)),
    ):
        monkeypatch.setattr(loader, name, value)
    original = raw_inventory(Path(config.input_root))
    holder = []
    protocol = HostedProtocolService(
        HostedProtocolStore(tmp_path / "protocol"),
        clock=lambda: bundle.hosted_recipe.started_at,
        verify_inputs=lambda spec: holder[0].verify_registered_inputs(spec),
    )
    service = loader.load_hosted_campaign_application(
        config, protocol, tmp_path / "locks", deployment_profile_hash="d" * 64
    )
    holder.append(service)
    status = service.start(service.registered_spec(bundle.campaign.content_hash).content_hash)
    assert status.state == "WAITING_FOR_AGENT"
    request = service.pending(bundle.campaign.content_hash)
    assert request is not None
    assert request.proposal_schema_hash in request.projection_object_hashes
    assert raw_inventory(Path(config.input_root)) == original
    native = service.verify_research_facts(protocol.store.snapshot(bundle.campaign.content_hash))
    assert not native.steps and not native.reports
    for damage in (
        "required_object",
        "family",
        "harness",
        "immutable_model",
        "snapshot_binding",
        "view_binding",
        "dataset_binding",
        "extra_seed",
    ):
        candidate = bundle
        if damage == "required_object":
            candidate = bundle.model_copy(
                update={
                    "frozen_byte_objects": tuple(
                        item
                        for item in bundle.frozen_byte_objects
                        if item.logical_path != "model.json"
                    )
                }
            )
        elif damage == "family":
            candidate = bundle.model_copy(
                update={
                    "family": bundle.family.model_copy(
                        update={"family_id": "unfrozen-synthetic-family"}
                    )
                }
            )
        elif damage in {"harness", "immutable_model"}:
            candidate = bundle.model_copy(
                update={
                    "agent_run_policy": bundle.agent_run_policy.model_copy(
                        update={"harness_identifier": "untrusted-runtime"}
                        if damage == "harness"
                        else {"model_snapshot_immutable": True}
                    )
                }
            )
        elif damage in {"snapshot_binding", "view_binding"}:
            candidate = bundle.model_copy(
                update={
                    "campaign": bundle.campaign.model_copy(
                        update={
                            "snapshot_hash"
                            if damage == "snapshot_binding"
                            else "qlib_view_hash": "0" * 64
                        }
                    )
                }
            )
        elif damage == "dataset_binding":
            candidate = bundle.model_copy(
                update={
                    "execution_bindings": bundle.execution_bindings.model_copy(
                        update={"dataset_id": "unfrozen-synthetic-dataset"}
                    )
                }
            )
        else:
            (Path(config.input_root) / bundle.initial_ledger_directory / "unlisted").write_bytes(
                b"unlisted seed"
            )
        candidate_config = _configuration(
            Path(config.input_root), tmp_path / "other-runtime", candidate
        )
        with pytest.raises(ArtifactIntegrityError):
            loader._verify_bundle(candidate_config, candidate)
        if damage == "extra_seed":
            (Path(config.input_root) / bundle.initial_ledger_directory / "unlisted").unlink()
    with pytest.raises(ArtifactIntegrityError, match="persisted protocol bytes"):
        loader.HostedProposalOnlyDriver().run(request.business_request)
    first = bundle.initial_ledger_files[0]
    seed = Path(config.input_root) / bundle.initial_ledger_directory / first.logical_path
    seed.write_bytes(b"changed immutable seed")
    with pytest.raises(ArtifactIntegrityError):
        service.resume(bundle.campaign.content_hash)
