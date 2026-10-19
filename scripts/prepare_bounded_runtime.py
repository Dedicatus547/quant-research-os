#!/usr/bin/env python3
"""Freeze one legacy two-candidate task offline; large immutable inputs are RO mounts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantos.application.autonomous_execution import (  # noqa: E402
    build_autonomous_execution_bindings,
)
from quantos.application.campaign_selection import CampaignSelectionService  # noqa: E402
from quantos.application.campaigns import ResearchCampaignGovernor  # noqa: E402
from quantos.application.provenance import capture_code_provenance  # noqa: E402
from quantos.application.sdk_producer import model_configuration  # noqa: E402
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file  # noqa: E402
from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.contracts.hosted_inputs import (  # noqa: E402
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    HostedFrozenInputFile,
    derive_hosted_campaign_spec,
)
from quantos.contracts.qlib_view import QlibViewManifest  # noqa: E402
from quantos.contracts.sdk_producer import SdkCampaignSpec, SdkProducerProfileV4  # noqa: E402
from quantos.contracts.snapshot import DataSnapshotManifest  # noqa: E402


def prepare(args):
    """No acquisition, model/science execution, input copying or historical allowance reuse."""
    environment = None
    environment_root = getattr(args, "runtime_environment", None)
    environment_profile = getattr(args, "runtime_profile", None)
    if (environment_root is None) != (environment_profile is None):
        raise ValueError("explicit environment and profile must be supplied together")
    if environment_root is not None:
        from quantos.infrastructure.runtime_environment import bind_environment

        environment = bind_environment(environment_root, environment_profile, ROOT)
    template_bytes = args.template.read_bytes()
    spec_bytes = args.template_spec.read_bytes()
    if (
        sha256_bytes(template_bytes) != args.template_sha256
        or sha256_bytes(spec_bytes) != args.template_spec_sha256
    ):
        raise ValueError("template pins differ")
    old = HostedFrozenBusinessInputs.model_validate_json(template_bytes)
    template_spec = SdkCampaignSpec.model_validate_json(spec_bytes)
    if template_bytes != old.canonical_bytes() or spec_bytes != template_spec.canonical_bytes():
        raise ValueError("canonical templates required")
    if (
        not isinstance(template_spec.sdk_profile, SdkProducerProfileV4)
        or template_spec.campaign_hash != old.campaign.content_hash
        or old.research_budget.max_executions != 2
        or old.research_budget.max_compute_seconds != 36
        or args.campaign_id == old.campaign.campaign_id
    ):
        raise ValueError("only the reviewed legacy 2-execution/36-unit shape is supported")
    started = datetime.fromisoformat(args.started_at)
    if started.tzinfo is None:
        raise ValueError("task timestamp requires timezone")
    code = capture_code_provenance(ROOT)
    if code.commit_hash != args.expected_commit:
        raise ValueError("release commit differs")
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = args.output / "inputs"
    inputs.mkdir()
    metadata = args.output / "metadata"
    metadata.mkdir()
    snapshot = DataSnapshotManifest.model_validate_json(
        confined_regular_file(
            args.source_inputs, old.snapshot_directory + "/manifest.json"
        ).read_bytes()
    )
    view = QlibViewManifest.model_validate_json(
        confined_regular_file(
            args.source_inputs, old.qlib_view_directory + "/manifest.json"
        ).read_bytes()
    )
    bindings = build_autonomous_execution_bindings(
        snapshot=snapshot,
        qlib_view=view,
        research_policy=old.research_policy,
        validation_policy=old.validation_policy,
        authoring=old.authoring,
        cost_policy=old.cost_policy,
        backtest_policy=old.backtest_policy,
        code_commit_hash=code.commit_hash,
        lockfile_hash=code.lockfile_hash,
    )
    # Only small frozen objects and seed bytes are copied. Never mutate the source collection.
    for item in old.frozen_byte_objects:
        data = confined_regular_file(args.source_inputs, item.logical_path).read_bytes()
        if len(data) != item.size_bytes or sha256_bytes(data) != item.sha256:
            raise ValueError("frozen object differs")
        atomic_write_bytes(inputs / item.logical_path, data)
    for item in old.initial_ledger_files:
        relative = old.initial_ledger_directory + "/" + item.logical_path
        data = confined_regular_file(args.source_inputs, relative).read_bytes()
        if len(data) != item.size_bytes or sha256_bytes(data) != item.sha256:
            raise ValueError("seed object differs")
        atomic_write_bytes(inputs / relative, data)
    profile = template_spec.sdk_profile.model_copy(
        update={
            "cwd": str(args.output / "empty-sdk-cwd"),
            "evidence_root": str(args.output / "sdk-evidence"),
        }
    )
    Path(profile.cwd).mkdir()
    config_bytes = model_configuration(profile)
    config_hash = sha256_bytes(config_bytes)
    profile = profile.model_copy(update={"requested_model_configuration_hash": config_hash})
    logical = "bounded-runtime/model-configuration.json"
    atomic_write_bytes(inputs / logical, config_bytes)
    budget = old.research_budget.model_copy(update={"budget_id": args.campaign_id + "-budget"})
    # Retain exposure/contamination ancestry, but never carry SDK launch counters/authority.
    campaign = old.campaign.model_copy(
        update={
            "campaign_id": args.campaign_id,
            "budget_hash": budget.content_hash,
            "parent_campaign_hash": old.campaign.content_hash,
            "inherited_contamination": tuple(
                sorted(
                    {
                        *old.campaign.inherited_contamination,
                        old.campaign.content_hash,
                    }
                )
            ),
        }
    )
    selection = CampaignSelectionService(
        campaign,
        old.family,
        budget,
        old.template,
        old.manifest,
        old.multiple_testing_policy,
        old.selection_policy,
        args.source_inputs / old.qlib_view_directory,
    )
    governor = ResearchCampaignGovernor(old.family, old.template, old.manifest)
    activation = governor.activate(
        campaign,
        old.family,
        budget,
        (),
        event_id=uuid5(NAMESPACE_URL, campaign.content_hash + ":activation"),
        occurred_at=started,
    )
    plan_event, _ = selection.freeze_plan(
        governor,
        (activation,),
        event_id=uuid5(NAMESPACE_URL, campaign.content_hash + ":plan"),
        occurred_at=started,
        artifact_root=metadata / "selection-plans",
    )
    bundle = old.model_copy(
        update={
            "campaign": campaign,
            "research_budget": budget,
            "selection_plan": selection.plan,
            "initial_events": (activation, plan_event),
            "code_provenance": code,
            "execution_bindings": bindings,
            "campaign_policy": old.campaign_policy.model_copy(
                update={
                    "readable_campaign_hashes": tuple(
                        sorted(
                            {
                                *old.campaign_policy.readable_campaign_hashes,
                                campaign.content_hash,
                                old.campaign.content_hash,
                            }
                        )
                    ),
                }
            ),
            "agent_run_policy": old.agent_run_policy.model_copy(
                update={
                    "requested_model_configuration_hash": config_hash,
                }
            ),
            "hosted_recipe": old.hosted_recipe.model_copy(
                update={
                    "started_at": started,
                    "requested_model_configuration_hash": config_hash,
                }
            ),
            "frozen_byte_objects": tuple(
                sorted(
                    (
                        *old.frozen_byte_objects,
                        HostedFrozenInputFile(
                            logical_path=logical,
                            sha256=config_hash,
                            size_bytes=len(config_bytes),
                        ),
                    ),
                    key=lambda item: item.logical_path,
                )
            ),
        }
    )
    bundle = HostedFrozenBusinessInputs.model_validate(bundle.model_dump(mode="python"))
    config = HostedBusinessLoaderConfiguration(
        business_inputs_hash=bundle.content_hash,
        input_root=str(inputs),
        business_root=str(args.output / "business-runtime"),
        provenance_workspace=str(ROOT),
    )
    deployment = {
        "release_commit": code.commit_hash,
        "lockfile_hash": code.lockfile_hash,
        "science_profile": "p14dq-frozen/v1",
        "sdk_profile_hash": profile.content_hash,
        "qualification": "NOT_QUALIFIED",
    }
    if environment is not None:
        deployment["runtime_environment"] = environment
    value = derive_hosted_campaign_spec(
        bundle,
        deployment_profile_hash=sha256_bytes(canonical_json_bytes(deployment)),
    ).model_dump(mode="python")
    value.update(
        schema_version="sdk-campaign-spec/v1",
        profile="sdk-bounded/v1",
        hosted_budget=template_spec.hosted_budget,
        sdk_profile=profile,
    )
    spec = SdkCampaignSpec.model_validate(value)
    atomic_write_bytes(inputs / f"sha256-{bundle.content_hash}.json", bundle.canonical_bytes())
    atomic_write_bytes(metadata / "loader-config.json", config.canonical_bytes())
    atomic_write_bytes(metadata / "sdk-campaign-spec.json", spec.canonical_bytes())
    atomic_write_bytes(metadata / "deployment.json", canonical_json_bytes(deployment))
    mounts = []
    for relative, identity in (
        (old.snapshot_directory, snapshot.snapshot_hash),
        (old.qlib_view_directory, view.view_hash),
    ):
        (inputs / relative).mkdir(parents=True, exist_ok=False)
        mounts.append(
            {
                "source": str(args.source_inputs / relative),
                "target": str(inputs / relative),
                "identity": identity,
                "mode": "ro",
            }
        )
    result = {
        "campaign_hash": campaign.content_hash,
        "spec_sha256": spec.content_hash,
        "config_sha256": config.content_hash,
        "mounts": mounts,
        "sdk_calls": 0,
        "scientific_executions": 0,
        "status": "METADATA_PREPARED_INPUT_MOUNTS_NOT_VERIFIED",
        "qualification": "NOT_QUALIFIED",
    }
    atomic_write_bytes(metadata / "prepared.json", canonical_json_bytes(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("template", "template-spec", "source-inputs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in (
        "template-sha256",
        "template-spec-sha256",
        "expected-commit",
        "campaign-id",
        "started-at",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--runtime-environment", type=Path)
    parser.add_argument("--runtime-profile", type=Path)
    args = parser.parse_args()
    output_existed = args.output.exists()
    try:
        if any(
            not getattr(args, name).is_absolute()
            for name in ("template", "template_spec", "source_inputs", "output")
        ):
            raise ValueError("absolute paths required")
        print(json.dumps(prepare(args), sort_keys=True))
        return 0
    except Exception as error:
        if not output_existed and args.output.is_dir():
            atomic_write_bytes(
                args.output / "preparation-failure.json",
                canonical_json_bytes(
                    {
                        "error_class": type(error).__name__,
                        "sdk_calls": 0,
                        "scientific_executions": 0,
                    }
                ),
            )
        print('{"error":"preparation_rejected"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
